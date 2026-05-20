//! Bundle plugin trait + compile-time registry.
//!
//! Bundles aren't dynamically loaded — every Rust bundle is a crate
//! linked into the binary at compile time. The CLI crate links the
//! default set; the UniFFI crate links a platform-appropriate subset.
//! (Optional `libloading` for `installed_agents/*/lib*.dylib` lands
//! behind a non-iOS feature flag in a later phase.)
//!
//! ## Contract
//!
//! Every bundle implements [`Bundle`]. The substrate calls `handle`
//! for any verb the Agent's system-verb table doesn't claim. Bundle
//! authors return `None` to mean "no reply" (fire-and-forget — the
//! Python equivalent is returning `None` from the handler).
//!
//! Lifecycle hooks:
//! - `on_delete` fires depth-first during cascade-delete BEFORE the
//!   agent unregisters from `kernel.agents`. Tear down process-memory
//!   state (open files, in-flight tasks). Substrate then rmtrees the
//!   agent's directory unless `ephemeral` is set.
//! - `on_shutdown` fires during graceful kernel shutdown. The default
//!   delegates to `on_delete`. Override if "tearing down, will
//!   restart" should behave differently from "gone forever".

use crate::agent::AgentId;
use async_trait::async_trait;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Arc;

/// Reply envelope. `None` = no reply (fire-and-forget); `Some(v)` =
/// caller receives `v` as the `kernel.send` return value.
pub type Reply = Option<Value>;

/// Plugin trait. Every Rust bundle implements this.
#[async_trait]
pub trait Bundle: Send + Sync {
    /// Stable bundle name. Matches what's stored in agent.json's
    /// `handler_module` (e.g. `"file.tools"`, `"web.tools"`).
    fn name(&self) -> &str;

    /// Dispatch a verb. `payload["type"]` names the verb. Substrate
    /// guarantees `payload` is an `Object` shape.
    ///
    /// Return `Ok(Some(value))` for normal replies, `Ok(None)` for
    /// fire-and-forget verbs (e.g. emit-style notifications).
    /// `Err` surfaces a substrate-level failure; domain errors should
    /// be returned as `Ok(Some(json!({"error": "..."})))`.
    async fn handle(
        &self,
        agent_id: &AgentId,
        payload: &Value,
    ) -> Result<Reply, Box<dyn std::error::Error + Send + Sync>>;

    /// Pre-detach hook. Default: noop.
    async fn on_delete(
        &self,
        _agent_id: &AgentId,
    ) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        Ok(())
    }

    /// Pre-shutdown hook. Default: delegate to on_delete.
    async fn on_shutdown(
        &self,
        agent_id: &AgentId,
    ) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        self.on_delete(agent_id).await
    }

    /// Optional readme text seeded into the agent's dir on creation.
    /// Default: empty (no readme). Bundles override with
    /// `include_str!("readme.md")` to ship their description.
    fn readme(&self) -> Option<&'static str> {
        None
    }
}

/// Compile-time bundle registry. Maps `handler_module` strings (as
/// stored in agent.json) to the implementing bundle.
///
/// Populated by the binary's `main()` before kernel bootstrap. Cloned
/// `Arc<dyn Bundle>` references go into the kernel's lookup table.
#[derive(Default)]
pub struct BundleRegistry {
    by_handler: HashMap<String, Arc<dyn Bundle>>,
}

impl BundleRegistry {
    /// Empty registry.
    pub fn new() -> Self {
        Self::default()
    }

    /// Register a bundle under its `handler_module` key.
    ///
    /// The key is what appears in `agent.json` — e.g. `"file.tools"`
    /// for the file bundle. Bundle authors choose this string; the
    /// substrate doesn't enforce a naming scheme.
    pub fn register<B: Bundle + 'static>(&mut self, handler_module: &str, bundle: B) {
        self.by_handler
            .insert(handler_module.to_string(), Arc::new(bundle));
    }

    /// Look up a bundle by `handler_module` key. Returns `None` for
    /// unknown — caller decides whether that's a hard error (live
    /// dispatch) or a weak-load skip (rehydration).
    pub fn get(&self, handler_module: &str) -> Option<Arc<dyn Bundle>> {
        self.by_handler.get(handler_module).cloned()
    }

    /// Iterate registered (handler_module, bundle) pairs. Used by
    /// `reflect` to enumerate `available_bundles`.
    pub fn iter(&self) -> impl Iterator<Item = (&str, &Arc<dyn Bundle>)> {
        self.by_handler.iter().map(|(k, v)| (k.as_str(), v))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    struct FakeBundle;

    #[async_trait]
    impl Bundle for FakeBundle {
        fn name(&self) -> &str {
            "fake"
        }
        async fn handle(
            &self,
            _agent_id: &AgentId,
            _payload: &Value,
        ) -> Result<Reply, Box<dyn std::error::Error + Send + Sync>> {
            Ok(Some(json!({"ok": true})))
        }
    }

    #[tokio::test]
    async fn register_and_lookup() {
        let mut reg = BundleRegistry::new();
        reg.register("fake.tools", FakeBundle);
        let b = reg.get("fake.tools").expect("registered");
        let reply = b
            .handle(&AgentId::from("x"), &json!({"type": "ping"}))
            .await
            .unwrap();
        assert_eq!(reply, Some(json!({"ok": true})));
    }

    #[test]
    fn unknown_handler_returns_none() {
        let reg = BundleRegistry::new();
        assert!(reg.get("nope.tools").is_none());
    }
}
