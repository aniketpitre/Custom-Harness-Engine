import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import litellm

from core.secrets import get_secret
from core.gateway.telegram import get_approver, request_approval
from core.primitives.policy import PolicyDecision, resolve_policy
from core.primitives.context import ContextPacket
from core.primitives.execution import ActionRecord
from core.primitives.verification import VerificationResult
from core.verification import verify_file_content
from core.snapshots import execute_with_snapshot
from domains.devops.tools.argocd_tools import argocd_app_get, argocd_app_list
from domains.devops.tools.kubectl_tools import (
    kubectl_describe_pod,
    kubectl_get_pods,
    kubectl_logs,
    kubectl_restart_pod,
)
from domains.devops.snapshots import pod_snapshot, pod_snapshot_after_restart
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

DEVOPS_READ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "kubectl_get_pods",
            "description": "List pod names and phases in a Kubernetes namespace.",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
                "required": ["namespace"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kubectl_describe_pod",
            "description": "Read the full object for a Kubernetes pod.",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "pod_name": {"type": "string"},
                },
                "required": ["namespace", "pod_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kubectl_logs",
            "description": "Read the last 200 lines of logs for a Kubernetes pod.",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "pod_name": {"type": "string"},
                    "container": {"type": "string"},
                },
                "required": ["namespace", "pod_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "argocd_app_list",
            "description": "List ArgoCD applications with sync and health status.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "argocd_app_get",
            "description": "Read details for one ArgoCD application.",
            "parameters": {
                "type": "object",
                "properties": {"app_name": {"type": "string"}},
                "required": ["app_name"],
                "additionalProperties": False,
            },
        },
    },
]

DEVOPS_ACTION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "kubectl_restart_pod",
            "description": "Restart a non-critical Kubernetes pod by deleting it so its controller recreates it. Requires human approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "pod_name": {"type": "string"},
                },
                "required": ["namespace", "pod_name"],
                "additionalProperties": False,
            },
        },
    },
]


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
    if "DevOpsRead" in allowed_tools:
        tools.extend(DEVOPS_READ_TOOLS)
    if "DevOpsWrite" in allowed_tools:
        tools.extend(DEVOPS_ACTION_TOOLS)
    events: list[Any] = []
    actions: list[ActionRecord] = []

    for _ in range(8):
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
                "actions": actions,
                "verification": _run_requested_verification(context),
            }

        messages.append(_assistant_message(message, tool_calls))
        for tool_call in tool_calls:
            arguments = json.loads(tool_call.function.arguments or "{}")
            tool_result, action = await _dispatch_tool(
                tool_call.id,
                tool_call.function.name,
                arguments,
                allowed_tools,
            )
            actions.append(action)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                }
            )

    raise RuntimeError("Grok exceeded the maximum number of tool turns (8)")


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
) -> tuple[str, ActionRecord]:
    if name in {"kubectl_get_pods", "kubectl_describe_pod", "kubectl_logs", "argocd_app_list", "argocd_app_get"}:
        if "DevOpsRead" not in allowed_tools:
            raise PermissionError(f"Tool is not allowed: {name}")
        result, policy_decision = _dispatch_devops_read_tool(name, arguments)
        return result, _action_record(policy_decision, result)
    if name == "kubectl_restart_pod":
        if "DevOpsWrite" not in allowed_tools:
            raise PermissionError(f"Tool is not allowed: {name}")
        policy_decision = resolve_policy("kubectl", "restart_pod", TOOL_RISK_TABLE)
        if policy_decision.decision == "DENY":
            raise PermissionError(policy_decision.reason)
        if policy_decision.decision == "REQUIRE_APPROVAL":
            approved = await request_approval(
                action_id=action_id,
                description=f"kubectl.restart_pod {arguments['namespace']}/{arguments['pod_name']}",
                risk_tier=policy_decision.risk_tier,
            )
            if not approved:
                raise PermissionError("Human approval denied this action")
            policy_decision = PolicyDecision.model_validate(
                policy_decision.model_copy(
                    update={"decision": "ALLOW", "approved_by": get_approver(action_id)}
                )
            )
        result, pre_state, post_state = await execute_with_snapshot(
            kubectl_restart_pod,
            pod_snapshot,
            pod_snapshot_after_restart,
            arguments["namespace"],
            arguments["pod_name"],
        )
        return result, _action_record(
            policy_decision,
            result,
            pre_state_snapshot=pre_state,
            post_state_snapshot=post_state,
            rollback_available=True,
        )
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
    result = _read_directory(arguments.get("path", "."))
    return result, _action_record(policy_decision, result)


def _dispatch_devops_read_tool(
    name: str,
    arguments: dict[str, Any],
) -> tuple[str, PolicyDecision]:
    if name == "kubectl_get_pods":
        tool, action = "kubectl", "get"
        execute = lambda: kubectl_get_pods(arguments["namespace"])
    elif name == "kubectl_describe_pod":
        tool, action = "kubectl", "describe"
        execute = lambda: kubectl_describe_pod(arguments["namespace"], arguments["pod_name"])
    elif name == "kubectl_logs":
        tool, action = "kubectl", "logs"
        execute = lambda: kubectl_logs(
            arguments["namespace"], arguments["pod_name"], arguments.get("container")
        )
    elif name == "argocd_app_list":
        tool, action = "argocd", "app_list"
        execute = argocd_app_list
    else:
        tool, action = "argocd", "app_get"
        execute = lambda: argocd_app_get(arguments["app_name"])

    policy_decision = resolve_policy(tool, action, TOOL_RISK_TABLE)
    if policy_decision.decision != "ALLOW":
        raise PermissionError(policy_decision.reason)
    return execute(), policy_decision


def _action_record(
    policy_decision: PolicyDecision,
    raw_result: str,
    *,
    pre_state_snapshot: dict[str, object] | None = None,
    post_state_snapshot: dict[str, object] | None = None,
    rollback_available: bool = False,
) -> ActionRecord:
    now = datetime.now(timezone.utc)
    return ActionRecord(
        tool=policy_decision.tool,
        action=policy_decision.action,
        policy_decision=policy_decision,
        approved_by=policy_decision.approved_by,
        started_at=now,
        finished_at=now,
        raw_result=raw_result,
        pre_state_snapshot=pre_state_snapshot,
        post_state_snapshot=post_state_snapshot,
        rollback_available=rollback_available,
    )


def _run_requested_verification(context: ContextPacket) -> VerificationResult | None:
    request = context.live_state.get("verification")
    if not isinstance(request, dict):
        return None
    path = request.get("path")
    expected_content = request.get("expected_content")
    if not isinstance(path, str) or not isinstance(expected_content, str):
        raise ValueError("Verification requires string path and expected_content")
    return verify_file_content(path, expected_content)


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
