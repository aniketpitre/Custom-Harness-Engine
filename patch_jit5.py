import re

with open("core/agent_engine.py", "r") as f:
    code = f.read()

# Dispatch dynamic tools and write_and_register_tool
dynamic_dispatch_code = """
    if name == "write_and_register_tool":
        from core.primitives.policy import PolicyDecision, RiskTier
        policy_decision = PolicyDecision(tool="harness", action="write_and_register_tool", decision="REQUIRE_APPROVAL", risk_tier=RiskTier.R3, reason="Self-modification requires explicit human approval")
        approved = await request_approval(
            action_id=action_id,
            description=f"Self Modify: Write Tool '{arguments.get('tool_name')}'",
            risk_tier=policy_decision.risk_tier,
        )
        if not approved:
            raise PermissionError("Human approval denied tool self-modification")
        policy_decision = PolicyDecision.model_validate(
            policy_decision.model_copy(
                update={"decision": "ALLOW", "approved_by": get_approver(action_id)}
            )
        )
        from core.plugins.registry import register_new_tool
        register_new_tool(arguments["tool_name"], arguments["python_code"])
        result = f"Successfully registered new dynamic tool '{arguments['tool_name']}'."
        return result, ActionRecord(tool="harness", action="write_and_register_tool", policy_decision=policy_decision, started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc), raw_result=result, approved_by=policy_decision.approved_by)

    from core.plugins.registry import dynamic_tool_callables
    if name in dynamic_tool_callables:
        from core.primitives.policy import PolicyDecision, RiskTier
        policy_decision = PolicyDecision(tool="dynamic", action=name, decision="ALLOW", risk_tier=RiskTier.R0, reason="Dynamic tool execution")
        fn = dynamic_tool_callables[name]
        try:
            if asyncio.iscoroutinefunction(fn):
                result = await fn(arguments)
            else:
                result = fn(arguments)
        except Exception as e:
            result = f"Error executing dynamic tool: {e}"
            
        return str(result), ActionRecord(tool="dynamic", action=name, policy_decision=policy_decision, started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc), raw_result=str(result))
"""

if 'name == "write_and_register_tool"' not in code:
    code = code.replace('    if name in {"kubectl_get_pods", "kubectl_describe_pod", "kubectl_logs", "argocd_app_list", "argocd_app_get"}:', dynamic_dispatch_code + '\n    if name in {"kubectl_get_pods", "kubectl_describe_pod", "kubectl_logs", "argocd_app_list", "argocd_app_get"}:')

with open("core/agent_engine.py", "w") as f:
    f.write(code)
