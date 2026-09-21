import pytest
from unittest.mock import patch
from main import reload_registry
from core.gateway.api import registry
from core.primitives.agent import AgentProfile
from core.registry import LifecycleState

def test_reload_registry_success():
    mock_agent = AgentProfile(id="reloaded_agent", domain="test", system_prompt="HMR active")
    with patch("main.load_agents", return_value={"reloaded_agent": mock_agent}):
        success = reload_registry()
        assert success is True
        assert "reloaded_agent" in registry._agents
        assert registry._lifecycle_states["reloaded_agent"] == LifecycleState.ACTIVE

def test_reload_registry_failure_rollbacks_state():
    initial_agents = dict(registry._agents)
    initial_states = dict(registry._lifecycle_states)
    
    with patch("main.load_agents", side_effect=ValueError("Invalid YAML configuration")):
        success = reload_registry()
        assert success is False
        assert registry._agents == initial_agents
        assert registry._lifecycle_states == initial_states
