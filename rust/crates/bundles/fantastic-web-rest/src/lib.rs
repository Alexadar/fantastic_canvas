//! REST verb channel — thin compat bundle.
//!
//! The actual REST routes (POST + `_reflect` GET helpers) live inside
//! [`fantastic-web`]'s axum router. This crate's presence in the
//! registry exists so workdirs persisting `handler_module:
//! "web_rest.tools"` records continue to rehydrate cleanly.
//!
//! Verbs:
//! - `reflect` — `{id, sentence, mounted_on}`
//! - `boot` / `shutdown` — no-op.

#![deny(missing_docs)]

use async_trait::async_trait;
use fantastic_kernel::bundle::{Bundle, BundleError, Reply};
use fantastic_kernel::{AgentId, Kernel};
use serde_json::{json, Value};
use std::sync::Arc;

/// `handler_module` key under which this bundle registers.
pub const HANDLER_MODULE: &str = "web_rest.tools";

/// readme.md auto-seeded into the agent's dir on creation.
pub const README: &str = include_str!("readme.md");

/// The REST verb-channel bundle.
pub struct WebRestBundle;

#[async_trait]
impl Bundle for WebRestBundle {
    fn name(&self) -> &str {
        "web_rest"
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
                let mounted_on = kernel
                    .agents
                    .get(agent_id)
                    .and_then(|e| e.parent_id.clone())
                    .map(|p| p.0)
                    .unwrap_or_default();
                json!({
                    "id": agent_id.as_str(),
                    "sentence": "REST verb channel (served by parent web agent).",
                    "mounted_on": mounted_on,
                    "verbs": {
                        "reflect": "Identity + parent web agent id. No args.",
                        "boot": "No-op (REST routes come up with the parent web agent).",
                        "shutdown": "No-op.",
                    }
                })
            }
            "boot" | "shutdown" => Value::Null,
            other => json!({"error": format!("unknown verb {other:?}")}),
        };
        Ok(Some(reply))
    }
}

#[cfg(test)]
mod tests;
