//! axum HTTP host bundle.
//!
//! Each `web` agent owns a `port` field on its record (REQUIRED — no
//! default). On `boot`, spawns an axum listener on `0.0.0.0:<port>`
//! serving the standard rendering routes:
//!
//! | route                          | what                                          |
//! |--------------------------------|-----------------------------------------------|
//! | `GET  /`                       | root index (link tree of served agents)       |
//! | `GET  /<id>/`                  | dispatch `render_html` on agent + inject transport.js |
//! | `GET  /<id>/file/<path>`       | proxy to the file agent's `read` verb         |
//! | `GET  /transport.js`           | the JS client embedded at compile-time        |
//! | `GET  /favicon.ico`            | embedded favicon                              |
//!
//! Verb-invocation surfaces (WS, REST) are NOT served here — they
//! live in sibling `fantastic-web-ws` / `fantastic-web-rest` agents
//! that mount onto the same router via their own listen ports
//! (Phase 1 keeps each surface on its own port; multi-port mounting
//! is a future hardening).
//!
//! ### Verbs
//!
//! - `reflect` → `{id, sentence, port, running}`
//! - `boot`    → spawn the server task, store its handle. Idempotent.
//! - `stop`    → cancel the task. Idempotent.
//! - `shutdown`→ alias of `stop`.

#![deny(missing_docs)]

use async_trait::async_trait;
use axum::{
    extract::{ws::Message, ws::WebSocket, Json, Path as AxPath, Query, State, WebSocketUpgrade},
    http::{header, StatusCode},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
    Router,
};
use fantastic_kernel::bundle::{Bundle, BundleError, Reply};
use fantastic_kernel::{AgentId, Kernel};
use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::{Arc, Mutex};
use tokio::task::JoinHandle;

/// `handler_module` key under which this bundle registers.
pub const HANDLER_MODULE: &str = "web.tools";

/// readme.md auto-seeded into the agent's dir on creation.
pub const README: &str = include_str!("readme.md");

/// `transport.js` body — the client transport script served at
/// `/transport.js` AND injected into every `<id>/` render. Plain
/// JavaScript; no Rust code expects it to round-trip.
pub const TRANSPORT_JS: &str = include_str!("transport.js");

/// Static `/` index — link tree placeholder.
pub const ROOT_INDEX_HTML: &str = include_str!("index.html");

/// Live web servers, keyed by web-agent id. Holds the JoinHandle so
/// `stop` / `on_delete` can cancel cleanly.
pub(crate) static SERVERS: once_cell_lock::OnceLockMap = once_cell_lock::OnceLockMap::new();

mod once_cell_lock {
    use super::*;
    use std::sync::OnceLock;
    /// Lazy-initialized concurrent map of web-agent id → JoinHandle.
    pub struct OnceLockMap(OnceLock<Mutex<HashMap<AgentId, JoinHandle<()>>>>);
    impl OnceLockMap {
        pub const fn new() -> Self {
            Self(OnceLock::new())
        }
        pub fn lock(&self) -> std::sync::MutexGuard<'_, HashMap<AgentId, JoinHandle<()>>> {
            self.0
                .get_or_init(|| Mutex::new(HashMap::new()))
                .lock()
                .expect("SERVERS poisoned")
        }
    }
}

/// Shared state available to every axum handler.
#[derive(Clone)]
struct AppState {
    /// Reference to the live kernel so handlers can `kernel.send(...)`.
    kernel: Arc<Kernel>,
    /// This web agent's id (used to look up port + render parent context).
    #[allow(dead_code)]
    web_agent_id: AgentId,
}

/// The HTTP host bundle.
pub struct WebBundle;

#[async_trait]
impl Bundle for WebBundle {
    fn name(&self) -> &str {
        "web"
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
            "reflect" => reflect_reply(agent_id, kernel).await,
            "boot" => boot_reply(agent_id, kernel).await,
            "stop" | "shutdown" => stop_reply(agent_id),
            other => json!({"error": format!("unknown verb {other:?}")}),
        };
        Ok(Some(reply))
    }

    async fn on_delete(
        &self,
        agent_id: &AgentId,
        _kernel: &Arc<Kernel>,
    ) -> Result<(), BundleError> {
        let _ = stop_reply(agent_id);
        Ok(())
    }
}

async fn reflect_reply(agent_id: &AgentId, kernel: &Arc<Kernel>) -> Value {
    let port = read_port(agent_id, kernel);
    let running = SERVERS.lock().contains_key(agent_id);
    json!({
        "id": agent_id.as_str(),
        "sentence": "axum HTTP host.",
        "port": port,
        "running": running,
        "verbs": {
            "reflect": "Identity + bound port + running flag. No args.",
            "boot": "Spawn the listener on `port`. Idempotent.",
            "stop": "Cancel the listener task. Idempotent.",
            "shutdown": "Alias of stop.",
        }
    })
}

async fn boot_reply(agent_id: &AgentId, kernel: &Arc<Kernel>) -> Value {
    if SERVERS.lock().contains_key(agent_id) {
        return json!({"id": agent_id.as_str(), "running": true, "already_booted": true});
    }
    let port = match read_port(agent_id, kernel) {
        Some(p) => p,
        None => {
            return json!({"error": format!(
                "web {}: port is required (no default). Set via update_agent.",
                agent_id
            )})
        }
    };
    let state = AppState {
        kernel: Arc::clone(kernel),
        web_agent_id: agent_id.clone(),
    };
    let app = build_router(state);
    let addr: SocketAddr = ([127, 0, 0, 1], port).into();
    let listener = match tokio::net::TcpListener::bind(addr).await {
        Ok(l) => l,
        Err(e) => return json!({"error": format!("bind {addr}: {e}")}),
    };
    let actual_port = match listener.local_addr() {
        Ok(a) => a.port(),
        Err(_) => port,
    };
    let serve = axum::serve(listener, app);
    let task = tokio::spawn(async move {
        if let Err(e) = serve.await {
            tracing::warn!(error = %e, "web: axum serve exited with error");
        }
    });
    SERVERS.lock().insert(agent_id.clone(), task);
    json!({
        "id": agent_id.as_str(),
        "running": true,
        "port": actual_port,
    })
}

fn stop_reply(agent_id: &AgentId) -> Value {
    let removed = SERVERS.lock().remove(agent_id);
    if let Some(task) = removed {
        task.abort();
        json!({"id": agent_id.as_str(), "stopped": true})
    } else {
        json!({"id": agent_id.as_str(), "stopped": false, "reason": "not running"})
    }
}

fn read_port(agent_id: &AgentId, kernel: &Kernel) -> Option<u16> {
    let agent = kernel.agents.get(agent_id).map(|e| Arc::clone(&e))?;
    let meta = agent.meta.read().expect("meta poisoned").clone();
    meta.get("port").and_then(|v| v.as_u64()).map(|p| p as u16)
}

fn build_router(state: AppState) -> Router {
    // Order matters for axum's matchit: place literal-segment routes
    // (transport.js, favicon, agent ws / _reflect / _reflect/{target})
    // before parametric ones so the trie disambiguates correctly.
    // The file proxy uses `:agent_id/file/*path` syntax so the
    // wildcard sits at the trailing position cleanly.
    Router::new()
        .route("/", get(serve_root_index))
        .route("/transport.js", get(serve_transport_js))
        .route("/favicon.ico", get(serve_favicon))
        .route("/:agent_id/ws", get(serve_ws))
        .route("/:agent_id/_reflect", get(serve_rest_reflect_root))
        .route("/:agent_id/_reflect/:target_id", get(serve_rest_reflect))
        .route("/:agent_id/file/*path", get(serve_file_proxy))
        .route("/:agent_id/", get(serve_agent_render))
        .route("/:rest_id/:target_id", post(serve_rest_post))
        .with_state(state)
}

async fn serve_root_index() -> impl IntoResponse {
    Html(ROOT_INDEX_HTML)
}

async fn serve_transport_js() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "application/javascript")],
        TRANSPORT_JS,
    )
}

async fn serve_favicon() -> Response {
    // 1x1 transparent PNG as a minimal placeholder favicon. Browsers
    // stop spamming the kernel with 404s.
    const FAVICON: &[u8] = &[
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44,
        0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1f,
        0x15, 0xc4, 0x89, 0x00, 0x00, 0x00, 0x0a, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x63, 0x00,
        0x01, 0x00, 0x00, 0x05, 0x00, 0x01, 0x0d, 0x0a, 0x2d, 0xb4, 0x00, 0x00, 0x00, 0x00, 0x49,
        0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
    ];
    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "image/png")],
        FAVICON,
    )
        .into_response()
}

async fn serve_agent_render(
    State(state): State<AppState>,
    AxPath(agent_id): AxPath<String>,
) -> Response {
    let target = AgentId::from(agent_id.as_str());
    let reply = state
        .kernel
        .send(&target, json!({"type": "render_html"}))
        .await;
    // Successful response: {html: "..."}.
    if let Some(html) = reply.get("html").and_then(Value::as_str) {
        let injected = inject_transport(html);
        return Html(injected).into_response();
    }
    if let Some(err) = reply.get("error").and_then(Value::as_str) {
        return (
            StatusCode::NOT_FOUND,
            [(header::CONTENT_TYPE, "text/plain")],
            format!("agent {agent_id}: {err}"),
        )
            .into_response();
    }
    (
        StatusCode::NOT_FOUND,
        [(header::CONTENT_TYPE, "text/plain")],
        format!("agent {agent_id}: no render_html reply"),
    )
        .into_response()
}

async fn serve_file_proxy(
    State(state): State<AppState>,
    AxPath((agent_id, path)): AxPath<(String, String)>,
) -> Response {
    let target = AgentId::from(agent_id.as_str());
    let reply = state
        .kernel
        .send(&target, json!({"type": "read", "path": path}))
        .await;
    if let Some(content) = reply.get("content").and_then(Value::as_str) {
        let mime = guess_mime(&path);
        return (
            StatusCode::OK,
            [(header::CONTENT_TYPE, mime)],
            content.to_string(),
        )
            .into_response();
    }
    if let Some(img) = reply.get("image_base64").and_then(Value::as_str) {
        let mime = reply
            .get("mime")
            .and_then(Value::as_str)
            .unwrap_or("application/octet-stream");
        use base64::Engine;
        if let Ok(bytes) = base64::engine::general_purpose::STANDARD.decode(img) {
            return (StatusCode::OK, [(header::CONTENT_TYPE, mime)], bytes).into_response();
        }
    }
    let msg = reply
        .get("error")
        .and_then(Value::as_str)
        .map(str::to_string)
        .unwrap_or_else(|| format!("agent {agent_id}: no file content"));
    (
        StatusCode::NOT_FOUND,
        [(header::CONTENT_TYPE, "text/plain")],
        msg,
    )
        .into_response()
}

/// Inject `<script src="/transport.js"></script>` before `</head>` if
/// present, else at the top of the body.
fn inject_transport(html: &str) -> String {
    const TAG: &str = "<script src=\"/transport.js\"></script>";
    if html.contains(TAG) {
        return html.to_string();
    }
    if let Some(idx) = html.find("</head>") {
        let (head, tail) = html.split_at(idx);
        format!("{head}{TAG}\n{tail}")
    } else {
        format!("{TAG}\n{html}")
    }
}

fn guess_mime(path: &str) -> &'static str {
    let lower = path.to_lowercase();
    if lower.ends_with(".html") || lower.ends_with(".htm") {
        "text/html; charset=utf-8"
    } else if lower.ends_with(".css") {
        "text/css; charset=utf-8"
    } else if lower.ends_with(".js") {
        "application/javascript"
    } else if lower.ends_with(".json") {
        "application/json"
    } else if lower.ends_with(".png") {
        "image/png"
    } else if lower.ends_with(".jpg") || lower.ends_with(".jpeg") {
        "image/jpeg"
    } else if lower.ends_with(".svg") {
        "image/svg+xml"
    } else {
        "text/plain; charset=utf-8"
    }
}

// ─── WebSocket surface ──────────────────────────────────────────────
//
// `ws://host/<agent_id>/ws` — frame protocol per docs/_proxy.py:
//   C→S {type:"call",  target, payload, id}     → kernel.send → reply
//   C→S {type:"emit",  target, payload}         → kernel.emit (no reply)
//   C→S {type:"watch", src}                     → register synthetic watcher
//   C→S {type:"unwatch", src}                   → unregister
//   S→C {type:"reply", id, data} | {type:"error", id, error}
//   S→C {type:"event", payload}                 → drained from watcher inbox
//
// Binary frames are deferred to a later milestone.

async fn serve_ws(
    State(state): State<AppState>,
    AxPath(_agent_id): AxPath<String>,
    upgrade: WebSocketUpgrade,
) -> Response {
    upgrade.on_upgrade(move |socket| ws_loop(state, socket))
}

async fn ws_loop(state: AppState, socket: WebSocket) {
    use std::sync::atomic::{AtomicU64, Ordering};
    static NEXT_CLIENT_HEX: AtomicU64 = AtomicU64::new(0);
    let n = NEXT_CLIENT_HEX.fetch_add(1, Ordering::SeqCst);
    let client_id = AgentId::from(format!("_ws_{n:06x}").as_str());

    let (mut sink, mut stream) = socket.split();

    // Spawn a watcher-drain task: pulls events from the client's
    // auto-vivified inbox and serializes them as {type:"event"} frames.
    // We need a separate channel because axum's split sink is single-
    // consumer; the inbox receiver lives in the kernel.
    let (out_tx, mut out_rx) = tokio::sync::mpsc::channel::<String>(state.kernel.inbox_bound);
    // Hook the synthetic client inbox into the kernel.
    let (inbox_tx, mut inbox_rx) = tokio::sync::mpsc::channel::<Value>(state.kernel.inbox_bound);
    state.kernel.inboxes.insert(client_id.clone(), inbox_tx);

    let drain_task = tokio::spawn({
        let out_tx = out_tx.clone();
        async move {
            while let Some(payload) = inbox_rx.recv().await {
                let frame = serde_json::json!({"type": "event", "payload": payload});
                let line = match serde_json::to_string(&frame) {
                    Ok(s) => s,
                    Err(_) => continue,
                };
                if out_tx.send(line).await.is_err() {
                    break;
                }
            }
        }
    });

    // Outbound forwarder: anything written to out_tx hits the socket.
    let send_task = tokio::spawn(async move {
        while let Some(line) = out_rx.recv().await {
            if sink.send(Message::Text(line)).await.is_err() {
                break;
            }
        }
    });

    // Inbound loop: parse text frames, dispatch.
    while let Some(msg) = stream.next().await {
        let text = match msg {
            Ok(Message::Text(t)) => t,
            Ok(Message::Close(_)) | Err(_) => break,
            _ => continue,
        };
        let Ok(env): Result<Value, _> = serde_json::from_str(&text) else {
            continue;
        };
        let ty = env.get("type").and_then(Value::as_str).unwrap_or("");
        let target = env.get("target").and_then(Value::as_str).map(AgentId::from);
        let payload = env.get("payload").cloned().unwrap_or(Value::Null);
        let id = env.get("id").and_then(Value::as_str).map(str::to_string);
        let kernel = Arc::clone(&state.kernel);
        let sender_for_scope = client_id.clone();
        let out = out_tx.clone();
        match ty {
            "call" => {
                let Some(target) = target else {
                    if let Some(id) = id {
                        let _ = out
                            .send(
                                serde_json::json!({"type":"error","id":id,"error":"call requires target"})
                                    .to_string(),
                            )
                            .await;
                    }
                    continue;
                };
                tokio::spawn(async move {
                    let reply = fantastic_kernel::send::with_sender(sender_for_scope, async {
                        kernel.send(&target, payload).await
                    })
                    .await;
                    if let Some(id) = id {
                        let frame = if reply.get("error").is_some() {
                            serde_json::json!({
                                "type": "error",
                                "id": id,
                                "error": reply
                                    .get("error")
                                    .and_then(Value::as_str)
                                    .unwrap_or("error")
                                    .to_string(),
                            })
                        } else {
                            serde_json::json!({
                                "type": "reply",
                                "id": id,
                                "data": reply,
                            })
                        };
                        let _ = out.send(frame.to_string()).await;
                    }
                });
            }
            "emit" => {
                let Some(target) = target else { continue };
                tokio::spawn(async move {
                    fantastic_kernel::send::with_sender(sender_for_scope, async {
                        kernel.emit(&target, payload).await
                    })
                    .await;
                });
            }
            "watch" => {
                let Some(src) = env.get("src").and_then(Value::as_str).map(AgentId::from) else {
                    continue;
                };
                kernel.watch(&src, client_id.clone()).await;
            }
            "unwatch" => {
                let Some(src) = env.get("src").and_then(Value::as_str).map(AgentId::from) else {
                    continue;
                };
                kernel.unwatch(&src, &client_id).await;
            }
            _ => {}
        }
    }

    // Cleanup.
    state.kernel.inboxes.remove(&client_id);
    drain_task.abort();
    send_task.abort();
}

// ─── REST surface ───────────────────────────────────────────────────
//
// POST /<rest_id>/<target_id> body=<payload-json> → kernel.send → JSON.
// GET  /<rest_id>/_reflect[/<target_id>][?readme=1]               → reflect helper.

#[derive(serde::Deserialize)]
struct ReflectQuery {
    readme: Option<u8>,
}

async fn serve_rest_post(
    State(state): State<AppState>,
    AxPath((rest_id, target_id)): AxPath<(String, String)>,
    Json(payload): Json<Value>,
) -> Response {
    let target = AgentId::from(target_id.as_str());
    let sender = AgentId::from(rest_id.as_str());
    let reply = fantastic_kernel::send::with_sender(sender, async {
        state.kernel.send(&target, payload).await
    })
    .await;
    let status = if reply.get("error").is_some() {
        StatusCode::BAD_REQUEST
    } else {
        StatusCode::OK
    };
    (
        status,
        [(header::CONTENT_TYPE, "application/json")],
        reply.to_string(),
    )
        .into_response()
}

async fn serve_rest_reflect_root(
    State(state): State<AppState>,
    AxPath(rest_id): AxPath<String>,
    Query(q): Query<ReflectQuery>,
) -> Response {
    let sender = AgentId::from(rest_id.as_str());
    let target = AgentId::from("kernel");
    let payload = serde_json::json!({
        "type": "reflect",
        "return_readme": q.readme.unwrap_or(0) != 0,
    });
    let reply = fantastic_kernel::send::with_sender(sender, async {
        state.kernel.send(&target, payload).await
    })
    .await;
    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "application/json")],
        reply.to_string(),
    )
        .into_response()
}

async fn serve_rest_reflect(
    State(state): State<AppState>,
    AxPath((rest_id, target_id)): AxPath<(String, String)>,
    Query(q): Query<ReflectQuery>,
) -> Response {
    let sender = AgentId::from(rest_id.as_str());
    let target = AgentId::from(target_id.as_str());
    let payload = serde_json::json!({
        "type": "reflect",
        "return_readme": q.readme.unwrap_or(0) != 0,
    });
    let reply = fantastic_kernel::send::with_sender(sender, async {
        state.kernel.send(&target, payload).await
    })
    .await;
    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "application/json")],
        reply.to_string(),
    )
        .into_response()
}

// base64 is a transitive dep — re-declare via fantastic-kernel's
// indirect graph. Pull it in via Cargo.toml if not already there.
#[allow(unused_imports)]
use base64 as _;

#[cfg(test)]
mod tests;
