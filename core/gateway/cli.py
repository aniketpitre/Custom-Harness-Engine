import asyncio
import sys
import uuid
from datetime import datetime, timezone

from core.agent_engine import run_agent
from core.memory.store import init_db, search_memory
from core.primitives.context import ContextPacket
from core.primitives.execution import RunReceipt
from core.primitives.goal import Goal, TriggerSource


def build_context(raw_text: str, conn) -> ContextPacket:
    goal = Goal(
        id=str(uuid.uuid4()),
        source=TriggerSource.cli,
        raw_input=raw_text,
        created_at=datetime.now(timezone.utc),
    )
    return ContextPacket(
        goal=goal,
        memory_hits=search_memory(conn, raw_text, goal.domain),
        live_state={},
        recent_history=[],
        tool_catalog=[],
    )


async def handle_cli_input(raw_text: str) -> RunReceipt:
    conn = init_db()
    try:
        context = build_context(raw_text, conn)
    finally:
        conn.close()
    goal = context.goal
    result = await run_agent(context, allowed_tools=["Read"])
    return RunReceipt(
        run_id=str(uuid.uuid4()),
        goal=goal,
        agent_id="default-agent",
        model_used=result["model_used"],
        actions=[],
        final_text=result["final_text"],
        status="success",
        started_at=goal.created_at,
        finished_at=datetime.now(timezone.utc),
    )


def main() -> None:
    raw_text = " ".join(sys.argv[1:]).strip()
    if not raw_text:
        raise SystemExit("Usage: python -m core.gateway.cli <goal>")
    receipt = asyncio.run(handle_cli_input(raw_text))
    print(receipt.model_dump_json(indent=2))


if __name__ == "__main__":
    main()