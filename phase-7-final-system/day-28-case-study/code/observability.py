"""
Day 28 — Production Observability Engine
========================================
Implements a production-grade telemetry system using standard libraries:
1. Structured JSON Logging: Consistent schemas for log processors (e.g., Fluentd, ELK).
2. Distributed Tracing: Nested Span and Trace context managers with parent/child linking.
3. Prometheus-style Metrics: Counters, gauge metrics, latency histograms, and cost tracking.

All components trace back to a centralized telemetry collector for offline audit.
"""

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any


class JSONLogger:
    """Production-style structured JSON logger for log aggregators."""

    def __init__(self, service_name: str = "intelligence-platform"):
        self.service_name = service_name

    def _log(self, level: str, msg: str, trace_id: Optional[str] = None, 
             span_id: Optional[str] = None, extra: Optional[Dict[str, Any]] = None):
        log_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "service": self.service_name,
            "message": msg,
        }
        if trace_id:
            log_record["trace_id"] = trace_id
        if span_id:
            log_record["span_id"] = span_id
        if extra:
            log_record["extra"] = extra

        # Print JSON representation
        print(json.dumps(log_record))

    def info(self, msg: str, trace_id: Optional[str] = None, span_id: Optional[str] = None, extra: Optional[Dict[str, Any]] = None):
        self._log("INFO", msg, trace_id, span_id, extra)

    def warn(self, msg: str, trace_id: Optional[str] = None, span_id: Optional[str] = None, extra: Optional[Dict[str, Any]] = None):
        self._log("WARN", msg, trace_id, span_id, extra)

    def error(self, msg: str, trace_id: Optional[str] = None, span_id: Optional[str] = None, extra: Optional[Dict[str, Any]] = None):
        self._log("ERROR", msg, trace_id, span_id, extra)


class Span:
    """A distributed tracing span tracking execution time and metadata."""

    def __init__(self, name: str, trace_id: str, parent_span_id: Optional[str] = None):
        self.name = name
        self.trace_id = trace_id
        self.span_id = str(uuid.uuid4())[:16]
        self.parent_span_id = parent_span_id
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.latency_ms: float = 0.0
        self.status = "PENDING"
        self.metadata: Dict[str, Any] = {}

    def start(self):
        self.start_time = time.time()
        self.status = "RUNNING"
        return self

    def finish(self, status: str = "SUCCESS", metadata: Optional[Dict[str, Any]] = None):
        self.end_time = time.time()
        self.latency_ms = (self.end_time - self.start_time) * 1000
        self.status = status
        if metadata:
            self.metadata.update(metadata)
        return self


class Trace:
    """A collection of spans representing a single transaction across services."""

    def __init__(self, name: str):
        self.trace_id = str(uuid.uuid4())
        self.name = name
        self.spans: List[Span] = []
        self.active_spans: List[Span] = []
        self.start_time = time.time()
        self.end_time: float = 0.0
        self.total_latency_ms: float = 0.0
        self.status = "RUNNING"
        self.response_preview: str = ""

    def start_span(self, name: str) -> Span:
        parent_id = self.active_spans[-1].span_id if self.active_spans else None
        span = Span(name, self.trace_id, parent_id)
        self.spans.append(span)
        self.active_spans.append(span)
        span.start()
        return span

    def finish_span(self, status: str = "SUCCESS", metadata: Optional[Dict[str, Any]] = None):
        if self.active_spans:
            span = self.active_spans.pop()
            span.finish(status, metadata)
            return span
        return None

    def finish(self, status: str = "SUCCESS", response_preview: str = ""):
        self.end_time = time.time()
        self.total_latency_ms = (self.end_time - self.start_time) * 1000
        self.status = status
        self.response_preview = response_preview
        # Finish any remaining active spans
        while self.active_spans:
            self.finish_span("ABORTED", {"error": "Trace finished before span closed"})
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "name": self.name,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "status": self.status,
            "spans": [
                {
                    "name": s.name,
                    "span_id": s.span_id,
                    "parent_span_id": s.parent_span_id,
                    "latency_ms": round(s.latency_ms, 2),
                    "status": s.status,
                    "metadata": s.metadata,
                }
                for s in self.spans
            ],
            "response": self.response_preview
        }


class MetricsCollector:
    """Prometheus-style local metrics accumulator for SLA and alerting validation."""

    def __init__(self):
        self.counters: Dict[str, float] = {}
        self.histograms: Dict[str, List[float]] = {}
        self.gauges: Dict[str, float] = {}

    def increment(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        key = self._metric_key(name, labels)
        self.counters[key] = self.counters.get(key, 0.0) + value

    def observe(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        key = self._metric_key(name, labels)
        if key not in self.histograms:
            self.histograms[key] = []
        self.histograms[key].append(value)

    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        key = self._metric_key(name, labels)
        self.gauges[key] = value

    def _metric_key(self, name: str, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def get_metric_summary(self) -> Dict[str, Any]:
        """Process histogram stats and return current metrics view."""
        summary = {
            "counters": self.counters,
            "gauges": self.gauges,
            "histograms": {}
        }
        
        for key, values in self.histograms.items():
            if not values:
                continue
            sorted_vals = sorted(values)
            n = len(sorted_vals)
            p50 = sorted_vals[int(n * 0.5)]
            p95 = sorted_vals[int(n * 0.95)] if n > 1 else sorted_vals[-1]
            p99 = sorted_vals[int(n * 0.99)] if n > 2 else sorted_vals[-1]
            summary["histograms"][key] = {
                "count": n,
                "avg": round(sum(sorted_vals) / n, 2),
                "p50": round(p50, 2),
                "p95": round(p95, 2),
                "p99": round(p99, 2),
                "min": round(sorted_vals[0], 2),
                "max": round(sorted_vals[-1], 2)
            }
        return summary


# Global metrics instance for pipeline convenience
metrics = MetricsCollector()
logger = JSONLogger()
