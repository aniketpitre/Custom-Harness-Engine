import pytest
from core.agent_engine import _dispatch_tool

@pytest.mark.asyncio
async def test_advisor_tool_dispatch(monkeypatch):
    async def mock_acompletion(*args, **kwargs):
        class MockMessage:
            def __init__(self):
                self.content = "I suggest deleting the file."
        class MockChoice:
            def __init__(self):
                self.message = MockMessage()
        class MockResponse:
            def __init__(self):
                self.choices = [MockChoice()]
        return MockResponse()

    monkeypatch.setattr("litellm.acompletion", mock_acompletion)
    monkeypatch.setattr("core.secrets.get_secret", lambda a, b: "mock-secret")
    
    result, action_record = await _dispatch_tool(
        "action-id",
        "advisor_consultation",
        {"query": "What to do?", "context": "Error 404"},
        ["Advisor"],
        "session-123"
    )
    
    assert "Advisor says: I suggest deleting the file." in result
    assert action_record.tool == "advisor"
    assert action_record.action == "advisor_consultation"
