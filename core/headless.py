"""Headless contract for scripts and CI: a stable result object, JSONL event stream and exit codes.

`penko run --output-format`:
  receipt      the full RunReceipt, pretty JSON (default; unchanged from earlier releases)
  json         one compact result object (RESULT_SCHEMA_VERSION), no transcript
  stream-json  one JSON object per line as the run progresses, ending with {"type": "result", ...}
  text         the agent's final answer only

Exit codes (stable):
  0  success: the run completed and its verification (if any) passed
  1  failure: error, crash, loop guard, cancellation, or verification failed
  2  usage or configuration error (unknown agent, bad flag, no goal)
  3  a limit stopped the run: token/cost budget, turn limit, time limit
"""
from __future__ import annotations

import json
from typing import Any

RESULT_SCHEMA_VERSION = 1
EXIT_OK, EXIT_FAILURE, EXIT_USAGE, EXIT_LIMIT = 0, 1, 2, 3
LIMIT_OUTCOMES = {"budget_exhausted", "turn_limit", "time_limit"}


def exit_code(status: str | None, outcome: str | None) -> int:
    if status == "success":
        return EXIT_OK
    if outcome in LIMIT_OUTCOMES:
        return EXIT_LIMIT
    return EXIT_FAILURE


def result(receipt) -> dict[str, Any]:
    """The stable, transcript-free summary of a run (`--output-format json`)."""
    r = json.loads(receipt.model_dump_json()) if hasattr(receipt, "model_dump_json") else dict(receipt)
    usage = r.get("usage") or {}
    started, finished = r.get("started_at"), r.get("finished_at")
    duration = None
    if started and finished:
        from datetime import datetime

        duration = round((datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds(), 3)
    actions = [{"tool": a["tool"], "action": a["action"],
                "decision": a["policy_decision"]["decision"], "risk_tier": a["policy_decision"]["risk_tier"],
                "approved_by": a.get("approved_by"), "is_error": a.get("is_error", False)}
               for a in r.get("actions") or []]
    verification = r.get("verification")
    return {
        "type": "result",
        "schema_version": RESULT_SCHEMA_VERSION,
        "session_id": r["run_id"],
        "agent_id": r["agent_id"],
        "status": r["status"],
        "outcome": r.get("outcome"),
        "verified": r.get("verified"),
        "exit_code": exit_code(r["status"], r.get("outcome")),
        "final_text": r.get("final_text", ""),
        "model": r.get("model_used"),
        "usage": {"input_tokens": usage.get("prompt", 0), "output_tokens": usage.get("completion", 0),
                  "turns": usage.get("turns", 0), "cost_usd": usage.get("cost_usd"),
                  "unpriced_calls": usage.get("unpriced_calls", 0)},
        "actions": actions,
        "verification": None if not verification else {"passed": verification.get("passed"),
                                                        "reason": verification.get("reason")},
        "chain_head": r.get("chain_head"),
        "duration_seconds": duration,
    }


def stream_line(event: dict) -> str | None:
    """One JSONL line for a live event, or None for events that are noise in a log."""
    if event.get("type") in {"keepalive", "final_receipt"}:
        return None
    return json.dumps(event, default=str, separators=(",", ":"))


def summary_markdown(res: dict) -> str:
    """A short Markdown report, e.g. for $GITHUB_STEP_SUMMARY."""
    from core.cost import fmt

    icon = {"success": "✅", "failure": "❌"}.get(res["status"], "⚠️")
    u = res["usage"]
    lines = [f"### {icon} Harness run: {res['status']} ({res['outcome']})", "",
             "| | |", "|---|---|",
             f"| Agent | `{res['agent_id']}` |", f"| Model | `{res['model']}` |",
             f"| Tokens | {u['input_tokens'] + u['output_tokens']:,} ({u['turns']} turns) |",
             f"| Cost | {fmt(u['cost_usd'])}" + (f" + {u['unpriced_calls']} unpriced call(s)" if u["unpriced_calls"] else "")
             + " |",
             f"| Verified | {res['verified']} |", f"| Session | `{res['session_id']}` |", ""]
    if res["actions"]:
        lines += ["<details><summary>Actions ({})</summary>\n".format(len(res["actions"])),
                  "| Tool | Action | Decision | Tier | Error |", "|---|---|---|---|---|"]
        lines += [f"| {a['tool']} | {a['action']} | {a['decision']} | {a['risk_tier']} | {'yes' if a['is_error'] else ''} |"
                  for a in res["actions"]]
        lines += ["", "</details>", ""]
    lines += ["#### Answer", "", res["final_text"] or "_(empty)_", ""]
    return "\n".join(lines)
