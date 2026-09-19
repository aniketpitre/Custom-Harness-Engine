import re

with open("core/agent_engine.py", "r") as f:
    content = f.read()

# 1. Add OpenTelemetry imports
imports = """
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.litellm import LitellmInstrumentor

def init_tracing():
    try:
        otlp_endpoint = get_secret("otel", "endpoint")
        if otlp_endpoint:
            resource = Resource.create({"service.name": "harness-engine", "service.version": "0.1.0"})
            provider = TracerProvider(resource=resource)
            processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
            LitellmInstrumentor().instrument()
            return trace.get_tracer(__name__)
    except Exception:
        pass
    return trace.get_tracer(__name__)

tracer = init_tracing()
"""
if "from opentelemetry import trace" not in content:
    content = content.replace("import litellm\n", f"import litellm\n{imports}")

# 2. Add tracer to run_agent
if "with tracer.start_as_current_span" not in content:
    run_agent_orig = "async def run_agent(context: ContextPacket, allowed_tools: list[str]) -> dict[str, Any]:\n"
    run_agent_new = """async def run_agent(context: ContextPacket, allowed_tools: list[str]) -> dict[str, Any]:
    with tracer.start_as_current_span("harness_agent_run") as span:
        span.set_attribute("agent.goal", context.goal.raw_input)
        span.set_attribute("agent.domain", context.goal.domain)
        span.set_attribute("agent.trigger_source", context.goal.source.value)
"""
    content = content.replace(run_agent_orig, run_agent_new)
    
    lines = content.splitlines()
    inside_run_agent = False
    for i, line in enumerate(lines):
        if line.startswith("    model = os.getenv"):
            inside_run_agent = True
        
        if inside_run_agent and line.startswith("def _build_prompt"):
            inside_run_agent = False
            
        if inside_run_agent:
            lines[i] = "    " + line
            if "response = await litellm.acompletion(" in line:
                # Insert span event
                lines[i] = '            span.add_event(f"llm_completion_turn_{_}", {"turn_number": _})\n' + lines[i]
            if "return {" in line and "events: events" in lines[i+1]:
                lines[i] = '            span.set_status(trace.Status(trace.StatusCode.OK))\n' + lines[i]
            if "raise RuntimeError" in line:
                lines[i] = '        span.set_status(trace.Status(trace.StatusCode.ERROR, "Max tool turns exceeded"))\n' + lines[i]
                inside_run_agent = False

    content = "\n".join(lines) + "\n"

with open("core/agent_engine.py", "w") as f:
    f.write(content)
