# AI Integration Tests

Manual test scenarios for the AI brain with Ollama provider.
Requires Ollama running locally with a model pulled.

## Prerequisites

```bash
# Install and start Ollama
# https://ollama.com

# Pull a model
ollama pull qwen3:8b-q4_K_M

# Verify
ollama list
```

## Test 1: No provider message

```bash
# Clear AI config
rm -f .fantastic/ai/config.json

uv run fantastic
> @ai hi
```

Expected:
```
AI provider not configured.

Usage: @ai start <provider> <model>

  @ai start ollama qwen3:8b-q4_K_M
  @ai start anthropic claude-sonnet-4-20250514
  @ai start integrated Qwen/Qwen3.5-4B
  @ai start proxy <instance_url>

  @ai stop
```

## Test 2: Start Ollama

```
> @ai start ollama qwen3:8b-q4_K_M
```

Expected: `swapped to ollama (qwen3:8b-q4_K_M)`

Verify config saved:
```bash
cat .fantastic/ai/config.json
# {"provider_name": "ollama", "provider_config": {"endpoint": "http://localhost:11434", "model": "qwen3:8b-q4_K_M"}}
```

## Test 3: Chat (no tools)

```
> @ai Say hello in one sentence
```

Expected: a single sentence response, printed atomically (not streamed char-by-char).

## Test 4: Tool calling — list agents

```
> @ai How many agents exist? Use list_agents tool.
```

Expected: model calls `list_agents`, reports count and agent IDs. Example:
```
ai : There are 2 agents:
1. agent_5baee1 (terminal)
2. agent_abb1d6 (canvas)
```

## Test 5: Tool calling — create agent

```
> @ai Create a terminal agent at position 400, 200
```

Expected: model calls `create_agent` tool, agent appears on canvas.

## Test 6: Stop provider

```
> @ai stop
```

Expected: `AI stopped`

Verify:
```
> @ai hi
```
Expected: shows "not configured" message again.

## Test 7: Start without model (should ask)

```
> @ai start ollama
```

Expected: `Usage: @ai start <provider> <model>`

## Test 8: Think block handling

Models like Qwen3 emit `<think>...</think>` blocks. The brain filters these — prints `[thinking...]` once, skips think content, resumes after `</think>`.

```
> @ai Explain what 2+2 is
```

Expected: response without any `<think>` tags visible. If model thinks, `[thinking...]` appears once in console (CLI only).

## Automated test script

Run with a server:

```bash
uv run fantastic serve &
sleep 5

uv run python -c "
import asyncio, os, json
os.environ['PROJECT_DIR'] = os.getcwd()

async def go():
    from core.ai.brain import AIBrain
    from core.tools import init_tools, _state
    from core.engine import Engine
    from core.process_runner import ProcessRunner

    engine = Engine(project_dir=os.getcwd())
    await engine.start()
    pr = ProcessRunner()
    async def noop(msg): pass
    init_tools(engine, noop, pr)

    brain = engine.ai

    # Start
    r = await brain.swap_provider('ollama', model='qwen3:8b-q4_K_M')
    print(f'1. Start: {r}')

    # Chat
    r = await brain.respond('Say hello in one sentence. No thinking.')
    print(f'2. Chat: {r[:100]}')

    # Tool call
    r = await brain.respond('How many agents exist? Use list_agents.')
    print(f'3. Tools: {r[:200]}')

    # Stop
    brain._provider.stop()
    brain._provider = None
    print('4. Stop: ok')

    # No provider
    r = await brain.respond('hi')
    print(f'5. No provider: {r[:60]}')

    await engine.stop()

asyncio.run(go())
"

kill %1
```
