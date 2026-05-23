//! End-to-end selftest demo for the foundation_models_backend
//! bundle's streaming path. Uses a plain-Rust mock host that
//! simulates token-by-token output from `LanguageModelSession`.
//!
//! Run: `cargo run -p fantastic-foundation-models-backend --example fm_mock_session`
//!
//! No Apple frameworks, no Swift, no real LLM — purely exercises the
//! kernel ↔ bundle ↔ mock-host loop with visible JSON output at
//! each step.

use fantastic_foundation_models_backend::{
    complete, error as fm_error, push_token, register_host, FoundationModelsBackendBundle,
    FoundationModelsHost, HANDLER_MODULE,
};
use fantastic_kernel::{Agent, AgentId, Kernel, StorageMode};
use serde_json::{json, Map, Value};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

/// Mock host. Records the streaming call so the demo can show what
/// Swift would receive in production.
#[derive(Default)]
struct MockHost {
    available: AtomicBool,
    model_loaded: AtomicBool,
    last_call: Mutex<Option<(String, String, String, String)>>,
    cancels: AtomicUsize,
}

impl FoundationModelsHost for MockHost {
    fn is_available(&self) -> bool {
        self.available.load(Ordering::Relaxed)
    }
    fn model_available(&self) -> bool {
        self.model_loaded.load(Ordering::Relaxed)
    }
    fn stream_response(
        &self,
        stream_id: String,
        system_prompt: String,
        history_json: String,
        user_message: String,
    ) {
        *self.last_call.lock().unwrap() =
            Some((stream_id, system_prompt, history_json, user_message));
    }
    fn cancel(&self, _stream_id: String) {
        self.cancels.fetch_add(1, Ordering::Relaxed);
    }
}

fn banner(s: &str) {
    println!("\n────────────────────────────────────────────────────────────");
    println!(" {s}");
    println!("────────────────────────────────────────────────────────────");
}

fn assert_or_die(cond: bool, label: &str) {
    if cond {
        println!("  ✓ {label}");
    } else {
        eprintln!("  ✗ {label}");
        std::process::exit(1);
    }
}

fn pretty(v: &Value) -> String {
    serde_json::to_string_pretty(v).unwrap_or_default()
}

#[tokio::main]
async fn main() {
    banner("Step 1: boot an in-memory kernel + register the FM bundle");
    let mut kernel = Kernel::with_storage(StorageMode::InMemory);
    kernel
        .bundles
        .register(HANDLER_MODULE, FoundationModelsBackendBundle::new());
    let kernel = Arc::new(kernel);
    let root = Agent::new(
        AgentId::from("core"),
        None,
        None,
        Map::new(),
        Default::default(),
        false,
    );
    let _rx = kernel.register(Arc::clone(&root));
    kernel.set_root(Arc::clone(&root));
    println!("  kernel: storage=InMemory, bundles registered");

    banner("Step 2: probe backend_state — no host yet");
    let fm = AgentId::from("fm");
    kernel
        .send(
            &AgentId::from("core"),
            json!({"type":"create_agent","handler_module":HANDLER_MODULE,"id":"fm"}),
        )
        .await;
    let bs1 = kernel.send(&fm, json!({"type":"backend_state"})).await;
    println!("  {}", pretty(&bs1));
    assert_or_die(
        bs1["backend_registered"] == false,
        "backend_registered: false",
    );
    assert_or_die(
        bs1["apple_intelligence_available"] == false,
        "apple_intelligence_available: false",
    );
    assert_or_die(bs1["model_available"] == false, "model_available: false");

    banner("Step 3: send without a host — graceful structured error");
    let send_no_host = kernel
        .send(&fm, json!({"type":"send", "text":"hello"}))
        .await;
    println!("  {}", pretty(&send_no_host));
    assert_or_die(send_no_host["reason"] == "no_host", "reason == no_host");

    banner("Step 4: register a mock host (Apple Intelligence + model both ready)");
    let host = Arc::new(MockHost::default());
    host.available.store(true, Ordering::Relaxed);
    host.model_loaded.store(true, Ordering::Relaxed);
    register_host(host.clone());
    let bs2 = kernel.send(&fm, json!({"type":"backend_state"})).await;
    println!("  {}", pretty(&bs2));
    assert_or_die(
        bs2["backend_registered"] == true,
        "backend_registered: true",
    );
    assert_or_die(
        bs2["apple_intelligence_available"] == true,
        "apple_intelligence_available: true",
    );

    banner("Step 5: send — host receives stream_response call");
    let resp = kernel
        .send(
            &fm,
            json!({"type":"send","text":"What's the capital of France?","client_id":"demo"}),
        )
        .await;
    println!("  send reply: {}", pretty(&resp));
    let stream_id = resp["stream_id"].as_str().unwrap().to_string();
    let captured = host.last_call.lock().unwrap().clone().unwrap();
    println!("  host received:");
    println!("    stream_id:    {}", captured.0);
    println!("    system:       {} chars", captured.1.len());
    println!("    history_json: {}", captured.2);
    println!("    user_message: {}", captured.3);

    banner("Step 6: simulate the host streaming tokens back");
    let tokens = ["The", " capital", " of", " France", " is", " Paris", "."];
    for tok in &tokens {
        push_token(&kernel, &stream_id, tok).await;
        println!("  push_token({tok:?})");
    }
    complete(&kernel, &stream_id).await;
    println!("  complete()");

    banner("Step 7: history reflects the conversation");
    let hist = kernel
        .send(&fm, json!({"type":"history","client_id":"demo"}))
        .await;
    println!("  {}", pretty(&hist));
    let msgs = hist["messages"].as_array().unwrap();
    assert_or_die(msgs.len() == 2, "history has 2 messages (user + assistant)");
    assert_or_die(msgs[0]["role"] == "user", "first is user");
    assert_or_die(msgs[1]["role"] == "assistant", "second is assistant");
    let assembled: String = tokens.iter().copied().collect();
    assert_or_die(
        msgs[1]["content"] == assembled,
        "assembled tokens match the assistant message",
    );

    banner("Step 8: second send — error path");
    let resp2 = kernel
        .send(
            &fm,
            json!({"type":"send","text":"explode please","client_id":"demo"}),
        )
        .await;
    let stream_id2 = resp2["stream_id"].as_str().unwrap().to_string();
    push_token(&kernel, &stream_id2, "I'm trying").await;
    fm_error(&kernel, &stream_id2, "model unavailable").await;
    let hist2 = kernel
        .send(&fm, json!({"type":"history","client_id":"demo"}))
        .await;
    let last = hist2["messages"].as_array().unwrap().last().unwrap();
    println!("  last message: {}", pretty(last));
    assert_or_die(last["error"] == "model unavailable", "error field recorded");
    assert_or_die(last["content"] == "I'm trying", "partial text preserved");

    banner("Step 9: interrupt cancels in-flight + emits done");
    let resp3 = kernel
        .send(
            &fm,
            json!({"type":"send","text":"long story","client_id":"demo"}),
        )
        .await;
    let stream_id3 = resp3["stream_id"].as_str().unwrap().to_string();
    push_token(&kernel, &stream_id3, "Once upon").await;
    let int_resp = kernel
        .send(&fm, json!({"type":"interrupt","client_id":"demo"}))
        .await;
    println!("  interrupt: {}", pretty(&int_resp));
    assert_or_die(int_resp["interrupted"] == true, "interrupted: true");
    assert_or_die(
        host.cancels.load(Ordering::Relaxed) == 1,
        "host.cancel called once",
    );
    let _ = stream_id3;

    banner("ALL ASSERTIONS GREEN — foundation_models_backend round-trip healthy");
}
