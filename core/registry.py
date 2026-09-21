from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from core.primitives.agent import AgentProfile

class LifecycleState(Enum):
    UNRESOLVED = "UNRESOLVED"
    INITIALIZING = "INITIALIZING"
    ACTIVE = "ACTIVE"
    DEACTIVATING = "DEACTIVATING"
    INACTIVE = "INACTIVE"
    FAILED = "FAILED"
    DISPOSING = "DISPOSING"

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
    def __init__(self, config_path: Path | str = "config/agents.yaml"):
        self.config_path = Path(config_path)
        self._agents = load_agents(self.config_path)
        self._lifecycle_states: Dict[str, LifecycleState] = {
            agent_id: LifecycleState.ACTIVE for agent_id in self._agents
        }

    def get_agent(self, agent_id: str) -> Optional[AgentProfile]:
        return self._agents.get(agent_id)

    def list_agents(self) -> List[Dict[str, __import__("typing").Any]]:
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
