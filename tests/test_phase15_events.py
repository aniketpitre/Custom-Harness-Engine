import pytest
import sqlite3
import json
from fastapi.testclient import TestClient

from core.gateway.api import app, registry
from core.primitives.agent import AgentProfile
from core.memory.store import init_db, get_session

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
    # Also patch in agent engine since generator uses it
    monkeypatch.setattr("core.agent_engine.init_db", mock_init_db)
    
    conn = init_db(db_path)
    # Ensure tables exist
    # 
    conn.commit()
    conn.close()
    return db_path

import os
os.environ["VAULT_ADDR"] = "http://127.0.0.1:8200"
os.environ["VAULT_TOKEN"] = "dev-only-token"
client = TestClient(app)

def test_sse_generator_and_interruption(override_agents, temp_db, monkeypatch):
    # Mock LLM strictly for yielding
    async def mock_acompletion(*args, **kwargs):
        class MockMessage:
            def __init__(self):
                self.content = "Mock LLM step"
                self.tool_calls = None
        class MockChoice:
            def __init__(self):
                self.message = MockMessage()
        class MockResponse:
            def __init__(self):
                self.choices = [MockChoice()]
            def dict(self):
                return {"choices": [{"message": {"content": "Mock LLM step"}}]}
            def model_dump(self):
               return self.dict()
        return MockResponse()

    monkeypatch.setattr("litellm.acompletion", mock_acompletion)
    monkeypatch.setattr("core.agent_engine.get_secret", lambda a, b: "mock-secret")

    # 1. Start Session via API
    payload = {"agent_id": "test_agent", "goal": "Test SSE"}
    resp = client.post("/sessions", json=payload)
    session_id = resp.json()["session_id"]
    
    # 2. Queue an interruption mid-task
    int_resp = client.post(f"/sessions/{session_id}/interrupt", json={"message": "STOP AND ABORT"})
    assert int_resp.status_code == 200
    
    # 3. Connect to stream
    with client.stream("GET", f"/sessions/{session_id}/stream") as stream_response:
        assert stream_response.status_code == 200
        events_fired = []
        for line in stream_response.iter_lines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                events_fired.append(data)
                
        # We expect:
        # - interruption_received
        # - message
        # - final_receipt
        print(f"\nEVENTS:\n{json.dumps(events_fired, indent=2)}\n")
        types = [e["type"] for e in events_fired]
        assert "interruption_received" in types
        assert "message" in types
        assert "final_receipt" in types
        
        interruption_event = next(e for e in events_fired if e["type"] == "interruption_received")
        assert interruption_event["content"] == "STOP AND ABORT"
        
        receipt_event = next(e for e in events_fired if e["type"] == "final_receipt")
        assert receipt_event["receipt"]["final_text"] == "Mock LLM step"

    # 4. Check DB status
    conn = init_db(temp_db)
    session = get_session(conn, session_id)
    assert session["status"] == "success"


def test_sse_client_disconnect(override_agents, temp_db, monkeypatch):
    import asyncio
    
    # Mock LLM to yield slowly to guarantee we disconnect mid-stream
    async def mock_acompletion(*args, **kwargs):
        await asyncio.sleep(0.5)
        class MockMessage:
            def __init__(self):
                self.content = "Mock LLM step"
                self.tool_calls = None
        class MockChoice:
            def __init__(self):
                self.message = MockMessage()
        class MockResponse:
            def __init__(self):
                self.choices = [MockChoice()]
            def dict(self):
                return {"choices": [{"message": {"content": "Mock LLM step"}}]}
            def model_dump(self):
               return self.dict()
        return MockResponse()

    monkeypatch.setattr("litellm.acompletion", mock_acompletion)
    monkeypatch.setattr("core.agent_engine.get_secret", lambda a, b: "mock-secret")

    # Start Session via API
    payload = {"agent_id": "test_agent", "goal": "Test SSE Chaos"}
    resp = client.post("/sessions", json=payload)
    session_id = resp.json()["session_id"]
    
    import time
    
    # Connect to stream and then abruptly close connection
    try:
        with client.stream("GET", f"/sessions/{session_id}/stream", timeout=0.2) as stream_response:
             # Just breaking out and closing context should cancel the generator?
             pass
    except Exception as e:
        print(f"Stream interrupted: {e}")
        
    time.sleep(0.5)

    conn = init_db(temp_db)
    session = get_session(conn, session_id)
    # The session status should not be stuck in "running" forever, or at least it should gracefully terminate
    print(f"Session status after disconnect: {session['status']}")


def test_sse_cancelled_error_marks_failure(override_agents, temp_db, monkeypatch):
    import asyncio
    
    async def mock_generator(*args, **kwargs):
        yield {"type": "message", "content": "Starting"}
        raise asyncio.CancelledError("Client disconnected")
        
    monkeypatch.setattr("core.gateway.api.run_agent_generator", mock_generator)
    
    payload = {"agent_id": "test_agent", "goal": "Test SSE Disconnect"}
    resp = client.post("/sessions", json=payload)
    session_id = resp.json()["session_id"]
    
    try:
        with client.stream("GET", f"/sessions/{session_id}/stream") as stream_response:
            for line in stream_response.iter_lines():
                pass
    except Exception as e:
        print("Caught exception:", e)
                
    conn = init_db(temp_db)
    session = get_session(conn, session_id)
    assert session["status"] == "failure", "Should clean up stuck 'running' tasks on disconnect"
