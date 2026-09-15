from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Provenance(StrEnum):
    user_input = "user-input"
    tool_observed = "tool-observed"
    external_fetched = "external-fetched"
    human_reviewed = "human-reviewed"


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    content: str = Field(min_length=1)
    provenance: Provenance
    observed_at: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, object] = Field(default_factory=dict)