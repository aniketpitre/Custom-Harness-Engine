import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.plugins.base import LifecycleState  # noqa: E402,F401
from core.primitives.agent import AgentProfile


def load_agents(path: Path | str = "config/agents.yaml") -> Dict[str, AgentProfile]:
    """Load declarative agent configurations from a YAML file."""
    filepath = Path(path)
    if not filepath.exists():
        return {}

    import yaml
    with open(filepath, "r") as f:
        data = yaml.safe_load(f) or []

    return {item["id"]: AgentProfile(**item) for item in data}


class AgentRegistry:
    """Registry object for managing agent profiles and their lifecycles."""
    def __init__(self, config_path: Path | str | None = None):
        from core.settings import find_config

        self.config_path = Path(config_path or os.getenv("HARNESS_AGENTS_FILE") or find_config("agents.yaml")).resolve()
        self._agents = load_agents(self.config_path)
        self._lifecycle_states: Dict[str, LifecycleState] = {
            agent_id: LifecycleState.ACTIVE for agent_id in self._agents
        }

    def get_agent(self, agent_id: str) -> Optional[AgentProfile]:
        return self._agents.get(agent_id)

    def list_agents(self) -> List[Dict[str, Any]]:
        return [
            {
                **agent.model_dump(),
                "lifecycle_state": self._lifecycle_states.get(agent.id, LifecycleState.UNRESOLVED).value
            }
            for agent in self._agents.values()
        ]

    def set_lifecycle_state(self, agent_id: str, state: LifecycleState):
        if agent_id in self._agents:
            self._lifecycle_states[agent_id] = state

    def reload(self) -> bool:
        """Transactional reload: a failed load leaves the previous agents and states untouched."""
        try:
            new_agents = load_agents(self.config_path)
        except Exception:  # noqa: BLE001
            return False
        previous = self._lifecycle_states
        self._agents = new_agents
        self._lifecycle_states = {
            agent_id: previous.get(agent_id, LifecycleState.ACTIVE)
            if previous.get(agent_id) is not LifecycleState.FAILED else LifecycleState.ACTIVE
            for agent_id in new_agents}
        return True
