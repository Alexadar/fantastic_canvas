//! Unit tests for this bundle crate.

use super::*;
use fantastic_kernel::Agent;
use serde_json::Map;
use tempfile::TempDir;

/// Spin up a kernel with this bundle registered and a `core` root
/// agent. Returns `(tmp, kernel)` — the tmp dir must outlive the
/// kernel so persisted records (and any seeded readmes) survive
/// through the test body.
fn bootstrap() -> (TempDir, Arc<Kernel>) {
    let tmp = TempDir::new().unwrap();
    let mut kernel = Kernel::new();
    kernel.bundles.register(HANDLER_MODULE, AiChatWebappBundle);
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
    (tmp, kernel)
}

#[test]
fn readme_present_and_titled() {
    assert!(!README.is_empty());
    assert!(README.contains("ai_chat_webapp"));
}

#[test]
fn chat_html_embedded() {
    // Pin a few load-bearing fragments of the embedded chat page.
    // Mostly an early-warning system for accidental drift.
    assert!(!CHAT_HTML.is_empty());
    assert!(CHAT_HTML.contains("<!doctype") || CHAT_HTML.contains("<!DOCTYPE"));
    assert!(CHAT_HTML.contains("chat"));
}

#[tokio::test]
async fn render_html_returns_embedded_page() {
    let (_tmp, kernel) = bootstrap();
    kernel
        .send(
            &AgentId::from("core"),
            json!({
                "type": "create_agent",
                "handler_module": HANDLER_MODULE,
                "id": "chat1",
                "upstream_id": "backend1",
            }),
        )
        .await;
    let r = kernel
        .send(&AgentId::from("chat1"), json!({"type": "render_html"}))
        .await;
    let html = r["html"].as_str().unwrap();
    // index.html starts with `<!doctype html>` (lowercase) — accept
    // either casing in case it gets normalized later.
    assert!(
        html.to_ascii_lowercase().starts_with("<!doctype html>"),
        "html did not start with doctype: {:?}",
        &html[..html.len().min(40)],
    );
}

#[tokio::test]
async fn get_webapp_returns_url_with_agent_id() {
    let (_tmp, kernel) = bootstrap();
    kernel
        .send(
            &AgentId::from("core"),
            json!({
                "type": "create_agent",
                "handler_module": HANDLER_MODULE,
                "id": "chat_test",
            }),
        )
        .await;
    let r = kernel
        .send(&AgentId::from("chat_test"), json!({"type": "get_webapp"}))
        .await;
    assert_eq!(r["url"], "/chat_test/");
    assert_eq!(r["title"], "chat");
    assert_eq!(r["default_width"], 480);
    assert_eq!(r["default_height"], 600);
}

#[tokio::test]
async fn boot_refuses_without_upstream_id() {
    let (_tmp, kernel) = bootstrap();
    kernel
        .send(
            &AgentId::from("core"),
            json!({
                "type": "create_agent",
                "handler_module": HANDLER_MODULE,
                "id": "chat_no_upstream",
            }),
        )
        .await;
    let r = kernel
        .send(&AgentId::from("chat_no_upstream"), json!({"type": "boot"}))
        .await;
    let err = r["error"].as_str().unwrap_or("");
    assert!(
        err.contains("upstream_id"),
        "expected upstream_id error, got: {r:?}",
    );
}

#[tokio::test]
async fn boot_ok_when_upstream_id_set() {
    let (_tmp, kernel) = bootstrap();
    kernel
        .send(
            &AgentId::from("core"),
            json!({
                "type": "create_agent",
                "handler_module": HANDLER_MODULE,
                "id": "chat_wired",
                "upstream_id": "anywhere",
            }),
        )
        .await;
    let r = kernel
        .send(&AgentId::from("chat_wired"), json!({"type": "boot"}))
        .await;
    assert_eq!(r["ok"], true);
    assert_eq!(r["upstream_id"], "anywhere");
}

#[tokio::test]
async fn reflect_includes_upstream_and_provider() {
    let (_tmp, kernel) = bootstrap();
    kernel
        .send(
            &AgentId::from("core"),
            json!({
                "type": "create_agent",
                "handler_module": HANDLER_MODULE,
                "id": "chat_reflect",
                "upstream_id": "backend_x",
                "provider": "nvidia_nim",
            }),
        )
        .await;
    let r = kernel
        .send(&AgentId::from("chat_reflect"), json!({"type": "reflect"}))
        .await;
    assert_eq!(r["id"], "chat_reflect");
    assert_eq!(r["upstream_id"], "backend_x");
    assert_eq!(r["provider"], "nvidia_nim");
    assert!(r["verbs"].is_object());
    assert!(r["verbs"]["render_html"].is_string());

    // And when provider is unset, defaults to "ollama".
    kernel
        .send(
            &AgentId::from("core"),
            json!({
                "type": "create_agent",
                "handler_module": HANDLER_MODULE,
                "id": "chat_default_provider",
                "upstream_id": "backend_y",
            }),
        )
        .await;
    let r2 = kernel
        .send(
            &AgentId::from("chat_default_provider"),
            json!({"type": "reflect"}),
        )
        .await;
    assert_eq!(r2["provider"], "ollama");
}
