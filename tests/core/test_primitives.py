from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core.primitives.context import ContextPacket
from core.primitives.evidence import EvidenceItem, Provenance
from core.primitives.execution import ActionRecord, RunReceipt
from core.primitives.goal import Goal, TriggerSource
from core.primitives.learning import CandidateSkill, CandidateSkillStatus
from core.primitives.policy import PolicyDecision, RiskTier
from core.primitives.verification import VerificationResult


NOW = datetime.now(timezone.utc)


def make_goal() -> Goal:
    return Goal(id="goal-1", source=TriggerSource.cli, raw_input="Inspect the service", created_at=NOW)


def make_policy() -> PolicyDecision:
    return PolicyDecision(
        decision="ALLOW",
        risk_tier=RiskTier.R0,
        reason="Read-only inspection",
        tool="kubectl",
        action="get",
    )


def test_goal_validates() -> None:
    assert make_goal().source is TriggerSource.cli


def test_goal_rejects_empty_input() -> None:
    with pytest.raises(ValidationError):
        Goal(id="goal-1", source=TriggerSource.cli, raw_input="", created_at=NOW)


def test_evidence_validates() -> None:
    evidence = EvidenceItem(
        id="evidence-1",
        source="kubernetes",
        content="Pod is Ready",
        provenance=Provenance.tool_observed,
        observed_at=NOW,
        confidence=1.0,
    )
    assert evidence.provenance is Provenance.tool_observed


def test_evidence_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            id="evidence-1",
            source="kubernetes",
            content="Pod is Ready",
            provenance=Provenance.tool_observed,
            observed_at=NOW,
            confidence=1.1,
        )


def test_context_validates() -> None:
    context = ContextPacket(goal=make_goal(), evidence=[])
    assert context.goal.id == "goal-1"


def test_context_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ContextPacket(goal=make_goal(), unexpected="value")


def test_policy_validates() -> None:
    assert make_policy().risk_tier is RiskTier.R0


def test_policy_rejects_unknown_decision() -> None:
    with pytest.raises(ValidationError):
        PolicyDecision(
            decision="MAYBE",
            risk_tier=RiskTier.R0,
            reason="Unknown",
            tool="kubectl",
            action="get",
        )


def test_action_and_receipt_validate() -> None:
    action = ActionRecord(
        tool="kubectl",
        action="get",
        policy_decision=make_policy(),
        started_at=NOW,
        finished_at=NOW,
        raw_result="Pod is Ready",
    )
    receipt = RunReceipt(
        run_id="run-1",
        goal=make_goal(),
        agent_id="default-agent",
        model_used="test-model",
        actions=[action],
        started_at=NOW,
    )
    assert receipt.actions[0].rollback_available is False


def test_action_rejects_missing_policy_decision() -> None:
    with pytest.raises(ValidationError):
        ActionRecord(
            tool="kubectl",
            action="get",
            started_at=NOW,
            finished_at=NOW,
            raw_result="Pod is Ready",
        )


def test_verification_validates() -> None:
    verification = VerificationResult(
        expected="HTTP 200",
        observed="HTTP 200",
        passed=True,
        method="http_check",
        checked_at=NOW,
    )
    assert verification.passed is True


def test_verification_rejects_empty_method() -> None:
    with pytest.raises(ValidationError):
        VerificationResult(
            expected="HTTP 200",
            observed="HTTP 200",
            passed=True,
            method="",
            checked_at=NOW,
        )


def test_candidate_skill_validates() -> None:
    skill = CandidateSkill(
        id="skill-1",
        name="inspect-service",
        proposed_body="Inspect service health.",
        derived_from_run="run-1",
        validation_test="assert verify()",
    )
    assert skill.status is CandidateSkillStatus.pending_approval


def test_candidate_skill_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        CandidateSkill(
            id="skill-1",
            name="inspect-service",
            proposed_body="Inspect service health.",
            derived_from_run="run-1",
            validation_test="assert verify()",
            status="draft",
        )


def test_candidate_skill_enforces_lifecycle_transitions() -> None:
    skill = CandidateSkill(
        id="skill-1",
        name="inspect-service",
        proposed_body="Inspect service health.",
        derived_from_run="run-1",
        validation_test="assert verify()",
    )
    skill.transition_to(CandidateSkillStatus.validated)
    skill.transition_to(CandidateSkillStatus.active)
    assert skill.status is CandidateSkillStatus.active


def test_candidate_skill_rejects_invalid_lifecycle_transition() -> None:
    skill = CandidateSkill(
        id="skill-1",
        name="inspect-service",
        proposed_body="Inspect service health.",
        derived_from_run="run-1",
        validation_test="assert verify()",
    )
    with pytest.raises(ValueError):
        skill.transition_to(CandidateSkillStatus.active)