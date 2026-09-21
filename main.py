import uvicorn
from core.gateway.api import app, registry
from core.registry import load_agents, LifecycleState

def reload_registry():
    """Transactional reload of components without restarting the process."""
    # Snapshot current states before attempting load
    old_agents = dict(registry._agents)
    old_states = dict(registry._lifecycle_states)
    try:
        new_agents = load_agents(registry.config_path)

        # Atomically apply new agents
        registry._agents = new_agents
        registry._lifecycle_states = {
            agent_id: LifecycleState.ACTIVE for agent_id in new_agents
        }
        return True
    except Exception as e:
        # Rollback on failure
        registry._agents = old_agents
        registry._lifecycle_states = old_states
        return False

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
