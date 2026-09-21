import pytest
import sqlite3
import json
from pathlib import Path
from fastapi.testclient import TestClient

from core.registry import AgentRegistry, load_agents
from core.primitives.agent import AgentProfile, Session
from core.gateway.api import app, registry, build_context
from core.memory.store import init_db, get_session, create_session, update_session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
    original_agents = registry._agents
    registry._agents = test_agents
    yield
    registry._agents = original_agents


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_memory.db"

    def mock_init_db():
        return init_db(db_path)

    monkeypatch.setattr("core.gateway.api.init_db", mock_init_db)

    conn = init_db(db_path)
    conn.close()
    return db_path


client = TestClient(app)


# ---------------------------------------------------------------------------
# 14.1  Declarative Agent Registry
# ---------------------------------------------------------------------------

def test_load_agents_from_real_yaml():
    """Verify load_agents parses the real config/agents.yaml without errors."""
    agents = load_agents("config/agents.yaml")
    assert isinstance(agents, dict)
    assert "devops_agent" in agents
    assert agents["devops_agent"].domain == "devops"
    assert "DevOpsRead" in agents["devops_agent"].allowed_tools
    assert "read_only_explorer" in agents
    assert "DevOpsWrite" not in agents["read_only_explorer"].allowed_tools


def test_agent_registry_get_and_list():
    """Verify AgentRegistry wraps load_agents correctly."""
    reg = AgentRegistry("config/agents.yaml")
    assert reg.get_agent("devops_agent") is not None
    assert reg.get_agent("nonexistent") is None
    agents_list = reg.list_agents()
    assert len(agents_list) >= 2
    ids = [a["id"] for a in agents_list]
    assert "devops_agent" in ids
    assert "read_only_explorer" in ids


def test_agent_profile_model_validation():
    """AgentProfile rejects empty id/domain/system_prompt."""
    with pytest.raises(Exception):
        AgentProfile(id="", domain="x", system_prompt="y")
    with pytest.raises(Exception):
        AgentProfile(id="x", domain="", system_prompt="y")


# ---------------------------------------------------------------------------
# 14.2  Durable Session Management  (real SQLite, no mocks)
# ---------------------------------------------------------------------------

def test_session_sqlite_roundtrip(tmp_path):
    """Create, read, and update a session in a real temporary SQLite database."""
    db_path = tmp_path / "session_test.db"
    conn = init_db(db_path)

    # Create
    create_session(conn, "sid-1", "devops_agent", "check pods", {"NS": "prod"})
    row = get_session(conn, "sid-1")
    assert row is not None
    assert row["id"] == "sid-1"
    assert row["agent_id"] == "devops_agent"
    assert row["goal"] == "check pods"
    assert row["status"] == "pending"
    assert row["environment"] == {"NS": "prod"}
    assert row["run_receipt"] is None
    assert row["created_at"] is not None
    assert row["updated_at"] is not None

    # Update to running
    update_session(conn, "sid-1", "running")
    row = get_session(conn, "sid-1")
    assert row["status"] == "running"
    assert row["run_receipt"] is None

    # Update to success with receipt payload
    receipt_dict = {"run_id": "sid-1", "model_used": "test-model", "final_text": "done"}
    update_session(conn, "sid-1", "success", run_receipt=receipt_dict)
    row = get_session(conn, "sid-1")
    assert row["status"] == "success"
    assert row["run_receipt"]["model_used"] == "test-model"
    assert row["run_receipt"]["final_text"] == "done"

    conn.close()


def test_session_not_found(tmp_path):
    """get_session returns None for a nonexistent session."""
    db_path = tmp_path / "empty.db"
    conn = init_db(db_path)
    assert get_session(conn, "does-not-exist") is None
    conn.close()


def test_session_model_validation():
    """Session primitive validates status values."""
    s = Session(agent_id="a", goal="g", status="pending")
    assert s.id  # auto-generated uuid
    with pytest.raises(Exception):
        Session(agent_id="a", goal="g", status="invalid_status")


# ---------------------------------------------------------------------------
# 14.3  REST API Gateway
# ---------------------------------------------------------------------------

def test_api_list_agents(override_agents):
    response = client.get("/agents")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "test_agent"
    assert data[0]["system_prompt"] == "Test sys prompt."


def test_api_get_agent(override_agents):
    response = client.get("/agents/test_agent")
    assert response.status_code == 200
    assert response.json()["id"] == "test_agent"


def test_api_get_agent_404(override_agents):
    response = client.get("/agents/nonexistent_agent")
    assert response.status_code == 404


def test_api_session_404():
    response = client.get("/sessions/nonexistent-session-id")
    assert response.status_code == 404


def test_api_create_session_unknown_agent(override_agents):
    payload = {"agent_id": "no_such_agent", "goal": "test"}
    response = client.post("/sessions", json=payload)
    assert response.status_code == 404


def test_api_full_session_lifecycle(override_agents, temp_db, monkeypatch):
    """End-to-end: create session via API, background task executes (mocked LLM),
    then retrieve session and verify the receipt was persisted in SQLite."""

    async def mock_run_agent(context, allowed_tools, agent_profile=None):
        return {
            "model_used": "mock-model",
            "actions": [],
            "final_text": "Mock success text",
            "verification": None,
        }

    monkeypatch.setattr("core.gateway.api.run_agent", mock_run_agent)

    # 1. Create
    payload = {
        "agent_id": "test_agent",
        "goal": "Test goal 123",
        "environment": {"TARGET": "prod"},
    }
    response = client.post("/sessions", json=payload)
    assert response.status_code == 201
    session_id = response.json()["session_id"]
    assert response.json()["status"] == "pending"

    # 1.5 Manually trigger execution since Phase 15 removed BackgroundTasks
    import asyncio
    from core.gateway.api import execute_session
    asyncio.run(execute_session(session_id, "test_agent", "Test goal 123"))

    # 2. Retrieve 
    response = client.get(f"/sessions/{session_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session_id
    assert data["agent_id"] == "test_agent"
    assert data["goal"] == "Test goal 123"
    assert data["environment"] == {"TARGET": "prod"}
    assert data["status"] == "success"
    assert data["run_receipt"] is not None
    assert data["run_receipt"]["model_used"] == "mock-model"
    assert data["run_receipt"]["final_text"] == "Mock success text"
