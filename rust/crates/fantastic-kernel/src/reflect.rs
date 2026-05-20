//! `reflect` verb implementation — substrate primer (root) or per-agent
//! summary.
//!
//! Returns the same shape consumed by the workdir's wire protocol:
//!
//! - Root reflect → `primer` object (sentence, primitive, envelope,
//!   universal_verb, transports, tree, available_bundles, agent_count,
//!   binary_protocol, browser_bus).
//! - Per-agent reflect → tree-node summary (id, parent_id,
//!   handler_module, display_name, optional verbs / readme).

use crate::agent::Agent;
#[cfg(test)]
use crate::agent::AgentId;
use crate::kernel::Kernel;
use serde_json::{json, Map, Value};
use std::sync::Arc;

/// Top-level entry — substrate primer for root, node summary otherwise.
pub fn reflect(kernel: &Arc<Kernel>, target: &Arc<Agent>, payload: &Value) -> Value {
    let return_readme = payload
        .get("return_readme")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if target.parent_id.is_none() {
        primer(kernel, target, return_readme)
    } else {
        node_summary(target, return_readme)
    }
}

/// Walk an agent and its descendants, producing a nested
/// `{id, parent_id, handler_module, display_name, children:[...]}`
/// dict. Matches the shape consumed by callers (and Swift's
/// AgentLoader walker).
pub fn tree_node(target: &Agent) -> Value {
    let mut obj = Map::new();
    obj.insert("id".to_string(), json!(target.id.0));
    if let Some(p) = target.parent_id.as_ref() {
        obj.insert("parent_id".to_string(), json!(p.0));
    } else {
        obj.insert("parent_id".to_string(), Value::Null);
    }
    obj.insert(
        "handler_module".to_string(),
        match &target.handler_module {
            Some(s) => json!(s),
            None => Value::Null,
        },
    );
    obj.insert(
        "display_name".to_string(),
        target
            .display_name()
            .map(|s| json!(s))
            .unwrap_or_else(|| json!(target.id.0)),
    );
    let mut children: Vec<Value> = target
        .children
        .iter()
        .map(|entry| tree_node(entry.value()))
        .collect();
    children.sort_by(|a, b| {
        a.get("id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .cmp(b.get("id").and_then(Value::as_str).unwrap_or(""))
    });
    obj.insert("children".to_string(), Value::Array(children));
    Value::Object(obj)
}

fn primer(kernel: &Arc<Kernel>, root: &Arc<Agent>, return_readme: bool) -> Value {
    let available: Vec<Value> = kernel
        .bundles
        .iter()
        .map(|(handler_module, b)| {
            json!({
                "name": b.name(),
                "handler_module": handler_module,
            })
        })
        .collect();
    let mut obj = Map::new();
    obj.insert(
        "sentence".to_string(),
        json!("Fantastic kernel. Everything is reachable by sending messages to agents."),
    );
    obj.insert(
        "primitive".to_string(),
        json!("send(target_id, payload) -> reply | None"),
    );
    obj.insert(
        "envelope".to_string(),
        json!("{\"type\": \"<verb>\", ...fields}"),
    );
    obj.insert(
        "universal_verb".to_string(),
        json!("reflect — every agent answers it; returns identity + flat state dict."),
    );
    obj.insert(
        "transports".to_string(),
        json!({
            "in_process": {
                "shape": "kernel.send(target_id, payload).await",
                "use_when": "Rust code inside the kernel binary."
            },
            "ws": {
                "shape": "ws://host:port/<agent_id>/ws — frames: {type,target,payload,id}",
                "use_when": "browsers + AI agents (the canonical surface)."
            },
            "rest": {
                "shape": "POST http://host:port/<rest_id>/<target_id> body=payload",
                "use_when": "diagnostic CLI tools that want one-shot JSON over HTTP."
            }
        }),
    );
    obj.insert("tree".to_string(), tree_node(root));
    obj.insert("available_bundles".to_string(), Value::Array(available));
    obj.insert("agent_count".to_string(), json!(kernel.agents.len()));
    obj.insert(
        "binary_protocol".to_string(),
        json!({
            "shape": "[4-byte BE u32 H | H-byte JSON header | M-byte raw blob]",
            "header_field": "_binary_path",
        }),
    );
    obj.insert(
        "browser_bus".to_string(),
        json!({
            "shape": "BroadcastChannel('fantastic')",
            "envelope": "{type, ...payload}",
        }),
    );
    if return_readme {
        if let Ok(s) = std::fs::read_to_string(root.readme_file()) {
            obj.insert("readme".to_string(), json!(s));
        }
    }
    Value::Object(obj)
}

fn node_summary(target: &Arc<Agent>, return_readme: bool) -> Value {
    let mut obj = Map::new();
    obj.insert("id".to_string(), json!(target.id.0));
    obj.insert(
        "parent_id".to_string(),
        target
            .parent_id
            .as_ref()
            .map(|p| json!(p.0))
            .unwrap_or(Value::Null),
    );
    obj.insert(
        "handler_module".to_string(),
        target
            .handler_module
            .as_ref()
            .map(|s| json!(s))
            .unwrap_or(Value::Null),
    );
    obj.insert(
        "display_name".to_string(),
        target
            .display_name()
            .map(|s| json!(s))
            .unwrap_or_else(|| json!(target.id.0)),
    );
    // Flatten current meta into the reply for visibility.
    if let Ok(meta) = target.meta.read() {
        for (k, v) in meta.iter() {
            if obj.contains_key(k) {
                continue;
            }
            obj.insert(k.clone(), v.clone());
        }
    }
    if return_readme {
        if let Ok(s) = std::fs::read_to_string(target.readme_file()) {
            obj.insert("readme".to_string(), json!(s));
        }
    }
    Value::Object(obj)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::Agent;
    use std::path::Path;

    fn mk_agent(id: &str, parent: Option<AgentId>) -> Arc<Agent> {
        Agent::new(
            AgentId::from(id),
            None,
            parent,
            Map::new(),
            Path::new("/tmp/nowhere").join(id),
            true,
        )
    }

    #[test]
    fn tree_node_includes_id_and_empty_children() {
        let a = mk_agent("leaf", Some(AgentId::from("p")));
        let v = tree_node(&a);
        assert_eq!(v["id"], "leaf");
        assert_eq!(v["parent_id"], "p");
        assert_eq!(v["children"], json!([]));
    }

    #[tokio::test]
    async fn root_reflect_returns_primer_shape() {
        let kernel = Arc::new(Kernel::new());
        let root = mk_agent("core", None);
        let _rx = kernel.register(Arc::clone(&root));
        kernel.set_root(Arc::clone(&root));
        let v = reflect(&kernel, &root, &json!({"type": "reflect"}));
        assert!(v.is_object());
        // Required primer keys.
        for k in [
            "sentence",
            "primitive",
            "envelope",
            "universal_verb",
            "transports",
            "tree",
            "available_bundles",
            "agent_count",
            "binary_protocol",
            "browser_bus",
        ] {
            assert!(v.get(k).is_some(), "missing primer key {k}");
        }
        assert_eq!(v["tree"]["id"], "core");
        assert_eq!(v["agent_count"], 1);
    }

    #[tokio::test]
    async fn child_reflect_returns_node_summary() {
        let kernel = Arc::new(Kernel::new());
        let root = mk_agent("core", None);
        let _rx = kernel.register(Arc::clone(&root));
        kernel.set_root(Arc::clone(&root));
        let child = mk_agent("kid_1", Some(AgentId::from("core")));
        let _rx2 = kernel.register(Arc::clone(&child));
        let v = reflect(&kernel, &child, &json!({"type": "reflect"}));
        assert_eq!(v["id"], "kid_1");
        assert_eq!(v["parent_id"], "core");
        // No primer keys on per-agent summaries.
        assert!(v.get("transports").is_none());
        assert!(v.get("agent_count").is_none());
    }
}
