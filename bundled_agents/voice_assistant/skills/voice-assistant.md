# Voice Assistant

Always-on voice agent for Fantastic Canvas. Browser-native STT/TTS with barge-in support.

## How It Works

The voice assistant is a canvas agent that renders as an interactive orb. Click to activate, click again to deactivate.

### State Machine

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

### AI Backend Connector

The voice agent connects to an AI backend (under development) that:
- Accepts transcribed text + conversation history
- Proxies to an LLM with tool calling capability
- Streams response chunks back for real-time TTS

Currently runs an **echo stub** until the AI backend is wired.

Configure the backend URL:
```
voice_configure(ai_backend_url="http://localhost:8001/v1/chat")
```

### WS Protocol

```
Frontend → Backend:
  voice_transcript  {agent_id, text, is_final}
  voice_interrupt   {agent_id}

Backend → Frontend:
  voice_response    {agent_id, text, done}
  voice_state       {agent_id, state}
  voice_error       {agent_id, error}
```

### Memory

Memory integration is TBD. The connector maintains a rolling conversation history (last 50 turns per agent) that will be augmented with project memory once available.

## Tools

| Tool | Description |
|------|-------------|
| `voice_configure` | Set AI backend URL |
| `get_handbook_voice_assistant` | This handbook |

## Technology

- **STT**: Web Speech API (`SpeechRecognition`) — free, browser-native
- **TTS**: Web Speech API (`speechSynthesis`) — free, instant, interruptible
- **VAD**: Piggybacks on STT's `onsoundstart` event for barge-in detection

### Provider Architecture

Both STT and TTS use a provider interface pattern (`SttProvider`, `TtsProvider`) allowing future swap-in of:
- **STT**: Whisper.cpp (WASM), Deepgram, AssemblyAI
- **TTS**: ElevenLabs, OpenAI TTS, Coqui/Piper
