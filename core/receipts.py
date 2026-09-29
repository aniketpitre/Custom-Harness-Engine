"""RunReceipt as a projection of the event log; status semantics in one place."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from core import eventlog
from core.primitives.execution import ActionRecord, RunReceipt
from core.primitives.goal import Goal
from core.primitives.learning import draft_skill_if_warranted
from core.primitives.verification import VerificationResult

OUTCOMES = {"completed", "budget_exhausted", "turn_limit", "time_limit", "error", "cancelled",
            "loop_guard", "crashed"}


def derive_status(outcome: str | None, verified: bool | None) -> str:
    """success only when the run completed AND its verification (if any) passed."""
    if outcome == "completed" and verified is not False:
        return "success"
    return "failure"


def actions_from_events(conn, session_id: str) -> list[ActionRecord]:
    return [ActionRecord.model_validate(e["payload"])
            for e in eventlog.list_events(conn, session_id, types={"action"})]


def build_receipt(
    conn,
    session_id: str,
    goal: Goal,
    agent_id: str,
    *,
    model_used: str,
    final_text: str,
    outcome: str,
    verification: VerificationResult | None,
    started_at: datetime,
    teardown_tasks: list[str] | None = None,
    include_history: bool = True,
    usage: dict | None = None,
) -> RunReceipt:
    verified = None if verification is None else verification.passed
    receipt = RunReceipt(
        run_id=session_id, goal=goal, agent_id=agent_id, model_used=model_used or "unknown",
        actions=actions_from_events(conn, session_id), verification=verification,
        final_text=final_text,
        message_history=eventlog.messages_for(conn, session_id) if include_history else None,
        status=derive_status(outcome, verified), outcome=outcome, verified=verified,
        chain_head=eventlog.chain_head(conn, session_id), started_at=started_at,
        finished_at=datetime.now(timezone.utc), teardown_tasks=teardown_tasks or [], usage=usage)
    if outcome == "completed" and verified:
        receipt.candidate_skill = draft_skill_if_warranted(receipt)
    return receipt


def receipt_json(receipt: RunReceipt) -> dict[str, Any]:
    return json.loads(receipt.model_dump_json())
