//! `fantastic` CLI — composes the kernel + default bundle set.
//!
//! Modes (matched in order):
//!
//! 1. `fantastic` (no args) — daemon mode. Bootstrap the workdir,
//!    dispatch `boot` on every loaded agent, then block until
//!    SIGINT/SIGTERM, then `shutdown` gracefully.
//! 2. `fantastic reflect [<agent_id>]` — one-shot reflect on root
//!    (or specific id). No lock acquired; works while a daemon owns
//!    the dir.
//! 3. `fantastic <agent_id> <verb> [k=v ...]` — one-shot RPC.
//!    Acquires the lock; refuses with a clear message if a daemon
//!    already holds it.

use fantastic_kernel::bootstrap::{self, BootstrapOptions, DEFAULT_ROOT_ID};
use fantastic_kernel::{AgentId, BundleRegistry};
use serde_json::{json, Map, Value};
use std::sync::Arc;

fn register_default_bundles() -> BundleRegistry {
    let mut reg = BundleRegistry::new();

    // ── Always-available bundles (work under both `desktop` and `embedded`).
    //
    // None of these spawn subprocesses, fork, or load dynamic libraries,
    // so they all compile + run on iOS. The Bundle trait is the only
    // dependency the kernel cares about; everything below is pure-Rust
    // async over axum/tokio.
    reg.register("file.tools", fantastic_file::FileBundle);
    reg.register("web.tools", fantastic_web::WebBundle);
    reg.register("web_ws.tools", fantastic_web_ws::WebWsBundle);
    reg.register("web_rest.tools", fantastic_web_rest::WebRestBundle);
    reg.register("html_agent.tools", fantastic_html_agent::HtmlAgentBundle);
    reg.register(
        "canvas_backend.tools",
        fantastic_canvas_backend::CanvasBackendBundle,
    );
    reg.register(
        "canvas_webapp.tools",
        fantastic_canvas_webapp::CanvasWebappBundle,
    );
    reg.register("scheduler.tools", fantastic_scheduler::SchedulerBundle);
    reg.register("gl_agent.tools", fantastic_gl_agent::GlAgentBundle);
    reg.register(
        "telemetry_pane.tools",
        fantastic_telemetry_pane::TelemetryPaneBundle,
    );
    reg.register(
        "ai_chat_webapp.tools",
        fantastic_ai_chat_webapp::AiChatWebappBundle,
    );

    // ── Full-tier-only bundles (subprocess / dynamic-loading / etc.).
    //
    // None ported yet. When a future bundle needs `std::process::Command`,
    // `fork`, or `libloading::Library`, add its crate as an optional dep
    // and register it under this gate. The `embedded` build (iOS Lite,
    // visionOS, sandboxed macOS) compiles cleanly without these.
    //
    // Example:
    //   #[cfg(feature = "full")]
    //   reg.register("terminal_backend.tools", fantastic_terminal_backend::TerminalBackendBundle);
    //
    //   #[cfg(feature = "full")]
    //   reg.register("python_runtime.tools", fantastic_python_runtime::PythonRuntimeBundle);
    #[cfg(feature = "full")]
    {
        // (placeholder — populate when desktop-only bundles land)
    }

    reg
}

#[tokio::main]
async fn main() -> std::process::ExitCode {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("warn,fantastic=info")),
        )
        .init();

    let args: Vec<String> = std::env::args().skip(1).collect();
    match dispatch(args).await {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("fantastic: {e}");
            std::process::ExitCode::FAILURE
        }
    }
}

async fn dispatch(args: Vec<String>) -> Result<(), Box<dyn std::error::Error>> {
    let workdir = std::env::current_dir()?;

    // Mode 2: `reflect [<id>]`
    if args.first().map(String::as_str) == Some("reflect") {
        let opts = BootstrapOptions::one_shot(&workdir);
        let booted = bootstrap::bootstrap(register_default_bundles(), opts)?;
        let target = args
            .get(1)
            .cloned()
            .unwrap_or_else(|| DEFAULT_ROOT_ID.to_string());
        let reply = booted
            .kernel
            .send(&AgentId::from(target.as_str()), json!({"type": "reflect"}))
            .await;
        println!("{}", serde_json::to_string_pretty(&reply)?);
        return Ok(());
    }

    // Mode 3: `<id> <verb> [k=v ...]`
    if args.len() >= 2 && args[0] != "boot" {
        let id = args[0].clone();
        let verb = args[1].clone();
        let mut payload = Map::new();
        payload.insert("type".to_string(), json!(verb));
        for kv in &args[2..] {
            if let Some((k, v)) = kv.split_once('=') {
                payload.insert(k.to_string(), parse_kv(v));
            }
        }
        let opts = BootstrapOptions::daemon(&workdir);
        let booted = bootstrap::bootstrap(register_default_bundles(), opts)?;
        let reply = booted
            .kernel
            .send(&AgentId::from(id.as_str()), Value::Object(payload))
            .await;
        println!("{}", serde_json::to_string_pretty(&reply)?);
        bootstrap::shutdown(&workdir)?;
        return Ok(());
    }

    // Mode 1: daemon.
    let opts = BootstrapOptions::daemon(&workdir);
    let booted = bootstrap::bootstrap(register_default_bundles(), opts)?;
    // Seed the root readme if missing.
    let _ = fantastic_core::seed_root_readme(&workdir);
    let kernel = Arc::clone(&booted.kernel);

    // `boot` every loaded agent. The web bundle uses this to spawn its
    // axum listener; other bundles use it for whatever lazy init they
    // need. Failures are logged + skipped — boot must never abort the
    // daemon (matches Python's behaviour).
    for id in booted.loaded.iter() {
        let reply = kernel.send(id, json!({"type": "boot"})).await;
        if let Some(err) = reply.get("error").and_then(Value::as_str) {
            tracing::warn!(agent = %id, error = %err, "boot failed");
        }
    }

    // Composition decision: block ONLY if at least one agent is a web
    // host (or if stdin is a tty — REPL mode in a later phase). Else
    // exit silently, matching the python kernel's compose semantics.
    let has_web = kernel
        .agents
        .iter()
        .any(|e| e.value().handler_module.as_deref() == Some("web.tools"));
    if !has_web {
        bootstrap::shutdown(&workdir)?;
        return Ok(());
    }

    // Wait for SIGINT/SIGTERM, then graceful shutdown.
    eprintln!(
        "fantastic: daemon up. {} agent(s) loaded. Ctrl-C to stop.",
        booted.loaded.len()
    );
    tokio::select! {
        _ = tokio::signal::ctrl_c() => {},
        _ = sigterm() => {},
    }
    eprintln!("fantastic: shutting down...");
    // Issue shutdown on every loaded agent (LIFO so children stop
    // before parents).
    for id in booted.loaded.iter().rev() {
        let _ = kernel.send(id, json!({"type": "shutdown"})).await;
    }
    bootstrap::shutdown(&workdir)?;
    eprintln!("fantastic: done.");
    Ok(())
}

#[cfg(unix)]
async fn sigterm() {
    use tokio::signal::unix::{signal, SignalKind};
    let mut s = match signal(SignalKind::terminate()) {
        Ok(s) => s,
        Err(_) => return std::future::pending::<()>().await,
    };
    s.recv().await;
}

#[cfg(not(unix))]
async fn sigterm() {
    std::future::pending::<()>().await
}

/// Crude k=v parser: try bool, then i64, then leave as string. Mirrors
/// what the Python CLI does for one-shot `fantastic <id> <verb> k=v`.
fn parse_kv(v: &str) -> Value {
    match v {
        "true" => return json!(true),
        "false" => return json!(false),
        _ => {}
    }
    if let Ok(n) = v.parse::<i64>() {
        return json!(n);
    }
    Value::String(v.to_string())
}
