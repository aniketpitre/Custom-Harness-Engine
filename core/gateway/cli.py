"""One-shot CLI: creates a durable session, runs it inline and prints the RunReceipt as JSON."""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from core import theme
from core.engine import get_engine
from core.gateway.channels import start_telegram, terminal_channel
from core.memory.store import create_session, get_session, init_db
from core.primitives.execution import RunReceipt
from core.registry import AgentRegistry
from core.runs import RunManager

DEFAULT_AGENT = "devops_agent"


class UnknownAgent(SystemExit):
    pass


def _live_status(engine):
    """Themed progress on stderr while a goal runs: which tool is working and how it ended."""
    err = sys.stderr

    def started(event: dict) -> None:
        print(f"{theme.glyph('tool', err)} {theme.paint(event['tool'], 'brand', err)} "
              f"{theme.paint(theme.verb() + '...', 'dim', err)}", file=err, flush=True)

    def finished(event: dict) -> None:
        mark = theme.status_mark("fail" if event.get("is_error") else "ok", err)
        print(f"  {mark} {event['tool']}", file=err, flush=True)

    disposers = [engine.hooks.on("pre_tool", started, priority=999), engine.hooks.on("post_tool", finished, priority=999)]
    return lambda: [d() for d in disposers]


async def handle_cli_input(
    raw_text: str,
    verification_request: dict | None = None,
    agent_id: str = DEFAULT_AGENT,
    agents: AgentRegistry | None = None,
    runs: RunManager | None = None,
    permission_mode: str | None = None,
    on_event=None,
    live_status: bool = True,
) -> RunReceipt:
    agents = agents or AgentRegistry()
    engine = get_engine()
    engine.extras["agents"] = agents
    if agents.get_agent(agent_id) is None:
        raise UnknownAgent(f"Unknown agent: {agent_id}")
    runs = runs or RunManager(engine, agents)
    await engine.ensure_started()
    session_id = str(uuid.uuid4())
    conn = init_db()
    try:
        create_session(conn, session_id, agent_id, raw_text, verification=verification_request,
                       permission_mode=permission_mode)
    finally:
        conn.close()
    channel = start_telegram(engine.broker)
    terminal = terminal_channel(engine.broker)
    live = _live_status(engine) if live_status and theme.styled(sys.stderr) else None
    try:
        if not await runs.start(session_id):
            raise RuntimeError(f"Session {session_id} is not pending")
        if on_event is not None:
            async for _id, event in runs.buffers[session_id].tail(keepalive=3600):
                on_event(event)
        await runs.wait(session_id)
    finally:
        if channel:
            await channel.stop()
        if terminal:
            terminal()
        if live:
            live()
    conn = init_db()
    try:
        session = get_session(conn, session_id)
    finally:
        conn.close()
    if not session or not session.get("run_receipt"):
        raise SystemExit(f"Run failed (outcome: {session and session.get('outcome')})")
    return RunReceipt.model_validate(session["run_receipt"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one goal through Penko Perry")
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
