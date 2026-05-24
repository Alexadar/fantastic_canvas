//! `foundation_models_backend.tools` — Apple Foundation Models adapter
//! bundle.
//!
//! Answers the same chat-backend verb surface as `ollama_backend` /
//! `nvidia_nim_backend` (`send` / `history` / `interrupt` / `reflect` /
//! `backend_state`) so it slots into `ai_chat_webapp`'s `upstream_id`
//! field without that bundle knowing or caring it's talking to FM.
//!
//! The bundle does **not** embed an LLM. It forwards generation
//! requests to a host implementation of [`FoundationModelsHost`].
//! On the fantastic_app's brain kernel that host is a Swift class
//! wrapping `LanguageModelSession`, registered via UniFFI (see
//! `fantastic-uniffi`). In tests a plain-Rust mock drives the same
//! trait.
//!
//! ## Token feedback (the "stream-id ping-pong")
//!
//! UniFFI 0.29 doesn't support a callback interface taking another
//! callback interface as a parameter — so the "sink" pattern from the
//! original spec is replaced by id-keyed feedback methods:
//!
//! 1. `send` generates a `stream_id` (UUID-ish), stashes an
//!    [`InFlight`] entry keyed by it, calls
//!    `host.stream_response(stream_id, system, history_json, user)`.
//! 2. The host runs the generation in its own task. For each token it
//!    calls back into the kernel via [`push_token`] / [`complete`] /
//!    [`error`] — sync pub fns in this crate, surfaced as methods on
//!    `Kernel` over UniFFI.
//! 3. Each callback mutates the in-flight entry + emits a `token` /
//!    `done` event to the caller (matches ollama's `to_caller`
//!    semantics — `cli` agent vs the backend's own inbox for browser
//!    watchers).
//!
//! ## Graceful degrade
//!
//! No host registered → `send` returns
//! `{"error":"Apple Foundation Models not registered or not available"}`.
//! Host registered but probes fail (`is_available: false` or
//! `model_available: false`) → `send` returns a structured error.
//! `backend_state` gives the client a single read-only probe for
//! rendering "Setup Apple Intelligence" / "Model loading" / "Ready".

#![deny(missing_docs)]

use async_trait::async_trait;
use fantastic_kernel::bundle::{Bundle, BundleError, Reply};
use fantastic_kernel::{AgentId, Kernel};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock, RwLock};

/// `handler_module` key under which this bundle registers.
pub const HANDLER_MODULE: &str = "foundation_models_backend.tools";

/// readme.md auto-seeded into the agent's dir on creation (Disk mode).
pub const README: &str = include_str!("readme.md");

/// Default `client_id` for callers that don't supply one. Matches the
/// ollama / nvidia precedent.
pub const DEFAULT_CLIENT_ID: &str = "cli";

/// Provider string surfaced in `reflect` + `backend_state` replies.
pub const PROVIDER: &str = "apple_foundation_models";

// ── host trait ─────────────────────────────────────────────────────

/// Trait the embedding host implements. Swift via UniFFI in production;
/// plain-Rust impls drive the unit tests.
///
/// All methods are sync — UniFFI 0.29 callback-interface methods can't
/// be async. Implementations that do async work internally (the Swift
/// `LanguageModelSession.streamResponse` loop) should kick off a task
/// inside `stream_response` and return immediately. Token feedback
/// happens via the kernel's sync [`push_token`] / [`complete`] /
/// [`error`] methods, not via the trait return value.
pub trait FoundationModelsHost: Send + Sync {
    /// True iff Apple Intelligence is enabled on this device + the
    /// user has opted in. Polled cheaply on every `reflect` /
    /// `backend_state` / `send`.
    fn is_available(&self) -> bool;

    /// True iff the on-device 3B model is downloaded + ready to serve.
    /// May be `false` immediately after first-launch while the model
    /// downloads; flips to `true` when ready.
    fn model_available(&self) -> bool;

    /// Begin a generation. Returns immediately — the host's own task
    /// runs the streaming loop and reports back via [`push_token`],
    /// [`complete`], or [`error`] keyed by `stream_id`.
    ///
    /// - `stream_id` — opaque token unique to this generation. The
    ///   host echoes it in every callback.
    /// - `system_prompt` — instructions for the session.
    /// - `history_json` — JSON array of prior turns: `[{role, text}, ...]`.
    ///   The host should replay these into the session before streaming.
    /// - `user_message` — the new user turn that drives this response.
    /// - `tools_json` — JSON array of currently-registered tools in
    ///   Apple-FM / OpenAI shape: `[{name, description, parameters},
    ///   ...]`. Comes from `kernel.send("tools", {list_for_llm})` —
    ///   `"[]"` when the tools agent isn't present or holds no tools.
    ///   The host wraps each entry as a `LanguageModelSession.Tool`
    ///   whose `call(...)` closure invokes `kernel.dispatch_tool`.
    fn stream_response(
        &self,
        stream_id: String,
        system_prompt: String,
        history_json: String,
        user_message: String,
        tools_json: String,
    );

    /// Cancel an in-flight stream by id. Idempotent. The host should
    /// stop emitting tokens; if the underlying session is mid-call it
    /// should be aborted as soon as possible.
    fn cancel(&self, stream_id: String);
}

// ── process-global state ───────────────────────────────────────────

/// Registered host (set once by the embedding app at boot). `None`
/// means no host is wired — every `send` returns the structured
/// "not registered" error.
static HOST: OnceLock<RwLock<Option<Arc<dyn FoundationModelsHost>>>> = OnceLock::new();

/// In-flight streams keyed by `stream_id`. Multiple concurrent
/// generations are supported (different stream_ids).
static STREAMS: OnceLock<Mutex<HashMap<String, InFlight>>> = OnceLock::new();

/// History key = (agent_id, client_id) — the bundle holds one chat
/// stream per client per FM agent.
type HistoryKey = (AgentId, String);

/// Per-`HistoryKey` conversation map.
type HistoryMap = HashMap<HistoryKey, Vec<Value>>;

/// Per-(agent_id, client_id) conversation history, in-RAM only. Disk
/// mode ALSO writes to a sidecar file (see [`history_sidecar_path`])
/// for parity with the ollama/nvidia bundles, but the in-RAM map is
/// always authoritative inside the running kernel.
static HISTORIES: OnceLock<Mutex<HistoryMap>> = OnceLock::new();

/// Monotonic counter for stream + message ids. Keeps test output
/// deterministic-ish; production uses the same counter (uniqueness is
/// what matters, not entropy).
static NEXT_ID: AtomicU64 = AtomicU64::new(1);

fn host_slot() -> &'static RwLock<Option<Arc<dyn FoundationModelsHost>>> {
    HOST.get_or_init(|| RwLock::new(None))
}

fn streams() -> &'static Mutex<HashMap<String, InFlight>> {
    STREAMS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn histories() -> &'static Mutex<HistoryMap> {
    HISTORIES.get_or_init(|| Mutex::new(HashMap::new()))
}

fn next_id(prefix: &str) -> String {
    let n = NEXT_ID.fetch_add(1, Ordering::Relaxed);
    format!("{prefix}_{n:08x}")
}

// ── registration API ──────────────────────────────────────────────

/// Install a host implementation. Replaces any previously-registered
/// host. Called once at kernel boot by the embedding app (Swift via
/// UniFFI; tests directly).
pub fn register_host(host: Arc<dyn FoundationModelsHost>) {
    *host_slot().write().expect("host lock poisoned") = Some(host);
}

/// Read-only access to the registered host. `None` if nothing's been
/// registered yet.
pub fn host() -> Option<Arc<dyn FoundationModelsHost>> {
    host_slot()
        .read()
        .expect("host lock poisoned")
        .as_ref()
        .map(Arc::clone)
}

/// Clear the registered host. Primarily for tests — production code
/// rarely needs to detach.
pub fn clear_host() {
    *host_slot().write().expect("host lock poisoned") = None;
    // Also clear in-flight state — a fresh test shouldn't see streams
    // from a prior test in the same process.
    streams().lock().expect("streams poisoned").clear();
    histories().lock().expect("histories poisoned").clear();
}

// ── in-flight state ────────────────────────────────────────────────

/// Per-stream bookkeeping. Mutated by the bundle's verb impls (on
/// `send` / `interrupt`) and by the host's feedback methods
/// ([`push_token`] / [`complete`] / [`error`]).
#[derive(Debug, Clone)]
struct InFlight {
    agent_id: AgentId,
    client_id: String,
    message_id: String,
    started_at: f64,
    accumulated: String,
    interrupted: bool,
    completed: bool,
    error: Option<String>,
}

// ── kernel-side feedback API (called from UniFFI Kernel methods) ───

/// Append `delta` to the in-flight assistant message identified by
/// `stream_id`. Emits a `token` event to the caller. Silently ignores
/// unknown stream_ids (the host might be slow to drop a cancelled
/// stream — no point panicking).
pub async fn push_token(kernel: &Arc<Kernel>, stream_id: &str, delta: &str) {
    let Some(snapshot) = update_stream(stream_id, |entry| {
        entry.accumulated.push_str(delta);
        Some(entry.clone())
    }) else {
        return;
    };
    let event = json!({
        "type": "token",
        "stream_id": stream_id,
        "message_id": snapshot.message_id,
        "delta": delta,
        "accumulated": snapshot.accumulated,
    });
    emit_to_caller(kernel, &snapshot.agent_id, &snapshot.client_id, event).await;
}

/// Mark the stream complete + persist the final assistant message to
/// history. Emits a `done` event.
pub async fn complete(kernel: &Arc<Kernel>, stream_id: &str) {
    let Some(snapshot) = update_stream(stream_id, |entry| {
        entry.completed = true;
        Some(entry.clone())
    }) else {
        return;
    };
    // Persist final assistant message to history.
    if !snapshot.accumulated.is_empty() || !snapshot.interrupted {
        push_history_message(
            &snapshot.agent_id,
            &snapshot.client_id,
            json!({
                "id": snapshot.message_id,
                "role": "assistant",
                "content": snapshot.accumulated,
                "complete": true,
                "interrupted": snapshot.interrupted,
            }),
            kernel,
        );
    }
    streams()
        .lock()
        .expect("streams poisoned")
        .remove(stream_id);
    let event = json!({
        "type": "done",
        "stream_id": stream_id,
        "message_id": snapshot.message_id,
        "accumulated": snapshot.accumulated,
        "interrupted": snapshot.interrupted,
    });
    emit_to_caller(kernel, &snapshot.agent_id, &snapshot.client_id, event).await;
}

/// Mark the stream failed. Records the error on the message; emits a
/// `done` event with `error` set.
pub async fn error(kernel: &Arc<Kernel>, stream_id: &str, message: &str) {
    let Some(snapshot) = update_stream(stream_id, |entry| {
        entry.error = Some(message.to_string());
        entry.completed = true;
        Some(entry.clone())
    }) else {
        return;
    };
    push_history_message(
        &snapshot.agent_id,
        &snapshot.client_id,
        json!({
            "id": snapshot.message_id,
            "role": "assistant",
            "content": snapshot.accumulated,
            "complete": true,
            "error": message,
        }),
        kernel,
    );
    streams()
        .lock()
        .expect("streams poisoned")
        .remove(stream_id);
    let event = json!({
        "type": "done",
        "stream_id": stream_id,
        "message_id": snapshot.message_id,
        "accumulated": snapshot.accumulated,
        "error": message,
    });
    emit_to_caller(kernel, &snapshot.agent_id, &snapshot.client_id, event).await;
}

/// Helper — locks the streams map briefly, applies `f` to the entry,
/// returns whatever `f` returned. Used to keep critical sections
/// short (no `.await` inside).
fn update_stream<F, T>(stream_id: &str, f: F) -> Option<T>
where
    F: FnOnce(&mut InFlight) -> Option<T>,
{
    let mut map = streams().lock().expect("streams poisoned");
    let entry = map.get_mut(stream_id)?;
    f(entry)
}

async fn emit_to_caller(kernel: &Arc<Kernel>, self_id: &AgentId, client_id: &str, mut ev: Value) {
    if let Some(obj) = ev.as_object_mut() {
        obj.insert("client_id".to_string(), json!(client_id));
    }
    if client_id == DEFAULT_CLIENT_ID {
        // Best-effort — if no `cli` agent is registered, the send
        // returns an error reply which we discard.
        let _ = kernel.send(&AgentId::from("cli"), ev).await;
    } else {
        kernel.emit(self_id, ev).await;
    }
}

fn now_secs() -> f64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

// ── history helpers ────────────────────────────────────────────────

fn push_history_message(agent_id: &AgentId, client_id: &str, message: Value, kernel: &Arc<Kernel>) {
    let key = (agent_id.clone(), client_id.to_string());
    let mut map = histories().lock().expect("histories poisoned");
    map.entry(key).or_default().push(message.clone());
    let history_snapshot = map.get(&(agent_id.clone(), client_id.to_string())).cloned();
    drop(map);
    // Disk-mode sidecar (parity with ollama/nvidia). Best-effort — a
    // write failure doesn't affect the in-RAM truth.
    if kernel.storage.is_disk() {
        if let (Some(path), Some(snapshot)) = (
            history_sidecar_path(kernel, agent_id, client_id),
            history_snapshot,
        ) {
            let _ = std::fs::create_dir_all(path.parent().expect("sidecar parent"));
            let _ = std::fs::write(
                &path,
                serde_json::to_string_pretty(&snapshot).unwrap_or_else(|_| "[]".to_string()),
            );
        }
    }
}

fn read_history(agent_id: &AgentId, client_id: &str) -> Vec<Value> {
    histories()
        .lock()
        .expect("histories poisoned")
        .get(&(agent_id.clone(), client_id.to_string()))
        .cloned()
        .unwrap_or_default()
}

fn history_sidecar_path(
    kernel: &Arc<Kernel>,
    agent_id: &AgentId,
    client_id: &str,
) -> Option<std::path::PathBuf> {
    let workdir = kernel.storage.workdir()?;
    Some(
        workdir
            .join(".fantastic/agents")
            .join(agent_id.as_str())
            .join(format!("chat_{client_id}.json")),
    )
}

// ── bundle ─────────────────────────────────────────────────────────

/// The Foundation Models backend bundle. Stateless — all per-stream /
/// per-agent state lives in the module-global maps above so the
/// UniFFI bridge can reach it without downcasting through the
/// `BundleRegistry`.
#[derive(Debug, Default)]
pub struct FoundationModelsBackendBundle;

impl FoundationModelsBackendBundle {
    /// Construct a fresh bundle. Stateless — `Default` works too.
    pub fn new() -> Self {
        Self
    }
}

#[async_trait]
impl Bundle for FoundationModelsBackendBundle {
    fn name(&self) -> &str {
        "foundation_models_backend"
    }

    fn readme(&self) -> Option<&'static str> {
        Some(README)
    }

    async fn handle(
        &self,
        agent_id: &AgentId,
        payload: &Value,
        kernel: &Arc<Kernel>,
    ) -> Result<Reply, BundleError> {
        let verb = payload.get("type").and_then(Value::as_str).unwrap_or("");
        let reply = match verb {
            "reflect" => reflect(agent_id),
            "boot" => json!({ "ok": true }),
            "shutdown" => shutdown(kernel).await,
            "send" => send(kernel, agent_id, payload).await,
            "history" => history(agent_id, payload),
            "interrupt" => interrupt(kernel, agent_id, payload).await,
            "backend_state" => backend_state(agent_id),
            "status" => status(agent_id),
            other => json!({"error": format!("unknown verb {other:?}")}),
        };
        Ok(Some(reply))
    }
}

// ── verb impls ─────────────────────────────────────────────────────

fn reflect(agent_id: &AgentId) -> Value {
    let probes = probe_host();
    json!({
        "id": agent_id.as_str(),
        "sentence": "Apple Foundation Models backend — streams responses from a host-provided LLM (Swift LanguageModelSession on iOS/Mac).",
        "provider": PROVIDER,
        "apple_intelligence_available": probes.apple_intelligence_available,
        "model_available": probes.model_available,
        "backend_registered": probes.backend_registered,
        "verbs": {
            "reflect": "Identity + availability probes.",
            "boot": "No-op (host is registered via UniFFI separately).",
            "shutdown": "Cancel any in-flight stream.",
            "send": "args: text:str, client_id:str?. Streams a response.",
            "history": "args: client_id:str?. Returns {messages, client_id}.",
            "interrupt": "args: client_id:str?. Cancel in-flight; returns {interrupted}.",
            "backend_state": "Probe host availability + in-flight state — single source of truth.",
            "status": "ollama-parity telemetry — current phase + accumulated text.",
        },
        "emits": {
            "token": "{type:'token', stream_id, message_id, delta, accumulated, client_id} — per token from the host",
            "done":  "{type:'done', stream_id, message_id, accumulated, interrupted?, error?, client_id} — terminal event per stream",
        },
    })
}

fn backend_state(agent_id: &AgentId) -> Value {
    let probes = probe_host();
    let in_flight_for_agent: Option<(String, InFlight)> = streams()
        .lock()
        .expect("streams poisoned")
        .iter()
        .find(|(_, s)| &s.agent_id == agent_id)
        .map(|(k, v)| (k.clone(), v.clone()));
    let (stream_id, message_id) = match &in_flight_for_agent {
        Some((sid, entry)) => (
            Value::String(sid.clone()),
            Value::String(entry.message_id.clone()),
        ),
        None => (Value::Null, Value::Null),
    };
    json!({
        "apple_intelligence_available": probes.apple_intelligence_available,
        "model_available": probes.model_available,
        "backend_registered": probes.backend_registered,
        "in_flight": in_flight_for_agent.is_some(),
        "stream_id": stream_id,
        "message_id": message_id,
    })
}

fn status(agent_id: &AgentId) -> Value {
    let in_flight = streams()
        .lock()
        .expect("streams poisoned")
        .values()
        .find(|s| &s.agent_id == agent_id)
        .cloned();
    let current = in_flight.map(|s| {
        json!({
            "client_id": s.client_id,
            "message_id": s.message_id,
            "started_at": s.started_at,
            "accumulated": s.accumulated,
            "interrupted": s.interrupted,
        })
    });
    json!({ "current": current })
}

async fn shutdown(kernel: &Arc<Kernel>) -> Value {
    // Cancel every in-flight stream owned by this agent's bundle —
    // we don't know which agent we are here without an agent_id param.
    // For safety, cancel all. shutdown is rare; the global blanket is
    // acceptable.
    let stream_ids: Vec<String> = streams()
        .lock()
        .expect("streams poisoned")
        .keys()
        .cloned()
        .collect();
    if let Some(h) = host() {
        for sid in &stream_ids {
            h.cancel(sid.clone());
        }
    }
    for sid in stream_ids {
        // Mark interrupted + emit done.
        if let Some(entry) = update_stream(&sid, |e| {
            e.interrupted = true;
            Some(e.clone())
        }) {
            let ev = json!({
                "type": "done",
                "stream_id": &sid,
                "message_id": entry.message_id,
                "accumulated": entry.accumulated,
                "interrupted": true,
            });
            emit_to_caller(kernel, &entry.agent_id, &entry.client_id, ev).await;
        }
        streams().lock().expect("streams poisoned").remove(&sid);
    }
    json!({"ok": true})
}

async fn send(kernel: &Arc<Kernel>, agent_id: &AgentId, payload: &Value) -> Value {
    let Some(text) = payload.get("text").and_then(Value::as_str) else {
        return json!({"error": "send requires text"});
    };
    let client_id = payload
        .get("client_id")
        .and_then(Value::as_str)
        .unwrap_or(DEFAULT_CLIENT_ID)
        .to_string();

    let probes = probe_host();
    if !probes.backend_registered {
        return json!({
            "error": "Apple Foundation Models not registered or not available",
            "reason": "no_host",
        });
    }
    if !probes.apple_intelligence_available {
        return json!({
            "error": "Apple Intelligence is not available on this device",
            "reason": "apple_intelligence_unavailable",
        });
    }
    if !probes.model_available {
        return json!({
            "error": "On-device model is not yet downloaded",
            "reason": "model_unavailable",
        });
    }

    let stream_id = next_id("stm");
    let message_id = next_id("msg");

    // Append the user turn to history immediately so subsequent
    // `history` calls see it.
    let user_message = json!({
        "id": next_id("msg"),
        "role": "user",
        "content": text,
        "complete": true,
    });
    push_history_message(agent_id, &client_id, user_message, kernel);

    // System prompt: read from this agent's meta, fall back to a
    // sensible default.
    let system_prompt = agent_system_prompt(kernel, agent_id);

    // History for the host: everything UP TO (but not including) the
    // assistant message we're about to spawn. The just-appended user
    // message IS included so the host has full context.
    let history_for_host = read_history(agent_id, &client_id);
    let history_json =
        serde_json::to_string(&history_for_host).unwrap_or_else(|_| "[]".to_string());

    // Record the in-flight entry BEFORE calling the host — push_token
    // could fire synchronously on the same thread and would otherwise
    // miss the entry.
    streams().lock().expect("streams poisoned").insert(
        stream_id.clone(),
        InFlight {
            agent_id: agent_id.clone(),
            client_id: client_id.clone(),
            message_id: message_id.clone(),
            started_at: now_secs(),
            accumulated: String::new(),
            interrupted: false,
            completed: false,
            error: None,
        },
    );

    // Fetch the current tool registry — empty array if the tools
    // agent isn't present or holds nothing. The LLM-using bundle
    // ALWAYS pulls this; per-call opt-in is intentionally absent.
    let tools_json = fetch_tools_json(kernel).await;

    if let Some(h) = host() {
        h.stream_response(
            stream_id.clone(),
            system_prompt,
            history_json,
            text.to_string(),
            tools_json,
        );
    }

    json!({
        "queued": true,
        "stream_id": stream_id,
        "message_id": message_id,
        "client_id": client_id,
    })
}

fn history(agent_id: &AgentId, payload: &Value) -> Value {
    let client_id = payload
        .get("client_id")
        .and_then(Value::as_str)
        .unwrap_or(DEFAULT_CLIENT_ID);
    let messages = read_history(agent_id, client_id);
    json!({ "messages": messages, "client_id": client_id })
}

async fn interrupt(kernel: &Arc<Kernel>, agent_id: &AgentId, payload: &Value) -> Value {
    let client_id = payload
        .get("client_id")
        .and_then(Value::as_str)
        .unwrap_or(DEFAULT_CLIENT_ID);
    // Find the in-flight stream for this (agent_id, client_id).
    let stream_entry = streams()
        .lock()
        .expect("streams poisoned")
        .iter()
        .find(|(_, s)| &s.agent_id == agent_id && s.client_id == client_id)
        .map(|(k, v)| (k.clone(), v.clone()));
    let Some((stream_id, entry)) = stream_entry else {
        return json!({"interrupted": false, "reason": "no in-flight stream"});
    };
    // Tell the host to stop.
    if let Some(h) = host() {
        h.cancel(stream_id.clone());
    }
    // Mark interrupted + emit done. The bundle is the source of
    // truth — even if the host doesn't honour cancel(), our state is
    // already consistent.
    let _ = update_stream(&stream_id, |s| {
        s.interrupted = true;
        s.completed = true;
        Some(())
    });
    // Persist the interrupted assistant message to history.
    push_history_message(
        agent_id,
        client_id,
        json!({
            "id": entry.message_id,
            "role": "assistant",
            "content": entry.accumulated.clone(),
            "complete": true,
            "interrupted": true,
        }),
        kernel,
    );
    let ev = json!({
        "type": "done",
        "stream_id": &stream_id,
        "message_id": entry.message_id,
        "accumulated": entry.accumulated.clone(),
        "interrupted": true,
    });
    emit_to_caller(kernel, &entry.agent_id, client_id, ev).await;
    streams()
        .lock()
        .expect("streams poisoned")
        .remove(&stream_id);
    json!({"interrupted": true})
}

// ── helpers ────────────────────────────────────────────────────────

struct HostProbes {
    apple_intelligence_available: bool,
    model_available: bool,
    backend_registered: bool,
}

fn probe_host() -> HostProbes {
    match host() {
        Some(h) => HostProbes {
            apple_intelligence_available: h.is_available(),
            model_available: h.model_available(),
            backend_registered: true,
        },
        None => HostProbes {
            apple_intelligence_available: false,
            model_available: false,
            backend_registered: false,
        },
    }
}

/// Fetch the current tool registry as a JSON string ready to hand
/// to the host. Returns `"[]"` when no tools agent is present, the
/// tools agent answers an unexpected shape, or the registry is empty.
/// Graceful — never blocks `send` on tool-registry trouble.
async fn fetch_tools_json(kernel: &Arc<Kernel>) -> String {
    let reply = kernel
        .send(&AgentId::from("tools"), json!({"type":"list_for_llm"}))
        .await;
    match reply.get("tools") {
        Some(arr @ Value::Array(_)) => {
            serde_json::to_string(arr).unwrap_or_else(|_| "[]".to_string())
        }
        _ => "[]".to_string(),
    }
}

fn agent_system_prompt(kernel: &Arc<Kernel>, agent_id: &AgentId) -> String {
    kernel
        .agents
        .get(agent_id)
        .and_then(|e| {
            e.value().meta.read().ok().and_then(|m| {
                m.get("system_prompt")
                    .and_then(Value::as_str)
                    .map(str::to_string)
            })
        })
        .unwrap_or_else(|| {
            "You are a helpful assistant running on Apple Foundation Models.".to_string()
        })
}

#[cfg(test)]
mod tests;
