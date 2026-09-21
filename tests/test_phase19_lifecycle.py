import pytest
from core.registry import AgentRegistry, LifecycleState
from core.primitives.agent import AgentProfile

def test_registry_initializes_agents_with_active_state():
    registry = AgentRegistry()
    
    registry._agents["test_agent"] = AgentProfile(id="test_agent", domain="test", system_prompt="hello")
    registry._lifecycle_states["test_agent"] = LifecycleState.ACTIVE
    
    agents = registry.list_agents()
    test_agent_data = next((a for a in agents if a["id"] == "test_agent"), None)
    assert test_agent_data is not None
    assert test_agent_data["lifecycle_state"] == "ACTIVE"

def test_registry_lifecycle_state_update():
    registry = AgentRegistry()
    registry._agents["test_agent_2"] = AgentProfile(id="test_agent_2", domain="test", system_prompt="hello")
    registry._lifecycle_states["test_agent_2"] = LifecycleState.ACTIVE
    
    registry.set_lifecycle_state("test_agent_2", LifecycleState.FAILED)
    
    agents = registry.list_agents()
    test_agent_data = next((a for a in agents if a["id"] == "test_agent_2"), None)
    assert test_agent_data is not None
    assert test_agent_data["lifecycle_state"] == "FAILED"
