# Dashboard Overview

A live-updating agent cards dashboard — shows all top-level agents at a glance.

## Getting Started

```bash
fantastic add dashboard              # creates dashboard agent (name: "main")
fantastic add dashboard --name ops   # creates a named dashboard instance
fantastic                            # starts server with dashboard loaded
```

The dashboard is served at `/dashboard/{name}` (e.g. `/dashboard/main`).

## What It Shows

- **Agent cards** for all top-level agents (no parent): canvases, dashboards, standalone bundles
- Each card displays: display name, bundle badge, agent ID, child count, created timestamp
- Cards are grouped by bundle type
- Canvas cards link to `/canvas/{name}`, dashboard cards link to `/dashboard/{name}`
- The current dashboard's own card is highlighted with an accent border

## Live Updates

The dashboard connects to `/ws` and re-fetches state on:
- `agent_created` — new agent added
- `agent_deleted` — agent removed
- `agent_updated` — agent metadata changed
- `reload` — full reload signal

A green/gray connection status dot shows WebSocket health.

## Multiple Dashboards

Multiple dashboard instances can coexist. Each shows all top-level agents (including other dashboards). Use `--name` to distinguish them:

```bash
fantastic add dashboard --name ops
fantastic add dashboard --name debug
```

## Tools

| Tool | Description |
|------|-------------|
| `get_handbook_dashboard(skill)` | Get dashboard skill docs |
