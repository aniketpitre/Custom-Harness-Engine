import pytest
import asyncio
import os
import json
from unittest.mock import patch, AsyncMock

from core.primitives.goal import Goal, TriggerSource
from core.primitives.context import ContextPacket
from core.agent_engine import run_agent

@pytest.fixture(autouse=True)
def vault_env():
    old_addr = os.environ.get("VAULT_ADDR")
    old_token = os.environ.get("VAULT_TOKEN")

    os.environ["VAULT_ADDR"] = "http://127.0.0.1:8200"
    os.environ["VAULT_TOKEN"] = "c6869775842d732f69f590ac45ec422847ca27ffa15a9bf9b45719437a6803f4"

    yield

    if old_addr: os.environ["VAULT_ADDR"] = old_addr
    if old_token: os.environ["VAULT_TOKEN"] = old_token


@pytest.mark.asyncio
@patch("core.agent_engine.request_approval", new_callable=AsyncMock)
@patch("core.agent_engine.get_approver")
@patch("domains.devops.tools.argocd_tools.argocd_app_sync")
async def test_r3_action_approval_granted(mock_sync, mock_get_approver, mock_request_approval):
    """Test that a real R3 action is properly intercepted, asks for approval, gets it, and executes."""
    mock_request_approval.return_value = True
    mock_get_approver.return_value = "tele_user_r3"
    mock_sync.return_value = "App synced successfully in production."

    from datetime import datetime, timezone
    goal = Goal(
        id="scenario-r3-goal",
        source=TriggerSource.cli,
        raw_input="Do not ask the user for approval via chat. You MUST immediately invoke the tool 'argocd_app_sync_production' using parameters {'app_name': 'guestbook'}. The system framework will handle the human approval mechanically when the tool is called.",
        domain="devops",
        created_at=datetime.now(timezone.utc)
    )

    context = ContextPacket(
        goal=goal,
        memory_hits=[], live_state={}, recent_history=[], tool_catalog=[], evidence=[]
    )

    # Allow DevOpsWrite which contains our R3 argocd_app_sync_production tool
    result = await run_agent(context, allowed_tools=["DevOpsWrite"])

    assert mock_request_approval.called
    assert mock_sync.called

    action = [a for a in result["actions"] if a.action == "app_sync_production"][0]

    # Confirm it passed through R3 correctly
    assert action.policy_decision.risk_tier == "R3"
    assert action.policy_decision.decision == "ALLOW"
    assert action.approved_by == "tele_user_r3"
