//! Verb routing — `Kernel::send`, `Kernel::emit`, watch fanout, the
//! `_current_sender` task-local that tags state events with the
//! originator.
//!
//! Routing model: the kernel's `agents` map is the only routing table.
//! `send(target_id, payload)` resolves `target_id` directly there;
//! parent-child structure doesn't enter routing. Inboxes are auto-
//! vivified for synthetic ids (browser clients).
//!
//! ### System verbs vs bundle verbs
//!
//! Substrate-native verbs (`create_agent`, `delete_agent`,
//! `update_agent`, `list_agents`, `reflect`, `boot`, `shutdown`) are
//! resolved on the target agent itself without consulting its bundle.
//! Everything else routes to the bundle whose `handler_module` matches
//! the agent's record. Unknown bundle → `{"error": "no bundle for
//! handler_module"}`. Missing target → `{"error": "no agent <id>"}`.
//!
//! ### Watcher fanout
//!
//! Every successful dispatch publishes a state event
//! `{"type":"send", "sender":<originator>, "target":<id>, "verb":<v>,
//! "summary": <stringified-payload>}` and fans the raw payload out to
//! every watcher's inbox. Emits (no reply) do the same with
//! `"type":"emit"`. Errors emit `{"type":"error", ...}`.

use crate::agent::{Agent, AgentId};
use crate::kernel::Kernel;
use serde_json::{json, Map, Value};
use std::sync::Arc;
use tokio::task_local;

task_local! {
    /// The agent id currently dispatching. Set by [`Kernel::send`]
    /// (and [`Kernel::emit`]) around the underlying dispatch so
    /// nested calls correctly attribute telemetry events. The
    /// WebSocket proxy seeds it to the webapp's own id for external
    /// traffic.
    pub static CURRENT_SENDER: AgentId;
}

/// Get the current sender if a task is mid-dispatch, else `None`.
pub fn current_sender() -> Option<AgentId> {
    CURRENT_SENDER.try_with(|s| s.clone()).ok()
}

/// Run `fut` with `sender` set as `CURRENT_SENDER` for its duration.
/// External transports (web_ws, web_rest) call this with the webapp's
/// own id so telemetry events attribute correctly.
pub async fn with_sender<F, T>(sender: AgentId, fut: F) -> T
where
    F: std::future::Future<Output = T>,
{
    CURRENT_SENDER.scope(sender, fut).await
}

/// One-line, bytes-stripped, max-160-char summary for telemetry.
/// Mirrors what Python emits as `summary` on state events.
fn summarize_payload(payload: &Value) -> String {
    let mut s = match serde_json::to_string(payload) {
        Ok(s) => s,
        Err(_) => format!("{payload:?}"),
    };
    if s.len() > 160 {
        s.truncate(157);
        s.push_str("...");
    }
    s
}

/// Extract `payload["type"]` as `&str`, or `""` if missing/wrong type.
fn verb_of(payload: &Value) -> &str {
    payload.get("type").and_then(Value::as_str).unwrap_or("")
}

impl Kernel {
    /// Send a verb. Resolves target in the flat agents index,
    /// dispatches through system-verb table or the agent's bundle,
    /// returns the reply (`None` for fire-and-forget).
    ///
    /// `CURRENT_SENDER` is set around dispatch. State event + watcher
    /// fanout fire after a successful dispatch.
    pub async fn send(self: &Arc<Self>, target_id: &AgentId, payload: Value) -> Value {
        // Resolve target. Special id `"kernel"` aliases to the root.
        let resolved: Option<Arc<Agent>> = if target_id.as_str() == "kernel" {
            self.root()
        } else {
            self.agents.get(target_id).map(|e| Arc::clone(&e))
        };
        let Some(target) = resolved else {
            return json!({ "error": format!("no agent {target_id}") });
        };

        let sender = current_sender().unwrap_or_else(|| target.id.clone());
        let verb = verb_of(&payload).to_string();

        // Run dispatch under a fresh CURRENT_SENDER scope so nested
        // sends attribute to this target (matches Python contextvars).
        let kernel = Arc::clone(self);
        let target_for_dispatch = Arc::clone(&target);
        let payload_clone = payload.clone();
        let reply = with_sender(target.id.clone(), async move {
            dispatch(&kernel, target_for_dispatch, &payload_clone).await
        })
        .await;

        // State event + watcher fanout (synchronous; cheap subscribers).
        let event = json!({
            "type": "send",
            "sender": sender.0,
            "target": target.id.0,
            "verb": verb,
            "summary": summarize_payload(&payload),
        });
        self.publish_state(&event);
        self.fanout_to_watchers(&target, &event).await;

        reply
    }

    /// Emit a payload to a target's inbox without dispatching. Returns
    /// immediately. Fans the event out to watchers; publishes a state
    /// event of type `"emit"`.
    ///
    /// The target's inbox is auto-vivified if missing (synthetic
    /// browser-client ids land here).
    pub async fn emit(self: &Arc<Self>, target_id: &AgentId, payload: Value) {
        // Auto-vivify the inbox for synthetic ids (any id not in
        // `agents` is treated as a watch-only listener).
        if !self.inboxes.contains_key(target_id) {
            let (tx, _rx) = tokio::sync::mpsc::channel(self.inbox_bound);
            self.inboxes.insert(target_id.clone(), tx);
        }
        if let Some(tx) = self.inboxes.get(target_id) {
            // try_send so a slow consumer doesn't deadlock the emitter.
            // Drops on full match Python's bounded-deque behaviour.
            let _ = tx.try_send(payload.clone());
        }

        let sender = current_sender().unwrap_or_else(|| target_id.clone());
        let verb = verb_of(&payload).to_string();
        let event = json!({
            "type": "emit",
            "sender": sender.0,
            "target": target_id.0,
            "verb": verb,
            "summary": summarize_payload(&payload),
        });
        self.publish_state(&event);
        // Best-effort watcher fanout — emits without a registered
        // Agent (synthetic targets) have no watcher set; skip.
        if let Some(target) = self.agents.get(target_id).map(|e| Arc::clone(&e)) {
            self.fanout_to_watchers(&target, &event).await;
        }
    }

    /// Register `watcher_id` as an observer of `src_id`'s inbox.
    /// Every subsequent `send`/`emit` targeting `src_id` mirrors the
    /// payload into `watcher_id`'s inbox via [`Self::fanout_to_watchers`].
    pub async fn watch(&self, src_id: &AgentId, watcher_id: AgentId) {
        if let Some(src) = self.agents.get(src_id) {
            src.watcher_ids.write().await.insert(watcher_id.clone());
        }
        // Auto-vivify the watcher's inbox so fanout has a destination
        // even if `watcher_id` is a synthetic browser-client id.
        if !self.inboxes.contains_key(&watcher_id) {
            let (tx, _rx) = tokio::sync::mpsc::channel(self.inbox_bound);
            self.inboxes.insert(watcher_id, tx);
        }
    }

    /// Detach a previously-registered watcher.
    pub async fn unwatch(&self, src_id: &AgentId, watcher_id: &AgentId) {
        if let Some(src) = self.agents.get(src_id) {
            src.watcher_ids.write().await.remove(watcher_id);
        }
    }

    /// Push `payload` to every watcher of `target`'s inbox.
    pub(crate) async fn fanout_to_watchers(&self, target: &Agent, payload: &Value) {
        let watchers: Vec<AgentId> = target.watcher_ids.read().await.iter().cloned().collect();
        for w in watchers {
            if let Some(tx) = self.inboxes.get(&w) {
                let _ = tx.try_send(payload.clone());
            }
        }
    }
}

/// Resolve verb → system handler or bundle handler.
async fn dispatch(kernel: &Arc<Kernel>, target: Arc<Agent>, payload: &Value) -> Value {
    let verb = verb_of(payload);
    if is_system_verb(verb) {
        return handle_system_verb(kernel, &target, verb, payload).await;
    }
    // No handler_module → only system verbs answerable.
    let Some(hm) = target.handler_module.as_deref() else {
        // Universal answers for bare agents.
        return match verb {
            "boot" | "shutdown" => Value::Null,
            "reflect" => crate::reflect::reflect(kernel, &target, payload),
            _ => json!({
                "error": format!(
                    "agent {:?} has no handler_module; cannot answer verb {:?}",
                    target.id.0, verb
                ),
            }),
        };
    };
    let Some(bundle) = kernel.bundles.get(hm) else {
        return json!({
            "error": format!("no bundle for handler_module {hm:?}"),
        });
    };
    match bundle.handle(&target.id, payload, kernel).await {
        Ok(Some(v)) => v,
        Ok(None) => Value::Null,
        Err(e) => json!({ "error": e.to_string() }),
    }
}

/// Substrate verbs answered natively on every agent.
fn is_system_verb(verb: &str) -> bool {
    matches!(
        verb,
        "create_agent" | "delete_agent" | "update_agent" | "list_agents" | "reflect" | "get"
    )
}

async fn handle_system_verb(
    kernel: &Arc<Kernel>,
    target: &Arc<Agent>,
    verb: &str,
    payload: &Value,
) -> Value {
    match verb {
        "reflect" => crate::reflect::reflect(kernel, target, payload),
        "list_agents" => {
            let mut out: Vec<Value> = Vec::new();
            for entry in kernel.agents.iter() {
                let a = entry.value();
                out.push(serde_json::to_value(a.record()).unwrap_or(Value::Null));
            }
            // Sort by id for stable output.
            out.sort_by(|a, b| {
                a.get("id")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .cmp(b.get("id").and_then(Value::as_str).unwrap_or(""))
            });
            json!({ "agents": out })
        }
        "create_agent" => crate::lifecycle::create_from_payload(kernel, target, payload).await,
        "delete_agent" => crate::lifecycle::delete_from_payload(kernel, target, payload).await,
        "update_agent" => update_from_payload(kernel, target, payload),
        "get" => {
            let id = payload.get("id").and_then(Value::as_str).map(AgentId::from);
            match id.and_then(|i| kernel.agents.get(&i).map(|e| Arc::clone(&e))) {
                Some(a) => serde_json::to_value(a.record()).unwrap_or(Value::Null),
                None => Value::Null,
            }
        }
        _ => unreachable!("is_system_verb gate"),
    }
}

fn update_from_payload(kernel: &Arc<Kernel>, _caller: &Arc<Agent>, payload: &Value) -> Value {
    let id = match payload.get("id").and_then(Value::as_str) {
        Some(s) => AgentId::from(s),
        None => return json!({ "error": "update_agent requires id" }),
    };
    let Some(target) = kernel.agents.get(&id).map(|e| Arc::clone(&e)) else {
        return json!({ "error": format!("no agent {id}") });
    };
    // Patch is every field in payload except `type` and `id`.
    let mut patch: Map<String, Value> = Map::new();
    if let Some(obj) = payload.as_object() {
        for (k, v) in obj {
            if k == "type" || k == "id" {
                continue;
            }
            patch.insert(k.clone(), v.clone());
        }
    }
    let rec = target.update_meta(patch);
    let _ = crate::persistence::persist(&target);
    let event = json!({
        "type": "updated",
        "id": rec.id,
    });
    kernel.publish_state(&event);
    serde_json::to_value(&rec).unwrap_or(Value::Null)
}

#[cfg(test)]
mod tests;
