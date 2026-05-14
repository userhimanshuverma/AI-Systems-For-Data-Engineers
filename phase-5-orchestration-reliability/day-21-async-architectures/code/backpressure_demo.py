"""
Backpressure Demo — Day 21: Async vs Sync Architectures
=========================================================
Simulates queue buildup and backpressure scenarios.

Demonstrates:
  - Queue depth growing when producer > consumer rate
  - Downstream slowdown cascading to queue growth
  - Backpressure detection and alerting
  - Producer throttling as a response
  - Worker autoscaling as a response
"""

import time
import random
import threading
from queue import Queue, Empty
from dataclasses import dataclass, field
from collections import deque


# ── METRICS TRACKER ───────────────────────────────────────────────────────────

@dataclass
class QueueMetrics:
    timestamp:      float
    queue_depth:    int
    producer_rate:  float   # tasks/sec
    consumer_rate:  float   # tasks/sec
    worker_count:   int
    alert_fired:    bool = False


class MetricsCollector:
    def __init__(self, window_s: float = 5.0):
        self._snapshots: list[QueueMetrics] = []
        self._window    = window_s

    def record(self, m: QueueMetrics) -> None:
        self._snapshots.append(m)

    def latest(self) -> QueueMetrics | None:
        return self._snapshots[-1] if self._snapshots else None

    def all(self) -> list[QueueMetrics]:
        return self._snapshots


# ── BACKPRESSURE MONITOR ──────────────────────────────────────────────────────

class BackpressureMonitor:
    """
    Monitors queue depth and fires alerts when thresholds are exceeded.
    In production: feeds into Prometheus/Grafana + PagerDuty.
    """
    ALERT_THRESHOLD  = 100   # alert when queue > 100 tasks
    CRITICAL_THRESHOLD = 500  # critical when queue > 500 tasks

    def __init__(self):
        self._alerts: list[dict] = []

    def check(self, queue_depth: int, ts: float) -> str | None:
        if queue_depth >= self.CRITICAL_THRESHOLD:
            alert = {"level": "CRITICAL", "depth": queue_depth, "ts": ts,
                     "message": f"Queue depth {queue_depth} exceeds critical threshold {self.CRITICAL_THRESHOLD}"}
            self._alerts.append(alert)
            return "CRITICAL"
        elif queue_depth >= self.ALERT_THRESHOLD:
            alert = {"level": "WARNING", "depth": queue_depth, "ts": ts,
                     "message": f"Queue depth {queue_depth} exceeds warning threshold {self.ALERT_THRESHOLD}"}
            self._alerts.append(alert)
            return "WARNING"
        return None

    def alert_count(self) -> int:
        return len(self._alerts)


# ── SIMULATION ────────────────────────────────────────────────────────────────

def simulate_backpressure(
    producer_rate: float,    # tasks/sec
    consumer_rate: float,    # tasks/sec per worker
    n_workers: int,
    duration_s: float,
    scenario_name: str,
) -> list[QueueMetrics]:
    """
    Simulates queue depth over time given producer and consumer rates.
    Returns time-series of queue metrics.
    """
    queue_depth = 0
    metrics     = []
    monitor     = BackpressureMonitor()
    t0          = time.perf_counter()
    dt          = 0.5  # sample every 0.5 seconds

    effective_consumer = consumer_rate * n_workers
    net_rate = producer_rate - effective_consumer  # positive = queue growing

    t = 0.0
    while t <= duration_s:
        queue_depth = max(0, queue_depth + net_rate * dt)
        alert_level = monitor.check(int(queue_depth), t)

        m = QueueMetrics(
            timestamp=round(t, 1),
            queue_depth=int(queue_depth),
            producer_rate=producer_rate,
            consumer_rate=effective_consumer,
            worker_count=n_workers,
            alert_fired=alert_level is not None,
        )
        metrics.append(m)
        t += dt

    return metrics, monitor


def print_queue_chart(metrics: list[QueueMetrics], max_width: int = 40) -> None:
    """Prints an ASCII chart of queue depth over time."""
    if not metrics:
        return
    max_depth = max(m.queue_depth for m in metrics)
    if max_depth == 0:
        print("  Queue depth: 0 throughout")
        return

    print(f"  {'Time':6s} {'Queue Depth':12s} {'Chart'}")
    print(f"  {'-'*60}")
    # Sample every 2 seconds for readability
    sampled = [m for m in metrics if m.timestamp % 2 < 0.6]
    for m in sampled:
        bar_len = int((m.queue_depth / max_depth) * max_width)
        bar     = "█" * bar_len
        alert   = " ⚠️" if m.alert_fired else ""
        print(f"  {m.timestamp:5.1f}s  {m.queue_depth:8d}    {bar}{alert}")


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("BACKPRESSURE DEMO — Queue buildup and response strategies")
    print("=" * 65)

    # ── Scenario 1: Balanced (no backpressure) ────────────────────────────
    print(f"\n[SCENARIO 1]  Balanced: producer=consumer rate")
    metrics1, mon1 = simulate_backpressure(
        producer_rate=100, consumer_rate=25, n_workers=4,
        duration_s=10, scenario_name="balanced",
    )
    print(f"  Producer: 100/sec | Workers: 4 × 25/sec = 100/sec")
    print(f"  Queue depth at end: {metrics1[-1].queue_depth}")
    print(f"  Alerts fired: {mon1.alert_count()}")
    print_queue_chart(metrics1)

    # ── Scenario 2: Traffic spike ─────────────────────────────────────────
    print(f"\n[SCENARIO 2]  Traffic spike: producer 3x consumer rate")
    metrics2, mon2 = simulate_backpressure(
        producer_rate=300, consumer_rate=25, n_workers=4,
        duration_s=20, scenario_name="spike",
    )
    print(f"  Producer: 300/sec | Workers: 4 × 25/sec = 100/sec")
    print(f"  Net queue growth: +200/sec")
    print(f"  Queue depth at end: {metrics2[-1].queue_depth}")
    print(f"  Alerts fired: {mon2.alert_count()}")
    print_queue_chart(metrics2)

    # ── Scenario 3: Downstream slowdown ──────────────────────────────────
    print(f"\n[SCENARIO 3]  Downstream slowdown: LLM API slow")
    print(f"  Normal: 4 workers × 25/sec = 100/sec")
    print(f"  LLM slow: 4 workers × 3/sec = 12/sec (8x slower)")
    metrics3, mon3 = simulate_backpressure(
        producer_rate=100, consumer_rate=3, n_workers=4,
        duration_s=20, scenario_name="slow_llm",
    )
    print(f"  Queue depth at end: {metrics3[-1].queue_depth}")
    print(f"  Alerts fired: {mon3.alert_count()}")
    print_queue_chart(metrics3)

    # ── Scenario 4: Autoscaling response ─────────────────────────────────
    print(f"\n[SCENARIO 4]  Autoscaling response to spike")
    print(f"  t=0-10s:  4 workers (queue growing)")
    print(f"  t=10-20s: 12 workers (autoscaled, queue draining)")

    # Phase 1: spike with 4 workers
    m_phase1, _ = simulate_backpressure(
        producer_rate=300, consumer_rate=25, n_workers=4,
        duration_s=10, scenario_name="spike_phase1",
    )
    # Phase 2: autoscaled to 12 workers
    start_depth = m_phase1[-1].queue_depth
    m_phase2 = []
    queue_depth = start_depth
    t = 10.0
    effective_consumer = 25 * 12  # 12 workers
    net_rate = 300 - effective_consumer  # negative = queue draining
    while t <= 20.0:
        queue_depth = max(0, queue_depth + net_rate * 0.5)
        m_phase2.append(QueueMetrics(
            timestamp=round(t, 1), queue_depth=int(queue_depth),
            producer_rate=300, consumer_rate=effective_consumer,
            worker_count=12,
        ))
        t += 0.5

    all_metrics = m_phase1 + m_phase2
    print(f"  Peak queue depth: {max(m.queue_depth for m in all_metrics)}")
    print(f"  Queue depth after autoscale: {m_phase2[-1].queue_depth}")
    print_queue_chart(all_metrics)

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  BACKPRESSURE RESPONSES:")
    print(f"  1. Monitor queue depth → alert when > threshold")
    print(f"  2. Autoscale workers → add capacity when queue grows")
    print(f"  3. Throttle producer → slow down when queue is full")
    print(f"  4. Priority queues → process urgent tasks first")
    print(f"  5. Dead letter queue → remove permanently failed tasks")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
