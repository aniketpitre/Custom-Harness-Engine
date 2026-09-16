from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from core.primitives.goal import Goal
from core.primitives.learning import CandidateSkill
from core.primitives.policy import PolicyDecision
from core.primitives.verification import VerificationResult


class ActionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1)
    action: str = Field(min_length=1)
    policy_decision: PolicyDecision
    approved_by: str | None = None
    started_at: datetime
    finished_at: datetime
    raw_result: str
    pre_state_snapshot: dict[str, object] | None = None
    post_state_snapshot: dict[str, object] | None = None
    rollback_available: bool = False


class RunReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    goal: Goal
    agent_id: str = Field(min_length=1)
    model_used: str = Field(min_length=1)
    actions: list[ActionRecord] = Field(default_factory=list)
    verification: VerificationResult | None = None
    candidate_skill: CandidateSkill | None = None
    final_text: str | None = None
    status: str = Field(pattern="^(running|success|failure|blocked)$", default="running")
    started_at: datetime
    finished_at: datetime | None = None