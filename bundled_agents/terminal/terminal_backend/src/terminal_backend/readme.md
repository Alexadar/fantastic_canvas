# terminal_backend — PTY shell
Verb: shell (`cmd`) runs a command in a persistent PTY, streams token/done. Per-agent interrupt/stop. The process running in the PTY (e.g. `claude`) reaches the kernel via `fantastic` CLI one-shots or the web surface.

Streaming output is flow-controlled (VSCode's terminal model, ported): the PTY reader detaches once >100K emitted chars sit unacked and re-attaches once a consumer's `ack` verb drains the backlog — real backpressure so a flood can't lock up a tab. `write` is looped + per-agent serialized so large pastes land whole and bracketed-paste sequences can't interleave. `shell` is exempt (drains via scrollback).
