//! Integration test: FM bundle's `send` verb must fetch the current
//! tool list from the `tools.tools` bundle and forward it to the
//! host as `tools_json`. Proves the brain-kernel step-4 chain:
//!
//!   `kernel.send("fm", {send, text})`
//!     → FM bundle's `send` verb fires
//!     → bundle calls `kernel.send("tools", {list_for_llm})`
//!     → bundle calls `host.stream_response(..., tools_json)`
//!     → MockHost captures tools_json containing the registered tool
//!
//! Tests hold a serialization lock across awaits because the FM
//! bundle's host slot is process-global (matches the FM bundle's
//! own test serialization).
#![allow(clippy::await_holding_lock)]

use fantastic_foundation_models_backend::{
    clear_host as fm_clear_host, register_host as fm_register_host, FoundationModelsBackendBundle,
    FoundationModelsHost, HANDLER_MODULE as FM_HM,
};
use fantastic_kernel::{Agent, AgentId, Kernel, StorageMode};
use fantastic_tools::{clear as tools_clear, ToolsBundle, HANDLER_MODULE as TOOLS_HM};
use serde_json::{json, Map, Value};
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex, MutexGuard, OnceLock as StdOnceLock};

/// Serialize integration tests — FM's host slot is process-global,
/// same isolation reason as the FM bundle's own tests.
fn test_lock() -> MutexGuard<'static, ()> {
    static LOCK: StdOnceLock<Mutex<()>> = StdOnceLock::new();
    let m = LOCK.get_or_init(|| Mutex::new(()));
    match m.lock() {
        Ok(g) => g,
        Err(p) => p.into_inner(),
    }
}

/// Captured `stream_response` args including the tools_json the
/// bundle is supposed to inject.
type StreamCall = (String, String, String, String, String);

#[derive(Default)]
struct CapturingHost {
    available: AtomicBool,
    model_loaded: AtomicBool,
    last_stream: Mutex<Option<StreamCall>>,
}

impl CapturingHost {
    fn ready() -> Arc<Self> {
        let h = Arc::new(Self::default());
        h.available
            .store(true, std::sync::atomic::Ordering::Relaxed);
        h.model_loaded
            .store(true, std::sync::atomic::Ordering::Relaxed);
        h
    }
}

impl FoundationModelsHost for CapturingHost {
    fn is_available(&self) -> bool {
        self.available.load(std::sync::atomic::Ordering::Relaxed)
    }
    fn model_available(&self) -> bool {
        self.model_loaded.load(std::sync::atomic::Ordering::Relaxed)
    }
    fn stream_response(
        &self,
        stream_id: String,
        system_prompt: String,
        history_json: String,
        user_message: String,
        tools_json: String,
    ) {
        *self.last_stream.lock().unwrap() = Some((
            stream_id,
            system_prompt,
            history_json,
            user_message,
            tools_json,
        ));
    }
    fn cancel(&self, _stream_id: String) {}
}

fn mk_kernel() -> Arc<Kernel> {
    tools_clear();
    fm_clear_host();
    let mut kernel = Kernel::with_storage(StorageMode::InMemory);
    kernel.bundles.register(TOOLS_HM, ToolsBundle::new());
    kernel
        .bundles
        .register(FM_HM, FoundationModelsBackendBundle::new());
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
    kernel
}

#[tokio::test]
async fn fm_send_fetches_registered_tools_and_passes_to_host() {
    let _g = test_lock();
    let kernel = mk_kernel();
    let host = CapturingHost::ready();
    fm_register_host(host.clone());

    // 1. Create the tools agent.
    let r = kernel
        .send(
            &AgentId::from("core"),
            json!({"type":"create_agent","handler_module":TOOLS_HM,"id":"tools"}),
        )
        .await;
    assert_eq!(r["id"], "tools");

    // 2. Create the FM agent.
    let r = kernel
        .send(
            &AgentId::from("core"),
            json!({"type":"create_agent","handler_module":FM_HM,"id":"fm"}),
        )
        .await;
    assert_eq!(r["id"], "fm");

    // 3. Register a tool BEFORE the FM call.
    let r = kernel
        .send(
            &AgentId::from("tools"),
            json!({
                "type":"register",
                "name":"get_weather",
                "agent_id":"weather_agent",
                "verb":"lookup",
                "description":"Returns the current weather for a city.",
                "parameters_schema":{
                    "type":"object",
                    "properties":{"city":{"type":"string","minLength":1}},
                    "required":["city"],
                    "additionalProperties":false,
                },
            }),
        )
        .await;
    assert_eq!(r["ok"], true, "register reply: {r}");

    // 4. Fire FM send. The bundle's send verb must internally call
    //    kernel.send("tools", {list_for_llm}) and pass the result to
    //    host.stream_response as tools_json.
    let r = kernel
        .send(
            &AgentId::from("fm"),
            json!({"type":"send","text":"hi","client_id":"test"}),
        )
        .await;
    assert_eq!(r["queued"], true, "FM send reply: {r}");

    // 5. The captured host call must include the registered tool in
    //    LLM-facing shape: {name, description, parameters}.
    let captured = host
        .last_stream
        .lock()
        .unwrap()
        .clone()
        .expect("host received stream_response");
    let tools_json = captured.4;
    assert!(
        !tools_json.is_empty() && tools_json != "[]",
        "tools_json must be non-empty array; got {tools_json:?}",
    );
    let tools: Vec<Value> =
        serde_json::from_str(&tools_json).expect("tools_json is valid JSON array");
    assert_eq!(tools.len(), 1, "exactly one tool registered");
    assert_eq!(tools[0]["name"], "get_weather");
    assert_eq!(
        tools[0]["description"],
        "Returns the current weather for a city."
    );
    assert!(
        tools[0]["parameters"].is_object(),
        "parameters field must be a JSON object"
    );
    assert_eq!(tools[0]["parameters"]["type"], "object");
    assert_eq!(tools[0]["parameters"]["required"][0], "city");
    // LLM-facing shape MUST NOT leak implementation details.
    assert!(
        tools[0].get("sender").is_none(),
        "sender must not be in LLM shape"
    );
    assert!(
        tools[0].get("agent_id").is_none(),
        "agent_id must not be in LLM shape"
    );
    assert!(
        tools[0].get("verb").is_none(),
        "verb must not be in LLM shape"
    );
}

#[tokio::test]
async fn fm_send_with_no_tools_agent_passes_empty_array() {
    let _g = test_lock();
    // Setup kernel WITHOUT creating the tools agent. FM's send must
    // still work — graceful degrade via the `_ => "[]"` arm in
    // fetch_tools_json.
    let kernel = mk_kernel();
    let host = CapturingHost::ready();
    fm_register_host(host.clone());

    let _ = kernel
        .send(
            &AgentId::from("core"),
            json!({"type":"create_agent","handler_module":FM_HM,"id":"fm"}),
        )
        .await;

    let r = kernel
        .send(
            &AgentId::from("fm"),
            json!({"type":"send","text":"hi","client_id":"test"}),
        )
        .await;
    assert_eq!(r["queued"], true, "FM send reply: {r}");

    let captured = host
        .last_stream
        .lock()
        .unwrap()
        .clone()
        .expect("host received stream_response");
    assert_eq!(
        captured.4, "[]",
        "tools_json must be empty array when no tools agent exists"
    );
}

#[tokio::test]
async fn fm_send_with_empty_registry_passes_empty_array() {
    let _g = test_lock();
    // tools agent exists but no tools registered.
    let kernel = mk_kernel();
    let host = CapturingHost::ready();
    fm_register_host(host.clone());

    let _ = kernel
        .send(
            &AgentId::from("core"),
            json!({"type":"create_agent","handler_module":TOOLS_HM,"id":"tools"}),
        )
        .await;
    let _ = kernel
        .send(
            &AgentId::from("core"),
            json!({"type":"create_agent","handler_module":FM_HM,"id":"fm"}),
        )
        .await;

    let r = kernel
        .send(
            &AgentId::from("fm"),
            json!({"type":"send","text":"hi","client_id":"test"}),
        )
        .await;
    assert_eq!(r["queued"], true);

    let captured = host
        .last_stream
        .lock()
        .unwrap()
        .clone()
        .expect("host received stream_response");
    assert_eq!(
        captured.4, "[]",
        "tools_json must be empty array when registry is empty"
    );
}
