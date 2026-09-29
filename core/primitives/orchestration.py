from typing import List, Optional

from pydantic import BaseModel, Field


class SubagentSpec(BaseModel):
    id: str
    goal: str
    tool_scope: List[str] = Field(default_factory=list)
    agent_id: Optional[str] = None

class Phase(BaseModel):
    name: str
    subagent_specs: List[SubagentSpec]

class OrchestrationPlan(BaseModel):
    id: str
    goal: str
    phases: List[Phase]
