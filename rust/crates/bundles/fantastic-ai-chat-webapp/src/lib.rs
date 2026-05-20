//! Provider-agnostic chat UI front-end.
//!
//! Holds an `upstream_id` pointing at a backend that answers `send`,
//! `history`, `interrupt` (and emits `token`/`done`/`queued`/`status`).
//! Any backend matching that surface (ollama, NVIDIA NIM, …) works
//! without changes here.
//!
//! ## Verbs
//!
//! - `reflect` → `{id, sentence, upstream_id, provider, verbs}`.
//!   `provider` defaults to `"ollama"`.
//! - `boot` — **Rust phase 1**: if `upstream_id` is set on the record,
//!   returns `{ok: true, upstream_id}`. If unset, returns an error —
//!   provider auto-spawn is deferred until the ollama_backend is
//!   ported. Set `upstream_id` manually via `update_agent`.
//! - `shutdown` → no-op.
//! - `render_html` → `{html}` — the embedded chat page; `transport.js`
//!   is injected by the web bundle on serve.
//! - `get_webapp` → `{url, default_width, default_height, title}` —
//!   makes this agent canvas-eligible.

#![deny(missing_docs)]

use async_trait::async_trait;
use fantastic_kernel::bundle::{Bundle, BundleError, Reply};
use fantastic_kernel::{AgentId, Kernel};
use serde_json::{json, Value};
use std::sync::Arc;

/// `handler_module` key under which this bundle registers.
pub const HANDLER_MODULE: &str = "ai_chat_webapp.tools";

/// readme.md auto-seeded into the agent's dir on creation.
pub const README: &str = include_str!("readme.md");

/// Embedded chat HTML (the JS frontend, served at `/<id>/`).
pub const CHAT_HTML: &str = include_str!("index.html");

/// The chat front-end bundle.
pub struct AiChatWebappBundle;

#[async_trait]
impl Bundle for AiChatWebappBundle {
    fn name(&self) -> &str {
        "ai_chat_webapp"
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
            "reflect" => reflect_reply(agent_id, kernel),
            "boot" => boot_reply(agent_id, kernel),
            "shutdown" => Value::Null,
            "render_html" => json!({"html": CHAT_HTML}),
            "get_webapp" => json!({
                "url": format!("/{}/", agent_id),
                "default_width": 480,
                "default_height": 600,
                "title": "chat",
            }),
            other => json!({"error": format!("ai_chat_webapp: unknown type {other:?}")}),
        };
        Ok(Some(reply))
    }
}

/// Read a string-typed meta field for the given agent, returning `None`
/// when the agent is missing or the field is absent / non-string.
fn meta_str(kernel: &Arc<Kernel>, agent_id: &AgentId, key: &str) -> Option<String> {
    kernel.agents.get(agent_id).and_then(|e| {
        e.meta
            .read()
            .expect("meta poisoned")
            .get(key)
            .and_then(Value::as_str)
            .map(str::to_string)
    })
}

fn reflect_reply(agent_id: &AgentId, kernel: &Arc<Kernel>) -> Value {
    let upstream = meta_str(kernel, agent_id, "upstream_id").unwrap_or_default();
    let provider = meta_str(kernel, agent_id, "provider").unwrap_or_else(|| "ollama".to_string());
    json!({
        "id": agent_id.as_str(),
        "sentence": "Chat UI fronting an upstream LLM backend.",
        "upstream_id": upstream,
        "provider": provider,
        "verbs": {
            "reflect": "Identity + upstream_id + provider. No args.",
            "boot": "Verify upstream_id is set; phase-1 no auto-spawn.",
            "shutdown": "No-op.",
            "render_html": "Return the embedded chat page.",
            "get_webapp": "Return iframeable URL + viewport defaults.",
        }
    })
}

fn boot_reply(agent_id: &AgentId, kernel: &Arc<Kernel>) -> Value {
    match meta_str(kernel, agent_id, "upstream_id") {
        Some(id) if !id.is_empty() => json!({"ok": true, "upstream_id": id}),
        _ => json!({
            "error": "ai_chat_webapp: upstream_id required (provider auto-spawn deferred to a later port — set upstream_id manually via update_agent)"
        }),
    }
}

#[cfg(test)]
mod tests;
