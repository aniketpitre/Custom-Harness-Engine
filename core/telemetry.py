"""OpenTelemetry setup. Tracing and metrics are no-ops unless an endpoint is configured."""
from __future__ import annotations

import logging

from opentelemetry import metrics, trace

log = logging.getLogger("harness.telemetry")
_initialised = False


def init_tracing(endpoint: str | None = None) -> None:
    """Idempotent. Reads OTEL_EXPORTER_OTLP_ENDPOINT / settings when endpoint is None."""
    global _initialised
    if _initialised:
        return
    _initialised = True
    if endpoint is None:
        from core.settings import settings

        endpoint = settings().otel_endpoint
    if not endpoint:
        return
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create({"service.name": "penko-perry", "service.version": __import__("core").__version__})
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
    except Exception as error:  # noqa: BLE001
        log.warning("tracing disabled: %s", error)
        return
    try:  # optional dependency
        from opentelemetry.instrumentation.litellm import LiteLLMInstrumentor

        LiteLLMInstrumentor().instrument()
    except Exception:  # noqa: BLE001
        pass


def get_tracer(name: str = "harness"):
    return trace.get_tracer(name)


_meter = metrics.get_meter("harness")
run_counter = _meter.create_counter("harness_agent_run_count", description="Agent runs")
policy_counter = _meter.create_counter(
    "resolve_policy_decision_count", description="Policy decisions by outcome"
)
tool_counter = _meter.create_counter("harness_tool_call_count", description="Tool calls")
