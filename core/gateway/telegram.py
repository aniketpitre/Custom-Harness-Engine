import asyncio

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler

from core.secrets import get_secret


_pending_approvals: dict[str, asyncio.Future[bool]] = {}
_approvers: dict[str, str] = {}


async def request_approval(action_id: str, description: str, risk_tier: str) -> bool:
    bot = Bot(token=get_secret("telegram", "bot_token"))
    chat_id = get_secret("telegram", "approval_chat_id")
    existing_updates = await bot.get_updates(timeout=0)
    offset = max((update.update_id for update in existing_updates), default=-1) + 1
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Approve", callback_data=f"approve:{action_id}"),
                InlineKeyboardButton("Deny", callback_data=f"deny:{action_id}"),
            ]
        ]
    )
    await bot.send_message(
        chat_id=chat_id,
        text=f"Risk tier {risk_tier}\n{description}\n\nApprove this action?",
        reply_markup=keyboard,
    )
    while True:
        updates = await bot.get_updates(
            offset=offset,
            timeout=20,
            allowed_updates=["callback_query"],
        )
        for update in updates:
            offset = update.update_id + 1
            callback_query = update.callback_query
            if callback_query is None or callback_query.data != f"approve:{action_id}" and callback_query.data != f"deny:{action_id}":
                continue
            approved = callback_query.data == f"approve:{action_id}"
            _approvers[action_id] = str(callback_query.from_user.id)
            await callback_query.answer()
            await callback_query.edit_message_text("Approved." if approved else "Denied.")
            return approved


def get_approver(action_id: str) -> str | None:
    return _approvers.pop(action_id, None)


async def handle_callback(update, context) -> None:
    callback_query = update.callback_query
    decision, action_id = callback_query.data.split(":", maxsplit=1)
    future = _pending_approvals.get(action_id)
    if future is not None and not future.done():
        _approvers[action_id] = str(callback_query.from_user.id)
        future.set_result(decision == "approve")
    await callback_query.answer()
    await callback_query.edit_message_text(
        "Approved." if decision == "approve" else "Denied."
    )


def build_approval_application() -> Application:
    application = Application.builder().token(get_secret("telegram", "bot_token")).build()
    application.add_handler(CallbackQueryHandler(handle_callback))
    return application


def run_approval_bot() -> None:
    build_approval_application().run_polling()