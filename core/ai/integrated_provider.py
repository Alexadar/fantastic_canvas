"""IntegratedProvider — runs HuggingFace models locally via transformers + torch."""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from .provider import AIProvider, DiscoverResult
from .messages import AI_MSG

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "Qwen/Qwen3.5-4B"

# Suppressed loggers when loading model
_NOISY_LOGGERS = [
    "transformers",
    "transformers.modeling_utils",
    "transformers.configuration_utils",
    "transformers.tokenization_utils_base",
    "accelerate",
    "bitsandbytes",
    "torch",
]


class IntegratedProvider:
    """Loads a HuggingFace model locally with optional 4-bit quantization."""

    def __init__(self, model: str = DEFAULT_MODEL):
        self._model_name = model
        self._model = None
        self._tokenizer = None
        self._loading = False
        self._stopped = False
        self._ready = False

    @classmethod
    async def discover(cls, endpoint: str | None = None) -> DiscoverResult:
        """Check if torch + transformers are importable."""
        try:
            import torch
            import transformers  # noqa: F401

            device = "cpu"
            if torch.cuda.is_available():
                device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"

            return DiscoverResult(
                available=True,
                models=[DEFAULT_MODEL],
                endpoint=f"local:{device}",
                provider_name="integrated",
            )
        except ImportError as e:
            return DiscoverResult(
                available=False,
                provider_name="integrated",
                error=f"missing dependency: {e}",
            )

    async def load_model(self, status_fn=None):
        """Download and load model. Calls status_fn with progress strings."""
        if self._ready:
            return
        if self._loading:
            return

        self._loading = True
        self._stopped = False

        try:
            if status_fn:
                status_fn(AI_MSG.MODEL_DOWNLOADING)

            # Suppress noisy logs during load
            saved_levels = {}
            for name in _NOISY_LOGGERS:
                lg = logging.getLogger(name)
                saved_levels[name] = lg.level
                lg.setLevel(logging.ERROR)

            try:
                model, tokenizer = await asyncio.get_event_loop().run_in_executor(
                    None, self._load_sync
                )
            finally:
                # Restore log levels
                for name, level in saved_levels.items():
                    logging.getLogger(name).setLevel(level)

            if self._stopped:
                # Provider was killed during load
                self._model = None
                self._tokenizer = None
                self._loading = False
                return

            self._model = model
            self._tokenizer = tokenizer
            self._ready = True

            if status_fn:
                status_fn(AI_MSG.MODEL_READY)
        finally:
            self._loading = False

    def _load_sync(self):
        """Synchronous model loading (runs in executor)."""
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            self._model_name, trust_remote_code=True
        )

        load_kwargs = {"trust_remote_code": True, "device_map": "auto"}

        # Use 4-bit quantization on CUDA to save VRAM
        if torch.cuda.is_available():
            try:
                from transformers import BitsAndBytesConfig

                load_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_compute_dtype=torch.bfloat16,
                )
            except ImportError:
                # bitsandbytes not available, load in half precision
                load_kwargs["torch_dtype"] = torch.float16
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            load_kwargs["torch_dtype"] = torch.float16
        else:
            load_kwargs["torch_dtype"] = torch.float32

        model = AutoModelForCausalLM.from_pretrained(self._model_name, **load_kwargs)

        return model, tokenizer

    async def chat(self, messages: list[dict]) -> AsyncIterator[str]:
        """Generate a response from messages. Loads model on first call."""
        if self._stopped:
            yield AI_MSG.PROVIDER_STOPPED
            return

        if not self._ready:
            await self.load_model()

        if self._stopped or not self._ready:
            yield AI_MSG.PROVIDER_STOPPED
            return

        text = await asyncio.get_event_loop().run_in_executor(
            None, self._generate_sync, messages
        )
        if text:
            yield text

    def _generate_sync(self, messages: list[dict]) -> str:
        """Synchronous generation (runs in executor)."""
        if self._model is None or self._tokenizer is None:
            return AI_MSG.PROVIDER_NOT_READY

        text = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._tokenizer(text, return_tensors="pt")
        inputs = {k: v.to(self._model.device) for k, v in inputs.items()}

        import torch

        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=1024,
                do_sample=True,
                temperature=0.7,
                top_p=0.9,
            )

        # Decode only new tokens
        new_tokens = outputs[0][inputs["input_ids"].shape[1] :]
        return self._tokenizer.decode(new_tokens, skip_special_tokens=True)

    async def list_models(self) -> list[str]:
        return [self._model_name]

    async def pull(self, model: str) -> AsyncIterator[str]:
        """'Pull' = change model name (will download on next load)."""
        self._model_name = model
        self._ready = False
        self._model = None
        self._tokenizer = None
        yield f"model set to {model} — will download on first use"

    @property
    def model(self) -> str:
        return self._model_name

    def set_model(self, model: str) -> None:
        self._model_name = model
        self._ready = False
        self._model = None
        self._tokenizer = None

    def stop(self) -> None:
        """Stop the provider, unload model."""
        self._stopped = True
        self._ready = False
        self._model = None
        self._tokenizer = None

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def is_loading(self) -> bool:
        return self._loading

    @property
    def is_stopped(self) -> bool:
        return self._stopped
