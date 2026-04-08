# Refactor Plan: voice_assistant → fantastic_agent

## 1. Rename to "fantastic_agent"

**Files to rename/update:**
- `bundled_agents/voice_assistant/` → `bundled_agents/fantastic_agent/`
- `template.json`: name + bundle → `"fantastic_agent"`
- `tools.py`: all `voice_assistant` references → `fantastic_agent`, handler names stay (`voice_transcript`, `voice_interrupt`) since they're voice-mode specific
- `plugin.ts`: plugin name → `fantastic_agent`, `matchAgent` → `agent.bundle === 'fantastic_agent'`
- `skills/voice-assistant.md` → `skills/fantastic-agent.md`
- `main.tsx` import: `@bundles/voice_assistant/plugin` → `@bundles/fantastic_agent/plugin`
- Backend tool names: `get_handbook_voice_assistant` → `get_handbook_fantastic_agent`

## 2. Two Modes: Voice / Chat

The agent supports two interaction modes, switchable via a toggle in the UI header.

### Frontend (`plugin.ts` / new `chat-ui.ts`)

- **Voice mode**: existing orb UI (STT → AI → TTS), unchanged behavior
- **Chat mode**: text input + scrollable message list, classic chat UX
- **Mode toggle**: button in the agent header (via `injectHeader`), switches between `voice` | `chat`
- **Both modes share the same conversation** — switching mode doesn't lose history
- Mode preference stored in `agent.json` metadata (`mode: "voice" | "chat"`) so it persists

### New file: `web/chat-ui.ts`
- `createChatUi(agentId, wsSend, events)` — mirrors `createVoiceUi` interface
- Renders: message list (scrollable div) + text input + send button
- On send: dispatches `voice_transcript` with `{text, is_final: true}` (reuses same backend handler)
- On receive `voice_response`: appends to message list
- Loads history from `chat.json` on init

### Plugin orchestration (`plugin.ts`)
```
injectAgent: create both UIs, show/hide based on mode
injectHeader: mode toggle button (🎙️ / 💬)
```

## 3. Persistent Chat — `chat.json`

**Location:** `.fantastic/agents/{agent_id}/chat.json`

```json
{
  "messages": [
    {"role": "user", "text": "hello", "ts": 1711100000, "mode": "voice"},
    {"role": "assistant", "text": "Hi there!", "ts": 1711100002, "mode": "voice"},
    {"role": "user", "text": "what's the weather?", "ts": 1711100050, "mode": "chat"}
  ]
}
```

### Backend changes (`tools.py`)
- On `voice_transcript`: append `{role: "user", text, ts, mode}` to chat.json
- On AI response complete (`done: true`): append `{role: "assistant", text, ts, mode}` to chat.json
- New WS handler `chat_history` → returns chat.json contents for an agent (frontend loads on init)
- `AiBackendConnector` loads history from chat.json on first access (replaces in-memory-only history)

### Frontend changes
- On mode switch or agent init, fetch chat history via `{type: "chat_history", agent_id}`
- Chat UI renders all messages; voice UI can optionally show last exchange as transcript

## 4. Voice Exclusivity — Shared State

**Problem:** When user clicks "listen" on agent A, all other fantastic_agent instances in voice mode should stop listening/speaking.

### Suggested approach: WS broadcast coordination

**Why WS broadcast (not frontend-only state):**
- Multiple browser tabs / viewers may exist (broadcast mode)
- Backend is the single source of truth for "who is active"
- Consistent with existing architecture (everything goes through WS)

### Protocol

**New WS messages:**

| Direction | Type | Payload | Purpose |
|-----------|------|---------|---------|
| FE → BE | `voice_claim_mic` | `{agent_id}` | "I want the mic" |
| BE → FE (broadcast) | `voice_mic_owner` | `{agent_id \| null}` | "This agent now owns the mic" |

### Backend (`tools.py`)
- Module-level `_mic_owner: str | None = None`
- On `voice_claim_mic`: set `_mic_owner = agent_id`, broadcast `voice_mic_owner` to all clients
- On `voice_transcript` / `voice_interrupt`: only process if `agent_id == _mic_owner`
- On agent delete: if deleted agent was mic owner, clear and broadcast `null`

### Frontend (`voice-ui.ts` / `plugin.ts`)
- On orb click → send `voice_claim_mic` instead of directly activating
- On receiving `voice_mic_owner`:
  - If `agent_id === myId` → activate (start STT/TTS)
  - If `agent_id !== myId` → deactivate (stop STT/TTS, go idle)
  - If `null` → all deactivate
- This naturally handles: click agent A → A claims → B/C/D receive broadcast → they deactivate

### Why this is better than alternatives

| Approach | Pros | Cons |
|----------|------|------|
| **Frontend-only global var** | Simple | Breaks with multiple tabs, no backend awareness |
| **Agent metadata in agent.json** | Persistent | Too slow (file I/O per toggle), race conditions |
| **WS broadcast (chosen)** | Real-time, multi-tab safe, consistent with architecture | Slight complexity |

## File Change Summary

| File | Action |
|------|--------|
| `bundled_agents/voice_assistant/` | Rename dir → `fantastic_agent/` |
| `template.json` | Update name/bundle |
| `tools.py` | Rename refs, add chat.json persistence, add `voice_claim_mic` / `voice_mic_owner` / `chat_history` handlers |
| `plugin.ts` | Rename, add mode toggle, orchestrate voice/chat UIs, handle `voice_mic_owner` |
| `web/voice-ui.ts` | Add `voice_claim_mic` on activate, react to `voice_mic_owner` |
| `web/chat-ui.ts` | **New** — chat mode UI |
| `web/ai-connector.ts` | Minor: pass `mode` field through |
| `skills/fantastic-agent.md` | Rename + update docs |
| `main.tsx` | Update import path |
| `source.py` | Update print message |
