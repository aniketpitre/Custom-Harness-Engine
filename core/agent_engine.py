import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import litellm

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.litellm import LiteLLMInstrumentor

def init_tracing():
    try:
        otlp_endpoint = get_secret("otel", "endpoint")
        if otlp_endpoint:
            resource = Resource.create({"service.name": "harness-engine", "service.version": "0.1.0"})
            provider = TracerProvider(resource=resource)
            processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
            LiteLLMInstrumentor().instrument()
            return trace.get_tracer(__name__)
    except Exception:
        pass
    return trace.get_tracer(__name__)

tracer = init_tracing()

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


GENERIC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Find text in files using regular expressions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"}
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Find files by shell wildcard pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"}
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": "Write or overwrite a file with new content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "new_content": {"type": "string"}
                },
                "required": ["path", "new_content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch text from a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"}
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }
]

DEVOPS_ACTION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "gitops_propose_change",
            "description": "Propose a configuration change via Pull Request. Instead of mutating the cluster directly, modify the declarative manifest. Requires approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string"},
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                    "branch_name": {"type": "string"},
                    "commit_message": {"type": "string"},
                    "pr_title": {"type": "string"},
                    "pr_body": {"type": "string"}
                },
                "required": ["repo_path", "file_path", "content", "branch_name", "commit_message", "pr_title", "pr_body"],
                "additionalProperties": False,
            },
        },
    },
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
    {
        "type": "function",
        "function": {
            "name": "argocd_app_sync_production",
            "description": "Risk Tier 3 (R3) Action: Synchronize an ArgoCD application strictly in the production environment. Requires explicit human approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string"},
                },
                "required": ["app_name"],
                "additionalProperties": False,
            },
        },
    },
]


from core.primitives.agent import AgentProfile

from core.memory.store import init_db, get_and_clear_interruption
from typing import AsyncGenerator


def _spill_if_needed(result: str, session_id: str | None, tag: str) -> str:
    MAX_LEN = 100_000
    if len(result) <= MAX_LEN:
        return result
    
    workspace = Path(".workspace/spill")
    workspace.mkdir(parents=True, exist_ok=True)
    filename = f"{session_id or 'anon'}_{tag}_{int(datetime.now().timestamp())}.txt"
    filepath = workspace / filename
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(result)
        
    preview = result[:MAX_LEN // 2]
    return f"{preview}\n\n...[TRUNCATED. Full output saved to {filepath}]"

async def run_agent_generator(session_id: str | None, context: ContextPacket, allowed_tools: list[str], agent_profile: AgentProfile | None = None) -> AsyncGenerator[dict[str, Any], None]:
    with tracer.start_as_current_span("harness_agent_run") as span:
        span.set_attribute("agent.goal", context.goal.raw_input)
        span.set_attribute("agent.domain", context.goal.domain)
        span.set_attribute("agent.trigger_source", context.goal.source.value)
        model = (agent_profile.model if agent_profile and agent_profile.model else None) or os.getenv("HARNESS_MODEL") or os.getenv("GROK_MODEL") or "groq/openai/gpt-oss-120b"
        api_key = get_secret("groq", "api_key")
        sys_prompt = agent_profile.system_prompt if agent_profile else "You are an execution agent. Use available tools when they provide direct evidence for the goal."
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": sys_prompt,
            },
            {"role": "user", "content": _build_prompt(context)},
        ]
        tools = [READ_DIRECTORY_TOOL] if "Read" in allowed_tools else []
        if "DevOpsRead" in allowed_tools:
            tools.extend(DEVOPS_READ_TOOLS)
        if "DevOpsWrite" in allowed_tools:
            tools.extend(DEVOPS_ACTION_TOOLS)
        if "Generic" in allowed_tools:
            tools.extend(GENERIC_TOOLS)
        events: list[Any] = []
        actions: list[ActionRecord] = []
    
        conn = init_db() if session_id else None
        token_budget = 200_000 # default
        total_tokens = 0
        turn_count = 0
        try:
            while turn_count < 30 and total_tokens < token_budget:
                span.add_event(f"llm_completion_turn_{turn_count}", {"turn_number": turn_count})
                turn_count += 1
                
                if conn and session_id:
                    interruption = get_and_clear_interruption(conn, session_id)
                    if interruption:
                        messages.append({"role": "user", "content": f"User Interruption: {interruption}"})
                        yield {"type": "interruption_received", "content": interruption}
                
                response = await litellm.acompletion(
                    model=model,
                    api_key=api_key,
                    messages=messages,
                    tools=tools or None,
                    tool_choice="auto" if tools else None,
                )
                events.append(response)
                
                # Phase 16.2 Token tracking
                if hasattr(response, "usage") and response.usage:
                    total_tokens += getattr(response.usage, "total_tokens", 0)
                
                if total_tokens >= token_budget:
                    yield {"type": "message", "content": "Token budget exceeded."}
                    yield {
                        "type": "final_receipt",
                        "receipt": {
                            "events": events.copy(),
                            "final_text": "Execution blocked: Token budget exceeded",
                            "model_used": model,
                            "actions": actions,
                            "verification": None,
                        }
                    }
                    return

                message = response.choices[0].message
                tool_calls = getattr(message, "tool_calls", None) or []
                if not tool_calls:
                    yield {"type": "message", "content": getattr(message, "content", None) or ""}
                    yield {
                        "type": "final_receipt",
                        "receipt": {
                            "events": events.copy(),
                            "final_text": getattr(message, "content", None) or "",
                            "model_used": model,
                            "actions": actions,
                            "verification": _run_requested_verification(context),
                        }
                    }
                    return
        
                messages.append(_assistant_message(message, tool_calls))
                if getattr(message, "content", None):
                    yield {"type": "message", "content": message.content}
                    
                for tool_call in tool_calls:
                    yield {"type": "tool_call", "name": tool_call.function.name, "arguments": json.loads(tool_call.function.arguments or "{}")}
                    arguments = json.loads(tool_call.function.arguments or "{}")
                    tool_result, action = await _dispatch_tool(
                        tool_call.id,
                        tool_call.function.name,
                        arguments,
                        allowed_tools,
                        session_id,
                    )
                    actions.append(action)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result,
                        }
                    )
                    yield {"type": "tool_result", "name": tool_call.function.name, "result_summary": tool_result[:256] + ("..." if len(tool_result) > 256 else "")}
        
            span.set_status(trace.Status(trace.StatusCode.ERROR, "Max tool turns exceeded"))
            raise RuntimeError("Grok exceeded the maximum number of tool turns (8)")
        finally:
            if conn:
                conn.close()

async def run_agent(context: ContextPacket, allowed_tools: list[str], agent_profile: AgentProfile | None = None) -> dict[str, Any]:
    async for event in run_agent_generator(None, context, allowed_tools, agent_profile):
        if event["type"] == "final_receipt":
            return event["receipt"]
    raise RuntimeError("Agent terminated without producing a final receipt")


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
    session_id: str | None = None,
) -> tuple[str, ActionRecord]:
    if name in {"kubectl_get_pods", "kubectl_describe_pod", "kubectl_logs", "argocd_app_list", "argocd_app_get"}:
        if "DevOpsRead" not in allowed_tools:
            raise PermissionError(f"Tool is not allowed: {name}")
        result, policy_decision = _dispatch_devops_read_tool(name, arguments)
        result = _spill_if_needed(result, session_id, name)
        return result, _action_record(policy_decision, result)
    if name == "gitops_propose_change":
        if "DevOpsWrite" not in allowed_tools:
            raise PermissionError(f"Tool is not allowed: {name}")
        from domains.devops.git_actions import resolve_gitops_route, create_change_pr
        policy_decision = resolve_gitops_route("gitops", "propose_change")
        if policy_decision.decision == "DENY":
            raise PermissionError(policy_decision.reason)
        if policy_decision.decision == "REQUIRE_APPROVAL":
            approved = await request_approval(
                action_id=action_id,
                description=f"gitops.propose_change PR: {arguments.get('pr_title')}",
                risk_tier=policy_decision.risk_tier,
            )
            if not approved:
                raise PermissionError("Human approval denied this action")
            policy_decision = PolicyDecision.model_validate(
                policy_decision.model_copy(
                    update={"decision": "ALLOW", "approved_by": get_approver(action_id)}
                )
            )
        try:
            result = create_change_pr(
                repo_path=arguments["repo_path"],
                branch_name=arguments["branch_name"],
                file_path=arguments["file_path"],
                content=arguments["content"],
                commit_message=arguments["commit_message"],
                pr_title=arguments["pr_title"],
                pr_body=arguments["pr_body"]
            )
        except Exception as e:
            result = str(e)
            
        return result, _action_record(
            policy_decision,
            result,
        )

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

        # Phase 13.3: Automated anomaly check and rollback wrapper
        if arguments.get("namespace") == "kube-system":
            try:
                from domains.devops.snapshots import rollback_pod_restart
                rollback_pod_restart(arguments["namespace"], arguments["pod_name"], pre_state)
            except Exception as e:
                pass
            raise PermissionError("Rollback triggered automatically (Phase 13.3): action targeted protected namespace 'kube-system'")

        return result, _action_record(
            policy_decision,
            result,
            pre_state_snapshot=pre_state,
            post_state_snapshot=post_state,
            rollback_available=True,
        )

    if name == "argocd_app_sync_production":
        if "DevOpsWrite" not in allowed_tools:
            raise PermissionError(f"Tool is not allowed: {name}")
        policy_decision = resolve_policy("argocd", "app_sync_production", TOOL_RISK_TABLE)
        if policy_decision.decision == "DENY":
            raise PermissionError(policy_decision.reason)
        if policy_decision.decision == "REQUIRE_APPROVAL":
            approved = await request_approval(
                action_id=action_id,
                description=f"argocd.app_sync_production {arguments['app_name']}",
                risk_tier=policy_decision.risk_tier,
            )
            if not approved:
                raise PermissionError("Human approval denied this action")
            policy_decision = PolicyDecision.model_validate(
                policy_decision.model_copy(
                    update={"decision": "ALLOW", "approved_by": get_approver(action_id)}
                )
            )
        try:
            from domains.devops.tools.argocd_tools import argocd_app_sync
            result = argocd_app_sync(arguments["app_name"])
        except Exception as e:
            result = str(e)
        result = _spill_if_needed(result, session_id, name)
        return result, _action_record(
            policy_decision,
            result,
        )

    if name in {"grep", "glob", "edit", "web_fetch", "web_search"}:
        if "Generic" not in allowed_tools:
            raise PermissionError(f"Tool is not allowed: {name}")
        import domains.generic.tools as gt
        if name == "grep":
            result = gt.tool_grep(arguments["pattern"], arguments.get("path", "."))
        elif name == "glob":
            result = gt.tool_glob(arguments["pattern"])
        elif name == "edit":
            result = gt.tool_edit(arguments["path"], arguments["new_content"])
        elif name == "web_fetch":
            result = gt.tool_web_fetch(arguments["url"])
        elif name == "web_search":
            result = gt.tool_web_search(arguments["query"])

        # Policy is generic R1
        from core.primitives.policy import RiskTier
        policy_decision = PolicyDecision(tool="generic", action=name, decision="ALLOW", risk_tier=RiskTier.R1, reason="Generic tool dispatch.")
        result_spilled = _spill_if_needed(result, session_id, name)
        return result_spilled, _action_record(policy_decision, result_spilled)

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

    # Phase 13.1 Sandbox Policy: Deny sensitive directories globally
    deny_patterns = {".ssh", ".aws", ".kube", "secrets"}
    for part in directory.parts:
        if part in deny_patterns:
            raise PermissionError(f"Sandbox violation: Access to '{part}' is restricted.")

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
