"""Test helpers: a scripted fake LLM and small builders."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from core.transcript import validate_transcript


def msg(content: str | None = None, tool_calls: list[tuple[str, dict]] | None = None, tokens: int = 10,
        prompt: int | None = None):
    """A scripted (non-streaming) completion response."""
    calls = [SimpleNamespace(id=f"call_{i}_{n}", type="function",
                             function=SimpleNamespace(name=n, arguments=json.dumps(a)))
             for i, (n, a) in enumerate(tool_calls or [])]
    message = SimpleNamespace(role="assistant", content=content, tool_calls=calls or None)
    usage = SimpleNamespace(total_tokens=tokens, prompt_tokens=prompt if prompt is not None else tokens // 2,
                            completion_tokens=tokens - (prompt if prompt is not None else tokens // 2))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def install_llm(monkeypatch, script: list[Any], *, validate: bool = True):
    """Patch litellm.acompletion to return `script` items in order (exceptions are raised).

    Returns the list of recorded calls (kwargs). Every call's transcript is validated.
    """
    import litellm

    calls: list[dict] = []
    queue = list(script)

    async def fake(**kwargs):
        calls.append(kwargs)
        if validate:
            problems = validate_transcript(kwargs["messages"])
            assert not problems, problems
        item = queue.pop(0) if queue else msg("(script exhausted)")
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            item = item(kwargs)
        return item

    monkeypatch.setattr(litellm, "acompletion", fake)
    return calls


def context(goal: str = "test goal", domain: str = "devops", live_state: dict | None = None):
    from datetime import datetime, timezone

    from core.primitives.context import ContextPacket
    from core.primitives.goal import Goal, TriggerSource

    return ContextPacket(
        goal=Goal(id="g1", source=TriggerSource.cli, raw_input=goal, domain=domain,
                  created_at=datetime.now(timezone.utc)),
        live_state=live_state or {})
