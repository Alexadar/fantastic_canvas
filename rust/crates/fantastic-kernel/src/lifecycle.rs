//! Agent lifecycle: create, delete (with depth-first cascade +
//! on_delete hooks + disk cleanup), update.
//!
//! `create_agent` is dispatched on a parent — the new agent becomes
//! its child under `<parent.root_path>/agents/<new_id>/`. Substrate
//! mints the id from the bundle name + a 6-hex token unless caller
//! supplies one.
//!
//! `delete_agent` is dispatched on the substrate (target id in
//! payload). It refuses if the agent carries `delete_lock: true`.
//! Otherwise it walks the subtree depth-first, calls each bundle's
//! `on_delete` hook BEFORE unregistering from `kernel.agents`, and
//! rmtrees the dir (unless the agent is ephemeral).

use crate::agent::{Agent, AgentId};
use crate::kernel::Kernel;
use crate::persistence;
use serde_json::{json, Map, Value};
use std::sync::Arc;

/// Mint a fresh id from `handler_module` (`<bundle>.tools` →
/// `<bundle>_<hex6>`). Uses a thread-local PRNG seeded from std's
/// random source to keep things deterministic-free without adding
/// a `rand` dep at the kernel level.
pub fn mint_id(handler_module: &str) -> String {
    let bundle = handler_module
        .strip_suffix(".tools")
        .unwrap_or(handler_module);
    // Use the address of a stack allocation + current time as entropy.
    // Not cryptographic — only needs uniqueness within a workdir.
    use std::time::{SystemTime, UNIX_EPOCH};
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.subsec_nanos() as u64)
        .unwrap_or(0);
    let mut stack: u64 = 0;
    let stack_ptr = &mut stack as *mut u64 as u64;
    let mix = nanos ^ stack_ptr ^ std::process::id() as u64;
    let hex6 = format!("{:06x}", (mix as u32) & 0xff_ffff);
    format!("{bundle}_{hex6}")
}

/// Implementation of the `create_agent` system verb.
///
/// `payload` shape (matches the workdir wire format):
/// ```json
/// {"type":"create_agent","handler_module":"file.tools","id":"opt"}
/// ```
/// Any extra fields become the new agent's meta.
pub(crate) async fn create_from_payload(
    kernel: &Arc<Kernel>,
    parent: &Arc<Agent>,
    payload: &Value,
) -> Value {
    let Some(hm) = payload.get("handler_module").and_then(Value::as_str) else {
        return json!({ "error": "create_agent requires handler_module" });
    };
    // We allow creation of agents whose bundle isn't yet registered —
    // record persists, agent is registered but won't dispatch domain
    // verbs until the bundle lands. Matches Python's behaviour. Only
    // the LOAD path skips unknown bundles (weak-load semantics).

    let id = match payload.get("id").and_then(Value::as_str) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => mint_id(hm),
    };
    if kernel.agents.contains_key(&AgentId::from(id.as_str())) {
        return json!({ "error": format!("agent {id:?} already exists") });
    }

    // Compose meta from the remaining payload fields.
    let mut meta: Map<String, Value> = Map::new();
    if let Some(obj) = payload.as_object() {
        for (k, v) in obj {
            if matches!(k.as_str(), "type" | "id" | "handler_module" | "parent_id") {
                continue;
            }
            meta.insert(k.clone(), v.clone());
        }
    }

    let root_path = parent.children_dir().join(&id);
    let new_agent = Agent::new(
        AgentId::from(id.as_str()),
        Some(hm.to_string()),
        Some(parent.id.clone()),
        meta,
        root_path,
        false,
    );
    // Persist + seed readme (the bundle ships its readme via the
    // `Bundle::readme()` method; we read it from the registry).
    if let Err(e) = persistence::persist(&new_agent) {
        return json!({ "error": format!("persist: {e}") });
    }
    if let Some(bundle) = kernel.bundles.get(hm) {
        if let Some(readme) = bundle.readme() {
            let _ = persistence::seed_readme(&new_agent, readme);
        }
    }

    // Wire into kernel + parent.
    let _rx = kernel.register(Arc::clone(&new_agent));
    parent
        .children
        .insert(new_agent.id.clone(), Arc::clone(&new_agent));

    let event = json!({
        "type": "created",
        "id": new_agent.id.0,
        "parent_id": parent.id.0,
        "handler_module": hm,
    });
    kernel.publish_state(&event);

    serde_json::to_value(new_agent.record()).unwrap_or(Value::Null)
}

/// Implementation of the `delete_agent` system verb.
pub(crate) async fn delete_from_payload(
    kernel: &Arc<Kernel>,
    _caller: &Arc<Agent>,
    payload: &Value,
) -> Value {
    let Some(id_str) = payload.get("id").and_then(Value::as_str) else {
        return json!({ "error": "delete_agent requires id" });
    };
    let id = AgentId::from(id_str);
    let Some(target) = kernel.agents.get(&id).map(|e| Arc::clone(&e)) else {
        return json!({ "error": format!("no agent {id_str:?}") });
    };
    if target.is_delete_locked() {
        return json!({
            "error": "delete refused",
            "locked": true,
            "id": id.0,
        });
    }
    cascade_delete(kernel, &target).await;
    json!({ "deleted": true, "id": id.0 })
}

/// Depth-first delete: each leaf's `on_delete` hook fires before its
/// parent's; the agent unregisters from `kernel.agents` and parent's
/// `children` map only AFTER its hook completes successfully.
pub async fn cascade_delete(kernel: &Arc<Kernel>, target: &Arc<Agent>) {
    // Snapshot children first (since we mutate during iteration).
    let child_ids = target.child_ids();
    for cid in child_ids {
        if let Some(child) = kernel.agents.get(&cid).map(|e| Arc::clone(&e)) {
            Box::pin(cascade_delete(kernel, &child)).await;
        }
    }
    // on_delete hook.
    if let Some(hm) = target.handler_module.as_deref() {
        if let Some(bundle) = kernel.bundles.get(hm) {
            if let Err(e) = bundle.on_delete(&target.id, kernel).await {
                tracing::warn!(
                    agent = %target.id,
                    handler_module = %hm,
                    error = %e,
                    "on_delete hook errored; continuing cascade",
                );
            }
        }
    }
    // Detach from parent's children map.
    if let Some(parent_id) = target.parent_id.as_ref() {
        if let Some(parent) = kernel.agents.get(parent_id).map(|e| Arc::clone(&e)) {
            parent.children.remove(&target.id);
        }
    }
    // Unregister + drop inbox.
    kernel.unregister(&target.id);
    // Disk cleanup (skip ephemeral).
    if !target.ephemeral && target.root_path.exists() {
        let _ = std::fs::remove_dir_all(&target.root_path);
    }
    let event = json!({ "type": "removed", "id": target.id.0 });
    kernel.publish_state(&event);
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct CountingBundle {
        deletes: Arc<AtomicUsize>,
    }
    #[async_trait]
    impl crate::Bundle for CountingBundle {
        fn name(&self) -> &str {
            "counting"
        }
        async fn handle(
            &self,
            _id: &AgentId,
            _payload: &Value,
            _k: &Kernel,
        ) -> Result<crate::Reply, crate::bundle::BundleError> {
            Ok(None)
        }
        async fn on_delete(
            &self,
            _id: &AgentId,
            _k: &Kernel,
        ) -> Result<(), crate::bundle::BundleError> {
            self.deletes.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
    }

    fn mk_kernel(deletes: Arc<AtomicUsize>) -> Arc<Kernel> {
        let mut kernel = Kernel::new();
        kernel
            .bundles
            .register("counting.tools", CountingBundle { deletes });
        Arc::new(kernel)
    }

    #[tokio::test]
    async fn mint_id_format_is_bundle_underscore_hex6() {
        let id = mint_id("file.tools");
        assert!(id.starts_with("file_"));
        // 6 hex chars after the underscore.
        let suffix = &id["file_".len()..];
        assert_eq!(suffix.len(), 6);
        assert!(suffix.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[tokio::test]
    async fn create_then_delete_unregisters_and_calls_hook() {
        let tmp = tempfile::TempDir::new().unwrap();
        let deletes = Arc::new(AtomicUsize::new(0));
        let kernel = mk_kernel(Arc::clone(&deletes));
        // Stand up a root pointing at the tempdir.
        let root = Agent::new(
            AgentId::from("core"),
            None,
            None,
            Map::new(),
            tmp.path().to_path_buf(),
            false,
        );
        let _rx = kernel.register(Arc::clone(&root));
        kernel.set_root(Arc::clone(&root));

        // Create one child via the system verb.
        let v = kernel
            .send(
                &AgentId::from("core"),
                json!({"type": "create_agent", "handler_module": "counting.tools", "id": "kid_1"}),
            )
            .await;
        assert_eq!(v["id"], "kid_1");
        assert!(kernel.agents.contains_key(&AgentId::from("kid_1")));
        assert!(tmp.path().join("agents/kid_1/agent.json").exists());

        // Delete it.
        let v = kernel
            .send(
                &AgentId::from("core"),
                json!({"type": "delete_agent", "id": "kid_1"}),
            )
            .await;
        assert_eq!(v["deleted"], true);
        assert!(!kernel.agents.contains_key(&AgentId::from("kid_1")));
        assert_eq!(deletes.load(Ordering::SeqCst), 1);
        assert!(!tmp.path().join("agents/kid_1").exists());
    }

    #[tokio::test]
    async fn delete_refuses_locked() {
        let tmp = tempfile::TempDir::new().unwrap();
        let kernel = mk_kernel(Arc::new(AtomicUsize::new(0)));
        let root = Agent::new(
            AgentId::from("core"),
            None,
            None,
            Map::new(),
            tmp.path().to_path_buf(),
            false,
        );
        let _rx = kernel.register(Arc::clone(&root));
        kernel.set_root(Arc::clone(&root));
        kernel
            .send(
                &AgentId::from("core"),
                json!({"type": "create_agent", "handler_module": "counting.tools", "id": "locked_1", "delete_lock": true}),
            )
            .await;
        let v = kernel
            .send(
                &AgentId::from("core"),
                json!({"type": "delete_agent", "id": "locked_1"}),
            )
            .await;
        assert_eq!(v["locked"], true);
        assert!(kernel.agents.contains_key(&AgentId::from("locked_1")));
    }

    #[tokio::test]
    async fn cascade_delete_fires_hooks_depth_first() {
        let tmp = tempfile::TempDir::new().unwrap();
        let deletes = Arc::new(AtomicUsize::new(0));
        let kernel = mk_kernel(Arc::clone(&deletes));
        let root = Agent::new(
            AgentId::from("core"),
            None,
            None,
            Map::new(),
            tmp.path().to_path_buf(),
            false,
        );
        let _rx = kernel.register(Arc::clone(&root));
        kernel.set_root(Arc::clone(&root));
        kernel
            .send(
                &AgentId::from("core"),
                json!({"type": "create_agent", "handler_module": "counting.tools", "id": "p_1"}),
            )
            .await;
        kernel
            .send(
                &AgentId::from("p_1"),
                json!({"type": "create_agent", "handler_module": "counting.tools", "id": "c_1"}),
            )
            .await;
        kernel
            .send(
                &AgentId::from("p_1"),
                json!({"type": "create_agent", "handler_module": "counting.tools", "id": "c_2"}),
            )
            .await;
        // Delete parent — both children's hooks must fire too.
        kernel
            .send(
                &AgentId::from("core"),
                json!({"type": "delete_agent", "id": "p_1"}),
            )
            .await;
        // 3 hook fires (p_1 + c_1 + c_2).
        assert_eq!(deletes.load(Ordering::SeqCst), 3);
        assert!(!kernel.agents.contains_key(&AgentId::from("p_1")));
        assert!(!kernel.agents.contains_key(&AgentId::from("c_1")));
        assert!(!kernel.agents.contains_key(&AgentId::from("c_2")));
    }
}
