from pydantic import BaseModel, ConfigDict, Field

from core.primitives.evidence import EvidenceItem
from core.primitives.goal import Goal


class ContextPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: Goal
    memory_hits: list[dict[str, object]] = Field(default_factory=list)
    live_state: dict[str, object] = Field(default_factory=dict)
    recent_history: list[dict[str, object]] = Field(default_factory=list)
    tool_catalog: list[dict[str, object]] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)