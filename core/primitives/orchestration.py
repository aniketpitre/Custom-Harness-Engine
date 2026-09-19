from pydantic import BaseModel, Field
from typing import List, Optional

class SubagentSpec(BaseModel):
    id: str
    goal: str
    tool_scope: List[str] = Field(default_factory=list)

class Phase(BaseModel):
    name: str
    subagent_specs: List[SubagentSpec]

class OrchestrationPlan(BaseModel):
    id: str
    goal: str
    phases: List[Phase]
