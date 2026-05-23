# proxy_agent — host-implemented agents

A bundle that forwards every verb to a host-provided implementation
of [`ProxyAgentHost`]. Hosts are registered per-agent-id, so
multiple `proxy_agent.tools` instances in the same kernel each have
their own behaviour.

Primary use: SwiftUI views as first-class agents in the kernel
(`chat_ui`, `settings_ui`, etc.) — addressable, in the reflect
tree, in state events, lifecycle-managed by standard
`create_agent` / `delete_agent`. Same mechanism serves any
host-driven feature: AppIntents bridges, Vision adapters, Clipboard
helpers, JavaScript runtimes, and so on. Naming is `ProxyAgent`
because UI is one consumer, not the only one.

## How it works

1. The Swift app creates a proxy agent via the standard verb:

   ```swift
   try await kernel.sendJson("core", #"""
     {"type":"create_agent","handler_module":"proxy_agent.tools","id":"chat_ui"}
   """#)
   ```

2. It registers a Swift `ProxyAgent` callback for that id:

   ```swift
   try kernel.registerProxyAgent(agentId: "chat_ui", host: ChatUIHost())
   ```

3. Other agents address it like any agent — `kernel.send("chat_ui",
   payload)` arrives at `host.handle(payload_json)`. Swift re-
   dispatches to `MainActor` for SwiftUI mutations and returns a
   sync ack.

4. The UI sends with sender attribution via the new
   `Kernel::send_json_as` method — state events carry
   `sender = "chat_ui"`.

5. The UI broadcasts state changes via `Kernel::proxy_emit` —
   watchers of the UI agent see them via the standard fan-out.

## Verbs (default behaviour)

| verb | no host registered | with host registered |
|---|---|---|
| `reflect` | `{id, sentence: "no host", host_registered: false}` | host's `handle({type:"reflect"})` reply (host_registered overlaid as `true`) |
| `boot` | `{ok: true}` | host's `on_boot()` + `handle({type:"boot"})` |
| `shutdown` | `{ok: true}` | host's `handle({type:"shutdown"})` |
| anything else | `{error, reason: "no_host"}` | host's `handle(payload_json)` |

## Lifecycle

`Bundle::on_delete` fires during cascade — calls `host.on_delete()`
+ drops the host from the registry. No explicit `unregisterProxyAgent`
needed if you cascade-delete through the standard verb.

## Threading

UniFFI 0.29 callback methods are sync. Swift impls re-dispatch to
`MainActor` via `Task { @MainActor in … }`; the sync return value
is just an ack. The standard streaming-out pattern (FM's
`{queued, stream_id}` + `proxy_emit` token feedback) applies here
too if the host needs to fire async events back.
