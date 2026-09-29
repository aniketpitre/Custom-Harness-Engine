"""Context compaction: token-based, cut-safe, prune-first, structured summary.

Rules (Pi / OpenClaw / Hermes): trigger near the window limit, keep ~20k recent tokens,
never cut between a tool call and its result, prune old tool outputs before paying for an
LLM summary, pin the first user message, put the summary in a user-role message, and fall
back to a deterministic summary when the summariser fails.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

Message = dict[str, Any]

SUMMARY_PROMPT = """Summarise the conversation below so the work can continue without it.
Use exactly these sections: Goal, Constraints & Preferences, Progress (Done / In Progress /
Blocked), Key Decisions (with reasons), Tool calls made (name and key arguments), Files and
resources touched, Next Steps, Critical Context. Be dense and factual; keep identifiers.

<conversation>
{transcript}
</conversation>"""


def message_tokens(m: Message) -> int:
    return len(json.dumps(m, default=str)) // 4 + 4


def estimate_tokens(messages: list[Message]) -> int:
    return sum(message_tokens(m) for m in messages)


def needs_compaction(messages: list[Message], window: int, reserve: int, last_prompt_tokens: int = 0) -> bool:
    return max(estimate_tokens(messages), last_prompt_tokens) > window - reserve


def _tool_names(messages: list[Message]) -> dict[str, str]:
    return {tc["id"]: tc["function"]["name"] for m in messages if m.get("role") == "assistant"
            for tc in m.get("tool_calls") or []}


def prune_tool_outputs(messages: list[Message], keep_recent_tokens: int,
                       min_chars: int = 800) -> dict[str, str]:
    """Stubs for large tool results outside the recent window. Returns {tool_call_id: stub}."""
    names, pruned, acc = _tool_names(messages), {}, 0
    for m in reversed(messages):
        acc += message_tokens(m)
        if acc <= keep_recent_tokens or m.get("role") != "tool":
            continue
        content = m.get("content") or ""
        if len(content) > min_chars and not content.startswith("[output of "):
            pruned[m["tool_call_id"]] = (
                f"[output of {names.get(m['tool_call_id'], 'tool')} pruned; {len(content)} chars]")
    return pruned


def apply_pruned(messages: list[Message], pruned: dict[str, str]) -> list[Message]:
    return [({**m, "content": pruned[m["tool_call_id"]]} if m.get("role") == "tool"
             and m.get("tool_call_id") in pruned else m) for m in messages]


def find_cut(messages: list[Message], keep_recent_tokens: int,
             can_cut: Callable[[int], bool] = lambda i: True) -> int | None:
    """Index of the first message to keep. Never a tool message; message 0 (system) is fixed."""
    acc = 0
    for i in range(len(messages) - 1, 0, -1):
        acc += message_tokens(messages[i])
        if acc >= keep_recent_tokens and messages[i].get("role") in {"user", "assistant"} and can_cut(i):
            return i
    return None


def serialize(messages: list[Message], tool_result_chars: int = 2000) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "?")
        if role == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                lines.append(f"assistant called {tc['function']['name']}({tc['function'].get('arguments', '')[:500]})")
        content = m.get("content")
        if isinstance(content, str) and content:
            if role == "tool":
                content = content[:tool_result_chars] + ("...[truncated]" if len(content) > tool_result_chars else "")
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def deterministic_summary(messages: list[Message]) -> str:
    users = [m["content"][:300] for m in messages if m.get("role") == "user" and isinstance(m.get("content"), str)]
    calls = [f"{tc['function']['name']}({tc['function'].get('arguments', '')[:120]})"
             for m in messages if m.get("role") == "assistant" for tc in m.get("tool_calls") or []]
    return ("(automatic summary; the summariser was unavailable)\nUser requests:\n- " +
            "\n- ".join(users[-5:] or ["(none)"]) + "\nTool calls so far:\n- " + "\n- ".join(calls[-30:] or ["(none)"]))


@dataclass
class CompactionPlan:
    first_kept_index: int
    summary: str


async def plan_compaction(
    messages: list[Message],
    keep_recent_tokens: int,
    summarize: Callable[[str], Awaitable[str]],
    can_cut: Callable[[int], bool] = lambda i: True,
    pinned_indexes: tuple[int, ...] = (1,),
) -> CompactionPlan | None:
    cut = find_cut(messages, keep_recent_tokens, can_cut)
    if cut is None or cut <= max(pinned_indexes, default=0) + 0:
        # not enough history outside the recent window: fall back to the last user message
        users = [i for i in range(len(messages) - 1, 1, -1)
                 if messages[i].get("role") == "user" and can_cut(i)]
        cut = users[0] if users else None
    if cut is None or cut <= 1:
        return None
    span = [m for i, m in enumerate(messages[:cut]) if i not in pinned_indexes and i != 0]
    if not span:
        return None
    try:
        summary = await summarize(SUMMARY_PROMPT.format(transcript=serialize(span)))
        summary = (summary or "").strip() or deterministic_summary(span)
    except Exception:  # noqa: BLE001
        summary = deterministic_summary(span)
    return CompactionPlan(cut, summary)
