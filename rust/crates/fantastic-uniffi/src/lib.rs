//! UniFFI-bound Swift surface for embedding the kernel.
//!
//! See `fantastic.udl` for the typed API exported to Swift. The
//! canonical Swift↔kernel data path stays HTTP + WS on
//! `127.0.0.1:<port>`; this crate only owns LIFECYCLE — bootstrap +
//! port discovery + send_json shortcut + clean shutdown.
//!
//! Build via `scripts/build-xcframework.sh`; the resulting
//! `Fantastic.xcframework` is wrapped in the SPM package at
//! `rust/packaging/FantasticKernel/`.

#![deny(missing_docs)]

use fantastic_kernel::bootstrap::{self, BootstrapOptions};
use fantastic_kernel::{AgentId, BundleRegistry};
use serde_json::{json, Value};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use thiserror::Error;

/// Errors surfaced to Swift via UniFFI's `[Throws=KernelError]`.
#[derive(Debug, Error)]
pub enum KernelError {
    /// `workdir` doesn't exist or isn't readable.
    #[error("workdir invalid: {0}")]
    WorkdirInvalid(String),
    /// axum couldn't bind to the requested port.
    #[error("port bind failed: {0}")]
    PortBindFailed(String),
    /// Substrate boot failed (lock contention, bad agent.json, etc.).
    #[error("boot failed: {0}")]
    BootFailed(String),
    /// `start_kernel` called more than once for the same workdir
    /// without an intervening `shutdown()`.
    #[error("already running")]
    AlreadyRunning,
    /// Catch-all for unexpected failures.
    #[error("internal: {0}")]
    Internal(String),
}

/// Default bundle set linked into the Swift-embedded build. Identical
/// to the CLI's default set; any `handler_module` outside this list
/// triggers weak-load skip+log at boot.
fn register_default_bundles() -> BundleRegistry {
    let mut reg = BundleRegistry::new();
    reg.register("file.tools", fantastic_file::FileBundle);
    reg.register("web.tools", fantastic_web::WebBundle);
    reg.register("web_ws.tools", fantastic_web_ws::WebWsBundle);
    reg.register("web_rest.tools", fantastic_web_rest::WebRestBundle);
    reg.register("html_agent.tools", fantastic_html_agent::HtmlAgentBundle);
    reg.register(
        "canvas_backend.tools",
        fantastic_canvas_backend::CanvasBackendBundle,
    );
    reg.register(
        "canvas_webapp.tools",
        fantastic_canvas_webapp::CanvasWebappBundle,
    );
    reg
}

/// Public bootstrap function. Constructs a kernel, hydrates persisted
/// agents (weak-load skip+log for unknown bundles), spins up the
/// axum listener via the web bundle's `boot` verb.
pub async fn start_kernel(workdir: String, port_hint: u16) -> Result<Arc<Kernel>, KernelError> {
    let workdir_path = PathBuf::from(&workdir);
    if !workdir_path.exists() {
        std::fs::create_dir_all(&workdir_path)
            .map_err(|e| KernelError::WorkdirInvalid(format!("create {}: {e}", workdir)))?;
    }
    let opts = BootstrapOptions::daemon(&workdir_path);
    let booted = bootstrap::bootstrap(register_default_bundles(), opts)
        .map_err(|e| KernelError::BootFailed(format!("{e}")))?;
    let kernel_arc = Arc::clone(&booted.kernel);

    // If the workdir already has a web agent, boot it (the listener
    // spawns inside the bundle). Otherwise create + boot a default
    // web agent on `port_hint` so the embedding app has SOMETHING to
    // point WKWebView at.
    let web_id = ensure_web_agent(&kernel_arc, port_hint).await?;
    // boot fires the listener.
    let boot_reply = kernel_arc.send(&web_id, json!({"type": "boot"})).await;
    if let Some(err) = boot_reply.get("error").and_then(Value::as_str) {
        return Err(KernelError::PortBindFailed(err.to_string()));
    }
    let actual_port = boot_reply
        .get("port")
        .and_then(Value::as_u64)
        .map(|p| p as u16)
        .unwrap_or(port_hint);

    // Also seed core's readme so callers that reflect with
    // return_readme=true on the root get useful output.
    let _ = fantastic_core::seed_root_readme(&workdir_path);

    Ok(Arc::new(Kernel::new_inner(
        booted.kernel,
        workdir_path,
        web_id,
        actual_port,
    )))
}

async fn ensure_web_agent(
    kernel: &Arc<fantastic_kernel::Kernel>,
    port_hint: u16,
) -> Result<AgentId, KernelError> {
    // Reuse an existing web.tools agent if any.
    if let Some(existing) = kernel
        .agents
        .iter()
        .find(|e| e.value().handler_module.as_deref() == Some("web.tools"))
    {
        return Ok(existing.key().clone());
    }
    // Otherwise create a new one under core with the requested port.
    let reply = kernel
        .send(
            &AgentId::from("core"),
            json!({
                "type": "create_agent",
                "handler_module": "web.tools",
                "id": "web",
                "port": port_hint,
            }),
        )
        .await;
    if let Some(err) = reply.get("error").and_then(Value::as_str) {
        return Err(KernelError::BootFailed(format!("create web agent: {err}")));
    }
    Ok(AgentId::from("web"))
}

/// Swift-facing handle. Holds the workdir + bound port + the kernel
/// Arc so handler closures (send_json) can talk to substrate.
pub struct Kernel {
    inner: Arc<fantastic_kernel::Kernel>,
    workdir: PathBuf,
    web_id: AgentId,
    port: u16,
    /// `true` after `shutdown()` so a second call is a no-op.
    stopped: Mutex<bool>,
}

impl Kernel {
    /// Wrap a freshly-booted substrate. Used by [`start_kernel`].
    fn new_inner(
        inner: Arc<fantastic_kernel::Kernel>,
        workdir: PathBuf,
        web_id: AgentId,
        port: u16,
    ) -> Self {
        Self {
            inner,
            workdir,
            web_id,
            port,
            stopped: Mutex::new(false),
        }
    }

    /// The bound port. Calling this before [`start_kernel`] finishes
    /// is a bug; the async bootstrap guarantees the port is known by
    /// the time the future resolves.
    pub fn http_port(&self) -> u16 {
        self.port
    }

    /// JSON-in, JSON-out shortcut. Equivalent to the WS `call` frame.
    pub async fn send_json(&self, target_id: String, payload_json: String) -> String {
        let payload: Value = serde_json::from_str(&payload_json)
            .unwrap_or_else(|_| json!({"error": "send_json: payload not valid JSON"}));
        let reply = self
            .inner
            .send(&AgentId::from(target_id.as_str()), payload)
            .await;
        serde_json::to_string(&reply).unwrap_or_else(|_| "null".to_string())
    }

    /// Stop the listener, release the workdir lock. Idempotent.
    pub fn shutdown(&self) {
        let mut g = self.stopped.lock().expect("stopped poisoned");
        if *g {
            return;
        }
        *g = true;
        // Block briefly on the web bundle's `shutdown` verb. We're in
        // a sync method (UniFFI doesn't async-bridge `shutdown`); use
        // a one-shot runtime for the await.
        let inner = Arc::clone(&self.inner);
        let web_id = self.web_id.clone();
        std::thread::spawn(move || {
            if let Ok(rt) = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
            {
                rt.block_on(async {
                    let _ = inner.send(&web_id, json!({"type": "shutdown"})).await;
                });
            }
        })
        .join()
        .ok();
        // Release the workdir lock.
        let _ = bootstrap::shutdown(&self.workdir);
    }
}

impl Drop for Kernel {
    fn drop(&mut self) {
        self.shutdown();
    }
}

uniffi::include_scaffolding!("fantastic");
