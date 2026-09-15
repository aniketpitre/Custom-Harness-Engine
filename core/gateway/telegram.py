import asyncio

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from core.secrets import get_secret


_pending_approvals: dict[str, asyncio.Future[bool]] = {}
_approvers: dict[str, str] = {}


async def request_approval(action_id: str, description: str, risk_tier: str) -> bool:
    bot = Bot(token=get_secret("telegram", "bot_token"))
    chat_id = get_secret("telegram", "approval_chat_id")
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
    future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
    _pending_approvals[action_id] = future
    try:
        return await future
    finally:
        _pending_approvals.pop(action_id, None)


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