"""Load tool plugins from bundles and project plugins."""

import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..dispatch import _DISPATCH

logger = logging.getLogger(__name__)

# Track which tool names belong to which bundle (for remove_bundle cleanup)
_bundle_tool_names: dict[str, list[str]] = {}


@dataclass
class BundleLoadResult:
    """Result of loading one or more bundles."""

    tools: dict[str, Any] = field(default_factory=dict)  # tool_name → callable


def load_single_bundle(
    entry: Path,
    engine,
    fire_broadcasts: Callable,
    process_runner=None,
) -> BundleLoadResult:
    """Load a single bundle directory. Calls register_tools if tools.py exists."""
    result = BundleLoadResult()
    tools_file = entry / "tools.py"
    if not tools_file.exists():
        return result
    try:
        import sys as _sys

        # Derive the real package path so relative imports inside the bundle
        # (e.g. `from .app import make_app`) resolve. Falls back to a synthetic
        # name if the bundle lives outside the importable tree.
        try:
            parts = entry.resolve().parts
            if "bundled_agents" in parts:
                idx = parts.index("bundled_agents")
                pkg = ".".join(parts[idx:])  # e.g. "bundled_agents.web"
                mod_name = f"{pkg}.tools"
                mod = importlib.import_module(mod_name)
            else:
                raise ImportError("outside bundled_agents tree")
        except Exception:
            mod_name = f"bundle_{entry.name}_tools"
            spec = importlib.util.spec_from_file_location(mod_name, tools_file)
            mod = importlib.util.module_from_spec(spec)
            _sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
        # Also expose under the short name so get_bundle_module() works.
        _sys.modules[f"bundle_{entry.name}_tools"] = mod
        if hasattr(mod, "register_tools"):
            tools = mod.register_tools(
                engine,
                fire_broadcasts,
                process_runner,
            )
            result.tools.update(tools)
            _bundle_tool_names[entry.name] = list(tools.keys())
            if tools:
                logger.info("Loaded %d tools from bundle '%s'", len(tools), entry.name)
        # Optional: a bundle may expose a zero-arg `register_dispatch()` factory
        # that returns a {name: handler} dict. Skip if it's the decorator
        # imported from core.dispatch (same name, very different signature).
        from ..dispatch import register_dispatch as _core_register_dispatch

        rd = getattr(mod, "register_dispatch", None)
        if rd is not None and rd is not _core_register_dispatch:
            inner = rd()
            if isinstance(inner, dict):
                _DISPATCH.update(inner)
    except Exception:
        logger.exception("Failed to load tools from %s", tools_file)
    return result


_SKIP_DIRS = {"__pycache__", "node_modules", "tests", "skills", "dist", "build"}


def _iter_bundle_dirs(bundles_dir: Path):
    """Yield every directory that contains a `template.json` (any depth).

    Skips dirs starting with `_` (shared/internal), plus conventional
    tooling/asset dirs. No hardcoded bundle names.
    """
    if not bundles_dir.exists():
        return
    stack = [bundles_dir]
    while stack:
        parent = stack.pop()
        try:
            entries = sorted(parent.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            name = entry.name
            if name.startswith("_") or name.startswith(".") or name in _SKIP_DIRS:
                continue
            if (entry / "template.json").exists():
                yield entry
                # Don't descend into a bundle further.
                continue
            # Could be a grouping dir (e.g. "ai/") — descend.
            stack.append(entry)


def load_bundle_tools(
    bundles_dir: Path,
    engine,
    fire_broadcasts: Callable,
    process_runner=None,
    added: set[str] | None = None,
) -> BundleLoadResult:
    """Scan bundles_dir recursively for dirs containing `template.json`.

    If `added` is provided, only load bundles whose directory name is in the set.
    If `added` is None, load all bundles.
    """
    combined = BundleLoadResult()
    if not bundles_dir.exists():
        return combined
    seen_names: dict[str, Path] = {}
    for entry in _iter_bundle_dirs(bundles_dir):
        if entry.name in seen_names:
            logger.error(
                "Duplicate bundle dir name '%s' at %s (already seen at %s) — skipping",
                entry.name,
                entry,
                seen_names[entry.name],
            )
            continue
        seen_names[entry.name] = entry
        if added is not None and entry.name not in added:
            continue
        result = load_single_bundle(entry, engine, fire_broadcasts, process_runner)
        combined.tools.update(result.tools)
    return combined


def get_bundle_module(bundle_name: str):
    """Return the loaded tools module for a bundle directory name, or None."""
    import sys

    return sys.modules.get(f"bundle_{bundle_name}_tools")


def load_project_plugins(
    project_dir: Path,
    engine,
    fire_broadcasts: Callable,
    process_runner=None,
) -> BundleLoadResult:
    """Scan project_dir/plugins/*/tools.py."""
    plugins_dir = project_dir / "plugins"
    if not plugins_dir.exists():
        return BundleLoadResult()
    return load_bundle_tools(plugins_dir, engine, fire_broadcasts, process_runner)


def load_installed_plugins(
    project_dir: Path,
    engine,
    fire_broadcasts: Callable,
    process_runner=None,
) -> BundleLoadResult:
    """Load tools from .fantastic/plugins/*/tools.py."""
    from .._install import list_plugin_dirs

    combined = BundleLoadResult()
    for plugin_dir in list_plugin_dirs(project_dir):
        result = load_single_bundle(plugin_dir, engine, fire_broadcasts, process_runner)
        combined.tools.update(result.tools)
    return combined
