# FantasticKernel — Swift Package

A Swift Package wrapping the Rust kernel as `Fantastic.xcframework`.
Consume from an Xcode project to embed the kernel inside a sandboxed
iOS / iPadOS / visionOS / macOS app where spawning a subprocess
isn't an option (App Sandbox, App Store).

## Build the XCFramework

```bash
cd ../..             # back to rust/
./scripts/build-xcframework.sh
```

Produces:
- `Fantastic.xcframework/` — universal binary (arm64 + x86_64
  device, simulator, and macOS slices)
- `Sources/FantasticKernel/fantastic.swift` — auto-generated UniFFI
  bindings

## Consume from Swift

```swift
import FantasticKernel

let kernel = try await Fantastic.startKernel(
    workdir: appGroupURL.path,
    portHint: 0
)
let port = kernel.httpPort()
// Point WKWebView at http://127.0.0.1:\(port)/<canvas_id>/
defer { kernel.shutdown() }
```

The kernel binds an axum HTTP / WS / REST server on `127.0.0.1:<port>`
inside the app process. Loopback TCP is permitted in iOS sandbox.
WKWebView consumes the same surface a browser does on a server — no
divergence between embedded and standalone runs.

## Wire-level surface

Same as the standalone CLI:

| route                                | what                              |
|--------------------------------------|-----------------------------------|
| `GET /`                              | root index                        |
| `GET /transport.js`                  | the JS transport client           |
| `GET /<agent_id>/`                   | render_html dispatch              |
| `GET /<agent_id>/file/<path>`        | file read proxy                   |
| `GET /<agent_id>/ws`                 | WebSocket verb channel            |
| `GET /<rest>/_reflect[/<target>]`    | REST reflect shortcut             |
| `POST /<rest>/<target>` body=json    | REST verb dispatch                |

## License

MIT.
