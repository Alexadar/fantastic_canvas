"""AI provider abstraction — pluggable LLM backends.

Provider protocol + auto-discovery. Ollama and local_transformers implementations.
"""

from .provider import AIProvider, DiscoverResult
from .brain import AIBrain
from .config import load_config, save_config
from .messages import AI_MSG
from .local_transformers_provider import LocalTransformersProvider

__all__ = [
    "AIProvider",
    "DiscoverResult",
    "AIBrain",
    "LocalTransformersProvider",
    "load_config",
    "save_config",
    "AI_MSG",
]
