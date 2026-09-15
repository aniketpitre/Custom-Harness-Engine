from core.primitives.policy import RiskTier, resolve_policy


POLICIES = {
    ("read", "inspect"): RiskTier.R0,
    ("service", "restart"): RiskTier.R2,
    ("database", "destroy"): RiskTier.R4,
}


def test_read_only_action_is_allowed() -> None:
    decision = resolve_policy("read", "inspect", POLICIES)

    assert decision.decision == "ALLOW"
    assert decision.risk_tier is RiskTier.R0


def test_operational_action_requires_approval() -> None:
    decision = resolve_policy("service", "restart", POLICIES)

    assert decision.decision == "REQUIRE_APPROVAL"
    assert decision.risk_tier is RiskTier.R2


def test_approved_operational_action_is_allowed() -> None:
    decision = resolve_policy("service", "restart", POLICIES, approved_by="operator-1")

    assert decision.decision == "ALLOW"
    assert decision.approved_by == "operator-1"


def test_destructive_action_is_denied() -> None:
    decision = resolve_policy("database", "destroy", POLICIES)

    assert decision.decision == "DENY"
    assert decision.risk_tier is RiskTier.R4


def test_unknown_action_is_denied() -> None:
    decision = resolve_policy("unknown", "action", POLICIES)

    assert decision.decision == "DENY"
    assert decision.risk_tier is RiskTier.R4