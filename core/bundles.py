"""Bundle store — discovers and applies agent bundles."""

import json
import shutil
from pathlib import Path
from typing import Any


class BundleStore:
    """Manages agent bundles from the bundled_agents/ directory."""

    def __init__(self, builtin_dir: Path):
        self._builtin_dir = builtin_dir

    def list_bundles(self) -> list[dict[str, Any]]:
        """List all available bundles."""
        result = []
        if not self._builtin_dir.exists():
            return result
        for entry in sorted(self._builtin_dir.iterdir()):
            if entry.is_dir():
                tmpl = self._load_template_json(entry)
                if tmpl:
                    result.append(tmpl)
        return result

    def get_bundle(self, name: str) -> dict[str, Any] | None:
        """Get bundle config by name."""
        tdir = self._builtin_dir / name
        if tdir.is_dir():
            return self._load_template_json(tdir)
        return None

    def apply_bundle(self, name: str, agent_dir: Path) -> dict[str, Any]:
        """Copy source.py from bundle into agent dir. Return {bundle, width, height}."""
        tdir = self._builtin_dir / name
        tmpl = self._load_template_json(tdir)
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
