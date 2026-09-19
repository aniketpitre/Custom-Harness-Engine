"""Phase 6: Policy and approval gate — risk tiers, decision routing, and approval state."""
import pytest

from core.primitives.policy import RiskTier, resolve_policy
from domains.devops.policy_table import TOOL_RISK_TABLE
from core.gateway.telegram import get_approver, _approvers


def test_r0_read_only_action_is_allowed():
    """R0 actions (like read_directory) should be immediately ALLOWED without approval."""
    decision = resolve_policy("filesystem", "read_directory", TOOL_RISK_TABLE)
    assert decision.decision == "ALLOW"
    assert decision.risk_tier is RiskTier.R0


def test_r2_action_requires_approval():
    """R2 actions (like restart_pod) should return REQUIRE_APPROVAL."""
    decision = resolve_policy("kubectl", "restart_pod", TOOL_RISK_TABLE)
    assert decision.decision == "REQUIRE_APPROVAL"
    assert decision.risk_tier is RiskTier.R2


def test_r3_action_requires_approval():
    """R3 actions (like production sync) should return REQUIRE_APPROVAL."""
    decision = resolve_policy("argocd", "app_sync_production", TOOL_RISK_TABLE)
    assert decision.decision == "REQUIRE_APPROVAL"
    assert decision.risk_tier is RiskTier.R3


def test_approved_r2_action_is_allowed():
    """Once an R2/R3 action receives an approver string from Telegram, it should be ALLOWED."""
    decision = resolve_policy("kubectl", "restart_pod", TOOL_RISK_TABLE, approved_by="tele_user_123")
    assert decision.decision == "ALLOW"
    assert decision.approved_by == "tele_user_123"


def test_r4_destructive_action_is_denied():
    """R4 actions (like terraform destroy) should be unconditionally DENIED."""
    decision = resolve_policy("terraform", "destroy", TOOL_RISK_TABLE)
    assert decision.decision == "DENY"
    assert decision.risk_tier is RiskTier.R4


def test_unknown_action_is_denied_as_r4():
    """Any unregistered tool/action should default to DENY and R4."""
    decision = resolve_policy("unknown_tool", "random_action", TOOL_RISK_TABLE)
    assert decision.decision == "DENY"
    assert decision.risk_tier is RiskTier.R4
    assert "not registered" in decision.reason


def test_telegram_get_approver_pops_value():
    """get_approver should return the Telegram user ID and clear it from pending states."""
    action_id = "test-action-123"
    _approvers[action_id] = "tele_user_456"

    # First call retrieves the approver
    assert get_approver(action_id) == "tele_user_456"

    # Second call returns None (it was popped)
    assert get_approver(action_id) is None
