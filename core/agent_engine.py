import json
import os
from pathlib import Path
from typing import Any

import litellm

from core.secrets import get_secret
from core.gateway.telegram import get_approver, request_approval
from core.primitives.policy import PolicyDecision, resolve_policy
from core.primitives.context import ContextPacket
from domains.devops.policy_table import TOOL_RISK_TABLE


READ_DIRECTORY_TOOL = {
    "type": "function",
    "function": {
        "name": "read_directory",
        "description": "List entries in a directory below the current working directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "A relative directory path. Use '.' for the current directory.",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}


async def run_agent(context: ContextPacket, allowed_tools: list[str]) -> dict[str, Any]:
    model = os.getenv("HARNESS_MODEL") or os.getenv("GROK_MODEL") or "groq/openai/gpt-oss-120b"
    api_key = get_secret("groq", "api_key")
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": "You are an execution agent. Use available tools when they provide direct evidence for the goal.",
        },
        {"role": "user", "content": _build_prompt(context)},
    ]
    tools = [READ_DIRECTORY_TOOL] if "Read" in allowed_tools else []
    events: list[Any] = []

    for _ in range(4):
        response = await litellm.acompletion(
            model=model,
            api_key=api_key,
            messages=messages,
            tools=tools or None,
            tool_choice="auto" if tools else None,
        )
        events.append(response)
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            return {
                "events": events,
                "final_text": getattr(message, "content", None) or "",
                "model_used": model,
            }

        messages.append(_assistant_message(message, tool_calls))
        for tool_call in tool_calls:
            arguments = json.loads(tool_call.function.arguments or "{}")
            tool_result = await _dispatch_tool(tool_call.id, tool_call.function.name, arguments, allowed_tools)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                }
            )

    raise RuntimeError("Grok exceeded the maximum number of tool turns")


def _build_prompt(context: ContextPacket) -> str:
    return (
        f"Goal: {context.goal.raw_input}\n\n"
        f"Relevant context:\n{context.live_state}\n\n"
        f"Evidence:\n{[item.model_dump() for item in context.evidence]}"
    )


def _assistant_message(message: Any, tool_calls: list[Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": getattr(message, "content", None),
        "tool_calls": [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in tool_calls
        ],
    }


async def _dispatch_tool(
    action_id: str,
    name: str,
    arguments: dict[str, Any],
    allowed_tools: list[str],
) -> str:
    if name != "read_directory" or "Read" not in allowed_tools:
        raise PermissionError(f"Tool is not allowed: {name}")
    policy_decision = resolve_policy("filesystem", name, TOOL_RISK_TABLE)
    if policy_decision.decision == "DENY":
        raise PermissionError(policy_decision.reason)
    if policy_decision.decision == "REQUIRE_APPROVAL":
        approved = await request_approval(
            action_id=action_id,
            description=f"{policy_decision.tool}.{policy_decision.action}",
            risk_tier=policy_decision.risk_tier,
        )
        if not approved:
            raise PermissionError("Human approval denied this action")
        approver = get_approver(action_id)
        policy_decision = PolicyDecision.model_validate(
            policy_decision.model_copy(update={"decision": "ALLOW", "approved_by": approver})
        )
    return _read_directory(arguments.get("path", "."))


def _read_directory(path: str) -> str:
    working_directory = Path.cwd().resolve()
    directory = (working_directory / path).resolve()
    try:
        directory.relative_to(working_directory)
    except ValueError as error:
        raise PermissionError("Read tool cannot access paths outside the working directory") from error
    if not directory.is_dir():
        raise NotADirectoryError(path)

    entries = []
    for entry in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
        prefix = "[dir]" if entry.is_dir() else "[file]"
        entries.append(f"{prefix} {entry.name}")
    return "\n".join(entries) or "<empty directory>"
