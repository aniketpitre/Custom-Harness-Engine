"""Telegram approval channel: one long-lived poller, callbacks routed to the broker."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from core.approvals import ApprovalBroker, ApprovalRequest, get_broker
from core.secrets import get_secret

log = logging.getLogger("harness.telegram")


class TelegramChannel:
    def __init__(self, broker: ApprovalBroker | None = None, bot_factory: Callable[[], Any] | None = None,
                 chat_id: str | None = None) -> None:
        self.broker = broker or get_broker()
        self._bot_factory = bot_factory
        self._bot = None
        self._chat_id = chat_id
        self._task: asyncio.Task | None = None
        self._offset = 0

    def bot(self):
        if self._bot is None:
            if self._bot_factory:
                self._bot = self._bot_factory()
            else:
                from telegram import Bot

                self._bot = Bot(token=get_secret("telegram", "bot_token"))
        return self._bot

    def chat_id(self) -> str:
        if self._chat_id is None:
            self._chat_id = str(get_secret("telegram", "approval_chat_id"))
        return self._chat_id

    async def notify(self, req: ApprovalRequest) -> None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Approve once", callback_data=f"approve:{req.id}"),
            InlineKeyboardButton("Approve (session)", callback_data=f"session:{req.id}"),
            InlineKeyboardButton("Deny", callback_data=f"deny:{req.id}"),
        ]])
        text = f"Risk tier {req.risk_tier} | {req.tool}\n{req.rendered[:3000]}\n\nargs sha256: {req.args_hash[:12]}"
        await self.bot().send_message(chat_id=self.chat_id(), text=text, reply_markup=keyboard)

    def handle_callback(self, data: str, user_id: Any, chat_id: Any) -> tuple[bool, str]:
        """Route one button press. Returns (accepted, message)."""
        action, _, req_id = (data or "").partition(":")
        if action not in {"approve", "session", "deny"}:
            return False, "Unknown action"
        if str(chat_id) != self.chat_id():
            return False, "Not the approval chat"
        approver = f"telegram:{user_id}"
        ok = self.broker.resolve(req_id, action != "deny", approver,
                                 "session" if action == "session" else "once")
        return ok, ("Approved." if action != "deny" else "Denied.") if ok else "Not authorised or already resolved."

    async def _poll(self) -> None:
        bot = self.bot()
        try:  # skip stale button presses from before we started
            stale = await bot.get_updates(timeout=0)
            self._offset = max((u.update_id for u in stale), default=-1) + 1
        except Exception:  # noqa: BLE001
            pass
        while True:
            try:
                updates = await bot.get_updates(offset=self._offset, timeout=20,
                                                allowed_updates=["callback_query"])
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                log.warning("telegram poll failed: %s", error)
                await asyncio.sleep(5)
                continue
            for update in updates:
                self._offset = update.update_id + 1
                cq = update.callback_query
                if cq is None:
                    continue
                ok, msg = self.handle_callback(cq.data, cq.from_user.id,
                                               cq.message.chat.id if cq.message else None)
                try:
                    await cq.answer(msg)
                    if ok:
                        await cq.edit_message_text(msg)
                except Exception:  # noqa: BLE001
                    pass

    def start(self) -> None:
        """Register the notification channel and start the single poller task."""
        self.broker.add_channel(self.notify)
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._poll())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None


async def request_approval(action_id: str, description: str, risk_tier: str) -> bool:
    """Legacy helper (skill promotion etc.): ask through the default broker."""
    from core.approvals import args_hash

    result = await get_broker().request(ApprovalRequest(
        tool=str(risk_tier), args_hash=args_hash(action_id, {"d": description}),
        rendered=description, risk_tier=str(risk_tier), id=str(action_id)))
    return result.approved
