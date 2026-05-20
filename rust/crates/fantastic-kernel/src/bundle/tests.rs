//! Unit tests for [`crate::bundle`].

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
        _kernel: &Arc<Kernel>,
    ) -> Result<Reply, BundleError> {
        Ok(Some(json!({"ok": true})))
    }
}

#[tokio::test]
async fn register_and_lookup() {
    let mut reg = BundleRegistry::new();
    reg.register("fake.tools", FakeBundle);
    let b = reg.get("fake.tools").expect("registered");
    let kernel = Arc::new(Kernel::new());
    let reply = b
        .handle(&AgentId::from("x"), &json!({"type": "ping"}), &kernel)
        .await
        .unwrap();
    assert_eq!(reply, Some(json!({"ok": true})));
}

#[test]
fn unknown_handler_returns_none() {
    let reg = BundleRegistry::new();
    assert!(reg.get("nope.tools").is_none());
}
