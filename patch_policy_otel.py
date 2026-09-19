with open("core/primitives/policy.py", "r") as f:
    content = f.read()

imports = """
from opentelemetry import trace
try:
    tracer = trace.get_tracer(__name__)
except Exception:
    pass
"""

if "from opentelemetry" not in content:
    content = content.replace("from pydantic import", f"{imports}\nfrom pydantic import")
    
if "with tracer.start_as_current_span" not in content:
    old_def = "def resolve_policy("
    new_def = """def resolve_policy(
    tool: str,
    action: str,
    risk_table: dict[tuple[str, str], RiskTier] | None = None,
    approved_by: str | None = None,
) -> PolicyDecision:
    with tracer.start_as_current_span("resolve_policy") as span:
        span.set_attribute("policy.tool", tool)
        span.set_attribute("policy.action", action)
        decision = _resolve_policy_internal(tool, action, risk_table, approved_by)
        span.set_attribute("policy.decision", decision.decision)
        span.set_attribute("policy.risk_tier", str(decision.risk_tier))
        return decision

def _resolve_policy_internal("""
    content = content.replace("def resolve_policy(", new_def)

with open("core/primitives/policy.py", "w") as f:
    f.write(content)
