//! xterm UI front-end as an agent.
//!
//! Pairs with a `terminal_backend` (tracked via `upstream_id` on the
//! record) and serves a single HTML page that runs xterm.js in the
//! browser. The Python version auto-creates the backend as a child on
//! first `boot`; the Rust port leaves boot as a no-op for now —
//! `terminal_backend` is not yet ported, so the UI runs dormant when
//! `upstream_id` is unset and the page renders a configuration hint.
//!
//! ## Verbs
//!
//! - `reflect` → `{id, sentence, upstream_id, verbs}`
//! - `render_html` → `{html}` — the embedded xterm page;
//!   `transport.js` is injected by the web bundle on serve.
//! - `get_webapp` → `{url, default_width, default_height, title,
//!   header_buttons}` — makes this agent canvas-eligible and declares
//!   the autoscroll chip the iframe drives via the browser bus.
//! - `boot` / `shutdown` → no-op. The terminal_backend (when ported)
//!   owns its own PTY lifecycle.

#![deny(missing_docs)]

use async_trait::async_trait;
use fantastic_kernel::bundle::{Bundle, BundleError, Reply};
use fantastic_kernel::{AgentId, Kernel};
use serde_json::{json, Value};
use std::sync::Arc;

/// `handler_module` key under which this bundle registers.
pub const HANDLER_MODULE: &str = "terminal_webapp.tools";

/// readme.md auto-seeded into the agent's dir on creation.
pub const README: &str = include_str!("readme.md");

/// Embedded xterm HTML (the JS frontend, served at `/<id>/`).
pub const TERMINAL_HTML: &str = include_str!("index.html");

/// The xterm front-end bundle.
pub struct TerminalWebappBundle;

#[async_trait]
impl Bundle for TerminalWebappBundle {
    fn name(&self) -> &str {
        "terminal_webapp"
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
            "reflect" => {
                let upstream = kernel
                    .agents
                    .get(agent_id)
                    .and_then(|e| {
                        e.meta
                            .read()
                            .expect("meta poisoned")
                            .get("upstream_id")
                            .and_then(Value::as_str)
                            .map(str::to_string)
                    })
                    .unwrap_or_default();
                json!({
                    "id": agent_id.as_str(),
                    "sentence": "xterm UI fronting an upstream terminal backend.",
                    "upstream_id": upstream,
                    "verbs": {
                        "reflect": "Identity + upstream_id binding. No args.",
                        "render_html": "Return the embedded xterm page.",
                        "get_webapp": "Return iframeable URL + viewport defaults + header chips.",
                        "boot": "No-op (terminal_backend owns PTY lifecycle).",
                        "shutdown": "No-op.",
                    }
                })
            }
            "boot" | "shutdown" => Value::Null,
            "render_html" => json!({"html": TERMINAL_HTML}),
            "get_webapp" => json!({
                "url": format!("/{}/", agent_id),
                "default_width": 600,
                "default_height": 400,
                "title": "xterm",
                "header_buttons": [
                    {
                        "id": "autoscroll",
                        "glyph": "\u{21e3}",
                        "title": "Toggle autoscroll",
                        "toggle": true,
                    },
                ],
            }),
            other => json!({"error": format!("unknown verb {other:?}")}),
        };
        Ok(Some(reply))
    }
}

#[cfg(test)]
mod tests;
