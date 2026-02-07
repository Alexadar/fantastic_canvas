"""
Agent store — persistent `.fantastic/` directory for agent state.

Each agent gets its own subdirectory with agent.json, source.py, output.html.
Registry and config live at the `.fantastic/` root level.
"""

import json
import logging
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


def new_agent_id() -> str:
    return f"agent_{secrets.token_hex(3)}"


class AgentStore:
    """Persistent agent storage backed by a `.fantastic/` directory."""

    def __init__(self, project_dir: Path):
        self._project_dir = project_dir
        self._root = project_dir / ".fantastic"
        self._agents_dir = self._root / "agents"
        self._on_delete_hooks: list[Callable[[str], None]] = []
        self._enrich_hooks: list[Callable[[str, dict], None]] = []

    @property
    def agents_dir(self) -> Path:
        return self._agents_dir

    # ─── Initialization ──────────────────────────────────────

    def on_agent_deleted(self, fn: Callable[[str], None]) -> None:
        """Register a hook called when an agent is deleted."""
        self._on_delete_hooks.append(fn)

    def on_enrich_agent(self, fn: Callable[[str, dict], None]) -> None:
        """Register a hook to enrich agent dicts (e.g. merge layout)."""
        self._enrich_hooks.append(fn)

    def init(self) -> None:
        """Create .fantastic/ directory and config files if needed."""
        self._root.mkdir(parents=True, exist_ok=True)
        self._agents_dir.mkdir(parents=True, exist_ok=True)

        # Ensure config and registry exist (.fantastic/config.json)
        config_path = self._root / "config.json"
        if not config_path.exists():
            config_path.write_text(
                json.dumps({"port": 8888}, indent=2),
                encoding="utf-8",
            )

        # (.fantastic/registry.json)
        registry_path = self._root / "registry.json"
        if not registry_path.exists():
            registry_path.write_text("{}", encoding="utf-8")

    # ─── Agent CRUD ──────────────────────────────────────────

    def create_agent(
        self,
        agent_id: str | None = None,
        bundle: str | None = None,
        parent: str | None = None,
    ) -> dict[str, Any]:
        """Create a new agent directory and return its full state dict."""
        aid = agent_id or new_agent_id()
        agent_dir = self._agents_dir / aid

        if agent_dir.exists():
            raise ValueError(f"Agent {aid} already exists")

        agent_dir.mkdir(parents=True, exist_ok=True)

        agent_json: dict[str, Any] = {
            "id": aid,
            "display_name": "",
            "delete_lock": False,
            "created_at": time.time(),
        }
        if bundle:
            agent_json["bundle"] = bundle
        if parent:
            agent_json["parent"] = parent
        (agent_dir / "agent.json").write_text(
            json.dumps(agent_json, indent=2), encoding="utf-8"
        )
        (agent_dir / "source.py").write_text("", encoding="utf-8")
        (agent_dir / "output.html").write_text("", encoding="utf-8")
        (agent_dir / "outputs").mkdir(exist_ok=True)

        return self._build_agent_dict(aid, agent_json)

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Get full state dict for an agent, or None if not found."""
        agent_dir = self._agents_dir / agent_id
        meta_path = agent_dir / "agent.json"
        if not meta_path.exists():
            return None
        agent_json = json.loads(meta_path.read_text(encoding="utf-8"))
        return self._build_agent_dict(agent_id, agent_json)

    def list_agents(self) -> list[dict[str, Any]]:
        """List all agents with their full state."""
        agents = []
        if not self._agents_dir.exists():
            return agents
        for entry in sorted(self._agents_dir.iterdir()):
            if entry.is_dir() and (entry / "agent.json").exists():
                agent = self.get_agent(entry.name)
                if agent:
                    agents.append(agent)
        return agents

    def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent."""
        agent_dir = self._agents_dir / agent_id
        if not agent_dir.exists():
            return False

        shutil.rmtree(agent_dir)

        for hook in self._on_delete_hooks:
            hook(agent_id)
        return True

    def set_delete_lock(self, agent_id: str, locked: bool) -> None:
        """Set or clear the delete_lock flag on an agent."""
        self.update_agent_meta(agent_id, delete_lock=locked)

    def update_agent_meta(self, agent_id: str, **kwargs: Any) -> None:
        """Update agent.json metadata fields (e.g. display_name)."""
        agent_dir = self._agents_dir / agent_id
        meta_path = agent_dir / "agent.json"
        if not meta_path.exists():
            raise ValueError(f"Agent {agent_id} not found")
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        for k, v in kwargs.items():
            data[k] = v
        meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ─── Source / Output ─────────────────────────────────────

    def get_source(self, agent_id: str) -> str:
        """Read source.py for an agent."""
        path = self._agents_dir / agent_id / "source.py"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def set_source(self, agent_id: str, source: str) -> None:
        """Write source.py for an agent."""
        path = self._agents_dir / agent_id / "source.py"
        if not path.parent.exists():
            raise ValueError(f"Agent {agent_id} not found")
        path.write_text(source, encoding="utf-8")

    def get_output(self, agent_id: str) -> str:
        """Read output.html for an agent."""
        path = self._agents_dir / agent_id / "output.html"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def set_output(self, agent_id: str, html: str) -> None:
        """Write output.html for an agent."""
        path = self._agents_dir / agent_id / "output.html"
        if not path.parent.exists():
            raise ValueError(f"Agent {agent_id} not found")
        path.write_text(html, encoding="utf-8")

    # ─── Registry (.fantastic/registry.json) ─────────────────────

    def get_registry(self) -> dict[str, Any]:
        """Read the Server registry."""
        path = self._root / "registry.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def set_registry(self, registry: dict[str, Any]) -> None:
        """Write the Server registry."""
        path = self._root / "registry.json"
        path.write_text(json.dumps(registry, indent=2), encoding="utf-8")

    # ─── Config (.fantastic/config.json) ───────────────────────

    def get_config(self) -> dict[str, Any]:
        """Read config."""
        path = self._root / "config.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def set_config(self, config: dict[str, Any]) -> None:
        """Write config."""
        path = self._root / "config.json"
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    # ─── Hierarchy ──────────────────────────────────────────────

    def list_children(self, parent_id: str) -> list[dict[str, Any]]:
        """Return agents whose parent == parent_id."""
        return [a for a in self.list_agents() if a.get("parent") == parent_id]

    def get_root_parent(self, agent_id: str) -> dict[str, Any] | None:
        """Walk up the parent chain to the root (no parent)."""
        agent = self.get_agent(agent_id)
        while agent and agent.get("parent"):
            agent = self.get_agent(agent["parent"])
        return agent

    # ─── Bundle lookup ────────────────────────────────────────

    def find_by_bundle(self, name: str) -> dict[str, Any] | None:
        """Find the first agent with the given bundle name."""
        if not self._agents_dir.exists():
            return None
        for entry in sorted(self._agents_dir.iterdir()):
            meta_path = entry / "agent.json"
            if not meta_path.exists():
                continue
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            if data.get("bundle") == name:
                return self._build_agent_dict(entry.name, data)
        return None

    # ─── Internal helpers ────────────────────────────────────

    def _build_agent_dict(
        self, agent_id: str, agent_json: dict[str, Any]
    ) -> dict[str, Any]:
        """Build a full agent state dict from agent.json + files.

        Starts from agent.json (forwarding all keys), then overlays file-derived
        fields. Enrich hooks (e.g. layout defaults) are called last.
        """
        source = self.get_source(agent_id)
        output_html = self.get_output(agent_id)
        result = dict(agent_json)
        result["id"] = agent_id          # canonical source
        result["source"] = source        # from file
        result["output_html"] = output_html  # from file
        # Backfill has_iframe from content presence
        if "has_iframe" not in result:
            if result.get("html_content") or (not result.get("bundle") and output_html):
                result["has_iframe"] = True
        for hook in self._enrich_hooks:
            hook(agent_id, result)
        return result
