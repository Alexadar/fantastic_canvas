# OpenAI Agent

Connects to any OpenAI-compatible `/v1/chat/completions` endpoint (llama-cpp-server, vLLM, TGI, OpenAI itself).

## Config

- `endpoint`: Default `http://localhost:8080/v1` (llama-cpp default)
- `model`: Model name
- `api_key`: Optional, falls back to `OPENAI_API_KEY` env var
- `context_length`: Auto-detected from `/v1/models` response metadata

## Dispatch/Broadcast API

Same as other AI bundles, prefixed with `openai_*`. See `_ai_shared` docs.
