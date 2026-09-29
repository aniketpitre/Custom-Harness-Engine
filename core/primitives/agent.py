import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from core.primitives.execution import RunReceipt


class AgentProfile(BaseModel):
    """Declarative definition of an agent profile."""
    id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    allowed_tools: List[str] = Field(default_factory=list)
    model: Optional[str] = None
    version: int = 1
    max_turns: Optional[int] = None
    token_budget: Optional[int] = None
    max_cost_usd: Optional[float] = None  # USD ceiling for one run including subagents; 0/None = settings
    deny_tools: List[str] = Field(default_factory=list)
    rules: List[str] = Field(default_factory=list)  # e.g. "deny:bash(rm *)", "ask:web_fetch"
    verification: Optional[Dict[str, str]] = None
    verify_with_agent: bool = False  # independent read-only verifier agent checks the final answer


class Session(BaseModel):
    """Durable state representation for an execution session."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    status: str = Field(pattern="^(pending|running|success|failure|blocked)$", default="pending")
    environment: Dict[str, str] = Field(default_factory=dict)
    run_receipt: Optional[RunReceipt] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
