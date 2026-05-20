//! Shared kernel context — flat agent index, inbox queues, bundle
//! registry, root pointer.
//!
//! The [`Kernel`] is `Arc`-cloneable and `Send + Sync` so handler
//! closures can capture it without contention. Concurrent paths use
//! lock-free `DashMap`s for the agent + inbox lookups; the root
//! pointer is an `ArcSwap` so swaps during boot are observable
//! atomically by every reader.

use crate::agent::{Agent, AgentId};
use crate::bundle::BundleRegistry;
use arc_swap::ArcSwapOption;
use dashmap::DashMap;
use serde_json::Value;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, RwLock};
use tokio::sync::mpsc;

/// Bounded inbox capacity per agent — matches Python's `INBOX_BOUND`.
/// 256 fits a chat-paced workload comfortably and bounds memory on a
/// runaway emitter. Tunable via [`Kernel::new_with_inbox_bound`].
pub const DEFAULT_INBOX_BOUND: usize = 256;

/// A subscriber callback fired on every state event (`send` / `emit`
/// / `removed` / etc.). Synchronous, called inline — keep it cheap;
/// off-thread the work if it might block.
pub type StateSubscriber = Arc<dyn Fn(&Value) + Send + Sync>;

/// Opaque token returned by [`Kernel::add_state_subscriber`]; pass to
/// [`Kernel::remove_state_subscriber`] to detach.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct SubscriberToken(u64);

/// Shared kernel context.
pub struct Kernel {
    /// Flat global id → Agent. The only routing table.
    pub agents: DashMap<AgentId, Arc<Agent>>,
    /// Per-id inbox (agents + synthetic browser client ids).
    pub inboxes: DashMap<AgentId, mpsc::Sender<Value>>,
    /// Active state-event taps (telemetry, debugging). Keyed by token
    /// for clean detach.
    state_subscribers: RwLock<Vec<(SubscriberToken, StateSubscriber)>>,
    /// Monotonic counter for [`SubscriberToken`].
    next_subscriber: AtomicU64,
    /// Compile-time bundle registry — caller fills before bootstrap.
    pub bundles: BundleRegistry,
    /// The root agent (`id="core"` by convention). Set during bootstrap.
    pub root: ArcSwapOption<Agent>,
    /// Per-inbox bound; same value applied to every channel.
    pub inbox_bound: usize,
}

impl Default for Kernel {
    fn default() -> Self {
        Self::new()
    }
}

impl Kernel {
    /// Empty kernel — no agents, no root, default inbox bound.
    pub fn new() -> Self {
        Self::new_with_inbox_bound(DEFAULT_INBOX_BOUND)
    }

    /// Empty kernel with a custom inbox bound. Use for testing
    /// back-pressure paths.
    pub fn new_with_inbox_bound(bound: usize) -> Self {
        Self {
            agents: DashMap::new(),
            inboxes: DashMap::new(),
            state_subscribers: RwLock::new(Vec::new()),
            next_subscriber: AtomicU64::new(1),
            bundles: BundleRegistry::new(),
            root: ArcSwapOption::const_empty(),
            inbox_bound: bound,
        }
    }

    /// Register an agent in the flat index + auto-vivify its inbox.
    /// Returns the bound channel receiver so the caller can drain it
    /// (typically a fanout loop or a per-bundle handler task).
    pub fn register(&self, agent: Arc<Agent>) -> mpsc::Receiver<Value> {
        let (tx, rx) = mpsc::channel(self.inbox_bound);
        self.inboxes.insert(agent.id.clone(), tx);
        self.agents.insert(agent.id.clone(), agent);
        rx
    }

    /// Unregister an agent + drop its inbox. Caller has already run
    /// the bundle's `on_delete` hook + rmtreed the dir.
    pub fn unregister(&self, id: &AgentId) {
        self.inboxes.remove(id);
        self.agents.remove(id);
    }

    /// Cheap clone of the current root pointer (`None` until
    /// bootstrap completes).
    pub fn root(&self) -> Option<Arc<Agent>> {
        self.root.load_full()
    }

    /// Swap the root pointer atomically. Bootstrap calls this once.
    pub fn set_root(&self, root: Arc<Agent>) {
        self.root.store(Some(root));
    }

    /// Push a state event to every subscriber. Keep callbacks short —
    /// they run on the dispatching task.
    pub fn publish_state(&self, event: &Value) {
        let subs = self.state_subscribers.read().expect("state subs poisoned");
        for (_token, cb) in subs.iter() {
            cb(event);
        }
    }

    /// Register a state-event tap. Returns a token the caller can
    /// pass to [`Self::remove_state_subscriber`] to detach.
    pub fn add_state_subscriber(&self, cb: StateSubscriber) -> SubscriberToken {
        let token = SubscriberToken(self.next_subscriber.fetch_add(1, Ordering::SeqCst));
        self.state_subscribers
            .write()
            .expect("state subs poisoned")
            .push((token, cb));
        token
    }

    /// Detach a previously-registered subscriber. No-op if `token`
    /// isn't (or no longer is) registered.
    pub fn remove_state_subscriber(&self, token: SubscriberToken) {
        self.state_subscribers
            .write()
            .expect("state subs poisoned")
            .retain(|(t, _)| *t != token);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::Agent;
    use serde_json::{json, Map};
    use std::path::Path;
    use std::sync::atomic::{AtomicUsize, Ordering};

    fn make_agent(id: &str) -> Arc<Agent> {
        Agent::new(
            id.into(),
            None,
            None,
            Map::new(),
            Path::new("/tmp/nowhere").join(id),
            true,
        )
    }

    #[test]
    fn empty_kernel_has_no_root() {
        let k = Kernel::new();
        assert!(k.root().is_none());
    }

    #[test]
    fn register_creates_inbox_and_indexes_agent() {
        let k = Kernel::new();
        let a = make_agent("agent_x");
        let _rx = k.register(Arc::clone(&a));
        assert!(k.agents.contains_key(&AgentId::from("agent_x")));
        assert!(k.inboxes.contains_key(&AgentId::from("agent_x")));
    }

    #[test]
    fn unregister_drops_both_indexes() {
        let k = Kernel::new();
        let a = make_agent("zap");
        let _rx = k.register(Arc::clone(&a));
        k.unregister(&AgentId::from("zap"));
        assert!(!k.agents.contains_key(&AgentId::from("zap")));
        assert!(!k.inboxes.contains_key(&AgentId::from("zap")));
    }

    #[test]
    fn root_swap_visible_to_all_readers() {
        let k = Arc::new(Kernel::new());
        let root = make_agent("core");
        k.set_root(Arc::clone(&root));
        let seen = k.root().expect("root set");
        assert_eq!(seen.id, AgentId::from("core"));
    }

    #[test]
    fn publish_state_reaches_every_subscriber() {
        let k = Kernel::new();
        let count1 = Arc::new(AtomicUsize::new(0));
        let count2 = Arc::new(AtomicUsize::new(0));
        let c1 = Arc::clone(&count1);
        let c2 = Arc::clone(&count2);
        let _t1 = k.add_state_subscriber(Arc::new(move |_ev| {
            c1.fetch_add(1, Ordering::SeqCst);
        }));
        let _t2 = k.add_state_subscriber(Arc::new(move |_ev| {
            c2.fetch_add(1, Ordering::SeqCst);
        }));
        k.publish_state(&json!({"type": "test"}));
        k.publish_state(&json!({"type": "test"}));
        assert_eq!(count1.load(Ordering::SeqCst), 2);
        assert_eq!(count2.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn remove_state_subscriber_detaches() {
        let k = Kernel::new();
        let count = Arc::new(AtomicUsize::new(0));
        let c = Arc::clone(&count);
        let token = k.add_state_subscriber(Arc::new(move |_ev| {
            c.fetch_add(1, Ordering::SeqCst);
        }));
        k.publish_state(&json!({"type": "tick"}));
        k.remove_state_subscriber(token);
        k.publish_state(&json!({"type": "tick"}));
        // Subscriber fired exactly once, before detach.
        assert_eq!(count.load(Ordering::SeqCst), 1);
        // Re-removing the same token is a no-op.
        k.remove_state_subscriber(token);
    }

    #[tokio::test]
    async fn inbox_channel_back_pressure_at_bound() {
        // Sender to a bound=2 inbox accepts 2 then blocks on the 3rd
        // (try_send returns Err). Verifies the bound is actually wired.
        let k = Kernel::new_with_inbox_bound(2);
        let a = make_agent("bp");
        let _rx = k.register(Arc::clone(&a));
        let tx = k.inboxes.get(&AgentId::from("bp")).unwrap().clone();
        tx.send(json!({"type": "one"})).await.unwrap();
        tx.send(json!({"type": "two"})).await.unwrap();
        // The 3rd push would block — try_send must report full.
        match tx.try_send(json!({"type": "three"})) {
            Err(tokio::sync::mpsc::error::TrySendError::Full(_)) => {}
            other => panic!("expected Full, got {other:?}"),
        }
    }
}
