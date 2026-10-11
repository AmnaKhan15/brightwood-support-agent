"""Tracing: one span per model call and per tool call, with duration and tokens.

A trace answers "what did the agent do, in what order, and how long did each
step take?" It is plain data (a list of dicts) for the page's inspector, and each
span is also emitted as an OpenTelemetry span, so the same steps show up in Grafana
when OTLP export is on (see telemetry.py).
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Callable, Iterator

from .telemetry import tracer as otel_tracer


class Tracer:
    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self.spans: list[dict] = []
        self._clock = clock

    @contextmanager
    def span(self, name: str, **attrs) -> Iterator[dict]:
        """Time a block. The yielded dict lets the block add attributes (tokens, status)."""
        record_attrs: dict = dict(attrs)
        start = self._clock()
        with otel_tracer.start_as_current_span(f"agent.{name}") as otel_span:
            try:
                yield record_attrs
            except Exception as error:  # noqa: BLE001 - record it, then let it propagate
                record_attrs["error"] = repr(error)
                raise
            finally:
                self.spans.append(
                    {"name": name, "attrs": record_attrs, "duration_s": round(self._clock() - start, 6)}
                )
                for key, value in record_attrs.items():
                    if isinstance(value, (str, bool, int, float)):
                        otel_span.set_attribute(f"agent.{key}", value)

    def summary(self, price_per_1k_tokens: float | None = None) -> dict:
        """Totals for a run. Cost is only reported if a price is supplied, never guessed."""
        model = [s for s in self.spans if s["name"] == "model_call"]
        tools = [s for s in self.spans if s["name"] == "tool_call"]
        tokens = sum(s["attrs"].get("tokens", 0) for s in model)
        return {
            "model_calls": len(model),
            "tool_calls": len(tools),
            "tokens": tokens,
            "model_seconds": round(sum(s["duration_s"] for s in model), 6),
            "tool_seconds": round(sum(s["duration_s"] for s in tools), 6),
            "cost": round(tokens / 1000 * price_per_1k_tokens, 6) if price_per_1k_tokens is not None else None,
            "tool_failures": sum(1 for s in tools if s["attrs"].get("status") not in ("ok", "pending_approval")),
        }

    def to_json(self) -> str:
        return json.dumps({"spans": self.spans}, indent=2, default=str)
