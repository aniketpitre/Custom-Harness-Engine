"""One-shot CLI: creates a durable session, runs it inline and prints the RunReceipt as JSON."""
from __future__ import annotations

import argparse
import asyncio
import uuid

from core.engine import get_engine
from core.gateway.channels import start_telegram, terminal_channel
from core.memory.store import create_session, get_session, init_db
from core.primitives.execution import RunReceipt
from core.registry import AgentRegistry
from core.runs import RunManager

DEFAULT_AGENT = "devops_agent"


async def handle_cli_input(
    raw_text: str,
    verification_request: dict | None = None,
    agent_id: str = DEFAULT_AGENT,
    agents: AgentRegistry | None = None,
    runs: RunManager | None = None,
) -> RunReceipt:
    agents = agents or AgentRegistry()
    engine = get_engine()
    engine.extras["agents"] = agents
    if agents.get_agent(agent_id) is None:
        raise SystemExit(f"Unknown agent: {agent_id}")
    runs = runs or RunManager(engine, agents)
    await engine.ensure_started()
    session_id = str(uuid.uuid4())
    conn = init_db()
    try:
        create_session(conn, session_id, agent_id, raw_text, verification=verification_request)
    finally:
        conn.close()
    channel = start_telegram(engine.broker)
    terminal = terminal_channel(engine.broker)
    try:
        await runs.run_inline(session_id)
    finally:
        if channel:
            await channel.stop()
        if terminal:
            terminal()
    conn = init_db()
    try:
        session = get_session(conn, session_id)
    finally:
        conn.close()
    if not session or not session.get("run_receipt"):
        raise SystemExit(f"Run failed (outcome: {session and session.get('outcome')})")
    return RunReceipt.model_validate(session["run_receipt"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one goal through the Harness Engine")
    parser.add_argument("goal", nargs="+")
    parser.add_argument("--agent", default=DEFAULT_AGENT)
    parser.add_argument("--verify-file", nargs=2, metavar=("PATH", "EXPECTED"),
                        help="verify that PATH contains EXPECTED after the run")
    args = parser.parse_args()
    verification = ({"type": "file_content", "path": args.verify_file[0], "expected_content": args.verify_file[1]}
                    if args.verify_file else None)
    receipt = asyncio.run(handle_cli_input(" ".join(args.goal), verification, args.agent))
    print(receipt.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
