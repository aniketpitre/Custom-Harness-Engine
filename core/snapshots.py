import inspect
from collections.abc import Callable
from typing import Any


async def execute_with_snapshot(
    tool_fn: Callable[..., Any],
    pre_state_fn: Callable[..., Any],
    post_state_fn: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> tuple[Any, Any, Any]:
    pre_state = pre_state_fn(*args, **kwargs)
    if inspect.isawaitable(pre_state):
        pre_state = await pre_state

    result = tool_fn(*args, **kwargs)
    if inspect.isawaitable(result):
        result = await result

    post_state = post_state_fn(*args, **kwargs)
    if inspect.isawaitable(post_state):
        post_state = await post_state
    return result, pre_state, post_state
