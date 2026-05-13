"""
Workflow Monitor — Day 20: Airflow for AI Systems
===================================================
Simulates monitoring logic for Airflow-orchestrated AI workflows.

Tracks:
  - DAG run history (success, failure, duration)
  - Task-level metrics (retry count, latency)
  - SLA compliance
  - Embedding freshness
  - Retrieval quality trends

In production: these metrics feed into Prometheus/Grafana
and trigger PagerDuty alerts when thresholds are breached.
"""

import time
import random
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from collections import defaultdict


# ── DATA MODELS ───────────────────────────────────────────────────────────────

@dataclass
class TaskRun:
    dag_id:     str
    task_id:    str
    run_id:     str
    state:      str       # "success", "failed", "running", "skipped"
    started_at: datetime
    duration_s: float
    retries:    int
    error:      str | None = None


@dataclass
class DAGRun:
    dag_id:     str
    run_id:     str
    state:      str
    started_at: datetime
    duration_s: float
    task_runs:  list[TaskRun] = field(default_factory=list)


@dataclass
class SLAStatus:
    dag_id:     str
    task_id:    str
    sla_s:      int
    actual_s:   float
    breached:   bool
    breach_pct: float   # how much over SLA (0.0 = on time, 0.5 = 50% over)


# ── WORKFLOW MONITOR ──────────────────────────────────────────────────────────

class WorkflowMonitor:
    """
    Tracks DAG run history and computes health metrics.
    In production: reads from Airflow metadata DB via REST API.
    """
    def __init__(self):
        self._dag_runs:  list[DAGRun]  = []
        self._sla_misses:list[SLAStatus] = []
        self._alerts:    list[dict]    = []

    def record_dag_run(self, run: DAGRun) -> None:
        self._dag_runs.append(run)
        self._check_slas(run)

    def _check_slas(self, run: DAGRun) -> None:
        SLA_CONFIG = {
            "detect_changed_documents": 300,   # 5 minutes
            "generate_embeddings":      900,   # 15 minutes
            "upsert_to_vector_store":   300,   # 5 minutes
            "validate_retrieval_quality":300,  # 5 minutes
        }
        for task in run.task_runs:
            sla_s = SLA_CONFIG.get(task.task_id, 600)
            if task.duration_s > sla_s:
                breach_pct = (task.duration_s - sla_s) / sla_s
                sla_status = SLAStatus(
                    dag_id=run.dag_id, task_id=task.task_id,
                    sla_s=sla_s, actual_s=task.duration_s,
                    breached=True, breach_pct=round(breach_pct, 2),
                )
                self._sla_misses.append(sla_status)
                self._fire_alert("SLA_MISS", f"{run.dag_id}.{task.task_id} took "
                                 f"{task.duration_s:.0f}s (SLA: {sla_s}s)")

    def _fire_alert(self, alert_type: str, message: str) -> None:
        self._alerts.append({
            "type":    alert_type,
            "message": message,
            "ts":      datetime.now(timezone.utc).isoformat(),
        })
        print(f"  🔔 ALERT [{alert_type}]: {message}")

    def compute_metrics(self) -> dict:
        if not self._dag_runs:
            return {}

        total     = len(self._dag_runs)
        success   = sum(1 for r in self._dag_runs if r.state == "success")
        failed    = sum(1 for r in self._dag_runs if r.state == "failed")
        durations = [r.duration_s for r in self._dag_runs]
        retries   = sum(t.retries for r in self._dag_runs for t in r.task_runs)

        return {
            "total_runs":       total,
            "success_rate":     f"{success/total:.0%}",
            "failure_count":    failed,
            "avg_duration_s":   round(sum(durations) / total, 1),
            "p99_duration_s":   round(sorted(durations)[int(total * 0.99)], 1) if total > 1 else durations[0],
            "total_retries":    retries,
            "sla_misses":       len(self._sla_misses),
            "alerts_fired":     len(self._alerts),
        }

    def print_run_history(self, last_n: int = 5) -> None:
        print(f"\n  [DAG RUN HISTORY]  Last {last_n} runs:")
        for run in self._dag_runs[-last_n:]:
            icon = "✅" if run.state == "success" else "❌"
            print(f"    {icon} {run.run_id:20s}  {run.state:8s}  {run.duration_s:6.1f}s  "
                  f"tasks={len(run.task_runs)}")
            for task in run.task_runs:
                t_icon = "✅" if task.state == "success" else "❌"
                retry_str = f" (retries={task.retries})" if task.retries > 0 else ""
                print(f"         {t_icon} {task.task_id:35s} {task.duration_s:5.1f}s{retry_str}")


# ── SIMULATE DAG RUNS ─────────────────────────────────────────────────────────

def simulate_dag_runs(monitor: WorkflowMonitor, n_runs: int = 10) -> None:
    """Simulates N DAG runs with realistic timing and occasional failures."""
    now = datetime.now(timezone.utc)

    for i in range(n_runs):
        run_start = now - timedelta(hours=n_runs - i) * 0.5
        run_id    = f"scheduled__{run_start.strftime('%Y%m%dT%H%M%S')}"

        # Simulate task durations with occasional failures
        tasks = []
        run_failed = False

        task_configs = [
            ("detect_changed_documents", 60, 120, 0.05),   # (name, min_s, max_s, fail_rate)
            ("generate_embeddings",      300, 800, 0.15),
            ("upsert_to_vector_store",   60, 180, 0.05),
            ("validate_retrieval_quality",30, 90, 0.03),
        ]

        for task_id, min_s, max_s, fail_rate in task_configs:
            if run_failed:
                break  # downstream tasks don't run if upstream failed

            duration = random.uniform(min_s, max_s)
            retries  = 0
            state    = "success"
            error    = None

            if random.random() < fail_rate:
                # Simulate failure with retries
                retries = random.randint(1, 3)
                duration += retries * 120  # each retry adds ~2 minutes
                if retries >= 3:
                    state    = "failed"
                    error    = "TimeoutError: API timeout after 3 retries"
                    run_failed = True

            tasks.append(TaskRun(
                dag_id="embedding_refresh_pipeline",
                task_id=task_id,
                run_id=run_id,
                state=state,
                started_at=run_start,
                duration_s=round(duration, 1),
                retries=retries,
                error=error,
            ))

        total_duration = sum(t.duration_s for t in tasks)
        run = DAGRun(
            dag_id="embedding_refresh_pipeline",
            run_id=run_id,
            state="failed" if run_failed else "success",
            started_at=run_start,
            duration_s=round(total_duration, 1),
            task_runs=tasks,
        )
        monitor.record_dag_run(run)


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("WORKFLOW MONITOR — Airflow observability simulation")
    print("=" * 65)

    random.seed(42)
    monitor = WorkflowMonitor()

    print(f"\n[SIMULATING]  10 DAG runs for embedding_refresh_pipeline\n")
    simulate_dag_runs(monitor, n_runs=10)

    monitor.print_run_history(last_n=5)

    print(f"\n[METRICS]")
    metrics = monitor.compute_metrics()
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    if monitor._sla_misses:
        print(f"\n[SLA MISSES]")
        for miss in monitor._sla_misses:
            print(f"  ⚠️  {miss.dag_id}.{miss.task_id}: "
                  f"{miss.actual_s:.0f}s (SLA={miss.sla_s}s, "
                  f"{miss.breach_pct:.0%} over)")

    if monitor._alerts:
        print(f"\n[ALERTS FIRED]  {len(monitor._alerts)} total")
        for alert in monitor._alerts[:3]:
            print(f"  🔔 [{alert['type']}] {alert['message']}")

    print(f"\n{'='*65}")
    print(f"  In production: these metrics feed into Prometheus/Grafana.")
    print(f"  SLA misses trigger PagerDuty alerts automatically.")
    print(f"  Airflow UI shows full run history and task logs.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
