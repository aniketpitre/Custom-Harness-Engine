import pytest
import os
import json
from unittest.mock import patch, AsyncMock
from pathlib import Path
from core.agent_engine import _spill_if_needed, run_agent_generator, _dispatch_tool
from core.primitives.goal import Goal, TriggerSource
from core.primitives.context import ContextPacket
from datetime import datetime, timezone
import asyncio

def test_spill_if_needed(tmp_path, monkeypatch):
    # Mock workspace creation to our tmp_path
    monkeypatch.setattr("core.agent_engine.Path", lambda p: tmp_path / p if p == ".workspace/spill" else Path(p))
    
    # Test text smaller than threshold (100k)
    small_text = "Hello world!"
    assert _spill_if_needed(small_text, "test-session", "test-spill") == small_text
    
    # Test text larger than threshold
    large_text = "A" * 150_000
    spilled = _spill_if_needed(large_text, "test-session", "test-spill")
    
    assert "...[TRUNCATED. Full output saved to" in spilled
    assert len(spilled) < 100_000  # Should be successfully truncated to about half + suffix
    
    # Check that it actually wrote the file
    files = list((tmp_path / ".workspace/spill").glob("test-session_test-spill_*.txt"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == large_text

@pytest.mark.asyncio
async def test_token_budget_enforcement(monkeypatch):
    # We want to mock litellm.acompletion to return a large token usage
    
    async def mock_acompletion(*args, **kwargs):
        class MockMessage:
            def __init__(self):
                self.content = "I mapped everything."
                self.tool_calls = None
        
        class MockUsage:
            def __init__(self):
                self.total_tokens = 250_000  # Exceeds the 200,000 budget
                
        class MockChoice:
            def __init__(self):
                self.message = MockMessage()
                
        class MockResponse:
            def __init__(self):
                self.choices = [MockChoice()]
                self.usage = MockUsage()
            def dict(self):
                return {"choices": [{"message": {"content": "Mock LLM step"}}]}
            def model_dump(self):
               return self.dict()
               
        return MockResponse()

    monkeypatch.setattr("litellm.acompletion", mock_acompletion)
    monkeypatch.setattr("core.agent_engine.get_secret", lambda a, b: "mock-secret")
    
    goal = Goal(
        id="test-hardening-goal",
        source=TriggerSource.cli,
        raw_input="Test context length check",
        domain="devops",
        created_at=datetime.now(timezone.utc)
    )

    context = ContextPacket(
        goal=goal,
        memory_hits=[], live_state={}, recent_history=[], tool_catalog=[], evidence=[]
    )
    
    events = []
    async for event in run_agent_generator("test-session-budget", context, allowed_tools=[]):
        events.append(event)
        
    messages = [e for e in events if e["type"] == "message"]
    final_receipt = next(e for e in events if e["type"] == "final_receipt")
    
    assert "Token budget exceeded." in [m["content"] for m in messages]
    assert final_receipt["receipt"]["final_text"] == "Execution blocked: Token budget exceeded"

@pytest.mark.asyncio
async def test_generic_tool_dispatches(monkeypatch):
    import domains.generic.tools as gt
    
    # Mock the tool implementations so we don't actually do web searches or file writes
    monkeypatch.setattr(gt, "tool_grep", lambda p, t: f"Mock grep {p}")
    monkeypatch.setattr(gt, "tool_glob", lambda p: f"Mock glob {p}")
    monkeypatch.setattr(gt, "tool_edit", lambda p, c: f"Mock edit {p}")
    monkeypatch.setattr(gt, "tool_web_fetch", lambda u: f"Mock fetch {u}")
    monkeypatch.setattr(gt, "tool_web_search", lambda q: f"Mock search {q}")
    
    tools = ["grep", "glob", "edit", "web_fetch", "web_search"]
    
    for tool_name in tools:
        args = {}
        if tool_name == "grep":
            args = {"pattern": "abc", "path": "def"}
        elif tool_name == "glob":
            args = {"pattern": "*.txt"}
        elif tool_name == "edit":
            args = {"path": "file.txt", "new_content": "hello"}
        elif tool_name == "web_fetch":
            args = {"url": "https://example.com"}
        elif tool_name == "web_search":
            args = {"query": "test query"}
            
        result, action = await _dispatch_tool(
            action_id="test-action",
            name=tool_name,
            arguments=args,
            allowed_tools=["Generic"],
            session_id="test-session"
        )
        
        # Verify result gets formatted correctly
        assert "Mock" in result
        
        # Verify ActionRecord creation
        assert action.tool == "generic"
        assert action.action == tool_name
        assert action.policy_decision.risk_tier == "R1"

