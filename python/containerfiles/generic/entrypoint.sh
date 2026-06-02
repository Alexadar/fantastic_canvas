#!/usr/bin/env bash
set -euo pipefail
cd /workdir

# Seed the host stack on first boot. Idempotent: subsequent starts find
# `.fantastic/agent.json` and skip seeding.
if [ ! -f .fantastic/agent.json ]; then
  # web + its call-surface children (ws/rest mount routes on web's app).
  fantastic core create_agent handler_module=web.tools port=8080 >/dev/null
  WEB_ID=$(ls .fantastic/agents | grep '^web_' | head -1)
  fantastic "$WEB_ID" create_agent handler_module=web_ws.tools   >/dev/null
  fantastic "$WEB_ID" create_agent handler_module=web_rest.tools >/dev/null
  # canvas_backend: the membership host the TS frontend kernel federates to.
  fantastic core create_agent handler_module=canvas_backend.tools >/dev/null
  # The frontend (canvas/terminal/chat/gl views) is the TS kernel in `ts/`,
  # served WEAKLY via generic agents — a `file` agent rooted at the built
  # `ts/dist` + an `html_agent` mount page (see ts/SERVE.md). Wiring that into
  # this image requires a node build step for ts/dist; tracked as a follow-up.
fi

# `fantastic` blocks on the web agent (uvicorn task) and listens for
# SIGTERM/SIGINT/SIGHUP via the graceful-shutdown path (PR #14).
# `podman stop` sends SIGTERM → graceful walk → clean exit.
exec fantastic
