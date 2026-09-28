import pytest
import os
import shutil
import asyncio
from unittest.mock import patch, AsyncMock
from core.agent_engine import run_agent, ContextPacket
from core.primitives.goal import Goal, TriggerSource
from datetime import datetime, timezone
from pathlib import Path
from core.plugins.registry import DYNAMIC_PLUGINS_DIR

@pytest.fixture(autouse=True)
def clean_dynamic_dir():
    # Make sure we start clean
    if DYNAMIC_PLUGINS_DIR.exists():
        for item in DYNAMIC_PLUGINS_DIR.iterdir():
            if item.name != "__init__.py":
                import shutil; shutil.rmtree(item) if item.is_dir() else item.unlink()
    yield
    # Cleanup after
    if DYNAMIC_PLUGINS_DIR.exists():
        for item in DYNAMIC_PLUGINS_DIR.iterdir():
            if item.name != "__init__.py":
                import shutil; shutil.rmtree(item) if item.is_dir() else item.unlink()

@pytest.mark.asyncio
@patch("core.agent_engine.get_secret")
@patch("core.agent_engine.request_approval", new_callable=AsyncMock)
@patch("core.agent_engine.get_approver")
async def test_write_and_register_tool(mock_get_secret, mock_get_approver, mock_request_approval):
    mock_get_secret.return_value = "mock_key"
    mock_request_approval.return_value = True
    mock_get_approver.return_value = "tele_user_phase24"

    goal = Goal(
        id="scenario-selfedit",
        source=TriggerSource.cli,
        raw_input="Use the 'write_and_register_tool' to create a tool named 'greet_agent' that simply returns 'Hello from dynamic tool!'. Use load_skill if needed.",
        domain="devops",
        created_at=datetime.now(timezone.utc)
    )
    context = ContextPacket(
        goal=goal,
        memory_hits=[], live_state={}, recent_history=[], tool_catalog=[], evidence=[]
    )
    
    # We run the agent, relying on groq LLM to use the tool
    # Let's mock litellm so we don't depend on network
    
    # Actually wait we can just patch litellm similarly to Phase 14 to run the tool
    mock_responses = [
        # First turn: call write_and_register_tool
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "I will create the tool.",
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "write_and_register_tool",
                                "arguments": '{"tool_name": "greet_agent", "python_code": "TOOL_SCHEMA = {\\"type\\": \\"function\\", \\"function\\": {\\"name\\": \\"greet_agent\\", \\"description\\": \\"greet\\", \\"parameters\\": {\\"type\\": \\"object\\", \\"properties\\": {}, \\"additionalProperties\\": False}}}\\n\\ndef execute(args):\\n    return \\"Hello from dynamic tool!\\""}'
                            }
                        }
                    ]
                }
            }],
            "usage": {"total_tokens": 100}
        },
        # Second turn: use the newly created tool
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Now I will call it.",
                    "tool_calls": [
                        {
                            "id": "call_456",
                            "type": "function",
                            "function": {
                                "name": "greet_agent",
                                "arguments": "{}"
                            }
                        }
                    ]
                }
            }],
            "usage": {"total_tokens": 200}
        },
        # Third turn: done
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Done! Tool executed successfully.",
                    "tool_calls": []
                }
            }],
            "usage": {"total_tokens": 300}
        }
    ]
    
    class MockCompletion:
        class Choice:
            def __init__(self, c_dict):
                class Message:
                    def __init__(self, m_dict):
                        self.role = m_dict.get("role")
                        self.content = m_dict.get("content")
                        if "tool_calls" in m_dict and m_dict["tool_calls"]:
                            class ToolCall:
                                def __init__(self, t_dict):
                                    self.id = t_dict["id"]
                                    self.type = t_dict["type"]
                                    class Function:
                                        def __init__(self, f_dict):
                                            self.name = f_dict["name"]
                                            self.arguments = f_dict["arguments"]
                                    self.function = Function(t_dict["function"])
                            self.tool_calls = [ToolCall(t) for t in m_dict["tool_calls"]]
                        else:
                            self.tool_calls = []
                self.message = Message(c_dict["message"])
                
        def __init__(self, r_dict):
            self.choices = [self.Choice(c) for c in r_dict["choices"]]
            class Usage:
                def __init__(self, u_dict):
                    self.total_tokens = u_dict["total_tokens"]
            self.usage = Usage(r_dict.get("usage", {"total_tokens": 0}))

    turn = 0
    async def mock_acompletion(*args, **kwargs):
        nonlocal turn
        resp = MockCompletion(mock_responses[turn])
        turn += 1
        return resp
        
    with patch("litellm.acompletion", side_effect=mock_acompletion):
        result = await run_agent(context, allowed_tools=["Generic"])

    assert mock_request_approval.called
    assert result["final_text"] == "Done! Tool executed successfully."
    assert any(a.action == "write_and_register_tool" for a in result["actions"])
    assert any(a.action == "greet_agent" for a in result["actions"])
    assert any("Hello from dynamic tool!" in a.raw_result for a in result["actions"] if a.action == "greet_agent")
    
    # Assert physical file was created
    assert (DYNAMIC_PLUGINS_DIR / "greet_agent.py").exists()
