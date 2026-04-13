# fantastic_agent

Generic chat UI that fronts any AI backend (ollama/openai/anthropic/integrated).

## Config (agent.json)

- `upstream_agent_id` — the AI agent to chat with
- `upstream_bundle` — bundle name of upstream (for dispatch routing)

## Usage

```
fantastic add ollama
fantastic add fantastic_agent
fantastic_agent_configure(agent_id="<fa_id>", upstream_agent_id="<ollama_id>", upstream_bundle="ollama")
```

Then open `/{fa_id}/` in browser. UI shows chat, subscribes to upstream via
`transport.watch()` — no knowledge of WS, just the protocol abstraction.
