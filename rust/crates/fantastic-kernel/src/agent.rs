//! Recursive `Agent` — the substrate's only node type.
//!
//! Identity + record + meta + children. `send`, `emit`, `watch`,
//! `cascade_delete` live in sibling modules (`send.rs`, `lifecycle.rs`)
//! and are added in sub-phase B.

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::Arc;

use dashmap::DashMap;
use tokio::sync::RwLock;

/// Stable identifier for an agent (newtype around `String`).
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct AgentId(pub String);

impl AgentId {
    /// Borrow the underlying string slice.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl From<&str> for AgentId {
    fn from(s: &str) -> Self {
        AgentId(s.to_string())
    }
}

impl From<String> for AgentId {
    fn from(s: String) -> Self {
        AgentId(s)
    }
}

impl std::fmt::Display for AgentId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

/// Persistent fields written to `<root>/agent.json`. Matches the
/// shape Python persists, byte-for-byte.
///
/// `meta` flattens into the JSON object — `display_name`, `port`,
/// `root`, etc. all appear at the top level alongside `id` /
/// `handler_module` / `parent_id`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentRecord {
    /// Agent id (unique tree-wide).
    pub id: String,
    /// Bundle handler key. `None` for the root and other bare agents.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub handler_module: Option<String>,
    /// Parent id, omitted for the root.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_id: Option<String>,
    /// All other key/value pairs.
    #[serde(flatten)]
    pub meta: Map<String, Value>,
}

/// The recursive substrate node.
///
/// Stable across the substrate; reads are lock-free for hot paths
/// (children, watcher_ids guarded by tokio RwLock; meta + record by
/// std::sync::RwLock to keep them sync). Lifecycle methods land with
/// sub-phase B (`send.rs`, `lifecycle.rs`).
pub struct Agent {
    /// Identifier (e.g. `"core"`, `"file_abc123"`).
    pub id: AgentId,
    /// Bundle handler key, if any.
    pub handler_module: Option<String>,
    /// Parent id; `None` for the root.
    pub parent_id: Option<AgentId>,
    /// Arbitrary metadata persisted to agent.json (display_name, port, root, …).
    pub meta: std::sync::RwLock<Map<String, Value>>,
    /// Direct children by id.
    pub(crate) children: DashMap<AgentId, Arc<Agent>>,
    /// Synthetic ids (browser clients) + agent ids currently watching
    /// this agent's inbox. Updated by `watch` / `unwatch` in sub-phase B.
    #[allow(dead_code)]
    pub(crate) watcher_ids: RwLock<HashSet<AgentId>>,
    /// Where this agent's `agent.json` + `agents/` dir lives on disk.
    pub root_path: PathBuf,
    /// Skip disk writes when true (cli, repl, in-test fixtures).
    pub ephemeral: bool,
}

impl Agent {
    /// Construct a fresh agent. Caller is responsible for registering
    /// it in the kernel's `agents` map.
    ///
    /// `root_path` is the directory that holds (or will hold) this
    /// agent's `agent.json` + recursive `agents/` subtree.
    pub fn new(
        id: AgentId,
        handler_module: Option<String>,
        parent_id: Option<AgentId>,
        meta: Map<String, Value>,
        root_path: PathBuf,
        ephemeral: bool,
    ) -> Arc<Self> {
        Arc::new(Self {
            id,
            handler_module,
            parent_id,
            meta: std::sync::RwLock::new(meta),
            children: DashMap::new(),
            watcher_ids: RwLock::new(HashSet::new()),
            root_path,
            ephemeral,
        })
    }

    /// The persistable record snapshot — `id` + `handler_module` +
    /// `parent_id` + meta (flattened).
    pub fn record(&self) -> AgentRecord {
        let meta = self.meta.read().expect("meta lock poisoned").clone();
        AgentRecord {
            id: self.id.0.clone(),
            handler_module: self.handler_module.clone(),
            parent_id: self.parent_id.as_ref().map(|p| p.0.clone()),
            meta,
        }
    }

    /// Display name (best-effort, from meta).
    pub fn display_name(&self) -> Option<String> {
        self.meta
            .read()
            .expect("meta lock poisoned")
            .get("display_name")
            .and_then(|v| v.as_str())
            .map(str::to_string)
    }

    /// Merge new key/value pairs into meta and return the updated record.
    pub fn update_meta(&self, patch: Map<String, Value>) -> AgentRecord {
        {
            let mut m = self.meta.write().expect("meta lock poisoned");
            for (k, v) in patch {
                m.insert(k, v);
            }
        }
        self.record()
    }

    /// Whether the record carries `delete_lock: true`. Substrate
    /// refuses cascade-delete on locked agents.
    pub fn is_delete_locked(&self) -> bool {
        self.meta
            .read()
            .expect("meta lock poisoned")
            .get("delete_lock")
            .and_then(|v| v.as_bool())
            .unwrap_or(false)
    }

    /// Path of `agent.json` under `root_path`.
    pub fn agent_file(&self) -> PathBuf {
        self.root_path.join("agent.json")
    }

    /// Path of the `agents/` subdir under `root_path` (children live here).
    pub fn children_dir(&self) -> PathBuf {
        self.root_path.join("agents")
    }

    /// Path of `readme.md` under `root_path` (seeded from the bundle).
    pub fn readme_file(&self) -> PathBuf {
        self.root_path.join("readme.md")
    }

    /// Does this agent own a child with the given id?
    pub fn has_child(&self, id: &AgentId) -> bool {
        self.children.contains_key(id)
    }

    /// Direct child count.
    pub fn child_count(&self) -> usize {
        self.children.len()
    }

    /// Snapshot of direct child ids (sorted for deterministic iteration).
    pub fn child_ids(&self) -> Vec<AgentId> {
        let mut ids: Vec<AgentId> = self
            .children
            .iter()
            .map(|entry| entry.key().clone())
            .collect();
        ids.sort_by(|a, b| a.0.cmp(&b.0));
        ids
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::path::Path;

    fn make() -> Arc<Agent> {
        Agent::new(
            "test_1".into(),
            Some("file.tools".to_string()),
            Some("core".into()),
            {
                let mut m = Map::new();
                m.insert("display_name".to_string(), json!("Testy"));
                m.insert("port".to_string(), json!(8080));
                m
            },
            Path::new("/tmp/nowhere/test_1").to_path_buf(),
            false,
        )
    }

    #[test]
    fn agent_id_round_trips() {
        let id: AgentId = "core".into();
        assert_eq!(id.as_str(), "core");
        let s: String = "file_abc123".into();
        let id2: AgentId = s.clone().into();
        assert_eq!(id2.0, s);
        assert_eq!(format!("{id2}"), "file_abc123");
    }

    #[test]
    fn record_includes_meta_and_omits_none() {
        let a = make();
        let rec = a.record();
        assert_eq!(rec.id, "test_1");
        assert_eq!(rec.handler_module.as_deref(), Some("file.tools"));
        assert_eq!(rec.parent_id.as_deref(), Some("core"));
        assert_eq!(rec.meta.get("display_name"), Some(&json!("Testy")));
        assert_eq!(rec.meta.get("port"), Some(&json!(8080)));
        // JSON round-trip respects skip_serializing_if=None.
        let v = serde_json::to_value(&rec).unwrap();
        assert_eq!(v["id"], "test_1");
        assert_eq!(v["handler_module"], "file.tools");
        assert_eq!(v["parent_id"], "core");
        assert_eq!(v["display_name"], "Testy");
        assert_eq!(v["port"], 8080);
    }

    #[test]
    fn display_name_reads_from_meta() {
        let a = make();
        assert_eq!(a.display_name().as_deref(), Some("Testy"));
    }

    #[test]
    fn update_meta_merges_and_persists() {
        let a = make();
        let mut patch = Map::new();
        patch.insert("port".to_string(), json!(9090));
        patch.insert("note".to_string(), json!("hi"));
        let rec = a.update_meta(patch);
        assert_eq!(rec.meta["port"], json!(9090));
        assert_eq!(rec.meta["note"], json!("hi"));
        // Unchanged keys survive.
        assert_eq!(rec.meta["display_name"], json!("Testy"));
    }

    #[test]
    fn delete_lock_flag() {
        let a = make();
        assert!(!a.is_delete_locked());
        let mut p = Map::new();
        p.insert("delete_lock".to_string(), json!(true));
        a.update_meta(p);
        assert!(a.is_delete_locked());
    }

    #[test]
    fn record_serializes_byte_compat_with_python_shape() {
        // Persistence parity: the JSON shape must match what the
        // Python kernel writes/reads. Key order isn't load-bearing
        // (Python uses json.dumps with sort), but the SET of keys is.
        let a = make();
        let v = serde_json::to_value(a.record()).unwrap();
        let obj = v.as_object().unwrap();
        assert!(obj.contains_key("id"));
        assert!(obj.contains_key("handler_module"));
        assert!(obj.contains_key("parent_id"));
        assert!(obj.contains_key("display_name"));
        assert!(obj.contains_key("port"));
        // None-valued optional fields must NOT appear (matches Python's
        // omission when handler_module / parent_id are None).
        let bare = Agent::new("root".into(), None, None, Map::new(), Path::new("/").to_path_buf(), false);
        let v2 = serde_json::to_value(bare.record()).unwrap();
        let o2 = v2.as_object().unwrap();
        assert!(o2.contains_key("id"));
        assert!(!o2.contains_key("handler_module"));
        assert!(!o2.contains_key("parent_id"));
    }
}
