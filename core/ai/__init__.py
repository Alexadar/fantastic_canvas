"""AI provider abstraction — pluggable LLM backends.

Provider protocol + auto-discovery. Ollama, integrated, and Anthropic implementations.
"""

from .provider import AIProvider, DiscoverResult
from .brain import AIBrain
from .config import load_config, save_config
from .messages import AI_MSG
from .providers.integrated_provider import IntegratedProvider
from .providers.proxy_provider import ProxyProvider
from .providers.anthropic_provider import AnthropicProvider

__all__ = [
    "AIProvider",
    "DiscoverResult",
    "AIBrain",
    "IntegratedProvider",
    "ProxyProvider",
    "AnthropicProvider",
    "load_config",
    "save_config",
    "AI_MSG",
]
