"""
Failure Monitor — Day 22: Failure Modes in AI Systems
=======================================================
Tracks reliability metrics for AI system components.

Monitors:
  - Component error rates and latency
  - LLM confidence score distribution
  - Retrieval quality (precision@k)
  - Embedding freshness
  - Hallucination detection rate

In production: these metrics feed into Prometheus/Grafana
and trigger PagerDuty alerts when thresholds are breached.
"""

import time
import random
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque


# ── METRIC TYPES ──────────────────────────────────────────────────────────────

@dataclass
class ComponentMetrics:
    name:           str
    total_calls:    int   = 0
    error_count:    int   = 0
    total_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    circuit_open:   bool  = False

    @property
    def error_rate(self) -> float:
        return self.error_count / max(self.total_calls, 1)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / max(self.total_calls, 1)


@dataclass
class LLMQualityMetrics:
    total_responses:    int   = 0
    low_confidence:     int   = 0   # confidence < 0.6
    hallucinations_detected: int = 0
    validation_failures:int   = 0
    avg_confidence:     float = 0.0
    confidence_history: list  = field(default_factory=list)

    @property
    def hallucination_rate(self) -> float:
        return self.hallucinations_detected / max(self.total_responses, 1)

    @property
    def low_confidence_rate(self) -> float:
        return self.low_confidence / max(self.total_responses, 1)


@dataclass
class RetrievalQualityMetrics:
    total_queries:      int   = 0
    precision_scores:   list  = field(default_factory=list)
    stale_retrievals:   int   = 0
    wrong_user_results: int   = 0
    empty_results:      int   = 0

    @property
    def avg_precision(self) -> float:
        if not self.precision_scores:
            return 0.0
        return sum(self.precision_scores) / len(self.precision_scores)

    @property
    def stale_rate(self) -> float:
        return self.stale_retrievals / max(self.total_queries, 1)


# ── FAILURE MONITOR ───────────────────────────────────────────────────────────

class FailureMonitor:
    """
    Tracks reliability metrics across all AI system components.
    Fires alerts when thresholds are breached.
    """

    # Alert thresholds
    THRESHOLDS = {
        "component_error_rate":     0.05,   # alert if > 5% errors
        "component_latency_p99_ms": 2000,   # alert if P99 > 2s
        "llm_low_confidence_rate":  0.20,   # alert if > 20% low confidence
        "llm_hallucination_rate":   0.05,   # alert if > 5% hallucinations
        "retrieval_precision":      0.70,   # alert if precision < 0.70
        "retrieval_stale_rate":     0.10,   # alert if > 10% stale
        "embedding_age_h":          1.0,    # alert if embeddings > 1h old
    }

    def __init__(self):
        self._components:  dict[str, ComponentMetrics]  = {}
        self._llm_quality: LLMQualityMetrics            = LLMQualityMetrics()
        self._retrieval:   RetrievalQualityMetrics      = RetrievalQualityMetrics()
        self._alerts:      list[dict]                   = []
        self._latency_windows: dict[str, deque]         = defaultdict(lambda: deque(maxlen=100))

    def record_component_call(self, name: str, latency_ms: float,
                               success: bool) -> None:
        if name not in self._components:
            self._components[name] = ComponentMetrics(name=name)
        m = self._components[name]
        m.total_calls      += 1
        m.total_latency_ms += latency_ms
        if not success:
            m.error_count += 1

        self._latency_windows[name].append(latency_ms)
        sorted_lats = sorted(self._latency_windows[name])
        p99_idx     = int(len(sorted_lats) * 0.99)
        m.p99_latency_ms = sorted_lats[min(p99_idx, len(sorted_lats)-1)]

        # Check thresholds
        if m.error_rate > self.THRESHOLDS["component_error_rate"]:
            self._fire_alert("COMPONENT_ERROR_RATE",
                f"{name} error rate {m.error_rate:.0%} > {self.THRESHOLDS['component_error_rate']:.0%}")
        if m.p99_latency_ms > self.THRESHOLDS["component_latency_p99_ms"]:
            self._fire_alert("COMPONENT_LATENCY",
                f"{name} P99 latency {m.p99_latency_ms:.0f}ms > {self.THRESHOLDS['component_latency_p99_ms']}ms")

    def record_llm_response(self, confidence: float, hallucination_detected: bool,
                             validation_failed: bool) -> None:
        m = self._llm_quality
        m.total_responses += 1
        m.confidence_history.append(confidence)
        m.avg_confidence = sum(m.confidence_history) / len(m.confidence_history)
        if confidence < 0.6:
            m.low_confidence += 1
        if hallucination_detected:
            m.hallucinations_detected += 1
        if validation_failed:
            m.validation_failures += 1

        if m.low_confidence_rate > self.THRESHOLDS["llm_low_confidence_rate"]:
            self._fire_alert("LLM_LOW_CONFIDENCE",
                f"LLM low confidence rate {m.low_confidence_rate:.0%} > threshold")
        if m.hallucination_rate > self.THRESHOLDS["llm_hallucination_rate"]:
            self._fire_alert("LLM_HALLUCINATION",
                f"Hallucination rate {m.hallucination_rate:.0%} > threshold")

    def record_retrieval(self, precision: float, stale: bool,
                          wrong_user: bool, empty: bool) -> None:
        m = self._retrieval
        m.total_queries += 1
        m.precision_scores.append(precision)
        if stale:       m.stale_retrievals   += 1
        if wrong_user:  m.wrong_user_results += 1
        if empty:       m.empty_results      += 1

        if m.avg_precision < self.THRESHOLDS["retrieval_precision"]:
            self._fire_alert("RETRIEVAL_QUALITY",
                f"Retrieval precision {m.avg_precision:.2f} < {self.THRESHOLDS['retrieval_precision']}")
        if m.stale_rate > self.THRESHOLDS["retrieval_stale_rate"]:
            self._fire_alert("RETRIEVAL_STALE",
                f"Stale retrieval rate {m.stale_rate:.0%} > threshold")

    def _fire_alert(self, alert_type: str, message: str) -> None:
        # Deduplicate: don't fire same alert type more than once per minute
        recent = [a for a in self._alerts
                  if a["type"] == alert_type and
                  time.perf_counter() - a["ts"] < 60]
        if recent:
            return
        alert = {"type": alert_type, "message": message, "ts": time.perf_counter()}
        self._alerts.append(alert)
        print(f"  🔔 ALERT [{alert_type}]: {message}")

    def print_dashboard(self) -> None:
        print(f"\n  {'─'*60}")
        print(f"  RELIABILITY DASHBOARD")
        print(f"  {'─'*60}")

        print(f"\n  [COMPONENTS]")
        for name, m in self._components.items():
            status = "🔴" if m.error_rate > 0.05 else "🟡" if m.error_rate > 0.01 else "🟢"
            print(f"  {status} {name:20s}  calls={m.total_calls:4d}  "
                  f"errors={m.error_rate:.0%}  "
                  f"avg={m.avg_latency_ms:.0f}ms  "
                  f"p99={m.p99_latency_ms:.0f}ms")

        m = self._llm_quality
        print(f"\n  [LLM QUALITY]")
        print(f"  Responses:       {m.total_responses}")
        print(f"  Avg confidence:  {m.avg_confidence:.2f}")
        print(f"  Low confidence:  {m.low_confidence_rate:.0%} ({m.low_confidence}/{m.total_responses})")
        print(f"  Hallucinations:  {m.hallucination_rate:.0%} ({m.hallucinations_detected}/{m.total_responses})")

        r = self._retrieval
        print(f"\n  [RETRIEVAL QUALITY]")
        print(f"  Queries:         {r.total_queries}")
        print(f"  Avg precision:   {r.avg_precision:.2f}")
        print(f"  Stale rate:      {r.stale_rate:.0%}")
        print(f"  Empty results:   {r.empty_results}")

        print(f"\n  [ALERTS]  {len(self._alerts)} total")
        for a in self._alerts[-5:]:
            print(f"  🔔 [{a['type']}] {a['message']}")


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("FAILURE MONITOR — AI system reliability tracking")
    print("=" * 65)

    random.seed(42)
    monitor = FailureMonitor()

    print(f"\n[SIMULATING]  100 requests through AI system\n")

    for i in range(100):
        # Simulate component calls with occasional failures
        for component, base_latency, fail_rate in [
            ("pinot",        68,  0.03),
            ("vector_store", 50,  0.02),
            ("llm_api",      500, 0.08),
        ]:
            latency = base_latency + random.gauss(0, base_latency * 0.2)
            success = random.random() > fail_rate
            if not success:
                latency *= 3  # failures are slower
            monitor.record_component_call(component, max(latency, 1), success)

        # Simulate LLM quality
        confidence = random.gauss(0.82, 0.15)
        confidence = max(0.1, min(1.0, confidence))
        hallucination = random.random() < 0.04  # 4% hallucination rate
        validation_fail = hallucination or confidence < 0.5
        monitor.record_llm_response(confidence, hallucination, validation_fail)

        # Simulate retrieval quality
        precision = random.gauss(0.85, 0.12)
        precision = max(0.0, min(1.0, precision))
        stale     = random.random() < 0.08   # 8% stale
        wrong_user= random.random() < 0.02   # 2% wrong user
        empty     = random.random() < 0.01   # 1% empty
        monitor.record_retrieval(precision, stale, wrong_user, empty)

    monitor.print_dashboard()

    print(f"\n{'='*65}")
    print(f"  In production: these metrics feed into Prometheus/Grafana.")
    print(f"  Alerts fire to PagerDuty when thresholds are breached.")
    print(f"  Monitor quality metrics, not just uptime.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
