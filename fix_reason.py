with open("core/agent_engine.py", "r") as f:
    text = f.read()

text = text.replace(
    'policy_decision = PolicyDecision(tool="generic", action=name, decision="ALLOW", risk_tier="R1", reason="")',
    'policy_decision = PolicyDecision(tool="generic", action=name, decision="ALLOW", risk_tier="R1", reason="Generic tool action allowed")'
)

with open("core/agent_engine.py", "w") as f:
    f.write(text)

