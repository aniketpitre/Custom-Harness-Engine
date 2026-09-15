from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TriggerSource(StrEnum):
    cli = "cli"
    telegram = "telegram"
    api = "api"
    event = "event"


class Goal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    source: TriggerSource
    raw_input: str = Field(min_length=1)
    created_at: datetime
    domain: str = Field(default="general", min_length=1)
    constraints: dict[str, object] = Field(default_factory=dict)