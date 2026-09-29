"""Compatibility facade. The engine lives in core/loop.py, core/tools.py and core/engine.py."""
from core.effects import EffectScope, EffectStack  # noqa: F401
from core.loop import run_agent, run_agent_generator  # noqa: F401
from core.telemetry import get_tracer, init_tracing  # noqa: F401
from core.tools import limit_output  # noqa: F401

tracer = get_tracer("harness")
