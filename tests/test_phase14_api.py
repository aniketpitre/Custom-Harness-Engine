import pytest
import sqlite3
import json
from pathlib import Path
from fastapi.testclient import TestClient

from core.registry import AgentRegistry
from core.primitives.agent import AgentProfile
from core.gateway.api import app, registry, build_context
from core.memory.store import init_db, get_session


# Provide a temporary configuration for agents to the registry during test
test_agents = {
    "test_agent": AgentProfile(
        id="test_agent",
        domain="devops",
        system_prompt="Test sys prompt.",
        allowed_tools=["Read"],
    )
}


@pytest.fixture
def override_agents():
    # Store original and override
    original_agents = registry._agents
    registry._agents = test_agents
    yield
    # Restore original
    registry._agents = original_agents


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_memory.db"

    # Patch init_db in api module
    def mock_init_db():
        return init_db(db_path)

    monkeypatch.setattr("core.gateway.api.init_db", mock_init_db)

    # Pre-populate empty db
    conn = init_db(db_path)
    conn.close()

    return db_path


client = TestClient(app)


def test_list_agents(override_agents):
    response = client.get("/agents")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "test_agent"
    assert data[0]["system_prompt"] == "Test sys prompt."


def test_get_agent(override_agents):
    response = client.get("/agents/test_agent")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test_agent"

    response = client.get("/agents/invalid_agent")
    assert response.status_code == 404


def test_create_and_fetch_session(override_agents, temp_db, monkeypatch):
    db_path = temp_db

    # Mock run_agent so we don't actually trigger LiteLLM calls.
    # We just return a mock run result.
    async def mock_run_agent(context, allowed_tools, agent_profile=None):
        return {
            "model_used": "mock-model",
            "actions": [],
            "final_text": "Mock success text",
            "verification": None
        }

    monkeypatch.setattr("core.gateway.api.run_agent", mock_run_agent)

    # 1. Start Session
    payload = {
        "agent_id": "test_agent",
        "goal": "Test goal 123",
        "environment": {"TARGET": "prod"}
    }
    response = client.post("/sessions", json=payload)
    assert response.status_code == 201

    data = response.json()
    session_id = data["session_id"]
    assert session_id is not None
    assert data["status"] == "pending"

    # Background task should have run and updated the DB synchronously for TestClient

    # 2. Retrieve session from API
    response = client.get(f"/sessions/{session_id}")
    assert response.status_code == 200

    session_data = response.json()
    assert session_data["id"] == session_id
    assert session_data["agent_id"] == "test_agent"
    assert session_data["goal"] == "Test goal 123"
    assert session_data["environment"] == {"TARGET": "prod"}
    assert session_data["status"] == "success"  # Because mock ran immediately and successfully
    assert session_data["run_receipt"] is not None
    assert session_data["run_receipt"]["model_used"] == "mock-model"
    assert session_data["run_receipt"]["final_text"] == "Mock success text"
