from enum import StrEnum
import ast
import re
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class CandidateSkillStatus(StrEnum):
    pending_approval = "pending_approval"
    validated = "validated"
    rejected = "rejected"
    active = "active"


class CandidateSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    proposed_body: str = Field(min_length=1)
    derived_from_run: str = Field(min_length=1)
    validation_test: str = Field(min_length=1)
    status: CandidateSkillStatus = CandidateSkillStatus.pending_approval
    version: str = Field(default="0.1.0", min_length=1)

    def transition_to(self, next_status: CandidateSkillStatus) -> None:
        allowed_transitions = {
            CandidateSkillStatus.pending_approval: {
                CandidateSkillStatus.validated,
                CandidateSkillStatus.rejected,
            },
            CandidateSkillStatus.validated: {CandidateSkillStatus.active},
            CandidateSkillStatus.rejected: set(),
            CandidateSkillStatus.active: set(),
        }
        if next_status not in allowed_transitions[self.status]:
            raise ValueError(f"Invalid skill status transition: {self.status} -> {next_status}")
        self.status = next_status


def synthesize_validation_test(receipt) -> str:
    verification = receipt.verification
    if verification is None or not verification.passed:
        raise ValueError("A passing verification result is required to synthesize a test")
    return (
        f"assert {verification.observed!r}.strip() == "
        f"{verification.expected!r}.strip()"
    )


def draft_skill_if_warranted(receipt) -> CandidateSkill | None:
    if len(receipt.actions) < 5 or receipt.verification is None or not receipt.verification.passed:
        return None
    name = _skill_name(receipt.goal.raw_input)
    actions = "\n".join(
        f"- Inspect `{action.tool}.{action.action}` evidence"
        for action in receipt.actions
    )
    body = f"# {name}\n\n## Procedure\n{actions}\n\n## Verification\nUse the run verification condition.\n"
    return CandidateSkill(
        id=str(uuid4()),
        name=name,
        proposed_body=body,
        derived_from_run=receipt.run_id,
        validation_test=synthesize_validation_test(receipt),
    )


def run_validation_test(validation_test: str) -> bool:
    tree = ast.parse(validation_test, mode="exec")
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assert):
        raise ValueError("Validation test must contain exactly one assert statement")
    assertion = tree.body[0].test
    if not isinstance(assertion, ast.Compare) or len(assertion.ops) != 1:
        raise ValueError("Validation test must be a single comparison")
    if not isinstance(assertion.ops[0], ast.Eq):
        raise ValueError("Validation test must use equality")
    left = _evaluate_stripped_constant(assertion.left)
    right = _evaluate_stripped_constant(assertion.comparators[0])
    return left == right


def write_skill_to_registry(candidate: CandidateSkill, registry_root: str | Path = "domains/devops/skills") -> Path:
    if candidate.status is not CandidateSkillStatus.validated:
        raise ValueError("Only validated skills can be written to the registry")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", candidate.name):
        raise ValueError("Skill name must be a lowercase hyphenated identifier")
    skill_dir = Path(registry_root) / candidate.name
    skill_dir.mkdir(parents=True, exist_ok=False)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\n"
        f"name: {candidate.name}\n"
        f"version: {candidate.version}\n"
        "authorship: agent-created\n"
        f"derived_from_run: {candidate.derived_from_run}\n"
        "---\n\n"
        f"{candidate.proposed_body}\n",
        encoding="utf-8",
    )
    return skill_path


async def promote_candidate_skill(candidate: CandidateSkill, registry_root: str | Path = "domains/devops/skills") -> CandidateSkill:
    from core.gateway.telegram import request_approval

    approved = await request_approval(
        action_id=candidate.derived_from_run,
        description=f"New skill proposed:\n{candidate.proposed_body[:300]}",
        risk_tier="SKILL_PROMOTION",
    )
    if not approved or not run_validation_test(candidate.validation_test):
        candidate.transition_to(CandidateSkillStatus.rejected)
        return candidate
    candidate.transition_to(CandidateSkillStatus.validated)
    write_skill_to_registry(candidate, registry_root)
    return candidate


def _skill_name(raw_input: str) -> str:
    words = re.findall(r"[a-z0-9]+", raw_input.lower())[:5]
    return "-".join(words) or "learned-skill"


def _evaluate_stripped_constant(node: ast.expr) -> str:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        raise ValueError("Validation test must compare stripped string constants")
    if node.func.attr != "strip" or node.args or node.keywords:
        raise ValueError("Validation test must call strip without arguments")
    if not isinstance(node.func.value, ast.Constant) or not isinstance(node.func.value.value, str):
        raise ValueError("Validation test must compare stripped string constants")
    return node.func.value.value.strip()