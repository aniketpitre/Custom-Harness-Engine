import pytest
import asyncio
import os
import json
from unittest.mock import patch

from core.primitives.goal import Goal, TriggerSource
from core.primitives.context import ContextPacket
from core.agent_engine import run_agent
from domains.devops.tools.argocd_tools import argocd_app_list, argocd_app_get

@pytest.fixture(autouse=True)
def vault_env():
    """Ensure vault env vars exist."""
    old_addr = os.environ.get("VAULT_ADDR")
    old_token = os.environ.get("VAULT_TOKEN")

    os.environ["VAULT_ADDR"] = "http://127.0.0.1:8200"
    os.environ["VAULT_TOKEN"] = "c6869775842d732f69f590ac45ec422847ca27ffa15a9bf9b45719437a6803f4"

    yield

    if old_addr: os.environ["VAULT_ADDR"] = old_addr
    if old_token: os.environ["VAULT_TOKEN"] = old_token


# Scenarios 4 and 5
def test_argocd_app_list():
    result = argocd_app_list()
    assert result == "[]"

def test_argocd_app_get_non_existent():
    # Attempting to get an app that doesn't exist usually throws a RuntimeError with PermissionDenied
    with pytest.raises(RuntimeError) as exc_info:
        argocd_app_get("non-existent-app")
    assert "PermissionDenied" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


# Scenario 6: Agent Scenario utilizing DevOpsRead
@pytest.mark.asyncio
async def test_agent_devops_read_scenario():
    """Test that the agent engine can properly route and execute a DevOpsRead tool like argocd_app_list."""
    from datetime import datetime, timezone

    goal = Goal(
        id="scenario-6-goal",
        source=TriggerSource.cli,
        raw_input="List the ArgoCD applications currently deployed.",
        domain="devops",
        created_at=datetime.now(timezone.utc)
    )

    context = ContextPacket(
        goal=goal,
        memory_hits=[],
        live_state={},
        recent_history=[],
        tool_catalog=[],
        evidence=[]
    )

    result = await run_agent(context, allowed_tools=["Read", "DevOpsRead"])

    assert "final_text" in result
    assert len(result["events"]) > 0

    # We should see that it took at least 1 action (calling the tool)
    assert len(result["actions"]) > 0

    # Tool used should be argocd_app_list
    action = result["actions"][0]
    assert action.tool == "argocd"
    assert action.action == "app_list"
    assert action.policy_decision.decision == "ALLOW"
    assert action.raw_result == "[]"


# Scenario 9: Receipt generation
def test_agent_receipt_creation():
    """Test that we can assemble a full receipt after running an argocd query."""
    import uuid
    from datetime import datetime, timezone
    from core.primitives.execution import RunReceipt, ActionRecord
    from core.primitives.policy import PolicyDecision, RiskTier

    goal = Goal(
        id="scenario-9",
        source=TriggerSource.cli,
        raw_input="List ArgoCD apps",
        domain="devops",
        created_at=datetime.now(timezone.utc)
    )

    action = ActionRecord(
        tool="argocd",
        action="app_list",
        policy_decision=PolicyDecision(
            decision="ALLOW", risk_tier=RiskTier.R0, reason="Read tool", tool="argocd", action="app_list"
        ),
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        raw_result="[]"
    )

    receipt = RunReceipt(
        run_id=str(uuid.uuid4()),
        goal=goal,
        agent_id="test-agent",
        model_used="gpt-oss",
        actions=[action],
        status="success",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc)
    )

    # Ensure receipt validates and is well formed
    json_rep = receipt.model_dump_json()
    assert "argocd" in json_rep
    assert "app_list" in json_rep
