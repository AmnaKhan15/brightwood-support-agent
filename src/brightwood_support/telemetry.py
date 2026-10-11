"""Logs, traces and metrics.

  - Logs: one JSON object per line on stdout, with the request id, so Render's log search (or any
    log tool) can filter by field. Message text and secrets are never logged.
  - Traces and metrics: OpenTelemetry, exported over OTLP/HTTP when OTEL_EXPORTER_OTLP_ENDPOINT is set
    (Grafana Cloud's free tier accepts it; set OTEL_EXPORTER_OTLP_HEADERS to its auth header). Without
    it the OpenTelemetry API is a no-op, so nothing changes locally.
  - LLM traces: LangGraph and LangChain send their own traces to LangSmith when LANGSMITH_TRACING=true.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from contextvars import ContextVar

from opentelemetry import metrics, trace

request_id: ContextVar[str] = ContextVar("request_id", default="-")

SERVICE = "brightwood-support-agent"
tracer = trace.get_tracer(SERVICE)
meter = metrics.get_meter(SERVICE)
runs_counter = meter.create_counter("agent_runs", description="assistant turns by outcome, agent and provider")
run_latency = meter.create_histogram("agent_run_ms", unit="ms", description="time to answer one customer turn")
tokens_counter = meter.create_counter("agent_tokens", description="model tokens used")
tool_counter = meter.create_counter("agent_tool_calls", description="tool calls by tool and status")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id.get(),
        }
        span = trace.get_current_span().get_span_context()
        if span.is_valid:
            out["trace_id"] = format(span.trace_id, "032x")
        out.update(getattr(record, "ctx", None) or {})
        if record.exc_info:
            out["error"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "uvicorn.access", "dramatiq", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def setup_otel(app, env, version: str) -> bool:
    """Export traces and metrics over OTLP if an endpoint is configured. Returns whether it did."""
    if not env.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({"service.name": SERVICE, "service.version": version,
                                "deployment.environment": env.get("APP_ENV", "production")})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(), 30_000)]))
    FastAPIInstrumentor.instrument_app(app, excluded_urls="api/health")
    logging.getLogger(__name__).info("OpenTelemetry export on")
    return True
