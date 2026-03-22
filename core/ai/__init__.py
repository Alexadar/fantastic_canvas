"""AI provider abstraction — pluggable LLM backends.

Provider protocol + auto-discovery. Ollama and integrated implementations.
"""

from .provider import AIProvider, DiscoverResult
from .brain import AIBrain
from .config import load_config, save_config
from .messages import AI_MSG
from .integrated_provider import IntegratedProvider

__all__ = [
    "AIProvider",
    "DiscoverResult",
    "AIBrain",
    "IntegratedProvider",
    "load_config",
    "save_config",
    "AI_MSG",
]
