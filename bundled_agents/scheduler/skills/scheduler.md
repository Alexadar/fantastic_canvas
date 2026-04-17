# `scheduler` bundle — recurring tasks as an agent

One agent per scheduler instance. Each scheduler runs its own tick loop
and owns its own schedules + fire-history. Core has no scheduler code.

## Add a scheduler

```
add scheduler                 # name defaults to "main"
add scheduler name=heartbeat  # additional scheduler with different policy
```

Quickstart seeds a `scheduler_main`; you rarely need to add another.

## Verbs (via `agent_call`)

```
# Schedule a tool call every N seconds (runs as `for_agent_id`)
@scheduler_<id> agent_call verb=schedule \
    for_agent_id=<target> \
    action='{"type":"tool","tool":"process_output","args":{"max_lines":5}}' \
    interval_seconds=60

# Schedule an AI prompt against an AI agent
@scheduler_<id> agent_call verb=schedule \
    for_agent_id=<ollama_id> \
    action='{"type":"prompt","text":"summarize recent activity"}' \
    interval_seconds=300

# Other verbs
@scheduler_<id> agent_call verb=list
@scheduler_<id> agent_call verb=pause   schedule_id=sch_abc    # pause one
@scheduler_<id> agent_call verb=pause                           # pause all (scheduler-wide)
@scheduler_<id> agent_call verb=resume  schedule_id=sch_abc
@scheduler_<id> agent_call verb=unschedule schedule_id=sch_abc
@scheduler_<id> agent_call verb=tick_now   schedule_id=sch_abc   # fire once now
@scheduler_<id> agent_call verb=history    limit=20              # last N fires
```

## What happens on every fire

The scheduler invokes the action (tool dispatch, or `{bundle}_send` for
`type: "prompt"`), then:

1. **Emits `schedule_fired` on the bus** to:
   - the **scheduler agent's** inbox (audit),
   - the **target agent's** inbox (so the target's UI sees "the reply arrived").

   Event shape:
   ```
   {type:"schedule_fired", schedule_id, scheduler_id, for_agent_id,
    action, result: <ToolResult.data|None>, error: null|str,
    ts, duration_ms}
   ```

2. **Appends to `.fantastic/agents/{sched_id}/history.jsonl`**
   (ring-trimmed to ~500 entries).

Callers have three modes:

| Mode | How |
|---|---|
| Fire-and-forget | Just `schedule`, ignore |
| Live notification | `transport.watch(SCHED_ID)` (frontend) or `bus.watch(SCHED_ID, me)` (backend) → every fire shows up in inbox |
| Pull results later | `agent_call verb=history [schedule_id=…] [limit=N]` |

## Metadata (agent.json fields)

| field | meaning |
|---|---|
| `tick_sec` | poll resolution (default 1.0) |
| `paused` | bool; when true, the tick loop skips all schedules on this scheduler |

## Sidecars

`.fantastic/agents/{scheduler_id}/schedules.json` — array of schedule dicts.
`.fantastic/agents/{scheduler_id}/history.jsonl` — one event per line,
trimmed when it grows past 2× ring size.

Both live under the scheduler agent's directory, so `delete_agent` wipes
both automatically.
