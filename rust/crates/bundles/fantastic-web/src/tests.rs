//! Unit tests for this bundle crate.

use super::*;

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
