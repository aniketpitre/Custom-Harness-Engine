import pytest
from fastapi.testclient import TestClient
from core.gateway.api import app
from core.memory.store import init_db
import json

client = TestClient(app)

def test_fork_session():
    # 1. Create agent profile conceptually mocked in tests or check if list_agents works
    agents_res = client.get("/agents")
    assert agents_res.status_code == 200
    agents = agents_res.json()
    if not agents:
        agent_id = "test_agent"
        # In a real environment, load_agents would have something. We'll bypass logic by testing the DB directly or relying on missing agent 404 falling back, but wait, create_session checks registry.
        
    # We will pick the first agent
    agent_id = agents[0]["id"]
    
    # 2. Create session
    req = {"agent_id": agent_id, "goal": "Find bugs", "environment": {}}
    res = client.post("/sessions", json=req)
    assert res.status_code == 201
    session_id = res.json()["session_id"]
    
    # 3. Simulate run_receipt existing
    conn = init_db()
    mock_receipt = {"message_history": [{"role": "system", "content": "I am forkable"}]}
    conn.execute("UPDATE sessions SET run_receipt = ? WHERE id = ?", (json.dumps(mock_receipt), session_id))
    conn.commit()
    conn.close()
    
    # 4. Fork it
    fork_req = {"goal_override": "Find specific bugs"}
    fork_res = client.post(f"/sessions/{session_id}/fork", json=fork_req)
    assert fork_res.status_code == 201
    new_session_id = fork_res.json()["session_id"]
    
    # 5. Get new session, verify parent_session_id and receipt propagation
    get_res = client.get(f"/sessions/{new_session_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["goal"] == "Find specific bugs"
    assert data["parent_session_id"] == session_id
    assert data["run_receipt"]["message_history"][0]["content"] == "I am forkable"

