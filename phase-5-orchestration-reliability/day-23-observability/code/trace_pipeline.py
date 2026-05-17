"""
Trace Pipeline — Day 23: Observability for AI Systems
======================================================
Simulates distributed tracing for AI request pipelines.

A trace follows a single request through all pipeline components:
  query_parse → pinot_query → vector_search → context_assembly
  → llm_call → output_validation

Each component creates a span with:
  - trace_id (shared across all spans for one request)
  - span_id (unique per component)
  - parent_span_id (for nested spans)
  - start_time, end_time, duration_ms
  - component-specific attributes

In production: use OpenTelemetry SDK to export to Jaeger/Zipkin.
"""

import time
import uuid
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from contextlib import contextmanager


# ── SPAN ──────────────────────────────────────────────────────────────────────

@dataclass
class Span:
    trace_id:       str
    span_id:        str
    parent_span_id: str | None
    component:      str
    operation:      str
    start_time:     float
    end_time:       float = 0.0
    attributes:     dict  = field(default_factory=dict)
    status:         str   = "ok"   # "ok" | "error"
    error_msg:      str | None = None

    @property
    def duration_ms(self) -> float:
        return round((self.end_time - self.start_time) * 1000, 1)

    def finish(self, attributes: dict = None, error: str = None) -> None:
        self.end_time = time.perf_counter()
        if attributes:
            self.attributes.update(attributes)
        if error:
            self.status    = "error"
            self.error_msg = error


# ── TRACER ────────────────────────────────────────────────────────────────────

class Tracer:
    """
    Collects spans for a single trace.
    In production: use opentelemetry-sdk:
        from opentelemetry import trace
        tracer = trace.get_tracer("ai-system")
        with tracer.start_as_current_span("vector_search") as span:
            span.set_attribute("top_k", 4)
    """
    def __init__(self, trace_id: str = None):
        self.trace_id = trace_id or f"trace_{uuid.uuid4().hex[:8]}"
        self._spans:  list[Span] = []
        self._active: list[Span] = []

    @contextmanager
    def span(self, component: str, operation: str):
        parent_id = self._active[-1].span_id if self._active else None
        s = Span(
            trace_id=self.trace_id,
            span_id=f"span_{uuid.uuid4().hex[:6]}",
            parent_span_id=parent_id,
            component=component,
            operation=operation,
            start_time=time.perf_counter(),
        )
        self._active.append(s)
        self._spans.append(s)
        try:
            yield s
            s.finish()
        except Exception as e:
            s.finish(error=str(e))
            raise
        finally:
            if s in self._active:
                self._active.remove(s)

    def get_spans(self) -> list[Span]:
        return self._spans

    def print_trace(self) -> None:
        total_ms = sum(s.duration_ms for s in self._spans if s.parent_span_id is None)
        print(f"\n  Trace: {self.trace_id} (total: {total_ms:.0f}ms)")
        for s in self._spans:
            indent = "  " if s.parent_span_id else ""
            status = "✅" if s.status == "ok" else "❌"
            attrs  = " | ".join(f"{k}={v}" for k, v in list(s.attributes.items())[:3])
            print(f"    {indent}{status} {s.component}.{s.operation} "
                  f"({s.duration_ms:.0f}ms)"
                  + (f" | {attrs}" if attrs else "")
                  + (f" | ERROR: {s.error_msg}" if s.error_msg else ""))


# ── SIMULATED PIPELINE ────────────────────────────────────────────────────────

def run_traced_pipeline(query: str, user_id: str,
                         inject_failure: str = None) -> dict:
    """
    Runs the full AI pipeline with distributed tracing.
    inject_failure: "pinot" | "vector" | "llm" | None
    """
    tracer = Tracer()
    result = {}

    with tracer.span("api", "handle_request") as root:
        root.attributes["query"] = query[:40]
        root.attributes["user_id"] = user_id

        # Step 1: Query parse
        with tracer.span("query_understanding", "parse_query") as s:
            time.sleep(0.005)
            s.attributes["intent"] = "churn_investigation"
            s.attributes["user_id"] = user_id

        # Step 2: Pinot query
        with tracer.span("pinot", "sql_query") as s:
            if inject_failure == "pinot":
                time.sleep(0.030)
                raise ConnectionError("Pinot broker unavailable")
            time.sleep(random.uniform(0.060, 0.080))
            s.attributes["rows_returned"] = 1
            result["metrics"] = {"errors_7d": 5, "error_rate": 0.50}

        # Step 3: Vector search
        with tracer.span("vector_store", "similarity_search") as s:
            if inject_failure == "vector":
                time.sleep(0.020)
                raise ConnectionError("Vector store unavailable")
            time.sleep(random.uniform(0.040, 0.060))
            s.attributes["top_k"]         = 4
            s.attributes["results_count"] = 4
            s.attributes["avg_score"]     = 0.87
            s.attributes["embedding_age_p99_s"] = 45
            result["chunks"] = ["User hit error on /checkout", "User clicked Upgrade"]

        # Step 4: Context assembly
        with tracer.span("context_builder", "assemble_context") as s:
            time.sleep(0.008)
            s.attributes["context_tokens"]    = 284
            s.attributes["chunks_selected"]   = 4
            s.attributes["token_budget_used"] = "71%"

        # Step 5: LLM call
        with tracer.span("llm_api", "generate_response") as s:
            if inject_failure == "llm":
                time.sleep(0.100)
                raise TimeoutError("LLM API timeout after 30s")
            time.sleep(random.uniform(0.200, 0.400))
            s.attributes["model"]         = "gpt-4o-mini"
            s.attributes["input_tokens"]  = 284
            s.attributes["output_tokens"] = 87
            s.attributes["cost_usd"]      = 0.00048
            result["response"] = {
                "summary":    "User u_4821 is at HIGH churn risk.",
                "action":     "escalate_checkout_fix",
                "confidence": 0.92,
            }

        # Step 6: Output validation
        with tracer.span("validator", "validate_output") as s:
            time.sleep(0.007)
            s.attributes["confidence"]          = 0.92
            s.attributes["grounding_score"]     = 1.0
            s.attributes["hallucination"]       = False
            s.attributes["validation_passed"]   = True

        root.attributes["total_spans"] = len(tracer.get_spans())

    return {"tracer": tracer, "result": result}


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("TRACE PIPELINE — Distributed tracing for AI requests")
    print("=" * 65)

    random.seed(42)

    # Normal trace
    print(f"\n[TRACE 1]  Normal request")
    out = run_traced_pipeline("Why is user u_4821 at risk?", "u_4821")
    out["tracer"].print_trace()

    # Trace with Pinot failure
    print(f"\n[TRACE 2]  Pinot failure")
    try:
        out2 = run_traced_pipeline("Why is user u_4821 at risk?", "u_4821",
                                    inject_failure="pinot")
    except ConnectionError:
        pass
    # The tracer still has spans up to the failure point
    tracer2 = Tracer()
    with tracer2.span("api", "handle_request"):
        with tracer2.span("query_understanding", "parse_query") as s:
            time.sleep(0.005); s.attributes["intent"] = "churn_investigation"
        with tracer2.span("pinot", "sql_query") as s:
            time.sleep(0.030); s.finish(error="ConnectionError: Pinot broker unavailable")
            s.status = "error"
    tracer2.print_trace()

    # Multiple traces — latency analysis
    print(f"\n[LATENCY ANALYSIS]  10 traces")
    latencies = []
    for i in range(10):
        out = run_traced_pipeline(f"Query {i}", "u_4821")
        spans = out["tracer"].get_spans()
        total = sum(s.duration_ms for s in spans if s.parent_span_id is None)
        latencies.append(total)

    latencies.sort()
    print(f"  P50: {latencies[4]:.0f}ms")
    print(f"  P90: {latencies[8]:.0f}ms")
    print(f"  P99: {latencies[-1]:.0f}ms")
    print(f"  Max: {max(latencies):.0f}ms")

    print(f"\n{'='*65}")
    print(f"  Traces show exactly where time is spent in each request.")
    print(f"  Failed spans are visible with error messages.")
    print(f"  In production: export to Jaeger via OpenTelemetry SDK.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
