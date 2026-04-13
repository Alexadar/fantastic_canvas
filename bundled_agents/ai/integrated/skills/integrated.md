# Integrated Agent (local)

Runs HuggingFace transformers models locally (CPU/CUDA/MPS auto-detected).

## Config

- `model`: HF model ID (e.g. `Qwen/Qwen3.5-4B`)
- `context_length`: auto from `tokenizer.model_max_length`

## Memory

Deleting the agent auto-unloads the model from VRAM via the `on_delete` hook.
