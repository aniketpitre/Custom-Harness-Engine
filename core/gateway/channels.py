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


def terminal_enabled() -> bool:
    """A live prompt is offered when stdin is a TTY, unless HARNESS_TERMINAL_APPROVALS turns it off."""
    import os

    if os.getenv("HARNESS_TERMINAL_APPROVALS", "").strip().lower() in {"0", "false", "no", "off"}:
        return False
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, OSError):
        return False


def _pending(broker: ApprovalBroker, req_id: str) -> bool:
    return any(p["id"] == req_id for p in broker.pending())


def terminal_channel(broker: ApprovalBroker, force: bool = False):
    """Prompt on the terminal, one request at a time; the first answer from any channel
    (terminal, API, Telegram) wins and a request answered elsewhere is skipped.
    Returns the disposer, or None when there is no terminal to ask on."""
    if not force and not terminal_enabled():
        return None
    lock = asyncio.Lock()

    async def notify(req: ApprovalRequest) -> None:
        async def ask() -> None:
            async with lock:
                if not _pending(broker, req.id):        # answered elsewhere while queued
                    return
                print(f"\n[approval needed: {req.risk_tier}] {req.tool}\n{req.rendered}\n"
                      f"(you can also answer via the API or Telegram)", file=sys.stderr, flush=True)
                try:
                    answer = await asyncio.to_thread(input, "Approve? [y]es / [s]ession / [N]o: ")
                except EOFError:
                    return
                if not _pending(broker, req.id):
                    return
                a = answer.strip().lower()
                broker.resolve(req.id, a in {"y", "yes", "s", "session"}, "cli:terminal",
                               "session" if a in {"s", "session"} else "once")

        asyncio.get_running_loop().create_task(ask())

    return broker.add_channel(notify)
