from enum import StrEnum

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