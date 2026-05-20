//! Unit tests for this bundle crate.

use super::*;
use fantastic_kernel::Agent;
use serde_json::Map;
use std::time::Duration;
use tempfile::TempDir;

/// Acquire a free local port — bind to 127.0.0.1:0 and read back the
/// assigned port. We close the listener before the test boots web; a
/// rebind race is theoretically possible but vanishingly rare in
/// practice and the kernel-binary CI runs serial.
fn free_port() -> u16 {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("bind 0");
    let port = listener.local_addr().expect("local addr").port();
    drop(listener);
    port
}

/// Build a kernel with web (+ optionally child surface bundles)
/// registered, with a root agent set as `core`.
fn mk_kernel(tmp: &TempDir, register_ws: bool, register_rest: bool) -> Arc<Kernel> {
    let mut kernel = Kernel::new();
    kernel.bundles.register(HANDLER_MODULE, WebBundle);
    if register_ws {
        kernel
            .bundles
            .register("web_ws.tools", fantastic_web_ws::WebWsBundle);
    }
    if register_rest {
        kernel
            .bundles
            .register("web_rest.tools", fantastic_web_rest::WebRestBundle);
    }
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
}

/// Wait briefly for the bound listener to start accepting. Reduces
/// flake on slow CI machines without padding fast runs.
async fn wait_until_port_accepts(port: u16) {
    use tokio::net::TcpStream;
    for _ in 0..50 {
        if TcpStream::connect(("127.0.0.1", port)).await.is_ok() {
            return;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

#[test]
fn readme_present_and_titled() {
    assert!(!README.is_empty());
    assert!(README.contains("web — axum HTTP host"));
}

#[test]
fn transport_js_self_invokes_global() {
    assert!(TRANSPORT_JS.contains("fantastic_transport"));
    assert!(TRANSPORT_JS.contains("BroadcastChannel"));
}

#[test]
fn root_index_includes_transport_script() {
    assert!(ROOT_INDEX_HTML.contains("transport.js"));
}

#[test]
fn inject_transport_adds_script_before_head_close() {
    let html = "<html><head><title>x</title></head><body>hi</body></html>";
    let out = inject_transport(html);
    assert!(out.contains(r#"<script src="/transport.js"></script>"#));
    let idx_script = out.find("/transport.js").unwrap();
    let idx_close = out.find("</head>").unwrap();
    assert!(idx_script < idx_close);
}

#[test]
fn inject_transport_is_idempotent() {
    let html = r#"<html><head><script src="/transport.js"></script></head><body>x</body></html>"#;
    assert_eq!(inject_transport(html), html);
}

#[test]
fn inject_transport_handles_no_head() {
    let html = "<body>x</body>";
    let out = inject_transport(html);
    assert!(out.starts_with(r#"<script src="/transport.js"></script>"#));
}

#[test]
fn guess_mime_known_types() {
    assert_eq!(guess_mime("a.html"), "text/html; charset=utf-8");
    assert_eq!(guess_mime("a.CSS"), "text/css; charset=utf-8");
    assert_eq!(guess_mime("a.png"), "image/png");
    assert_eq!(guess_mime("a.json"), "application/json");
    assert_eq!(guess_mime("unknown"), "text/plain; charset=utf-8");
}

#[test]
fn translate_path_substitutes_python_placeholders() {
    assert_eq!(translate_path("/{host_id}/ws"), "/:host_id/ws");
    assert_eq!(
        translate_path("/{rest}/_reflect/{target_id}"),
        "/:rest/_reflect/:target_id"
    );
    assert_eq!(translate_path("/static"), "/static");
    assert_eq!(translate_path("/{x:path}"), "/*x");
}

/// `web` alone (no web_ws child) must NOT expose `/<id>/ws`. The
/// dynamic-mount step is a no-op when there are no children to query,
/// so the surface-less router 404s on the WS path.
#[tokio::test]
async fn web_alone_has_no_ws_endpoint() {
    let tmp = TempDir::new().unwrap();
    let kernel = mk_kernel(&tmp, false, false);
    let port = free_port();
    let web_id = "web_alone";

    // create + boot web
    let create_reply = kernel
        .send(
            &AgentId::from("core"),
            json!({
                "type": "create_agent",
                "handler_module": HANDLER_MODULE,
                "id": web_id,
                "port": port,
            }),
        )
        .await;
    assert!(
        create_reply.get("error").is_none(),
        "create: {create_reply}"
    );
    let boot_reply = kernel
        .send(&AgentId::from(web_id), json!({"type": "boot"}))
        .await;
    assert_eq!(boot_reply["running"], true, "boot: {boot_reply}");
    wait_until_port_accepts(port).await;

    // HTTP GET on /<id>/ws should NOT 101-upgrade; should 404.
    let url = format!("http://127.0.0.1:{port}/{web_id}/ws");
    let resp = reqwest::Client::new()
        .get(&url)
        .send()
        .await
        .expect("http get");
    assert_eq!(
        resp.status().as_u16(),
        404,
        "expected 404 on bare web's /ws"
    );

    // cleanup
    kernel
        .send(&AgentId::from(web_id), json!({"type": "stop"}))
        .await;
}

/// `web` + `web_ws` child: WS endpoint live at `/<web_id>/ws` after boot.
#[tokio::test]
async fn web_with_ws_child_serves_ws() {
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::Message as TMessage;

    let tmp = TempDir::new().unwrap();
    let kernel = mk_kernel(&tmp, true, false);
    let port = free_port();
    let web_id = "web_with_ws";

    kernel
        .send(
            &AgentId::from("core"),
            json!({
                "type": "create_agent",
                "handler_module": HANDLER_MODULE,
                "id": web_id,
                "port": port,
            }),
        )
        .await;
    kernel
        .send(
            &AgentId::from(web_id),
            json!({
                "type": "create_agent",
                "handler_module": "web_ws.tools",
                "id": "wws_child",
            }),
        )
        .await;
    let boot_reply = kernel
        .send(&AgentId::from(web_id), json!({"type": "boot"}))
        .await;
    assert_eq!(boot_reply["running"], true, "boot: {boot_reply}");
    wait_until_port_accepts(port).await;

    // Open a WS to /<web_id>/ws and round-trip a `call` frame.
    let url = format!("ws://127.0.0.1:{port}/{web_id}/ws");
    let (mut ws, _resp) = tokio_tungstenite::connect_async(&url)
        .await
        .expect("ws connect");
    let frame =
        json!({"type": "call", "target": "kernel", "payload": {"type": "list_agents"}, "id": "x1"});
    ws.send(TMessage::Text(frame.to_string()))
        .await
        .expect("ws send");
    let reply = tokio::time::timeout(Duration::from_secs(2), ws.next())
        .await
        .expect("reply within 2s")
        .expect("ws stream open")
        .expect("ws msg ok");
    let text = match reply {
        TMessage::Text(t) => t,
        other => panic!("expected text reply, got {other:?}"),
    };
    let v: Value = serde_json::from_str(&text).expect("reply json");
    assert_eq!(v["type"], "reply");
    assert_eq!(v["id"], "x1");
    assert!(v["data"]["agents"].is_array());

    kernel
        .send(&AgentId::from(web_id), json!({"type": "stop"}))
        .await;
}

/// `web` + `web_rest` child: POST endpoint live at `/<rest_id>/<target>`.
#[tokio::test]
async fn web_with_rest_child_serves_rest() {
    let tmp = TempDir::new().unwrap();
    let kernel = mk_kernel(&tmp, false, true);
    let port = free_port();
    let web_id = "web_with_rest";
    let rest_id = "wr_child";

    kernel
        .send(
            &AgentId::from("core"),
            json!({
                "type": "create_agent",
                "handler_module": HANDLER_MODULE,
                "id": web_id,
                "port": port,
            }),
        )
        .await;
    kernel
        .send(
            &AgentId::from(web_id),
            json!({
                "type": "create_agent",
                "handler_module": "web_rest.tools",
                "id": rest_id,
            }),
        )
        .await;
    let boot_reply = kernel
        .send(&AgentId::from(web_id), json!({"type": "boot"}))
        .await;
    assert_eq!(boot_reply["running"], true, "boot: {boot_reply}");
    wait_until_port_accepts(port).await;

    let url = format!("http://127.0.0.1:{port}/{rest_id}/core");
    let resp = reqwest::Client::new()
        .post(&url)
        .header("Content-Type", "application/json")
        .body(r#"{"type": "list_agents"}"#)
        .send()
        .await
        .expect("http post");
    assert!(resp.status().is_success(), "status: {}", resp.status());
    let body: Value = resp.json().await.expect("body json");
    assert!(body["agents"].is_array(), "body: {body}");

    kernel
        .send(&AgentId::from(web_id), json!({"type": "stop"}))
        .await;
}

/// Boot web alone, then create a `web_ws` child + emit `routes_changed`,
/// verify the WS endpoint becomes available without restarting axum.
#[tokio::test]
async fn runtime_added_ws_child_hot_mounts() {
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::Message as TMessage;

    let tmp = TempDir::new().unwrap();
    let kernel = mk_kernel(&tmp, true, false);
    let port = free_port();
    let web_id = "web_hot";

    kernel
        .send(
            &AgentId::from("core"),
            json!({
                "type": "create_agent",
                "handler_module": HANDLER_MODULE,
                "id": web_id,
                "port": port,
            }),
        )
        .await;
    let boot_reply = kernel
        .send(&AgentId::from(web_id), json!({"type": "boot"}))
        .await;
    assert_eq!(boot_reply["running"], true, "boot: {boot_reply}");
    wait_until_port_accepts(port).await;

    // Sanity: no WS yet.
    let url_http = format!("http://127.0.0.1:{port}/{web_id}/ws");
    let pre = reqwest::Client::new()
        .get(&url_http)
        .send()
        .await
        .expect("pre http");
    assert_eq!(pre.status().as_u16(), 404, "pre-mount must 404");

    // Stage the child + trigger a re-mount via `routes_changed` emit.
    kernel
        .send(
            &AgentId::from(web_id),
            json!({
                "type": "create_agent",
                "handler_module": "web_ws.tools",
                "id": "wws_hot",
            }),
        )
        .await;
    // `create_agent` itself emits `created` which the subscriber treats
    // as a re-mount signal — but we also explicitly emit
    // `routes_changed` for spec parity. Both should be idempotent.
    kernel
        .send(&AgentId::from("wws_hot"), json!({"type": "routes_changed"}))
        .await;

    // The subscriber tokio::spawns the rebuild; poll until the WS
    // upgrades or we time out.
    let mut ok = false;
    for _ in 0..50 {
        tokio::time::sleep(Duration::from_millis(40)).await;
        let url_ws = format!("ws://127.0.0.1:{port}/{web_id}/ws");
        if let Ok((mut ws, _)) = tokio_tungstenite::connect_async(&url_ws).await {
            let frame = json!({"type": "call", "target": "kernel", "payload": {"type": "list_agents"}, "id": "hot1"});
            if ws.send(TMessage::Text(frame.to_string())).await.is_err() {
                continue;
            }
            if let Ok(Some(Ok(TMessage::Text(t)))) =
                tokio::time::timeout(Duration::from_secs(1), ws.next()).await
            {
                if let Ok(v) = serde_json::from_str::<Value>(&t) {
                    if v["type"] == "reply" && v["id"] == "hot1" {
                        ok = true;
                        break;
                    }
                }
            }
        }
    }
    assert!(ok, "WS endpoint never became live after hot-mount");

    kernel
        .send(&AgentId::from(web_id), json!({"type": "stop"}))
        .await;
}
