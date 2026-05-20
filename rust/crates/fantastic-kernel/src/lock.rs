//! `.fantastic/lock.json` PID guard.
//!
//! Shape: `{"pid": <u32>}`. A daemon writes the lock at boot; later
//! invocations refuse with `KernelError::LockHeld` if the pid is alive.
//! Stale locks (dead pid) get overwritten — matches Python's behavior.
//!
//! Liveness check: `libc::kill(pid, 0)` returns `Ok` if the process
//! exists (or `EPERM` if we lack permission but the process IS alive);
//! it returns `ESRCH` if the process is gone.

use crate::errors::{KernelError, KernelResult};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Serialize, Deserialize, Clone, Copy)]
struct LockFile {
    pid: u32,
}

/// Check whether a pid is alive on this system.
///
/// On unix: `kill(pid, 0)`. On other platforms: assume alive (we
/// only run macOS + Linux today; Windows handling lands when we
/// add Windows CI).
pub fn pid_alive(pid: u32) -> bool {
    #[cfg(unix)]
    {
        // Safety: kill(pid, 0) only checks existence + permission; no
        // signal is actually delivered.
        let rc = unsafe { libc::kill(pid as libc::pid_t, 0) };
        if rc == 0 {
            return true;
        }
        // -1 + ESRCH = dead; -1 + EPERM = alive but not ours.
        let errno = std::io::Error::last_os_error().raw_os_error();
        errno == Some(libc::EPERM)
    }
    #[cfg(not(unix))]
    {
        let _ = pid;
        true
    }
}

/// Acquire the workdir lock for the current process. Writes
/// `.fantastic/lock.json` with our pid.
///
/// If the lock file already exists AND the pid in it is alive,
/// returns [`KernelError::LockHeld`]. If the pid is dead, the lock
/// is stale and gets overwritten.
pub fn acquire(workdir: &Path) -> KernelResult<PathBuf> {
    let path = workdir.join(super::persistence::LOCK_PATH);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| KernelError::LockIo {
            path: path.clone(),
            source: e,
        })?;
    }
    if path.exists() {
        let raw = fs::read_to_string(&path).map_err(|e| KernelError::LockIo {
            path: path.clone(),
            source: e,
        })?;
        if let Ok(existing) = serde_json::from_str::<LockFile>(&raw) {
            if pid_alive(existing.pid) {
                return Err(KernelError::LockHeld { pid: existing.pid });
            }
            // Stale — fall through to overwrite.
        }
    }
    let me = std::process::id();
    let lock = LockFile { pid: me };
    let json = serde_json::to_string(&lock).expect("LockFile always serializable");
    fs::write(&path, json).map_err(|e| KernelError::LockIo {
        path: path.clone(),
        source: e,
    })?;
    Ok(path)
}

/// Release the workdir lock if we hold it. No error on missing file.
pub fn release(workdir: &Path) -> KernelResult<()> {
    let path = workdir.join(super::persistence::LOCK_PATH);
    if !path.exists() {
        return Ok(());
    }
    fs::remove_file(&path).map_err(|e| KernelError::LockIo {
        path,
        source: e,
    })?;
    Ok(())
}

/// Read the pid currently in the lock file, if any. Used by callers
/// that want to attach to a running daemon (e.g. one-shot CLI
/// invocations detecting a serve in the same workdir).
pub fn current_holder(workdir: &Path) -> KernelResult<Option<u32>> {
    let path = workdir.join(super::persistence::LOCK_PATH);
    if !path.exists() {
        return Ok(None);
    }
    let raw = fs::read_to_string(&path).map_err(|e| KernelError::LockIo {
        path: path.clone(),
        source: e,
    })?;
    let lock: LockFile = serde_json::from_str(&raw).map_err(|_| KernelError::LockIo {
        path: path.clone(),
        source: std::io::Error::new(std::io::ErrorKind::InvalidData, "lock.json malformed"),
    })?;
    Ok(Some(lock.pid))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn pid_alive_self_returns_true() {
        let me = std::process::id();
        assert!(pid_alive(me));
    }

    #[test]
    fn pid_alive_clearly_dead_returns_false() {
        // PID 0 is reserved on unix; kill(0, 0) signals the process
        // group and isn't a clean "is this PID alive" check. Pick a
        // very high pid unlikely to exist.
        let probably_dead = u32::MAX - 1;
        assert!(!pid_alive(probably_dead));
    }

    #[test]
    fn acquire_writes_lock_file() {
        let tmp = TempDir::new().unwrap();
        let path = acquire(tmp.path()).unwrap();
        assert!(path.exists());
        let raw = std::fs::read_to_string(&path).unwrap();
        let lock: LockFile = serde_json::from_str(&raw).unwrap();
        assert_eq!(lock.pid, std::process::id());
    }

    #[test]
    fn acquire_refuses_when_live_pid_holds() {
        let tmp = TempDir::new().unwrap();
        // Pretend a live process (ourselves) owns the lock.
        acquire(tmp.path()).unwrap();
        let err = acquire(tmp.path()).unwrap_err();
        match err {
            KernelError::LockHeld { pid } => assert_eq!(pid, std::process::id()),
            other => panic!("expected LockHeld, got {other:?}"),
        }
    }

    #[test]
    fn acquire_overwrites_stale_lock() {
        let tmp = TempDir::new().unwrap();
        // Plant a stale lock with a clearly-dead PID.
        let lock_path = tmp.path().join(crate::persistence::LOCK_PATH);
        std::fs::create_dir_all(lock_path.parent().unwrap()).unwrap();
        std::fs::write(&lock_path, r#"{"pid": 4294967294}"#).unwrap();
        let acquired = acquire(tmp.path()).unwrap();
        assert_eq!(acquired, lock_path);
        let raw = std::fs::read_to_string(&lock_path).unwrap();
        let lock: LockFile = serde_json::from_str(&raw).unwrap();
        assert_eq!(lock.pid, std::process::id());
    }

    #[test]
    fn release_removes_file() {
        let tmp = TempDir::new().unwrap();
        let path = acquire(tmp.path()).unwrap();
        assert!(path.exists());
        release(tmp.path()).unwrap();
        assert!(!path.exists());
    }

    #[test]
    fn release_when_missing_is_noop() {
        let tmp = TempDir::new().unwrap();
        release(tmp.path()).unwrap();
    }

    #[test]
    fn current_holder_returns_pid() {
        let tmp = TempDir::new().unwrap();
        assert!(current_holder(tmp.path()).unwrap().is_none());
        acquire(tmp.path()).unwrap();
        let pid = current_holder(tmp.path()).unwrap().expect("locked");
        assert_eq!(pid, std::process::id());
    }
}
