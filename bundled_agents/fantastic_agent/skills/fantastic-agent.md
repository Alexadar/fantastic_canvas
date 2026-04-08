# Fantastic Agent

Multi-mode AI agent for Fantastic Canvas. Supports **voice** and **chat** modes with persistent conversation history.

## Modes

### Voice Mode
Always-on voice interaction with browser-native STT/TTS and barge-in support. Renders as an interactive orb.

### Chat Mode
Text-based chat with scrollable message history and input field. Same AI backend, different interface.

Both modes share the same conversation history stored in `chat.json`.

## How It Works

Click the mode toggle in the agent header to switch between voice (microphone icon) and chat (message icon).

### Voice State Machine

```
idle → listening → processing → speaking → listening (loop)
                                    ↓
                              speaking → listening (barge-in: user interrupts)
```

**States:**
- **idle**: Mic off. Tap the orb to start.
- **listening**: Mic on, transcribing speech. Waits for user to finish a complete thought before sending.
- **processing**: Transcript sent to AI backend. Awaiting response. Orb shows spinner.
- **speaking**: AI response being spoken via TTS. User can interrupt (barge-in) by talking.

Each state change is announced audibly: "listening", "processing".

### Voice Exclusivity

Only one fantastic agent can listen at a time. Clicking "listen" on one agent automatically stops listening/speech on all others. This is coordinated via WS broadcast (`voice_claim_mic` / `voice_mic_owner`).

### Intelligent Prompt Detection

The STT doesn't fire on every pause. It accumulates speech and commits when:
1. Browser's speech recognizer marks a result as final (sentence boundary), OR
2. Silence after speech for 1.2 seconds with accumulated text, OR
3. No new speech for 2 seconds (user paused mid-thought)

This prevents sending half-sentences to the AI.

### Barge-In

When the AI is speaking and the user starts talking:
1. TTS is immediately cancelled
2. An interrupt signal is sent to the AI backend
3. STT resumes listening for the new input

### Chat History (`chat.json`)

All conversations are persisted to `.fantastic/agents/{id}/chat.json`:
```json
{
  "messages": [
    {"role": "user", "text": "hello", "ts": 1711100000, "mode": "voice"},
    {"role": "assistant", "text": "Hi!", "ts": 1711100002, "mode": "voice"}
  ]
}
```

History is loaded on agent init and shared across mode switches.

### AI Backend Connector

The agent connects to an AI backend (under development) that:
- Accepts transcribed text + conversation history
- Proxies to an LLM with tool calling capability
- Streams response chunks back for real-time TTS

Currently runs an **echo stub** until the AI backend is wired.

Configure the backend URL:
```
fantastic_agent_configure(ai_backend_url="http://localhost:8001/v1/chat")
```

### WS Protocol

```
Frontend → Backend:
  voice_transcript  {agent_id, text, is_final, mode}
  voice_interrupt   {agent_id}
  voice_claim_mic   {agent_id}
  chat_history      {agent_id}

Backend → Frontend:
  voice_response    {agent_id, text, done}
  voice_state       {agent_id, state}
  voice_error       {agent_id, error}
  voice_mic_owner   {agent_id | null}
  chat_history_response {agent_id, messages}
```

## Tools

| Tool | Description |
|------|-------------|
| `fantastic_agent_configure` | Set AI backend URL |
| `get_handbook_fantastic_agent` | This handbook |

## Technology

- **STT**: Web Speech API (`SpeechRecognition`) — free, browser-native
- **TTS**: Web Speech API (`speechSynthesis`) — free, instant, interruptible
- **VAD**: Piggybacks on STT's `onsoundstart` event for barge-in detection

### Provider Architecture

Both STT and TTS use a provider interface pattern (`SttProvider`, `TtsProvider`) allowing future swap-in of:
- **STT**: Whisper.cpp (WASM), Deepgram, AssemblyAI
- **TTS**: ElevenLabs, OpenAI TTS, Coqui/Piper
