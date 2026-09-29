"""memory (add/replace/remove/list with size limits and scanning) and session_search tools."""
from __future__ import annotations

import uuid

from core.eventlog import search_events
from core.memory.store import add_memory, init_db
from core.plugins.base import Plugin, PluginContext
from core.primitives.policy import RiskTier
from core.safety import scan_text
from core.settings import settings
from core.tools import ToolSpec


def _entries(conn, domain: str) -> list:
    return conn.execute(
        "SELECT id, content FROM memory_entries WHERE domain = ? AND authorship = 'agent-created' "
        "AND superseded_by IS NULL ORDER BY created_at", (domain,)).fetchall()


def memory_tool(args: dict, ctx) -> str:
    st = settings()
    conn = init_db(st.db_path)
    try:
        domain, action = ctx.domain, args["action"]
        rows = _entries(conn, domain)
        if action == "list":
            used = sum(len(r["content"]) for r in rows)
            body = "\n".join(f"- {r['content']}" for r in rows) or "(no agent-created memory)"
            return f"{body}\n[{used}/{st.memory_limit_chars} chars used]"
        content = (args.get("content") or "").strip()
        if action in {"add", "replace"}:
            if not content:
                raise ValueError("content is required")
            findings = scan_text(content, allow=("external-url",))
            if findings:
                raise ValueError(f"Rejected by content scan: {', '.join(findings)}")
            if any(r["content"].strip().lower() == content.lower() for r in rows):
                raise ValueError("Duplicate memory entry")
        if action == "add":
            used = sum(len(r["content"]) for r in rows)
            if used + len(content) > st.memory_limit_chars:
                raise ValueError(f"Memory is full ({used}/{st.memory_limit_chars} chars). Consolidate with "
                                 "replace/remove first.")
            add_memory(conn, str(uuid.uuid4()), content, "agent-created",
                       "external-fetched" if ctx.tainted else "tool-observed", domain)
            return "Memory added."
        needle = (args.get("old_text") or "").strip()
        matches = [r for r in rows if needle and needle.lower() in r["content"].lower()]
        if len(matches) != 1:
            raise ValueError(f"old_text must match exactly one entry (matched {len(matches)})")
        if action == "remove":
            conn.execute("DELETE FROM memory_entries WHERE id = ?", (matches[0]["id"],))
            conn.commit()
            return "Memory removed."
        if action == "replace":
            used = sum(len(r["content"]) for r in rows) - len(matches[0]["content"])
            if used + len(content) > st.memory_limit_chars:
                raise ValueError("Replacement would exceed the memory limit")
            conn.execute("UPDATE memory_entries SET content = ? WHERE id = ?", (content, matches[0]["id"]))
            conn.commit()
            return "Memory replaced."
        raise ValueError(f"Unknown action: {action}")
    finally:
        conn.close()


def session_search(args: dict, ctx) -> str:
    conn = init_db(settings().db_path)
    try:
        hits = search_events(conn, args["query"], int(args.get("limit", 8)))
    finally:
        conn.close()
    return "\n".join(f"[{h['session_id'][:8]} #{h['seq']} {h['type']}] {h['snippet']}" for h in hits) \
        or "No matching past sessions."


class MemoryPlugin(Plugin):
    name = "memory"

    def register(self, ctx: PluginContext) -> None:
        ctx.tool(ToolSpec(
            "memory", "Curated long-term memory (small, size-limited). Save durable facts only.",
            {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["add", "replace", "remove", "list"]},
                "content": {"type": "string"}, "old_text": {"type": "string",
                                                            "description": "Substring identifying the entry."}},
             "required": ["action"], "additionalProperties": False},
            memory_tool, capability="Memory", risk=RiskTier.R1, policy_tool="memory", policy_action="write"))
        ctx.tool(ToolSpec(
            "session_search", "Full-text search over past session transcripts.",
            {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
             "required": ["query"], "additionalProperties": False},
            session_search, capability="Read", risk=RiskTier.R0, read_only=True, parallel_safe=True,
            untrusted=True, policy_tool="memory", policy_action="search"))
