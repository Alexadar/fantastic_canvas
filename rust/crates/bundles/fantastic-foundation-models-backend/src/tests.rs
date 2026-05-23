//! Bundle unit tests.
//!
//! Uses a plain-Rust [`MockHost`] in place of Swift's
//! `LanguageModelSession` wrapper. Tests drive the same token-feedback
//! API (`push_token` / `complete` / `error`) the real Swift host
//! calls via UniFFI.
//!
//! ## Test isolation
//!
//! The bundle's state (registered host, in-flight streams, history)
//! is process-global by design — the UniFFI bridge needs to reach it
//! without downcasting through the kernel's bundle registry. That
//! means tests must serialize. `TEST_LOCK` enforces this; every test
//! holds the lock for its duration and `mk_kernel` calls
//! `clear_host()` at the top to drop any prior state. Yes, the
//! `MutexGuard` IS deliberately held across `.await` — that's the
//! whole point of the lock.
#![allow(clippy::await_holding_lock)]

use super::*;
use fantastic_kernel::{Agent, StorageMode};
use serde_json::Map;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex as StdMutex, MutexGuard, OnceLock as StdOnceLock};
use tempfile::TempDir;

/// Single serializer for the test suite. The bundle's process-global
/// state (host, streams, histories) can't be shared between parallel
/// tests; this lock makes them run one at a time without losing
/// cargo's per-test isolation reporting.
fn test_lock() -> MutexGuard<'static, ()> {
    static LOCK: StdOnceLock<StdMutex<()>> = StdOnceLock::new();
    let m = LOCK.get_or_init(|| StdMutex::new(()));
    match m.lock() {
        Ok(g) => g,
        Err(poisoned) => poisoned.into_inner(),
    }
}

/// Mock host. Records calls + lets tests choose what to report from
/// the probes. `stream_response` doesn't actually stream — tests
/// drive token feedback by calling `push_token` / `complete` /
/// `error` directly.
#[derive(Default)]
struct MockHost {
    available: AtomicBool,
    model_loaded: AtomicBool,
    last_stream: Mutex<Option<(String, String, String, String)>>,
    cancels: AtomicUsize,
}

impl MockHost {
    fn ready() -> Arc<Self> {
        let h = Arc::new(Self::default());
        h.available.store(true, Ordering::Relaxed);
        h.model_loaded.store(true, Ordering::Relaxed);
        h
    }
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
        *self.last_stream.lock().expect("last_stream poisoned") =
            Some((stream_id, system_prompt, history_json, user_message));
    }
    fn cancel(&self, _stream_id: String) {
        self.cancels.fetch_add(1, Ordering::Relaxed);
    }
}

/// Build a kernel with this bundle registered + a root agent + the
/// FM agent, in the specified storage mode. Returns the kernel +
/// the FM agent's id (`fm`).
fn mk_kernel(storage: StorageMode, host: Option<Arc<dyn FoundationModelsHost>>) -> Arc<Kernel> {
    clear_host(); // Tests run in the same process; isolate via clear.
    if let Some(h) = host {
        register_host(h);
    }
    let mut kernel = Kernel::with_storage(storage);
    kernel
        .bundles
        .register(HANDLER_MODULE, FoundationModelsBackendBundle::new());
    let kernel = Arc::new(kernel);
    let workdir = kernel.storage.workdir().map(|p| p.to_path_buf());
    let root_path = workdir
        .as_ref()
        .map(|w| w.join(".fantastic"))
        .unwrap_or_default();
    let root = Agent::new(
        AgentId::from("core"),
        None,
        None,
        Map::new(),
        root_path,
        false,
    );
    let _rx = kernel.register(Arc::clone(&root));
    kernel.set_root(Arc::clone(&root));
    kernel
}

async fn create_fm_agent(kernel: &Arc<Kernel>) -> AgentId {
    let r = kernel
        .send(
            &AgentId::from("core"),
            json!({"type":"create_agent","handler_module":HANDLER_MODULE,"id":"fm"}),
        )
        .await;
    assert_eq!(r["id"], "fm", "create_agent reply: {r}");
    AgentId::from("fm")
}

#[test]
fn readme_present_and_titled() {
    assert!(!README.is_empty());
    assert!(README.contains("foundation_models_backend"));
}

#[tokio::test]
async fn backend_state_reports_no_host_initially() {
    let _guard = test_lock();
    let kernel = mk_kernel(StorageMode::InMemory, None);
    let fm = create_fm_agent(&kernel).await;
    let r = kernel.send(&fm, json!({"type":"backend_state"})).await;
    assert_eq!(r["backend_registered"], false);
    assert_eq!(r["apple_intelligence_available"], false);
    assert_eq!(r["model_available"], false);
    assert_eq!(r["in_flight"], false);
}

#[tokio::test]
async fn backend_state_mirrors_host_probes() {
    let _guard = test_lock();
    let host = MockHost::ready();
    let kernel = mk_kernel(StorageMode::InMemory, Some(host.clone()));
    let fm = create_fm_agent(&kernel).await;
    let r = kernel.send(&fm, json!({"type":"backend_state"})).await;
    assert_eq!(r["backend_registered"], true);
    assert_eq!(r["apple_intelligence_available"], true);
    assert_eq!(r["model_available"], true);
    // Flip host probes — backend_state should re-read each call.
    host.model_loaded.store(false, Ordering::Relaxed);
    let r2 = kernel.send(&fm, json!({"type":"backend_state"})).await;
    assert_eq!(r2["model_available"], false);
}

#[tokio::test]
async fn send_with_no_host_returns_structured_error() {
    let _guard = test_lock();
    let kernel = mk_kernel(StorageMode::InMemory, None);
    let fm = create_fm_agent(&kernel).await;
    let r = kernel
        .send(&fm, json!({"type":"send", "text":"hello"}))
        .await;
    assert!(r["error"]
        .as_str()
        .unwrap()
        .contains("not registered or not available"));
    assert_eq!(r["reason"], "no_host");
}

#[tokio::test]
async fn send_with_unavailable_intelligence_returns_structured_error() {
    let _guard = test_lock();
    let host = Arc::new(MockHost::default());
    // host registered but is_available=false.
    let kernel = mk_kernel(StorageMode::InMemory, Some(host));
    let fm = create_fm_agent(&kernel).await;
    let r = kernel.send(&fm, json!({"type":"send", "text":"hi"})).await;
    assert_eq!(r["reason"], "apple_intelligence_unavailable");
}

#[tokio::test]
async fn send_with_no_model_returns_structured_error() {
    let _guard = test_lock();
    let host = Arc::new(MockHost::default());
    host.available.store(true, Ordering::Relaxed);
    // model_loaded stays false.
    let kernel = mk_kernel(StorageMode::InMemory, Some(host));
    let fm = create_fm_agent(&kernel).await;
    let r = kernel.send(&fm, json!({"type":"send", "text":"hi"})).await;
    assert_eq!(r["reason"], "model_unavailable");
}

#[tokio::test]
async fn send_succeeds_and_calls_host() {
    let _guard = test_lock();
    let host = MockHost::ready();
    let kernel = mk_kernel(StorageMode::InMemory, Some(host.clone()));
    let fm = create_fm_agent(&kernel).await;
    let r = kernel
        .send(
            &fm,
            json!({"type":"send", "text":"hello world", "client_id":"test_client"}),
        )
        .await;
    assert_eq!(r["queued"], true);
    let stream_id = r["stream_id"].as_str().unwrap().to_string();
    let message_id = r["message_id"].as_str().unwrap();
    assert!(stream_id.starts_with("stm_"));
    assert!(message_id.starts_with("msg_"));

    let captured = host
        .last_stream
        .lock()
        .unwrap()
        .clone()
        .expect("host got the stream_response call");
    assert_eq!(captured.0, stream_id);
    assert!(captured.1.contains("Apple Foundation Models")); // default system prompt
    let history: Vec<Value> = serde_json::from_str(&captured.2).unwrap();
    assert_eq!(history.len(), 1, "history has the just-added user turn");
    assert_eq!(history[0]["role"], "user");
    assert_eq!(history[0]["content"], "hello world");
    assert_eq!(captured.3, "hello world");
}

#[tokio::test]
async fn push_token_complete_round_trip() {
    let _guard = test_lock();
    let host = MockHost::ready();
    let kernel = mk_kernel(StorageMode::InMemory, Some(host));
    let fm = create_fm_agent(&kernel).await;
    let r = kernel
        .send(&fm, json!({"type":"send", "text":"hi", "client_id":"c1"}))
        .await;
    let stream_id = r["stream_id"].as_str().unwrap().to_string();

    // Simulate the host driving the stream.
    push_token(&kernel, &stream_id, "Hel").await;
    push_token(&kernel, &stream_id, "lo!").await;
    complete(&kernel, &stream_id).await;

    // History should now have the user + the completed assistant.
    let hist = kernel
        .send(&fm, json!({"type":"history", "client_id":"c1"}))
        .await;
    let msgs = hist["messages"].as_array().unwrap();
    assert_eq!(msgs.len(), 2);
    assert_eq!(msgs[0]["role"], "user");
    assert_eq!(msgs[1]["role"], "assistant");
    assert_eq!(msgs[1]["content"], "Hello!");
    assert_eq!(msgs[1]["complete"], true);
    assert_eq!(msgs[1]["interrupted"], false);
}

#[tokio::test]
async fn error_marks_message_failed() {
    let _guard = test_lock();
    let host = MockHost::ready();
    let kernel = mk_kernel(StorageMode::InMemory, Some(host));
    let fm = create_fm_agent(&kernel).await;
    let r = kernel.send(&fm, json!({"type":"send", "text":"hi"})).await;
    let stream_id = r["stream_id"].as_str().unwrap().to_string();
    push_token(&kernel, &stream_id, "partial").await;
    error(&kernel, &stream_id, "model crashed").await;
    let hist = kernel.send(&fm, json!({"type":"history"})).await;
    let last = hist["messages"].as_array().unwrap().last().unwrap();
    assert_eq!(last["role"], "assistant");
    assert_eq!(last["content"], "partial");
    assert_eq!(last["error"], "model crashed");
}

#[tokio::test]
async fn interrupt_calls_host_cancel_and_marks_message() {
    let _guard = test_lock();
    let host = MockHost::ready();
    let kernel = mk_kernel(StorageMode::InMemory, Some(host.clone()));
    let fm = create_fm_agent(&kernel).await;
    let r = kernel
        .send(
            &fm,
            json!({"type":"send", "text":"long question", "client_id":"c1"}),
        )
        .await;
    let _stream_id = r["stream_id"].as_str().unwrap().to_string();
    push_token(&kernel, _stream_id.as_str(), "I'm thinking").await;

    let int_r = kernel
        .send(&fm, json!({"type":"interrupt", "client_id":"c1"}))
        .await;
    assert_eq!(int_r["interrupted"], true);
    assert_eq!(host.cancels.load(Ordering::Relaxed), 1);

    // History contains an interrupted assistant message with the
    // partial accumulated text.
    let hist = kernel
        .send(&fm, json!({"type":"history", "client_id":"c1"}))
        .await;
    let last = hist["messages"].as_array().unwrap().last().unwrap();
    assert_eq!(last["role"], "assistant");
    assert_eq!(last["content"], "I'm thinking");
    assert_eq!(last["interrupted"], true);

    // backend_state shows no in_flight after interrupt.
    let st = kernel.send(&fm, json!({"type":"backend_state"})).await;
    assert_eq!(st["in_flight"], false);
}

#[tokio::test]
async fn interrupt_when_idle_is_a_no_op() {
    let _guard = test_lock();
    let host = MockHost::ready();
    let kernel = mk_kernel(StorageMode::InMemory, Some(host.clone()));
    let fm = create_fm_agent(&kernel).await;
    let r = kernel.send(&fm, json!({"type":"interrupt"})).await;
    assert_eq!(r["interrupted"], false);
    assert_eq!(host.cancels.load(Ordering::Relaxed), 0);
}

#[tokio::test]
async fn reflect_carries_provider_and_probes() {
    let _guard = test_lock();
    let host = MockHost::ready();
    let kernel = mk_kernel(StorageMode::InMemory, Some(host));
    let fm = create_fm_agent(&kernel).await;
    let r = kernel.send(&fm, json!({"type":"reflect"})).await;
    assert_eq!(r["id"], "fm");
    assert_eq!(r["provider"], PROVIDER);
    assert_eq!(r["apple_intelligence_available"], true);
    assert_eq!(r["model_available"], true);
    assert_eq!(r["backend_registered"], true);
    assert!(r["verbs"]["send"].is_string());
    assert!(r["verbs"]["backend_state"].is_string());
}

#[tokio::test]
async fn concurrent_streams_route_independently() {
    let _guard = test_lock();
    let host = MockHost::ready();
    let kernel = mk_kernel(StorageMode::InMemory, Some(host));
    let fm = create_fm_agent(&kernel).await;

    let r1 = kernel
        .send(
            &fm,
            json!({"type":"send", "text":"q1", "client_id":"alpha"}),
        )
        .await;
    let r2 = kernel
        .send(&fm, json!({"type":"send", "text":"q2", "client_id":"beta"}))
        .await;
    let s1 = r1["stream_id"].as_str().unwrap().to_string();
    let s2 = r2["stream_id"].as_str().unwrap().to_string();
    assert_ne!(s1, s2);

    push_token(&kernel, &s1, "alpha-").await;
    push_token(&kernel, &s2, "BETA-").await;
    push_token(&kernel, &s1, "answer").await;
    complete(&kernel, &s1).await;
    complete(&kernel, &s2).await;

    let h_alpha = kernel
        .send(&fm, json!({"type":"history", "client_id":"alpha"}))
        .await;
    let h_beta = kernel
        .send(&fm, json!({"type":"history", "client_id":"beta"}))
        .await;
    assert_eq!(
        h_alpha["messages"].as_array().unwrap().last().unwrap()["content"],
        "alpha-answer"
    );
    assert_eq!(
        h_beta["messages"].as_array().unwrap().last().unwrap()["content"],
        "BETA-"
    );
}

#[tokio::test]
async fn disk_mode_writes_history_sidecar() {
    let _guard = test_lock();
    let host = MockHost::ready();
    let tmp = TempDir::new().unwrap();
    let kernel = mk_kernel(StorageMode::Disk(tmp.path().to_path_buf()), Some(host));
    let fm = create_fm_agent(&kernel).await;
    let r = kernel
        .send(&fm, json!({"type":"send", "text":"hi", "client_id":"web1"}))
        .await;
    let stream_id = r["stream_id"].as_str().unwrap().to_string();
    push_token(&kernel, &stream_id, "Hi back").await;
    complete(&kernel, &stream_id).await;

    let sidecar = tmp.path().join(".fantastic/agents/fm/chat_web1.json");
    assert!(sidecar.exists(), "history sidecar at {}", sidecar.display());
    let raw = std::fs::read_to_string(&sidecar).unwrap();
    let arr: Vec<Value> = serde_json::from_str(&raw).unwrap();
    assert_eq!(arr.len(), 2);
    assert_eq!(arr[0]["role"], "user");
    assert_eq!(arr[1]["role"], "assistant");
    assert_eq!(arr[1]["content"], "Hi back");
}

#[tokio::test]
async fn in_memory_mode_writes_no_sidecar() {
    let _guard = test_lock();
    let host = MockHost::ready();
    let tmp = TempDir::new().unwrap();
    let prev = std::env::current_dir().ok();
    std::env::set_current_dir(tmp.path()).unwrap();

    let kernel = mk_kernel(StorageMode::InMemory, Some(host));
    let fm = create_fm_agent(&kernel).await;
    let r = kernel.send(&fm, json!({"type":"send", "text":"hi"})).await;
    let stream_id = r["stream_id"].as_str().unwrap().to_string();
    push_token(&kernel, &stream_id, "ok").await;
    complete(&kernel, &stream_id).await;

    // No `.fantastic/` dir anywhere in the cwd.
    assert!(!tmp.path().join(".fantastic").exists());
    if let Some(p) = prev {
        let _ = std::env::set_current_dir(p);
    }
}

#[tokio::test]
async fn push_token_for_unknown_stream_is_silent() {
    let _guard = test_lock();
    let host = MockHost::ready();
    let kernel = mk_kernel(StorageMode::InMemory, Some(host));
    let _fm = create_fm_agent(&kernel).await;
    // No panic, no error.
    push_token(&kernel, "stm_does_not_exist", "x").await;
    complete(&kernel, "stm_does_not_exist").await;
    error(&kernel, "stm_does_not_exist", "boom").await;
}

#[tokio::test]
async fn shutdown_cancels_in_flight() {
    let _guard = test_lock();
    let host = MockHost::ready();
    let kernel = mk_kernel(StorageMode::InMemory, Some(host.clone()));
    let fm = create_fm_agent(&kernel).await;
    let r = kernel.send(&fm, json!({"type":"send", "text":"hi"})).await;
    let _stream_id = r["stream_id"].as_str().unwrap().to_string();
    let _ = kernel.send(&fm, json!({"type":"shutdown"})).await;
    assert_eq!(host.cancels.load(Ordering::Relaxed), 1);
    let st = kernel.send(&fm, json!({"type":"backend_state"})).await;
    assert_eq!(st["in_flight"], false);
}

#[tokio::test]
async fn unknown_verb_returns_error() {
    let _guard = test_lock();
    let host = MockHost::ready();
    let kernel = mk_kernel(StorageMode::InMemory, Some(host));
    let fm = create_fm_agent(&kernel).await;
    let r = kernel.send(&fm, json!({"type":"floppy"})).await;
    assert!(r["error"].as_str().unwrap().contains("unknown verb"));
}
