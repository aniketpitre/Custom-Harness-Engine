"""Transcript validity: every assistant tool call has exactly one following tool message."""
from __future__ import annotations

from typing import Any

Message = dict[str, Any]


def validate_transcript(messages: list[Message]) -> list[str]:
    """Return a list of problems (empty means the transcript is valid for OpenAI/Anthropic APIs)."""
    problems: list[str] = []
    pending: dict[str, int] = {}
    for i, m in enumerate(messages):
        role = m.get("role")
        if pending and role != "tool":
            problems.append(f"message {i}: tool calls {sorted(pending)} have no results")
            pending = {}
        if role == "assistant":
            for tc in m.get("tool_calls") or []:
                pending[tc["id"]] = i
        elif role == "tool":
            tcid = m.get("tool_call_id")
            if tcid not in pending:
                problems.append(f"message {i}: orphaned tool result {tcid!r}")
            else:
                del pending[tcid]
        if role == "system" and i > 0:
            problems.append(f"message {i}: system message after the first message")
    if pending:
        problems.append(f"tool calls {sorted(pending)} have no results")
    return problems


def repair_transcript(messages: list[Message]) -> list[Message]:
    """Fill in results for interrupted tool calls and drop orphaned tool results."""
    out: list[Message] = []
    pending: list[str] = []

    def flush() -> None:
        for tcid in pending:
            out.append({"role": "tool", "tool_call_id": tcid,
                        "content": "Interrupted: this tool call did not complete."})
        pending.clear()

    for m in messages:
        role = m.get("role")
        if pending and role != "tool":
            flush()
        if role == "tool":
            if m.get("tool_call_id") in pending:
                pending.remove(m["tool_call_id"])
                out.append(m)
            continue
        out.append(m)
        if role == "assistant":
            pending.extend(tc["id"] for tc in m.get("tool_calls") or [])
    flush()
    return out
