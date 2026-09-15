from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RiskTier(StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern="^(ALLOW|REQUIRE_APPROVAL|DENY)$")
    risk_tier: RiskTier
    reason: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    action: str = Field(min_length=1)
    approved_by: str | None = None


TOOL_RISK_TABLE: dict[tuple[str, str], RiskTier] = {}


def resolve_policy(
    tool: str,
    action: str,
    risk_table: dict[tuple[str, str], RiskTier] | None = None,
    approved_by: str | None = None,
) -> PolicyDecision:
    table = TOOL_RISK_TABLE if risk_table is None else risk_table
    risk_tier = table.get((tool, action))
    if risk_tier is None:
        return PolicyDecision(
            decision="DENY",
            risk_tier=RiskTier.R4,
            reason="Tool action is not registered in the policy table",
            tool=tool,
            action=action,
        )
    if risk_tier is RiskTier.R4:
        decision = "DENY"
        reason = "Destructive actions are denied by default"
    elif risk_tier in {RiskTier.R2, RiskTier.R3} and approved_by is None:
        decision = "REQUIRE_APPROVAL"
        reason = "Human approval is required for this risk tier"
    else:
        decision = "ALLOW"
        reason = "Action is allowed by the policy table"
    return PolicyDecision(
        decision=decision,
        risk_tier=risk_tier,
        reason=reason,
        tool=tool,
        action=action,
        approved_by=approved_by,
    )