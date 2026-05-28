// `fantastic` CLI binary.
//
// Supports:
//   - `fantastic reflect [<id>]`        — one-shot reflect
//   - `fantastic <id> <verb> [k=v ...]` — one-shot RPC
//   - `fantastic chat [<workdir>]`      — interactive REPL probe
//                                         talking to the canvas
//                                         agent surface via the
//                                         Apple FM backend bundle
//   - (no args)                          — usage banner

import FantasticJSON
import FantasticKernel
import FantasticKernelStartup
import Foundation

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

        // `chat` boots a disk-backed kernel against a workdir, so
        // we branch BEFORE the in-memory boot below.
        if args.first == "chat" {
            let workdir = args.dropFirst().first.map { String($0) } ?? "./.fantastic-chat"
            await ChatMode.run(workdir: workdir)
            return
        }

        let kernel: Kernel
        do {
            kernel = try await startKernelInMemory(portHint: 0)
        } catch {
            FileHandle.standardError.write(
                "fantastic: kernel boot failed: \(error)\n".data(using: .utf8) ?? Data())
            exit(1)
        }

        if args.isEmpty {
            print(
                """
                fantastic (Swift port) — usage:
                  fantastic reflect [<id>]
                  fantastic <id> <verb> [k=v ...]
                  fantastic chat [<workdir>]
                """
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
            var payload: [(String, JSON)] = [("type", .string(verb))]
            for kv in argsArr.dropFirst(2) {
                if let eq = kv.firstIndex(of: "=") {
                    let key = String(kv[..<eq])
                    let value = String(kv[kv.index(after: eq)...])
                    payload.append((key, parseKV(value)))
                }
            }
            let reply = await kernel.send(
                AgentId(id),
                .object(.init(uniqueKeysWithValues: payload))
            )
            print(reply.serialize())
            return
        }

        print("fantastic: unrecognized arguments")
    }
}
