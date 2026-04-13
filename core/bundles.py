"""Bundle store — discovers and applies agent bundles."""

import json
import shutil
from pathlib import Path
from typing import Any


class BundleStore:
    """Manages agent bundles from the bundled_agents/ directory."""

    def __init__(self, builtin_dir: Path):
        self._builtin_dir = builtin_dir

    _SKIP = {"__pycache__", "node_modules", "tests", "skills", "dist", "build"}

    def _iter_bundle_dirs(self):
        """Yield bundle directories recursively (anything with a template.json)."""
        if not self._builtin_dir.exists():
            return
        stack = [self._builtin_dir]
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
                if name.startswith("_") or name.startswith(".") or name in self._SKIP:
                    continue
                if (entry / "template.json").exists():
                    yield entry
                    continue
                stack.append(entry)

    def list_bundles(self) -> list[dict[str, Any]]:
        """List all available bundles (scans recursively)."""
        result = []
        for entry in self._iter_bundle_dirs():
            tmpl = self._load_template_json(entry)
            if tmpl:
                result.append(tmpl)
        return result

    def get_bundle(self, name: str) -> dict[str, Any] | None:
        """Get bundle config by directory name (anywhere in the tree)."""
        for entry in self._iter_bundle_dirs():
            if entry.name == name:
                return self._load_template_json(entry)
        return None

    def _find_bundle_dir(self, name: str) -> Path | None:
        for entry in self._iter_bundle_dirs():
            if entry.name == name:
                return entry
        return None

    def apply_bundle(self, name: str, agent_dir: Path) -> dict[str, Any]:
        """Copy source.py from bundle into agent dir. Return {bundle, width, height}."""
        tdir = self._find_bundle_dir(name)
        tmpl = self._load_template_json(tdir) if tdir else None
        if not tmpl:
            raise ValueError(f"Bundle '{name}' not found")

        # Copy source.py if present
        src = tdir / "source.py"
        if src.exists():
            shutil.copy2(src, agent_dir / "source.py")

        params = tmpl.get("parameters", {})
        return {
            "bundle": tmpl.get("bundle", name),
            "width": params.get("default_width", tmpl.get("default_width", 800)),
            "height": params.get("default_height", tmpl.get("default_height", 600)),
        }

    def _load_template_json(self, tdir: Path) -> dict[str, Any] | None:
        """Load template.json from a bundle directory."""
        meta = tdir / "template.json"
        if not meta.exists():
            return None
        try:
            return json.loads(meta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
