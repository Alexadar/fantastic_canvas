"""IntegratedProvider — runs HuggingFace models locally via transformers + torch."""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from ..provider import DiscoverResult, GenerationResult
from ..messages import AI_MSG

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


def _detect_device(torch) -> tuple[str, str]:
    """Detect the best available device and return (device, detail_message).

    Checks system accelerators vs torch capabilities and produces
    clear diagnostics for each scenario.
    """
    # Detect what the system has vs what torch supports
    system_has_cuda = _system_has_cuda()
    system_has_mps = _system_has_mps()
    torch_cuda = torch.cuda.is_available()
    torch_mps = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()

    if torch_cuda:
        return "cuda", "cuda found, running on cuda"

    if torch_mps:
        return "mps", "mps found, running on mps"

    # Torch doesn't see any accelerator — check if the system actually has one
    if system_has_cuda:
        return "cpu", (
            "cuda device found but torch not built with CUDA support. "
            "Reinstall torch with CUDA (uv pip install torch --index-url "
            "https://download.pytorch.org/whl/cu124). Falling back to cpu"
        )

    if system_has_mps:
        return "cpu", (
            "mps device found but torch not built with MPS support. "
            "Reinstall torch for macOS Metal (uv pip install torch). "
            "Falling back to cpu"
        )

    return "cpu", "system is cpu, running on cpu"


def _system_has_cuda() -> bool:
    """Check if the system has NVIDIA GPU (independent of torch build)."""
    import shutil
    import subprocess

    if shutil.which("nvidia-smi"):
        try:
            subprocess.run(
                ["nvidia-smi"],
                capture_output=True,
                timeout=5,
            )
            return True
        except Exception:
            pass
    return False


def _system_has_mps() -> bool:
    """Check if the system is macOS with Apple Silicon (independent of torch build)."""
    import platform

    if platform.system() != "Darwin":
        return False
    # Apple Silicon = arm64
    return platform.machine() == "arm64"


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
        """Check if torch + transformers are importable, detect device."""
        try:
            import torch
        except ImportError:
            return DiscoverResult(
                available=False,
                provider_name="integrated",
                error="torch not installed. Run: uv pip install torch",
            )

        try:
            import transformers  # noqa: F401
        except ImportError:
            return DiscoverResult(
                available=False,
                provider_name="integrated",
                error="transformers not installed. Run: uv pip install transformers",
            )

        device, detail = _detect_device(torch)

        return DiscoverResult(
            available=True,
            models=[DEFAULT_MODEL],
            endpoint=f"local:{device}",
            provider_name="integrated",
            detail=detail,
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

    async def generate(self, messages: list[dict]) -> AsyncIterator[str]:
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

    async def generate_with_tools(
        self, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[str | GenerationResult]:
        """Integrated models don't natively support tool calling — delegates to generate()."""
        text_parts = []
        async for token in self.generate(messages):
            text_parts.append(token)
            yield token
        yield GenerationResult(text="".join(text_parts), tool_calls=None)

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

    @property
    def context_length(self) -> int:
        if self._tokenizer and hasattr(self._tokenizer, "model_max_length"):
            val = self._tokenizer.model_max_length
            # transformers sometimes returns a huge int for "unlimited"
            if isinstance(val, int) and val < 10_000_000:
                return val
        return 4096  # conservative default for small local models

    def set_model(self, model: str) -> None:
        self._model_name = model

    def __str__(self) -> str:
        return f"integrated ({self._model_name})"
        self._ready = False
        self._model = None
        self._tokenizer = None

    def stop(self) -> None:
        """Stop the provider, unload model from memory."""
        self._stopped = True
        self._ready = False
        if self._model is not None:
            del self._model
            self._model = None
        if self._tokenizer is not None:
            del self._tokenizer
            self._tokenizer = None
        try:
            import gc

            gc.collect()
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except ImportError:
            pass

    def unload(self) -> None:
        """Unload model from memory."""
        self.stop()

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def is_loading(self) -> bool:
        return self._loading

    @property
    def is_stopped(self) -> bool:
        return self._stopped
