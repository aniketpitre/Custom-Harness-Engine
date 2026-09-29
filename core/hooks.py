"""Hook bus. Handlers run in priority order with a per-hook time budget; failures are skipped.

Events: session_start, before_turn, pre_tool, post_tool, pre_compact, post_compact, stop,
session_end. A `pre_tool` hook may return {"decision": "deny"|"ask", "reason": ..,
"updatedInput": {...}, "additionalContext": ..}. Hooks can only tighten: "allow" is ignored.
`stop` hooks may return {"continue": "reason"} to force the agent to keep working.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from core.effects import Disposer

log = logging.getLogger("harness.hooks")
HOOK_BUDGET_SECONDS = 10.0
EVENTS = {"session_start", "before_turn", "pre_tool", "post_tool", "pre_compact",
          "post_compact", "stop", "session_end"}


@dataclass
class HookResult:
    decision: str | None = None  # deny | ask
    reason: str | None = None
    updated_input: dict | None = None
    additional_context: list[str] = field(default_factory=list)
    force_continue: str | None = None


class HookBus:
    def __init__(self) -> None:
        self._hooks: dict[str, list[tuple[int, int, Callable]]] = {e: [] for e in EVENTS}
        self._counter = 0

    def on(self, event: str, fn: Callable[[dict], Any | Awaitable[Any]], priority: int = 100) -> Disposer:
        if event not in EVENTS:
            raise ValueError(f"Unknown hook event: {event}")
        self._counter += 1
        entry = (priority, self._counter, fn)
        self._hooks[event].append(entry)
        self._hooks[event].sort(key=lambda e: (e[0], e[1]))

        def dispose() -> None:
            if entry in self._hooks[event]:
                self._hooks[event].remove(entry)

        return dispose

    def count(self, event: str | None = None) -> int:
        return sum(len(v) for k, v in self._hooks.items() if event in (None, k))

    async def emit(self, event: str, payload: dict[str, Any]) -> HookResult:
        result = HookResult()
        for _prio, _n, fn in list(self._hooks.get(event, [])):
            try:
                out = fn(dict(payload))
                if inspect.isawaitable(out):
                    out = await asyncio.wait_for(out, HOOK_BUDGET_SECONDS)
            except Exception as error:  # noqa: BLE001 - a failing hook is skipped
                log.warning("hook %s failed on %s: %s", getattr(fn, "__name__", fn), event, error)
                continue
            if not isinstance(out, dict):
                continue
            decision = out.get("decision") or out.get("permissionDecision")
            if decision == "deny" or (decision == "ask" and result.decision != "deny"):
                result.decision = decision
                result.reason = out.get("reason") or out.get("permissionDecisionReason") or result.reason
            if isinstance(out.get("updatedInput"), dict):
                result.updated_input = out["updatedInput"]
                payload = {**payload, "args": out["updatedInput"]}
            if out.get("additionalContext"):
                result.additional_context.append(str(out["additionalContext"]))
            if out.get("continue"):
                result.force_continue = str(out["continue"])
        return result


def command_hook(command: str, timeout: float = HOOK_BUDGET_SECONDS) -> Callable[[dict], Awaitable[dict | None]]:
    """Classic shell hook: JSON on stdin; exit code 2 blocks; JSON stdout is the decision."""

    def _run(payload: dict) -> dict | None:
        from core.confine import safe_env

        proc = subprocess.run(command, shell=True, input=json.dumps(payload, default=str),
                              capture_output=True, text=True, timeout=timeout, env=safe_env())
        if proc.returncode == 2:
            return {"decision": "deny", "reason": proc.stderr.strip() or "blocked by hook"}
        if proc.stdout.strip():
            try:
                return json.loads(proc.stdout)
            except ValueError:
                return None
        return None

    async def run(payload: dict) -> dict | None:
        return await asyncio.to_thread(_run, payload)

    run.__name__ = f"command_hook[{command[:30]}]"
    return run


def load_hook_config(bus: HookBus, path: str | None = None) -> list[Disposer]:
    """config/hooks.yaml: `- event: pre_tool` / `command: ./check.sh` / `priority: 50`."""
    from core.settings import find_config

    path = path or str(find_config("hooks.yaml"))
    if not os.path.isfile(path):
        return []
    import yaml

    disposers = []
    for entry in yaml.safe_load(open(path)) or []:
        disposers.append(bus.on(entry["event"], command_hook(entry["command"]), entry.get("priority", 100)))
    return disposers
