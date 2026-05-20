//! Unit tests for this bundle crate.

use super::*;
use async_trait::async_trait;
use fantastic_kernel::Agent;
use serde_json::Map;
use tempfile::TempDir;

/// Tiny in-process "ui-answering" bundle for membership tests: any
/// agent registered as `ui.tools` answers get_webapp with a stub URL.
struct UiStub;
#[async_trait]
impl Bundle for UiStub {
    fn name(&self) -> &str {
        "ui"
    }
    async fn handle(
        &self,
        agent_id: &AgentId,
        payload: &Value,
        _k: &Arc<Kernel>,
    ) -> Result<Reply, BundleError> {
        let verb = payload.get("type").and_then(Value::as_str).unwrap_or("");
        Ok(Some(match verb {
            "get_webapp" => json!({
                "url": format!("/{}/", agent_id),
                "default_width": 320,
                "default_height": 220,
                "title": "ui",
            }),
            "reflect" => json!({"id": agent_id.as_str(), "sentence": "ui stub"}),
            "boot" | "shutdown" => Value::Null,
            other => json!({"error": format!("unknown {other:?}")}),
        }))
    }
}

/// A bundle that doesn't answer get_webapp — for "refused" cases.
struct NoUiStub;
#[async_trait]
impl Bundle for NoUiStub {
    fn name(&self) -> &str {
        "no_ui"
    }
    async fn handle(
        &self,
        agent_id: &AgentId,
        payload: &Value,
        _k: &Arc<Kernel>,
    ) -> Result<Reply, BundleError> {
        let verb = payload.get("type").and_then(Value::as_str).unwrap_or("");
        Ok(Some(match verb {
            "reflect" => json!({"id": agent_id.as_str(), "sentence": "headless"}),
            "boot" | "shutdown" => Value::Null,
            other => json!({"error": format!("unknown {other:?}")}),
        }))
    }
}

async fn mk_kernel(tmp: &TempDir) -> Arc<Kernel> {
    let mut kernel = Kernel::new();
    kernel.bundles.register(HANDLER_MODULE, CanvasBackendBundle);
    kernel.bundles.register("ui.tools", UiStub);
    kernel.bundles.register("no_ui.tools", NoUiStub);
    let kernel = Arc::new(kernel);
    let root = Agent::new(
        AgentId::from("core"),
        None,
        None,
        Map::new(),
        tmp.path().join(".fantastic"),
        false,
    );
    let _rx = kernel.register(Arc::clone(&root));
    kernel.set_root(Arc::clone(&root));
    kernel
        .send(
            &AgentId::from("core"),
            json!({"type":"create_agent","handler_module":HANDLER_MODULE,"id":"canvas"}),
        )
        .await;
    kernel
}

#[test]
fn readme_present_and_titled() {
    assert!(!README.is_empty());
    assert!(README.contains("canvas_backend"));
}

#[tokio::test]
async fn reflect_reports_member_count() {
    let tmp = TempDir::new().unwrap();
    let kernel = mk_kernel(&tmp).await;
    let r = kernel
        .send(&AgentId::from("canvas"), json!({"type": "reflect"}))
        .await;
    assert_eq!(r["member_count"], 0);
    assert!(r["sentence"].as_str().unwrap().contains("Spatial UI"));
}

#[tokio::test]
async fn add_agent_with_ui_bundle_accepts() {
    let tmp = TempDir::new().unwrap();
    let kernel = mk_kernel(&tmp).await;
    let r = kernel
        .send(
            &AgentId::from("canvas"),
            json!({"type":"add_agent","handler_module":"ui.tools","id":"m1","x":10,"y":20}),
        )
        .await;
    assert_eq!(r["ok"], true);
    assert_eq!(r["member_id"], "m1");
    let members = r["members"].as_array().unwrap();
    assert!(members.iter().any(|v| v == "m1"));
}

#[tokio::test]
async fn add_agent_with_non_ui_bundle_refused_and_rolled_back() {
    let tmp = TempDir::new().unwrap();
    let kernel = mk_kernel(&tmp).await;
    let r = kernel
        .send(
            &AgentId::from("canvas"),
            json!({"type":"add_agent","handler_module":"no_ui.tools","id":"bad1"}),
        )
        .await;
    assert!(r["error"].as_str().unwrap().contains("does not answer"));
    let list = kernel
        .send(&AgentId::from("canvas"), json!({"type": "list_members"}))
        .await;
    let members = list["members"].as_array().unwrap();
    assert!(!members.iter().any(|v| v == "bad1"));
}

#[tokio::test]
async fn remove_agent_cascades() {
    let tmp = TempDir::new().unwrap();
    let kernel = mk_kernel(&tmp).await;
    kernel
        .send(
            &AgentId::from("canvas"),
            json!({"type":"add_agent","handler_module":"ui.tools","id":"m2"}),
        )
        .await;
    let r = kernel
        .send(
            &AgentId::from("canvas"),
            json!({"type":"remove_agent","agent_id":"m2"}),
        )
        .await;
    assert_eq!(r["removed"], true);
    assert!(!kernel.agents.contains_key(&AgentId::from("m2")));
}

#[tokio::test]
async fn discover_returns_intersecting_members() {
    let tmp = TempDir::new().unwrap();
    let kernel = mk_kernel(&tmp).await;
    kernel
        .send(
            &AgentId::from("canvas"),
            json!({"type":"add_agent","handler_module":"ui.tools","id":"in1","x":0,"y":0,"width":50,"height":50}),
        )
        .await;
    kernel
        .send(
            &AgentId::from("canvas"),
            json!({"type":"add_agent","handler_module":"ui.tools","id":"out1","x":1000,"y":1000,"width":50,"height":50}),
        )
        .await;
    let r = kernel
        .send(
            &AgentId::from("canvas"),
            json!({"type":"discover","x":10,"y":10,"w":20,"h":20}),
        )
        .await;
    let agents = r["agents"].as_array().unwrap();
    let ids: Vec<&str> = agents.iter().filter_map(|v| v.as_str()).collect();
    assert!(ids.contains(&"in1"));
    assert!(!ids.contains(&"out1"));
}
