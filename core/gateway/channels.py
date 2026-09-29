"""Approval channel wiring: Telegram when configured, an interactive terminal prompt for the CLI."""
from __future__ import annotations

import asyncio
import logging
import sys

from core.approvals import ApprovalBroker, ApprovalRequest
from core.gateway.telegram import TelegramChannel

log = logging.getLogger("harness.channels")


def start_telegram(broker: ApprovalBroker) -> TelegramChannel | None:
    """Start the single Telegram poller if the bot token and chat id are available."""
    from core.secrets import get_secret

    try:
        get_secret("telegram", "bot_token")
        get_secret("telegram", "approval_chat_id")
    except Exception:  # noqa: BLE001
        log.info("Telegram approvals not configured; use the API (/approvals) or the terminal")
        return None
    channel = TelegramChannel(broker)
    channel.start()
    return channel


def terminal_channel(broker: ApprovalBroker):
    """Prompt on the terminal (only when stdin is a TTY). Returns the disposer, or None."""
    if not sys.stdin.isatty():
        return None

    async def notify(req: ApprovalRequest) -> None:
        async def ask() -> None:
            print(f"\n[approval {req.risk_tier}] {req.tool}\n{req.rendered}\n", file=sys.stderr)
            answer = await asyncio.to_thread(input, "Approve? [y]es / [s]ession / [N]o: ")
            a = answer.strip().lower()
            broker.resolve(req.id, a in {"y", "yes", "s", "session"}, "cli:terminal",
                           "session" if a in {"s", "session"} else "once")

        asyncio.get_running_loop().create_task(ask())

    return broker.add_channel(notify)
