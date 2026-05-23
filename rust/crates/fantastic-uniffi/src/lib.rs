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

/// Callback bridge for the kernel's state stream. UniFFI generates a
/// Swift protocol of the same name; consumers implement it on their
/// side and hand an instance to [`Kernel::subscribe`].
///
/// `on_event` fires inline on the kernel's dispatching task. Keep the
/// implementation short — off-thread heavy work via Swift's
/// structured concurrency (`Task.detached`, `MainActor.run`, etc.).
pub trait StateListener: Send + Sync {
    /// One JSON-serialized state event per call. Shapes:
    /// `{"type":"send",  sender, target, verb, summary}`
    /// `{"type":"emit",  sender, target, verb, summary}`
    /// `{"type":"created", id, parent_id, handler_module}`
    /// `{"type":"removed", id}`
    /// `{"type":"updated", id}`
    fn on_event(&self, event_json: String);
}

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
    /// A `Kernel::load` call received a snapshot that was malformed,
    /// missing a root, had a duplicate id, dangling parent_id, or a
    /// schema version this kernel doesn't understand.
    #[error("invalid snapshot: {0}")]
    InvalidSnapshot(String),
    /// Catch-all for unexpected failures.
    #[error("internal: {0}")]
    Internal(String),
}

/// Default bundle set linked into the Swift-embedded build.
///
/// Always-available bundles compile under both the `embedded` (iOS /
/// sandboxed) and `desktop` (unsandboxed) features. Full-tier-only
/// bundles are added via the `#[cfg(feature = "full")]` gate below
/// — currently none, but the placeholder keeps the contract explicit
/// so the iOS-sandbox guarantee doesn't silently regress when a
/// subprocess-using bundle gets ported.
fn register_default_bundles() -> BundleRegistry {
    let mut reg = BundleRegistry::new();

    // ── Always-available (iOS-safe).
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
    reg.register("scheduler.tools", fantastic_scheduler::SchedulerBundle);
    reg.register("gl_agent.tools", fantastic_gl_agent::GlAgentBundle);
    reg.register(
        "telemetry_pane.tools",
        fantastic_telemetry_pane::TelemetryPaneBundle,
    );
    reg.register(
        "ai_chat_webapp.tools",
        fantastic_ai_chat_webapp::AiChatWebappBundle,
    );
    reg.register(
        "terminal_webapp.tools",
        fantastic_terminal_webapp::TerminalWebappBundle,
    );
    reg.register(
        "ollama_backend.tools",
        fantastic_ollama_backend::OllamaBackendBundle,
    );
    reg.register(
        "kernel_bridge.tools",
        fantastic_kernel_bridge::KernelBridgeBundle,
    );
    reg.register(
        "nvidia_nim_backend.tools",
        fantastic_nvidia_nim_backend::NvidiaNimBundle,
    );
    reg.register(
        fantastic_proxy_agent::HANDLER_MODULE,
        fantastic_proxy_agent::ProxyAgentBundle::new(),
    );

    // ── Full-tier-only (subprocess / fork / dynamic loading).
    //
    // None ported yet. Sandboxed iOS builds must NOT see these. When
    // adding one, gate both the dep in Cargo.toml AND the register
    // call here on `feature = "full"`.
    #[cfg(feature = "full")]
    {
        // Desktop / unsandboxed bundles. PTY + subprocess + dynamic
        // loading; iOS sandbox forbids these so they're feature-gated.
        // Pro Mac links the `full` XCFramework and gets the registrations
        // below; Lite (any platform) compiles without these crates at all.
        reg.register(
            "terminal_backend.tools",
            fantastic_terminal_backend::TerminalBackendBundle,
        );
        reg.register(
            "local_runner.tools",
            fantastic_local_runner::LocalRunnerBundle,
        );
        reg.register(
            "python_runtime.tools",
            fantastic_python_runtime::PythonRuntimeBundle,
        );
        reg.register("ssh_runner.tools", fantastic_ssh_runner::SshRunnerBundle);
    }

    // ── Apple-only bundle.
    //
    // `foundation_models_backend` forwards chat to a Swift host that
    // wraps Apple's `LanguageModelSession`. The host is registered
    // via `Kernel::set_foundation_models_backend` (UniFFI-exposed) at
    // brain-kernel boot. The bundle is iOS-sandbox-safe — pure Rust,
    // no subprocess / PTY — so it ships in BOTH the embedded and full
    // XCFramework variants. Linux + Windows builds skip the bundle
    // entirely (no Swift host can register; the bundle would be dead
    // code).
    #[cfg(target_vendor = "apple")]
    {
        reg.register(
            fantastic_foundation_models_backend::HANDLER_MODULE,
            fantastic_foundation_models_backend::FoundationModelsBackendBundle::new(),
        );
    }

    reg
}

/// Public bootstrap function. Constructs a kernel, hydrates persisted
/// agents (weak-load skip+log for unknown bundles), spins up the
/// axum listener via the web bundle's `boot` verb.
///
/// `async_runtime = "tokio"` is critical — without it, UniFFI's
/// Rust-side scaffolding polls this future on its default executor
/// which has no Tokio reactor. The first internal `tokio::spawn` /
/// `tokio::net::TcpListener::bind` / `axum::serve` then panics with
/// "there is no reactor running, must be called from the context of
/// a Tokio 1.x runtime". The proc-macro form is the only way to set
/// `async_runtime` per-function — uniffi 0.29's UDL grammar doesn't
/// support `[Async=tokio]`, and the `uniffi.toml [bindings.swift]
/// async_runtime` knob only configures the FOREIGN-language bindgen,
/// not the Rust scaffolding poll loop.
///
/// Docs: https://mozilla.github.io/uniffi-rs/latest/futures.html
#[uniffi::export(async_runtime = "tokio")]
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

/// Boot a brain-tier kernel — no workdir, no lock file, no on-disk
/// state. Everything lives in process memory; the consumer extracts
/// state via [`Kernel::save`] (returns JSON) and restores it via
/// [`Kernel::load`].
///
/// Mode parity with [`start_kernel`]: ensures a web agent and boots
/// it, so the brain still serves HTTP / WS on `127.0.0.1:<port>` the
/// embedding app can point a WebView at. The wire surface is
/// identical to a disk-backed kernel after boot — Swift consumers
/// treat both kernel handles the same way (`sendJson`, `subscribe`,
/// etc.).
#[uniffi::export(async_runtime = "tokio")]
pub async fn start_kernel_in_memory(port_hint: u16) -> Result<Arc<Kernel>, KernelError> {
    let opts = BootstrapOptions::in_memory();
    let booted = bootstrap::bootstrap(register_default_bundles(), opts)
        .map_err(|e| KernelError::BootFailed(format!("{e}")))?;
    let kernel_arc = Arc::clone(&booted.kernel);
    let web_id = ensure_web_agent(&kernel_arc, port_hint).await?;
    let boot_reply = kernel_arc.send(&web_id, json!({"type": "boot"})).await;
    if let Some(err) = boot_reply.get("error").and_then(Value::as_str) {
        return Err(KernelError::PortBindFailed(err.to_string()));
    }
    let actual_port = boot_reply
        .get("port")
        .and_then(Value::as_u64)
        .map(|p| p as u16)
        .unwrap_or(port_hint);
    // Workdir field is a never-read sentinel — Kernel::new_inner
    // requires one but the shutdown path skips lock release when the
    // underlying storage is InMemory.
    Ok(Arc::new(Kernel::new_inner(
        booted.kernel,
        PathBuf::new(),
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

/// Private impl block — methods NOT exported to Swift. The exported
/// surface lives in the two `#[uniffi::export]` blocks below.
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
}

/// Sync methods exposed to Swift. Declared via proc-macro so the
/// UDL stays type-only — see the matching `interface Kernel` block
/// in `fantastic.udl` which only declares the type, not its methods.
#[uniffi::export]
impl Kernel {
    /// The bound port. Calling this before [`start_kernel`] finishes
    /// is a bug; the async bootstrap guarantees the port is known by
    /// the time the future resolves.
    pub fn http_port(&self) -> u16 {
        self.port
    }

    /// Register a [`StateListener`] for the kernel's state stream.
    /// Returns an opaque token consumers pass to [`Self::unsubscribe`]
    /// to detach. The closure runs inline on the dispatching task —
    /// keep it short.
    pub fn subscribe(&self, listener: Box<dyn StateListener>) -> u64 {
        let listener: Arc<dyn StateListener> = Arc::from(listener);
        let cb: fantastic_kernel::StateSubscriber = Arc::new(move |event: &Value| {
            let s = serde_json::to_string(event).unwrap_or_else(|_| "null".to_string());
            listener.on_event(s);
        });
        let token = self.inner.add_state_subscriber(cb);
        token.0
    }

    /// Detach a listener previously registered via [`Self::subscribe`].
    /// No-op if `token` isn't (or no longer is) registered.
    pub fn unsubscribe(&self, token: u64) {
        self.inner
            .remove_state_subscriber(fantastic_kernel::kernel::SubscriberToken(token));
    }

    /// Snapshot the kernel's current state as a JSON string.
    ///
    /// Both storage modes answer this — Disk-mode callers usually
    /// don't need it (state.json is already on disk), but it's useful
    /// for cross-process inspection and "export this workdir" UX.
    /// InMemory consumers (Swift brain kernel) call this to persist
    /// state externally (UserDefaults, CloudKit, file) and
    /// `kernel.load(json)` later to restore.
    ///
    /// Output is byte-deterministic for equal in-memory state —
    /// agents are sorted by id (ASCII) inside the snapshot.
    pub fn save(&self) -> String {
        self.inner.save_json()
    }

    /// Replace the kernel's agent tree with the snapshot in `json`.
    ///
    /// Drops every currently-registered agent + closes their inboxes,
    /// then rebuilds the tree from the snapshot. Weak-load: agents
    /// whose `handler_module` isn't in this kernel's bundle registry
    /// are logged + skipped along with their subtree.
    ///
    /// In Disk mode the new state is also flushed to
    /// `<workdir>/.fantastic/state.json` so subsequent boots see the
    /// loaded state.
    ///
    /// Errors:
    /// - [`KernelError::InvalidSnapshot`] if the JSON doesn't parse,
    ///   if the snapshot's schema version is too new, if it has no
    ///   root, has duplicate ids, or has dangling parent references.
    pub fn load(&self, json: String) -> Result<(), KernelError> {
        self.inner.load_json(&json).map_err(|e| match e {
            fantastic_kernel::KernelError::InvalidSnapshot(msg) => {
                KernelError::InvalidSnapshot(msg)
            }
            other => KernelError::Internal(format!("{other}")),
        })?;
        // For Disk mode, persist each loaded agent to its on-disk
        // dir. The merge-only `persist` won't delete dirs of agents
        // that USED to be in this kernel but aren't in the new
        // snapshot — those stay on disk per the dirty-binding
        // contract ("agents will reconcile when they next touch
        // them"). The brain kernel use case is InMemory, which
        // no-ops here.
        for entry in self.inner.agents.iter() {
            let _ = fantastic_kernel::persistence::persist(entry.value(), &self.inner.storage);
        }
        Ok(())
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

/// Async method — needs its OWN proc-macro impl block with
/// `async_runtime = "tokio"` so UniFFI wraps the Rust-side
/// scaffolding's `.poll()` in a Tokio runtime context. Without this
/// the future panics on its first internal `tokio::spawn` /
/// `tokio::mpsc` op (kernel.send awaits both). uniffi 0.29 doesn't
/// support per-method runtime tagging inside a shared impl block,
/// so the async fn lives here alone.
#[uniffi::export(async_runtime = "tokio")]
impl Kernel {
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
}

impl Drop for Kernel {
    fn drop(&mut self) {
        self.shutdown();
    }
}

// ── Apple Foundation Models bridge ─────────────────────────────────
//
// Cfg-gated on `target_vendor = "apple"`. Linux + Windows builds skip
// this module entirely; the callback trait + the four FM methods on
// `Kernel` simply don't exist on those targets. UDL stays unchanged
// — we declare the callback interface via proc-macro for per-target
// granularity.

#[cfg(target_vendor = "apple")]
mod fm_bridge {
    use super::*;
    use fantastic_foundation_models_backend as fmb;

    /// Apple Foundation Models host. Swift implements this via UniFFI;
    /// the Swift impl wraps `FoundationModels.LanguageModelSession`.
    ///
    /// All methods are sync — UniFFI 0.29 callback-interface methods
    /// can't be async. Swift implementations that need async (the
    /// `LanguageModelSession.streamResponse` loop) kick off a `Task`
    /// inside `stream_response` and report back via the kernel's
    /// `fm_push_token` / `fm_complete` / `fm_error` methods.
    #[uniffi::export(callback_interface)]
    pub trait FoundationModelsBackend: Send + Sync {
        /// True iff Apple Intelligence is enabled + the user opted in.
        fn is_available(&self) -> bool;

        /// True iff the on-device model is downloaded + ready.
        fn model_available(&self) -> bool;

        /// Begin a generation. Returns immediately; the implementation
        /// runs the streaming loop in its own task + reports tokens
        /// via `kernel.fm_push_token(stream_id, delta)`, finalizes via
        /// `kernel.fm_complete(stream_id)`, and surfaces failures via
        /// `kernel.fm_error(stream_id, message)`.
        fn stream_response(
            &self,
            stream_id: String,
            system_prompt: String,
            history_json: String,
            user_message: String,
        );

        /// Cancel an in-flight stream by id. Idempotent.
        fn cancel(&self, stream_id: String);
    }

    /// Bridge struct — implements the bundle-crate's
    /// [`fmb::FoundationModelsHost`] trait by forwarding to the
    /// UniFFI callback. Constructed once per
    /// `Kernel::set_foundation_models_backend` call.
    pub(super) struct SwiftHostAdapter {
        inner: Arc<dyn FoundationModelsBackend>,
    }

    impl SwiftHostAdapter {
        pub(super) fn new(inner: Box<dyn FoundationModelsBackend>) -> Arc<Self> {
            Arc::new(Self {
                inner: Arc::from(inner),
            })
        }
    }

    impl fmb::FoundationModelsHost for SwiftHostAdapter {
        fn is_available(&self) -> bool {
            self.inner.is_available()
        }
        fn model_available(&self) -> bool {
            self.inner.model_available()
        }
        fn stream_response(
            &self,
            stream_id: String,
            system_prompt: String,
            history_json: String,
            user_message: String,
        ) {
            self.inner
                .stream_response(stream_id, system_prompt, history_json, user_message);
        }
        fn cancel(&self, stream_id: String) {
            self.inner.cancel(stream_id);
        }
    }
}

/// Apple-only Kernel methods that bridge to the
/// `foundation_models_backend` bundle. Swift consumers register a
/// host via `set_foundation_models_backend`, then feed tokens back
/// via `fm_push_token` / `fm_complete` / `fm_error` (keyed by the
/// `stream_id` the bundle handed out from its `send` reply).
///
/// Bridge async because `fm_push_token` / `fm_complete` / `fm_error`
/// internally `kernel.send` / `kernel.emit` (Tokio mpsc) to fan out
/// `token` / `done` events to caller inboxes — same `async_runtime
/// = "tokio"` reason as the other async exports.
#[cfg(target_vendor = "apple")]
#[uniffi::export(async_runtime = "tokio")]
impl Kernel {
    /// Register a Foundation Models host. Replaces any previously-
    /// registered host (single global slot). Returns immediately.
    pub fn set_foundation_models_backend(
        &self,
        backend: Box<dyn fm_bridge::FoundationModelsBackend>,
    ) {
        let adapter = fm_bridge::SwiftHostAdapter::new(backend);
        fantastic_foundation_models_backend::register_host(adapter);
    }

    /// Append a token to the in-flight assistant message identified
    /// by `stream_id`. Emits a `token` event to the caller.
    pub async fn fm_push_token(&self, stream_id: String, delta: String) {
        fantastic_foundation_models_backend::push_token(&self.inner, &stream_id, &delta).await;
    }

    /// Mark the stream complete + persist the final assistant
    /// message. Emits a `done` event.
    pub async fn fm_complete(&self, stream_id: String) {
        fantastic_foundation_models_backend::complete(&self.inner, &stream_id).await;
    }

    /// Mark the stream failed. Emits a `done` event with the error.
    pub async fn fm_error(&self, stream_id: String, message: String) {
        fantastic_foundation_models_backend::error(&self.inner, &stream_id, &message).await;
    }
}

// ── ProxyAgent bridge (host-implemented agents) ────────────────────
//
// The `proxy_agent.tools` bundle forwards every verb to a host
// implementation keyed by agent_id. Swift implements `ProxyAgent`;
// the kernel routes verbs to it. Two-way: hosts handle inbound
// verbs synchronously (returning JSON acks/replies); outbound
// SwiftUI-originated sends use `send_json_as` for sender
// attribution; outbound async events use `proxy_emit` to fan out
// on the agent's own inbox.
//
// Generic — ships on every platform (no cfg gate). Linux / Windows
// builds get it too since a Rust host (egui, slint, tests) is just
// as valid as a Swift host.

/// Apple-side / Swift / any-host trait. Hosts implement this and
/// register an instance per agent_id via
/// [`Kernel::register_proxy_agent`].
///
/// Methods are sync because UniFFI 0.29 callback interfaces don't
/// support `async`. Swift impls that need async (SwiftUI updates,
/// network calls) should kick off a `Task { @MainActor in … }`
/// inside `handle` and return immediately with a sync ack.
#[uniffi::export(callback_interface)]
pub trait ProxyAgent: Send + Sync {
    /// Verb dispatch. JSON in, JSON out. Reply can be a real
    /// response or a fire-and-forget ack like `{"ok":true}`.
    fn handle(&self, payload_json: String) -> String;

    /// Fired when the agent's `boot` verb dispatches. Default: noop.
    fn on_boot(&self) {}

    /// Fired during cascade-delete (before the agent unregisters).
    /// Default: noop. The bundle drops the host from its registry
    /// after this — no `unregister_proxy_agent` call needed.
    fn on_delete(&self) {}
}

/// Bridge — implements the bundle-crate's [`ProxyAgentHost`] trait
/// by forwarding to the UniFFI callback. One per registered host.
struct SwiftProxyHostAdapter {
    inner: Arc<dyn ProxyAgent>,
}

impl SwiftProxyHostAdapter {
    fn new(inner: Box<dyn ProxyAgent>) -> Arc<Self> {
        Arc::new(Self {
            inner: Arc::from(inner),
        })
    }
}

impl fantastic_proxy_agent::ProxyAgentHost for SwiftProxyHostAdapter {
    fn handle(&self, payload_json: String) -> String {
        self.inner.handle(payload_json)
    }
    fn on_boot(&self) {
        self.inner.on_boot();
    }
    fn on_delete(&self) {
        self.inner.on_delete();
    }
}

/// Sync methods on the `Kernel` handle that manage proxy_agent
/// host registration. Registration is sync — just slots an entry
/// into the bundle's process-global host map.
#[uniffi::export]
impl Kernel {
    /// Install a Swift host for the given proxy_agent. Replaces any
    /// previously-registered host for the same id. Best practice is
    /// to call this BEFORE creating the agent so the first verb
    /// dispatch finds the host; the bundle gracefully degrades to
    /// `{error, reason:"no_host"}` until registration completes.
    pub fn register_proxy_agent(&self, agent_id: String, host: Box<dyn ProxyAgent>) {
        let adapter = SwiftProxyHostAdapter::new(host);
        fantastic_proxy_agent::register_host(AgentId::from(agent_id.as_str()), adapter);
    }

    /// Drop the host for the given proxy_agent. Returns whether a
    /// host was registered. No-op if nothing was installed.
    /// Standard cascade-delete also clears the host (`Bundle::on_delete`
    /// hook on the bundle), so explicit unregister is rarely needed.
    pub fn unregister_proxy_agent(&self, agent_id: String) -> bool {
        let id = AgentId::from(agent_id.as_str());
        let had = fantastic_proxy_agent::host_for(&id).is_some();
        fantastic_proxy_agent::unregister_host(&id);
        had
    }
}

/// Async methods on the `Kernel` handle that the UI uses for
/// outbound traffic (`send_json_as` with sender attribution +
/// `proxy_emit` for fan-out on the agent's own inbox).
#[uniffi::export(async_runtime = "tokio")]
impl Kernel {
    /// JSON-in, JSON-out RPC like `send_json` — but tags the
    /// dispatch with `sender_id` so state events attribute correctly.
    /// SwiftUI's input handlers call this to send AS the UI agent
    /// rather than as an untagged external client.
    pub async fn send_json_as(
        &self,
        sender_id: String,
        target_id: String,
        payload_json: String,
    ) -> String {
        let payload: Value = serde_json::from_str(&payload_json)
            .unwrap_or_else(|_| json!({"error": "send_json_as: payload not valid JSON"}));
        let target = AgentId::from(target_id.as_str());
        let sender = AgentId::from(sender_id.as_str());
        let kernel = Arc::clone(&self.inner);
        let reply = fantastic_kernel::send::with_sender(sender, async move {
            kernel.send(&target, payload).await
        })
        .await;
        serde_json::to_string(&reply).unwrap_or_else(|_| "null".to_string())
    }

    /// Fire an event on `agent_id`'s own inbox. Watchers receive
    /// via the standard `kernel.emit` fan-out. The UI uses this to
    /// broadcast state changes ("focus_changed", "selection_set",
    /// streaming tokens, etc.) without driving an RPC.
    pub async fn proxy_emit(&self, agent_id: String, event_json: String) {
        let event: Value = serde_json::from_str(&event_json)
            .unwrap_or_else(|_| json!({"error": "proxy_emit: event not valid JSON"}));
        self.inner
            .emit(&AgentId::from(agent_id.as_str()), event)
            .await;
    }
}

uniffi::include_scaffolding!("fantastic");

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct Counting {
        count: Arc<AtomicUsize>,
    }
    impl StateListener for Counting {
        fn on_event(&self, _event_json: String) {
            self.count.fetch_add(1, Ordering::SeqCst);
        }
    }

    #[tokio::test]
    async fn subscribe_callback_fires_for_each_event() {
        let tmp = tempfile::TempDir::new().unwrap();
        let kernel = start_kernel(tmp.path().to_string_lossy().to_string(), 0)
            .await
            .expect("boot");
        let count = Arc::new(AtomicUsize::new(0));
        let listener = Counting {
            count: Arc::clone(&count),
        };
        let token = kernel.subscribe(Box::new(listener));

        // Trigger a few state events. Every send publishes one;
        // create_agent also publishes a "created" event on its own.
        let _ = kernel
            .send_json(
                "core".into(),
                r#"{"type":"create_agent","handler_module":"file.tools","id":"t1","root":"/tmp"}"#
                    .into(),
            )
            .await;
        let _ = kernel
            .send_json("t1".into(), r#"{"type":"reflect"}"#.into())
            .await;
        let _ = kernel
            .send_json("core".into(), r#"{"type":"delete_agent","id":"t1"}"#.into())
            .await;

        // Each send fires at least one state event; some fire two
        // (created + send, removed + send, etc.). Assert lower bound.
        let after = count.load(Ordering::SeqCst);
        assert!(
            after >= 3,
            "expected >=3 state events fired through listener, got {after}",
        );

        // Detach + confirm the counter stops climbing.
        kernel.unsubscribe(token);
        let frozen = count.load(Ordering::SeqCst);
        let _ = kernel
            .send_json("kernel".into(), r#"{"type":"reflect"}"#.into())
            .await;
        assert_eq!(
            count.load(Ordering::SeqCst),
            frozen,
            "events still firing after unsubscribe",
        );

        kernel.shutdown();
    }

    #[tokio::test]
    async fn unsubscribe_unknown_token_is_noop() {
        let tmp = tempfile::TempDir::new().unwrap();
        let kernel = start_kernel(tmp.path().to_string_lossy().to_string(), 0)
            .await
            .expect("boot");
        kernel.unsubscribe(99_999_999);
        kernel.shutdown();
    }
}
