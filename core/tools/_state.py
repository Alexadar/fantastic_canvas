"""Shared mutable state for tools submodules.

Wired at startup via init_tools(). Submodules import this module
and access _state._engine, _state._broadcast, etc.
"""

from typing import Callable

# Wired to singletons at startup via init_tools()
_engine = None
_broadcast = None
_process_runner = None

# Per-bundle loaded status: bundle_name → True
_bundle_loaded: dict[str, bool] = {}

# Hook called after an agent is created (for layout persistence etc.)
_on_agent_created: list[Callable] = []

# Fires once after init_tools() has loaded all bundles.
# Handlers: async (engine) → None. Bundles register in register_tools().
_on_subagents_loaded: list[Callable] = []
