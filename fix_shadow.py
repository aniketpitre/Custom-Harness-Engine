with open("core/agent_engine.py", "r") as f:
    text = f.read()

text = text.replace(
'''        # Policy is generic R1
        from core.primitives.policy import PolicyDecision
        policy_decision = PolicyDecision(tool="generic", action=name, decision="ALLOW", risk_tier="R1", reason="")''',
'''        # Policy is generic R1
        policy_decision = PolicyDecision(tool="generic", action=name, decision="ALLOW", risk_tier="R1", reason="")'''
)

with open("core/agent_engine.py", "w") as f:
    f.write(text)

