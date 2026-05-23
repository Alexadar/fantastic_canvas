# foundation_models_backend — Apple Foundation Models adapter

A chat backend bundle that answers the same surface as `ollama_backend` /
`nvidia_nim_backend` (`send` / `history` / `interrupt` / `reflect` /
`backend_state`) so it drops into `ai_chat_webapp`'s `upstream_id` field
without any client changes.

The bundle **does not embed an LLM**. It forwards `send` requests to a
host-provided implementation of `FoundationModelsHost`. On the
fantastic_app's brain kernel the host is a Swift class wrapping
`LanguageModelSession` (Apple Foundation Models); in plain-Rust tests
the host is a mock that drives token feedback directly.

## Why dirty binding to a host

Apple's `FoundationModels` is **pure Swift**, no Objective-C surface,
no C ABI, no published Rust bindings. The only path is a UniFFI
callback interface — Rust defines the trait, Swift implements it, the
embedding app calls `Kernel::set_foundation_models_backend(host)` at
boot.

## Verbs

| verb | shape |
|---|---|
| `reflect` | `{id, sentence, provider, available, model_available, backend_registered, verbs}` |
| `boot` | `{ok: true}` — no-op (host registration is independent) |
| `shutdown` | cancels in-flight stream if any |
| `send` | args `{text, client_id?}` → `{queued, stream_id, message_id}` |
| `history` | args `{client_id?}` → `{messages, client_id}` |
| `interrupt` | args `{client_id?}` → `{interrupted: bool}` |
| `backend_state` | `{apple_intelligence_available, model_available, backend_registered, in_flight, stream_id?, message_id?}` |
| `status` | telemetry parity with ollama/nvidia (`current` field) |

## Graceful degrade

- No host registered → `send` returns `{error: "Apple Foundation
  Models not registered or not available"}`; `backend_state` reports
  `backend_registered: false`. Client renders a CTA.
- Host registered but `is_available: false` → `send` errors with
  structured reason.
- Host registered + available but `model_available: false` → `send`
  errors with structured reason.

## Lineage

The verb shape mirrors `ollama_backend` (in this workspace). The
`backend_state` verb is new — gives a single read-only probe that the
client can poll without parsing reflect.
