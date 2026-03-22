"""AI provider abstraction — pluggable LLM backends.

Provider protocol + auto-discovery. Ollama is the first implementation.
"""

from .provider import AIProvider, DiscoverResult
from .brain import AIBrain
from .config import load_config, save_config

__all__ = ["AIProvider", "DiscoverResult", "AIBrain", "load_config", "save_config"]
