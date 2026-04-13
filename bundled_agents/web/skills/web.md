# Web Agent

HTTP/WebSocket transport bundle. Serves every other agent's UI at `{base}/{agent_id}/`
and injects `fantastic_transport()` as a global.

## Config (agent.json)

- `port` (int, default 8888) — uvicorn port
- `base_route` (str, default `""`) — URL prefix, e.g. `"/admin"`
- `readonly` (bool, default false) — reject non-GET dispatches (planned)

## Routes

- `{base}/_fantastic/transport.js` — the injected transport
- `{base}/_fantastic/description.json` — protocol spec for LLM introspection
- `{base}/{agent_id}/` — serve agent's HTML + injected transport
- `{base}/{agent_id}/{asset}` — static assets from bundle's `web/dist/`
- `{base}/{agent_id}/ws` — protocol WebSocket

## Dispatch API

- `web_configure(agent_id, port?, base_route?)` — change config; uvicorn hot-restarts.

## Multiple web agents

Add multiple web instances for different ports, policies, or base routes.
Each is independent — its own uvicorn task, own config.
