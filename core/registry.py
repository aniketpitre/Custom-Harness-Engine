import yaml
from pathlib import Path
from typing import Dict, List

from core.primitives.agent import AgentProfile


def load_agents(path: Path | str = "config/agents.yaml") -> Dict[str, AgentProfile]:
    """Load declarative agent configurations from a YAML file."""
    filepath = Path(path)
    if not filepath.exists():
        return {}

    with open(filepath, "r") as f:
        data = yaml.safe_load(f) or []

    return {item["id"]: AgentProfile(**item) for item in data}


class AgentRegistry:
    """Registry object for managing agent profiles."""
    def __init__(self, config_path: Path | str = "config/agents.yaml"):
        self.config_path = Path(config_path)
        self._agents = load_agents(self.config_path)

    def get_agent(self, agent_id: str) -> AgentProfile | None:
        return self._agents.get(agent_id)

    def list_agents(self) -> List[AgentProfile]:
        return list(self._agents.values())
