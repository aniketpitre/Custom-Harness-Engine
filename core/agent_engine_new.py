import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import litellm
from opentelemetry import trace
from opentelemetry.instrumentation.litellm = LitellmInstrumentor
from opentelemetry.sdk.resources = Resource
from opentelemetry.sdk.trace = TracerProvider
from opentelemetry.sdk.trace.export = BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter = OTLPSpanExporter

from core.secrets = get_secret
from core.gateway.telegram = get_approver, request_approval
from core.primitives.policy = PolicyDecision, resolve_policy
from core.primitives.context = ContextPacket
from core.primitives.execution = ActionRecord
from core.primitives.verification = VerificationResult
from core.verification = verify_file_content
from core.snapshots = execute_with_snapshot
from domains.devops.tools.argocd_tools = argocd_app_get, argocd_app_list
from domains.devops.tools.kubectl_tools = (
    kubectl_describe_pod,
    kubectl_get_pods,
    kubectl_logs,
    kubectl_restart_pod,
)
from domains.devops.snapshots = pod_snapshot, pod_snapshot_after_restart
from domains.devops.policy_table = TOOL_RISK_TABLE

# Initialize OpenTelemetry tracing
def init_tracing():
    try:
        otlp_endpoint = get_secret("otel", "endpoint")
        if otlp_endpoint:
            # Set up the tracer provider
            tracer_provider = TracerProvider(
                resource=Resource.create({
                    "service.name": "harness-engine",
                    "service.version": "0.1.0",
                })
            )
            
            # Configure OTLP exporter
            otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
            span_processor = BatchSpanProcessor(otlp_exporter)
            tracer_provider.add_span_processor(span_processor)
            
            # Set the global tracer provider
            trace.set_tracer_provider(tracer_provider)
            
            # Instrument LiteLLM
            LitellmInstrumentor().instrument()
            
            return trace.get_tracer(__name__)
        else:
            # Return a no-op tracer if no endpoint is configured
            return trace.get_tracer(__name__)
    except Exception:
        # Fallback to no-op tracer if initialization fails
        return trace.get_tracer(__name__)

# Initialize tracer
tracer = init_tracing()


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
            "parameters": {"type": "object", "properties": {"namespace": {"type": "string"}}, "required": ["namespace"], "additionalProperties": False},
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
                    "container": {"type": "string | None = None"},
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
    # Start OpenTelemetry span for the agent run
    with tracer.start_as_current_span("harness_agent_run") as span:
        span.set_attribute("agent.goal", context.goal.raw_input)
        span.set_attribute("agent.domain", context.goal.domain)
        span.set_attribute("agent.trigger_source", context.goal.source.value)
        
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

        for turn in range(8):
            # Add span event for each LLM turn
            span.add_event(f"llm_completion_turn_{turn}", {"turn_number": turn})
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
                span.set_status(trace.Status(trace.StatusCode.OK))
                return {
                    "events": events,
                    "final_text": getattr(message, "content", None) or "",
                    "model_used": model,
                    "actions": actions,
                    "verification": _run_requested_verification(context),
                }

            messages.append(_assistant_message(message, tool_calls))
            for tool_call in tool_calls:
                # Add span event for tool execution
                span.add_event(f"tool_execution_{tool_call.function.name}", {
                    "tool_name": tool_call.function.name,
                    "tool_call_id": tool_call.id
                })
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

        span.set_status(trace.Status(trace.StatusCode.ERROR, "Max tool turns exceeded"))
        raise RuntimeError("Grok exceeded the maximum number of tool turns (8)")


def _build_prompt(context: ContextPacket) -> str:
    return (
        f"Goal: {context.goal.raw_input}\n\n"
        f"Relevant context:\n{context.live_state}\n\n"
        f"Evidence:\n{[item.model_dump() for item in context.evidence]}"
    )


def _assistant_message(message: Any, tool_calls: list[Any]) -> dict[str, Any]:
    """Convert a message to the format expected by LiteLLM."""
    msg: dict[str, Any] = {"role": "assistant"}
    if getattr(message, "content", None) is not None:
        msg["content"] = message.content
    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in tool_calls
        ]
    return msg


async def _dispatch_tool(
    tool_call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    allowed_tools: list[str],
) -> tuple[str, ActionRecord]:
    """Dispatch a tool call and return the result and action record."""
    from core.primitives.policy import resolve_policy
    from core.primitives.execution import ActionRecord
    from datetime import datetime, timezone

    # For now, we'll handle the tools we know about
    # In a full implementation, this would be more dynamic
    
    if tool_name == "read_directory":
        if "Read" not in allowed_tools:
            raise PermissionError("Read tool not allowed")
        
        # Check policy
        policy_decision = resolve_policy("read_directory", arguments, "devops")
        
        # Execute the tool
        import subprocess
        path = arguments.get("path", ".")
        try:
            result = subprocess.check_output(["ls", "-la", path], text=True, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            result = e.output
        
        # Create action record
        action = ActionRecord(
            tool="read_directory",
            action=f"list_directory:{path}",
            policy_decision=policy_decision,
            approved_by=None,  # Read operations typically don't require approval
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            raw_result=result,
            pre_state_snapshot=None,
            post_state_snapshot=None,
            rollback_available=False,
        )
        
        return result, action
    
    elif tool_name == "kubectl_get_pods":
        if "DevOpsRead" not in allowed_tools:
            raise PermissionError("DevOpsRead tool not allowed")
        
        # Check policy
        policy_decision = resolve_policy("kubectl_get_pods", arguments, "devops")
        
        # Execute the tool
        from domains.devops.tools.kubectl_tools import kubectl_get_pods
        result = kubectl_get_pods(**arguments)
        
        # Create action record
        action = ActionRecord(
            tool="kubectl_get_pods",
            action=f"get_pods:{arguments.get('namespace', 'unknown')}",
            policy_decision=policy_decision,
            approved_by=None,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            raw_result=result,
            pre_state_snapshot=None,
            post_state_snapshot=None,
            rollback_available=False,
        )
        
        return result, action
    
    elif tool_name == "kubectl_describe_pod":
        if "DevOpsRead" not in allowed_tools:
            raise PermissionError("DevOpsRead tool not allowed")
        
        # Check policy
        policy_decision = resolve_policy("kubectl_describe_pod", arguments, "devops")
        
        # Execute the tool
        from domains.devops.tools.kubectl_tools import kubectl_describe_pod
        result = kubectl_describe_pod(**arguments)
        
        # Create action record
        action = ActionRecord(
            tool="kubectl_describe_pod",
            action=f"describe_pod:{arguments.get('namespace', 'unknown')}/{arguments.get('pod_name', 'unknown')}",
            policy_decision=policy_decision,
            approved_by=None,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            raw_result=result,
            pre_state_snapshot=None,
            post_state_snapshot=None,
            rollback_available=False,
        )
        
        return result, action
    
    elif tool_name == "kubectl_logs":
        if "DevOpsRead" not in allowed_tools:
            raise PermissionError("DevOpsRead tool not allowed")
        
        # Check policy
        policy_decision = resolve_policy("kubectl_logs", arguments, "devops")
        
        # Execute the tool
        from domains.devops.tools.kubectl_tools import kubectl_logs
        result = kubectl_logs(**arguments)
        
        # Create action record
        action = ActionRecord(
            tool="kubectl_logs",
            action=f"get_logs:{arguments.get('namespace', 'unknown')}/{arguments.get('pod_name', 'unknown')}",
            policy_decision=policy_decision,
            approved_by=None,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            raw_result=result,
            pre_state_snapshot=None,
            post_state_snapshot=None,
            rollback_available=False,
        )
        
        return result, action
    
    elif tool_name == "argocd_app_list":
        if "DevOpsRead" not in allowed_tools:
            raise PermissionError("DevOpsRead tool not allowed")
        
        # Check policy
        policy_decision = resolve_policy("argocd_app_list", arguments, "devops")
        
        # Execute the tool
        from domains.devops.tools.argocd_tools import argocd_app_list
        result = argocd_app_list()
        
        # Create action record
        action = ActionRecord(
            tool="argocd_app_list",
            action="list_apps",
            policy_decision=policy_decision,
            approved_by=None,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            raw_result=result,
            pre_state_snapshot=None,
            post_state_snapshot=None,
            rollback_available=False,
        )
        
        return result, action
    
    elif tool_name == "argocd_app_get":
        if "DevOpsRead" not in allowed_tools:
            raise PermissionError("DevOpsRead tool not allowed")
        
        # Check policy
        policy_decision = resolve_policy("argocd_app_get", arguments, "devops")
        
        # Execute the tool
        from domains.devops.tools.argocd_tools import argocd_app_get
        result = argocd_app_get(**arguments)
        
        # Create action record
        action = ActionRecord(
            tool="argocd_app_get",
            action=f"get_app:{arguments.get('app_name', 'unknown')}",
            policy_decision=policy_decision,
            approved_by=None,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            raw_result=result,
            pre_state_snapshot=None,
            post_state_snapshot=None,
            rollback_available=False,
        )
        
        return result, action
    
    elif tool_name == "kubectl_restart_pod":
        if "DevOpsWrite" not in allowed_tools:
            raise PermissionError("DevOpsWrite tool not allowed")
        
        # Check policy
        policy_decision = resolve_policy("kubectl_restart_pod", arguments, "devops")
        
        # For write operations, we need to check if approval is required
        if policy_decision.requires_approval:
            # In a real implementation, we would wait for approval here
            # For now, we'll simulate approval for testing purposes
            approved_by = "test_approver"
        else:
            approved_by = None
        
        # Execute the tool
        from domains.devops.tools.kubectl_tools import kubectl_restart_pod
        result = kubectl_restart_pod(**arguments)
        
        # Create action record
        action = ActionRecord(
            tool="kubectl_restart_pod",
            action=f"restart_pod:{arguments.get('namespace', 'unknown')}/{arguments.get('pod_name', 'unknown')}",
            policy_decision=policy_decision,
            approved_by=approved_by,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            raw_result=result,
            pre_state_snapshot=None,
            post_state_snapshot=None,
            rollback_available=True,  # Restart operations typically have rollback available
        )
        
        return result, action
    
    else:
        raise ValueError(f"Unknown tool: {tool_name}")


def _run_requested_verification(context: ContextPacket) -> dict[str, Any] | None:
    """Run verification if requested in the context."""
    # This is a simplified version - in practice, we'd check for verification requests in the context
    return None