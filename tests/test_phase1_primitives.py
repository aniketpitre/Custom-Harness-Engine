"""Phase 1: Core primitives — Goal, Context, Evidence, Policy, Execution, Verification, Learning."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core.primitives.goal import Goal, TriggerSource
from core.primitives.context import ContextPacket
from core.primitives.evidence import EvidenceItem, Provenance
from core.primitives.policy import PolicyDecision, RiskTier
from core.primitives.execution import ActionRecord, RunReceipt
from core.primitives.verification import VerificationResult
from core.primitives.learning import CandidateSkill, CandidateSkillStatus


NOW = datetime.now(timezone.utc)


# --- Goal ---

def test_goal_all_trigger_sources():
    for source in TriggerSource:
        goal = Goal(id="g1", source=source, raw_input="test", created_at=NOW)
        assert goal.source is source


def test_goal_domain_defaults_to_general():
    goal = Goal(id="g1", source=TriggerSource.cli, raw_input="test", created_at=NOW)
    assert goal.domain == "general"


def test_goal_custom_domain():
    goal = Goal(id="g1", source=TriggerSource.cli, raw_input="test", created_at=NOW, domain="devops")
    assert goal.domain == "devops"


def test_goal_rejects_empty_id():
    with pytest.raises(ValidationError):
        Goal(id="", source=TriggerSource.cli, raw_input="test", created_at=NOW)


def test_goal_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        Goal(id="g1", source=TriggerSource.cli, raw_input="test", created_at=NOW, extra="nope")


# --- Evidence ---

def test_evidence_all_provenances():
    for prov in Provenance:
        e = EvidenceItem(id="e1", source="k8s", content="ok", provenance=prov, observed_at=NOW, confidence=0.5)
        assert e.provenance is prov


def test_evidence_confidence_boundaries():
    EvidenceItem(id="e1", source="k8s", content="ok", provenance=Provenance.user_input, observed_at=NOW, confidence=0.0)
    EvidenceItem(id="e1", source="k8s", content="ok", provenance=Provenance.user_input, observed_at=NOW, confidence=1.0)
    with pytest.raises(ValidationError):
        EvidenceItem(id="e1", source="k8s", content="ok", provenance=Provenance.user_input, observed_at=NOW, confidence=-0.1)


# --- Policy ---

def test_all_risk_tiers_exist():
    assert set(RiskTier) == {RiskTier.R0, RiskTier.R1, RiskTier.R2, RiskTier.R3, RiskTier.R4}


def test_policy_decision_patterns():
    for valid in ("ALLOW", "REQUIRE_APPROVAL", "DENY"):
        p = PolicyDecision(decision=valid, risk_tier=RiskTier.R0, reason="r", tool="t", action="a")
        assert p.decision == valid

    with pytest.raises(ValidationError):
        PolicyDecision(decision="MAYBE", risk_tier=RiskTier.R0, reason="r", tool="t", action="a")


# --- ActionRecord ---

def test_action_record_snapshot_fields():
    policy = PolicyDecision(decision="ALLOW", risk_tier=RiskTier.R0, reason="ok", tool="t", action="a")
    a = ActionRecord(tool="t", action="a", policy_decision=policy, started_at=NOW, finished_at=NOW,
                     raw_result="ok", pre_state_snapshot={"phase": "Running"}, post_state_snapshot={"phase": "Running"},
                     rollback_available=True)
    assert a.rollback_available is True
    assert a.pre_state_snapshot["phase"] == "Running"


# --- RunReceipt ---

def test_receipt_status_values():
    policy = PolicyDecision(decision="ALLOW", risk_tier=RiskTier.R0, reason="ok", tool="t", action="a")
    for status in ("running", "success", "failure", "blocked"):
        r = RunReceipt(run_id="r1", goal=Goal(id="g1", source=TriggerSource.cli, raw_input="test", created_at=NOW),
                       agent_id="agent", model_used="model", status=status, started_at=NOW)
        assert r.status == status

    with pytest.raises(ValidationError):
        RunReceipt(run_id="r1", goal=Goal(id="g1", source=TriggerSource.cli, raw_input="test", created_at=NOW),
                   agent_id="agent", model_used="model", status="invalid", started_at=NOW)


# --- VerificationResult ---

def test_verification_result_fields():
    v = VerificationResult(expected="a", observed="a", passed=True, method="file_check", checked_at=NOW)
    assert v.passed is True
    assert v.method == "file_check"


# --- CandidateSkill lifecycle ---

def test_skill_full_lifecycle():
    s = CandidateSkill(id="s1", name="test-skill", proposed_body="body", derived_from_run="r1",
                       validation_test="assert True")
    assert s.status is CandidateSkillStatus.pending_approval
    s.transition_to(CandidateSkillStatus.validated)
    assert s.status is CandidateSkillStatus.validated
    s.transition_to(CandidateSkillStatus.active)
    assert s.status is CandidateSkillStatus.active


def test_skill_rejection_is_terminal():
    s = CandidateSkill(id="s1", name="test-skill", proposed_body="body", derived_from_run="r1",
                       validation_test="assert True")
    s.transition_to(CandidateSkillStatus.rejected)
    with pytest.raises(ValueError):
        s.transition_to(CandidateSkillStatus.validated)


def test_skill_cannot_skip_to_active():
    s = CandidateSkill(id="s1", name="test-skill", proposed_body="body", derived_from_run="r1",
                       validation_test="assert True")
    with pytest.raises(ValueError):
        s.transition_to(CandidateSkillStatus.active)
