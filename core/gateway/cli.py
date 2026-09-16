import asyncio
import sys
import uuid
from datetime import datetime, timezone

from core.agent_engine import run_agent
from core.memory.store import init_db, search_memory
from core.primitives.context import ContextPacket
from core.primitives.execution import RunReceipt
from core.primitives.goal import Goal, TriggerSource
from core.primitives.learning import draft_skill_if_warranted


def build_context(raw_text: str, conn, verification_request: dict[str, str] | None = None) -> ContextPacket:
    goal = Goal(
        id=str(uuid.uuid4()),
        source=TriggerSource.cli,
        raw_input=raw_text,
        created_at=datetime.now(timezone.utc),
    )
    return ContextPacket(
        goal=goal,
        memory_hits=search_memory(conn, raw_text, goal.domain),
        live_state={"verification": verification_request} if verification_request else {},
        recent_history=[],
        tool_catalog=[],
    )


async def handle_cli_input(
    raw_text: str,
    verification_request: dict[str, str] | None = None,
) -> RunReceipt:
    conn = init_db()
    try:
        context = build_context(raw_text, conn, verification_request)
    finally:
        conn.close()
    goal = context.goal
    result = await run_agent(context, allowed_tools=["Read", "DevOpsRead", "DevOpsWrite"])
    verification = result["verification"]
    receipt = RunReceipt(
        run_id=str(uuid.uuid4()),
        goal=goal,
        agent_id="default-agent",
        model_used=result["model_used"],
        actions=result["actions"],
        final_text=result["final_text"],
        status="success" if verification is None or verification.passed else "failure",
        verification=verification,
        started_at=goal.created_at,
        finished_at=datetime.now(timezone.utc),
    )
    receipt.candidate_skill = draft_skill_if_warranted(receipt)
    return receipt


def main() -> None:
    raw_text = " ".join(sys.argv[1:]).strip()
    if not raw_text:
        raise SystemExit("Usage: python -m core.gateway.cli <goal>")
    receipt = asyncio.run(handle_cli_input(raw_text))
    print(receipt.model_dump_json(indent=2))


if __name__ == "__main__":
    main()