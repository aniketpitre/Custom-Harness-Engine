from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected: str
    observed: str
    passed: bool
    method: str = Field(min_length=1)
    checked_at: datetime