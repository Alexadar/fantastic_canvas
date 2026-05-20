//! Recursive `Agent` substrate + `Kernel` shared context.
//!
//! Stable surface: `send`, `emit`, `watch`, `create`/`delete`/`update`,
//! `reflect`, on-disk `.fantastic/` layout. One runtime is active per
//! workdir at a time, locked by `.fantastic/lock.json`. Agents whose
//! bundle isn't installed in this runtime are skipped + logged at boot.
//!
//! Phase 1 scaffolding: types declared, real impl lands with task #228.

#![deny(missing_docs)]

/// Stable identifier for an agent (newtype around `String`).
///
/// The full Agent/Kernel/send/emit machinery arrives with the
/// substrate implementation; this stub keeps the workspace compiling
/// and downstream crates importing the right names.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct AgentId(pub String);

impl From<&str> for AgentId {
    fn from(s: &str) -> Self {
        AgentId(s.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn agent_id_from_str_round_trips() {
        let id: AgentId = "core".into();
        assert_eq!(id, AgentId("core".to_string()));
        assert_eq!(id.0, "core");
    }

    #[test]
    fn agent_id_equality_and_hashing() {
        let a = AgentId::from("file_abc123");
        let b = AgentId::from("file_abc123");
        let c = AgentId::from("file_xyz789");
        assert_eq!(a, b);
        assert_ne!(a, c);
        // Hash invariant: equal keys → equal hashes (verified via HashSet).
        let mut set = std::collections::HashSet::new();
        set.insert(a);
        assert!(set.contains(&b));
        assert!(!set.contains(&c));
    }
}
