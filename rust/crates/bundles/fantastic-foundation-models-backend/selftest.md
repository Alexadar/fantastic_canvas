# foundation_models_backend selftest

> scopes: backend bundle, verb surface, graceful-degrade,
>   UniFFI host registration
> requires: `cargo build --release --bin fantastic` (Apple build)
> out-of-scope: real Foundation Models inference (Swift app test)

CLI-driven smoke that exercises the wire shape via `fantastic`. The
"real" end-to-end test (Swift host wrapping `LanguageModelSession`,
tokens flowing from on-device model) is verified by the app-side
Claude on a machine with Apple Intelligence enabled — this selftest
only covers the canvas surface.

## Pre-flight

```bash
rm -rf /tmp/fk_fm
mkdir -p /tmp/fk_fm
cd /tmp/fk_fm
FANTASTIC=/path/to/rust/target/release/fantastic
```

Note: the CLI must be built on an Apple target (`target_vendor =
"apple"`) for `foundation_models_backend.tools` to be linked in. On
Linux the bundle is intentionally excluded — running these tests
there will fail at the `create_agent` step with
`bundle foundation_models_backend.tools not installed in this runtime`.

## Tests

### Test 1: cold-boot creates the FM agent

```bash
$FANTASTIC reflect >/tmp/fk_fm/reflect1.json
$FANTASTIC core create_agent handler_module=foundation_models_backend.tools id=fm \
  > /tmp/fk_fm/create.json
jq -e '.id == "fm"' /tmp/fk_fm/create.json
test -d .fantastic/agents/fm
jq -e '.handler_module == "foundation_models_backend.tools"' \
  .fantastic/agents/fm/agent.json
```

Expect: bundle is registered (build is Apple-target); FM agent
created + persisted via the standard merge-only path.

### Test 2: reflect carries provider + probe fields

```bash
$FANTASTIC fm reflect > /tmp/fk_fm/reflect.json
jq -e '.provider == "apple_foundation_models"' /tmp/fk_fm/reflect.json
jq -e '.backend_registered == false' /tmp/fk_fm/reflect.json
jq -e '.apple_intelligence_available == false' /tmp/fk_fm/reflect.json
jq -e '.model_available == false' /tmp/fk_fm/reflect.json
jq -e '.verbs.send | type == "string"' /tmp/fk_fm/reflect.json
jq -e '.verbs.backend_state | type == "string"' /tmp/fk_fm/reflect.json
```

Expect: identity + all four probe fields (provider +
backend_registered + Apple-Intelligence-available +
model_available). No Swift host is wired into the CLI yet (step 2b),
so all probes return `false` and `send` will graceful-degrade.

### Test 3: backend_state — single source of truth

```bash
$FANTASTIC fm backend_state > /tmp/fk_fm/bs.json
jq -e '.backend_registered == false' /tmp/fk_fm/bs.json
jq -e '.apple_intelligence_available == false' /tmp/fk_fm/bs.json
jq -e '.model_available == false' /tmp/fk_fm/bs.json
jq -e '.in_flight == false' /tmp/fk_fm/bs.json
```

Expect: the dedicated verb returns the same probes reflect does,
plus `in_flight` so a client doesn't need to parse reflect (which
also carries verbs + emits + sentence).

### Test 4: send without a host degrades gracefully

```bash
$FANTASTIC fm send text="hello" > /tmp/fk_fm/send.json
jq -e '.error | contains("not registered or not available")' /tmp/fk_fm/send.json
jq -e '.reason == "no_host"' /tmp/fk_fm/send.json
```

Expect: structured error — `reason` lets the client switch between
"setup Apple Intelligence" UX, "model downloading" UX, etc.

### Test 5: history starts empty

```bash
$FANTASTIC fm history > /tmp/fk_fm/hist.json
jq -e '.messages | length == 0' /tmp/fk_fm/hist.json
jq -e '.client_id == "cli"' /tmp/fk_fm/hist.json
```

Expect: empty messages array; default `client_id` is `"cli"`.

### Test 6: interrupt when idle is a no-op

```bash
$FANTASTIC fm interrupt > /tmp/fk_fm/int.json
jq -e '.interrupted == false' /tmp/fk_fm/int.json
```

Expect: `interrupted: false` without erroring — safe to call
defensively from any UI.

### Test 7: status reports nothing in-flight

```bash
$FANTASTIC fm status > /tmp/fk_fm/status.json
jq -e '.current == null' /tmp/fk_fm/status.json
```

Expect: telemetry parity with ollama / nvidia — `current` is null
when idle.

### Test 8: cargo tests (the streaming round-trips)

The CLI selftest can't drive the streaming path without a registered
host. The full token-feedback contract is exercised by the bundle's
unit tests:

```bash
cd /path/to/fantastic_canvas/rust
cargo test -p fantastic-foundation-models-backend
```

Expect: 18 tests pass — `push_token` + `complete` + `error` +
`interrupt` + concurrent streams + Disk-mode sidecar + InMemory
zero-fs.

## Summary table

| Test | Pass / Fail | Notes |
|---|---|---|
| 1. cold-boot creates fm agent |  |  |
| 2. reflect carries provider + probes |  |  |
| 3. backend_state single source of truth |  |  |
| 4. send without host degrades gracefully |  |  |
| 5. history starts empty |  |  |
| 6. interrupt when idle |  |  |
| 7. status reports idle |  |  |
| 8. cargo tests (streaming round-trips) |  |  |

## End-to-end with a Swift host (manual)

When the app side wires up `setFoundationModelsBackend(host:)` with
a real `LanguageModelSession`-backed host, this test exercises the
full path:

1. Boot the brain kernel via `startKernelInMemory(portHint: 0)`
2. Register Swift FM host:
   `try kernel.setFoundationModelsBackend(host: SwiftFMHost())`
3. Create the FM agent:
   `try await kernel.sendJson("core", "{\"type\":\"create_agent\",
   \"handler_module\":\"foundation_models_backend.tools\",
   \"id\":\"fm\"}")`
4. `kernel.sendJson("fm", "{\"type\":\"backend_state\"}")`
   → `{backend_registered:true, apple_intelligence_available:true,
   model_available:true, in_flight:false}`
5. `kernel.sendJson("fm", "{\"type\":\"send\",\"text\":\"Hi there\",
   \"client_id\":\"swift\"}")`
   → `{queued:true, stream_id:..., message_id:...}`
6. Swift's `LanguageModelSession.streamResponse` loop calls
   `kernel.fmPushToken(streamId:..., delta:...)` for each token,
   then `kernel.fmComplete(streamId:...)`.
7. State subscribers receive `token` then `done` events.
8. `kernel.sendJson("fm", "{\"type\":\"history\",\"client_id\":\"swift\"}")`
   returns the full conversation.

Estimated walk-through time on a machine with Apple Intelligence
enabled: ~5 min once the Swift host is implemented.
