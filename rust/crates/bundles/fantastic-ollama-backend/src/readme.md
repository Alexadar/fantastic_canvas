# ollama_backend — local LLM agent
Talks to a local ollama. Per-client chat threads, FIFO lock, native tool-calls, menu cache. Persistence via `file_agent_id`.

This crate is the canonical Rust reference implementation of the
**LLM backend contract**: every other backend (nvidia_nim, future
apple_fm, etc.) must speak the same verbs and emit the same events
so any client can retarget from one backend to another by changing a
single record field — no client-side change. See the module header in
`lib.rs` for the full contract.
