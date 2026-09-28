import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from core.agent_engine import _compact_history, run_agent_generator
from core.primitives.context import ContextPacket
from core.primitives.goal import Goal, TriggerSource
from core.primitives.agent import AgentProfile
from datetime import datetime, timezone

@pytest.mark.asyncio
async def test_compact_history_threshold():
    messages = [{"role": "system", "content": "Hi"}] * 5
    result = await _compact_history(messages, "gpt", "key")
    assert len(result) == 5

    messages = [{"role": "system", "content": "System"}]
    for i in range(8):
        messages.append({"role": "user", "content": f"msg {i}"})
    messages.append({"role": "user", "content": "Tail"})
    
    with patch("core.agent_engine.litellm.acompletion", new_callable=AsyncMock) as mock_llm:
        mock_res = MagicMock()
        mock_res.choices = [MagicMock()]
        mock_res.choices[0].message.content = "Mock Summary"
        mock_llm.return_value = mock_res
        
        compacted = await _compact_history(messages, "test_model", "test_key")
        
        assert len(compacted) == 5
        assert compacted[0]["content"] == "System"
        assert "Mock Summary" in compacted[1]["content"]
        assert compacted[-1]["content"] == "Tail"

@pytest.mark.asyncio
@patch("core.agent_engine.litellm.acompletion", new_callable=AsyncMock)
@patch("core.agent_engine._compact_history", new_callable=AsyncMock)
async def test_run_agent_triggers_compaction(mock_compact, mock_llm):
    mock_compact.return_value = [{"role": "system", "content": "compacted"}]
    
    mock_res_tool = MagicMock()
    mock_res_tool.usage = MagicMock(total_tokens=10)
    mock_res_tool.choices = [MagicMock()]
    mock_tool = MagicMock()
    mock_tool.id = "call_123"
    mock_tool.function.name = "web_fetch"
    mock_tool.function.arguments = '{"url": "https://example.com"}'
    mock_res_tool.choices[0].message.tool_calls = [mock_tool]
    
    mock_res_final = MagicMock()
    mock_res_final.usage = MagicMock(total_tokens=10)
    mock_res_final.choices = [MagicMock()]
    mock_res_final.choices[0].message.tool_calls = []
    mock_res_final.choices[0].message.content = "Done"
    
    mock_llm.side_effect = [mock_res_tool] * 6 + [mock_res_final]
    
    goal = Goal(id="compaction_goal", source=TriggerSource.cli, raw_input="Fetch six times", domain="generic", created_at=datetime.now(timezone.utc))
    context = ContextPacket(goal=goal, memory_hits=[], live_state={}, recent_history=[], tool_catalog=[], evidence=[])
    
    with patch("core.agent_engine.get_secret", return_value="mock_key"), patch("core.agent_engine._dispatch_tool", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = ("Success", MagicMock())
        
        async for event in run_agent_generator(None, context, ["Generic"]):
            if event["type"] == "message" and "background history compaction" in event["content"]:
                pass
        
        assert mock_compact.called, "Agent engine didn't trigger auto-compaction over threshold!"
