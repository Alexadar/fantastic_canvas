//! Spatial UI front-end as an agent.
//!
//! Pairs with a `canvas_backend` (the `upstream_id` on the record) and
//! serves a single HTML page that renders the backend's members as
//! positioned DOM iframes + optional GL views.
//!
//! ## Verbs
//!
//! - `reflect` → `{id, sentence, upstream_id}`
//! - `render_html` → `{html}` — the embedded canvas page;
//!   `transport.js` is injected by the web bundle on serve.
//! - `get_webapp` → `{url, default_width, default_height, title}` —
//!   makes this agent itself canvas-eligible.
//! - `boot` / `shutdown` → no-op.

#![deny(missing_docs)]

use async_trait::async_trait;
use fantastic_kernel::bundle::{Bundle, BundleError, Reply};
use fantastic_kernel::{AgentId, Kernel};
use serde_json::{json, Value};
use std::sync::Arc;

/// `handler_module` key under which this bundle registers.
pub const HANDLER_MODULE: &str = "canvas_webapp.tools";

/// readme.md auto-seeded into the agent's dir on creation.
pub const README: &str = include_str!("readme.md");

/// Embedded canvas HTML (the JS frontend, served at `/<id>/`).
pub const CANVAS_HTML: &str = include_str!("canvas.html");

/// The canvas front-end bundle.
pub struct CanvasWebappBundle;

#[async_trait]
impl Bundle for CanvasWebappBundle {
    fn name(&self) -> &str {
        "canvas_webapp"
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
                    "sentence": "Spatial UI front-end. Embeds members as iframes.",
                    "upstream_id": upstream,
                    "verbs": {
                        "reflect": "Identity + upstream_id. No args.",
                        "render_html": "Return the embedded canvas page.",
                        "get_webapp": "Return iframeable URL + viewport defaults.",
                        "boot": "No-op.",
                        "shutdown": "No-op.",
                    }
                })
            }
            "boot" | "shutdown" => Value::Null,
            "render_html" => json!({"html": CANVAS_HTML}),
            "get_webapp" => json!({
                "url": format!("/{}/", agent_id),
                "default_width": 800,
                "default_height": 600,
                "title": "canvas",
            }),
            other => json!({"error": format!("unknown verb {other:?}")}),
        };
        Ok(Some(reply))
    }
}

#[cfg(test)]
mod tests;
