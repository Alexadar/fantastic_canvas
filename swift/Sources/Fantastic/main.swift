// `fantastic` CLI binary.
//
// Mirrors Rust's `fantastic-cli`. Composes the kernel + default
// bundle set into an executable that supports:
//   - `fantastic reflect [<id>]` — one-shot reflect (root or named id)
//   - `fantastic <id> <verb> [k=v ...]` — one-shot RPC
//   - (no args) — daemon mode placeholder (not wired in Phase 7)
//
// macOS-only because the unsandboxed bundle set includes subprocess
// bundles (local_runner, python_runtime).

import FantasticAiChatWebapp
import FantasticCanvasBackend
import FantasticCanvasWebapp
import FantasticCliBundle
import FantasticFile
import FantasticGlAgent
import FantasticHtmlAgent
import FantasticJSON
import FantasticKernel
import FantasticKernelBridge
import FantasticOllamaBackend
import FantasticProxyAgent
import FantasticScheduler
import FantasticTelemetryPane
import FantasticTerminalWebapp
import FantasticTools
import FantasticWeb
import Foundation

#if os(macOS)
    import FantasticLocalRunner
    import FantasticPythonRuntime
#endif

func makeDefaultRegistry() -> BundleRegistry {
    let r = BundleRegistry()
    r.register("file.tools", FileBundle())
    r.register("proxy_agent.tools", ProxyAgentBundle())
    r.register("tools.tools", ToolsBundle())
    r.register("html_agent.tools", HtmlAgentBundle())
    r.register("gl_agent.tools", GlAgentBundle())
    r.register("scheduler.tools", SchedulerBundle())
    r.register("canvas_backend.tools", CanvasBackendBundle())
    r.register("canvas_webapp.tools", CanvasWebappBundle())
    r.register("ai_chat_webapp.tools", AiChatWebappBundle())
    r.register("terminal_webapp.tools", TerminalWebappBundle())
    r.register("telemetry_pane.tools", TelemetryPaneBundle())
    r.register("kernel_bridge.tools", KernelBridgeBundle())
    r.register("web.tools", WebBundle())
    r.register("ollama_backend.tools", OllamaBackendBundle())
    #if os(macOS)
        r.register("local_runner.tools", LocalRunnerBundle())
        r.register("python_runtime.tools", PythonRuntimeBundle())
    #endif
    return r
}

func parseKV(_ s: String) -> JSON {
    switch s {
    case "true": return .bool(true)
    case "false": return .bool(false)
    default: break
    }
    if let i = Int64(s) { return .integer(i) }
    return .string(s)
}

@main
struct FantasticCLI {
    static func main() async {
        let args = CommandLine.arguments.dropFirst()
        let kernel = Kernel(storage: .inMemory, bundles: makeDefaultRegistry())
        let core = Agent(id: "core", handlerModule: nil, parentId: nil)
        kernel.register(core)
        kernel.setRoot(core)

        if args.isEmpty {
            print(
                "fantastic (Swift port) — usage: fantastic reflect [<id>] | fantastic <id> <verb> [k=v ...]"
            )
            return
        }

        if args.first == "reflect" {
            let target = args.dropFirst().first ?? "core"
            let reply = await kernel.send(
                AgentId(target), .object(["type": .string("reflect")]))
            print(reply.serialize())
            return
        }

        if args.count >= 2 {
            let argsArr = Array(args)
            let id = argsArr[0]
            let verb = argsArr[1]
            var payload: [String: JSON] = ["type": .string(verb)]
            for kv in argsArr.dropFirst(2) {
                if let eq = kv.firstIndex(of: "=") {
                    let key = String(kv[..<eq])
                    let value = String(kv[kv.index(after: eq)...])
                    payload[key] = parseKV(value)
                }
            }
            let reply = await kernel.send(AgentId(id), .object(.init(uniqueKeysWithValues: payload.map { ($0.key, $0.value) })))
            print(reply.serialize())
            return
        }

        print("fantastic: unrecognized arguments")
    }
}
