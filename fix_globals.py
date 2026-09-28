with open("core/agent_engine.py", "r") as f:
    t = f.read()

t = t.replace(
'''    if name == "write_and_register_tool":

        policy_decision = PolicyDecision(tool="harness", action="write_and_register_tool", decision="REQUIRE_APPROVAL", risk_tier=RiskTier.R3, reason="Self-modification requires explicit human approval")''',
'''    if name == "write_and_register_tool":
        from core.primitives.policy import PolicyDecision, RiskTier
        policy_decision = PolicyDecision(tool="harness", action="write_and_register_tool", decision="REQUIRE_APPROVAL", risk_tier=RiskTier.R3, reason="Self-modification requires explicit human approval")'''
)

t = t.replace(
'''    from core.plugins.registry import dynamic_tool_callables
    if name in dynamic_tool_callables:

        policy_decision = PolicyDecision(tool="dynamic", action=name, decision="ALLOW", risk_tier=RiskTier.R0, reason="Dynamic tool execution")''',
'''    from core.plugins.registry import dynamic_tool_callables
    if name in dynamic_tool_callables:
        from core.primitives.policy import PolicyDecision, RiskTier
        policy_decision = PolicyDecision(tool="dynamic", action=name, decision="ALLOW", risk_tier=RiskTier.R0, reason="Dynamic tool execution")'''
)
with open("core/agent_engine.py", "w") as f:
    f.write(t)
