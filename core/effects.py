"""Revertible effects: every registration returns a disposer; disposers run LIFO."""
from __future__ import annotations

import inspect
import logging
from typing import Any, Callable

log = logging.getLogger("harness.effects")

Disposer = Callable[[], Any]


class EffectStack:
    def __init__(self) -> None:
        self._stack: list[tuple[str, Disposer]] = []
        self.ran: list[str] = []

    def __len__(self) -> int:
        return len(self._stack)

    def push(self, invoker: str, disposer: Disposer) -> Disposer:
        """Track an effect. Returns a function that disposes it early (at most once)."""
        entry = (invoker, disposer)
        self._stack.append(entry)

        async def dispose_now() -> None:
            if entry in self._stack:
                self._stack.remove(entry)
                await _run(invoker, disposer, self.ran)

        return dispose_now

    async def rollback(self) -> list[str]:
        while self._stack:
            invoker, disposer = self._stack.pop()
            await _run(invoker, disposer, self.ran)
        return self.ran


async def _run(invoker: str, disposer: Disposer, ran: list[str]) -> None:
    try:
        result = disposer()
        if inspect.isawaitable(result):
            await result
        ran.append(invoker)
    except Exception as error:  # noqa: BLE001 - cleanup must never raise
        log.warning("error rolling back effect from %s: %s", invoker, error)


class EffectScope:
    """`async with EffectScope() as stack:` - disposes everything pushed, even on error."""

    def __init__(self) -> None:
        self.stack = EffectStack()

    async def __aenter__(self) -> EffectStack:
        return self.stack

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stack.rollback()
