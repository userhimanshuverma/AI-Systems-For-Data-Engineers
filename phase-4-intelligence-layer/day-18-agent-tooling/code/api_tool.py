"""
API Tool — Day 18: Tooling for Agents
=======================================
Simulates REST API tool calls that agents make to external services.

Covers:
  - Alert sending (PagerDuty / Slack)
  - Airflow DAG triggering
  - Log search (Elasticsearch)
  - Monitoring queries (Prometheus)

Each tool demonstrates:
  - Input validation
  - Timeout enforcement
  - Retry with backoff
  - Structured output
  - Dry-run mode for write tools

In production: replace mock implementations with real HTTP calls.
"""

import time
import random
from dataclasses import dataclass
from typing import Any


# ── API RESULT ────────────────────────────────────────────────────────────────

@dataclass
class APIResult:
    tool_name:  str
    success:    bool
    output:     Any
    latency_ms: float
    attempts:   int
    error:      str | None = None
    dry_run:    bool = False


# ── RETRY DECORATOR ───────────────────────────────────────────────────────────

def with_retry(fn, max_retries: int = 3, timeout_ms: int = 5000):
    """Executes fn with retry and exponential backoff."""
    for attempt in range(max_retries):
        t0 = time.perf_counter()
        try:
            result = fn()
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            return result, latency_ms, attempt + 1
        except TimeoutError:
            if attempt == max_retries - 1:
                raise
            time.sleep(0.1 * (2 ** attempt))
        except Exception:
            if attempt == max_retries - 1:
                raise
            time.sleep(0.1 * (2 ** attempt))
    raise RuntimeError("max_retries_exceeded")


# ── ALERT TOOL ────────────────────────────────────────────────────────────────

def send_alert(
    message: str,
    priority: str = "medium",
    user_ids: list | None = None,
    channel: str = "support-alerts",
    dry_run: bool = False,
) -> APIResult:
    """
    Sends alert to PagerDuty or Slack.
    In production: POST to PagerDuty Events API or Slack Webhooks.

    dry_run=True: validates and logs but does not actually send.
    """
    t0 = time.perf_counter()

    if dry_run:
        time.sleep(0.010)
        return APIResult(
            tool_name="send_alert", success=True,
            output={"alert_id": "dry_run_001", "sent": False, "dry_run": True,
                    "would_send_to": channel, "recipients": len(user_ids or [])},
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            attempts=1, dry_run=True,
        )

    # Simulate API call (~150ms)
    time.sleep(random.uniform(0.100, 0.200))
    alert_id = f"alert_{int(time.time() * 1000) % 100000}"

    return APIResult(
        tool_name="send_alert", success=True,
        output={
            "alert_id":   alert_id,
            "sent":       True,
            "channel":    channel,
            "priority":   priority,
            "recipients": len(user_ids or []),
            "message":    message[:50] + "..." if len(message) > 50 else message,
        },
        latency_ms=round((time.perf_counter() - t0) * 1000, 1),
        attempts=1,
    )


# ── AIRFLOW DAG TRIGGER ───────────────────────────────────────────────────────

def trigger_airflow_dag(
    dag_id: str,
    conf: dict | None = None,
    dry_run: bool = False,
) -> APIResult:
    """
    Triggers an Airflow DAG run.
    In production: POST to Airflow REST API:
        POST /api/v1/dags/{dag_id}/dagRuns
        {"conf": conf}
    """
    t0 = time.perf_counter()

    KNOWN_DAGS = {
        "payment_gateway_failover": "Switches payment gateway to backup endpoint",
        "user_data_reprocess":      "Reprocesses user events for a given time range",
        "embedding_refresh":        "Re-embeds documents with updated model",
        "nightly_feature_compute":  "Computes batch features for all users",
    }

    if dag_id not in KNOWN_DAGS:
        return APIResult(
            tool_name="trigger_airflow_dag", success=False,
            output=None, latency_ms=5.0, attempts=1,
            error=f"DAG '{dag_id}' not found. Known DAGs: {list(KNOWN_DAGS.keys())}",
        )

    if dry_run:
        time.sleep(0.010)
        return APIResult(
            tool_name="trigger_airflow_dag", success=True,
            output={"run_id": "dry_run", "status": "would_trigger", "dag_id": dag_id,
                    "description": KNOWN_DAGS[dag_id]},
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            attempts=1, dry_run=True,
        )

    time.sleep(random.uniform(0.150, 0.250))
    run_id = f"manual__{dag_id}_{int(time.time())}"

    return APIResult(
        tool_name="trigger_airflow_dag", success=True,
        output={"run_id": run_id, "status": "running", "dag_id": dag_id,
                "conf": conf or {}, "description": KNOWN_DAGS[dag_id]},
        latency_ms=round((time.perf_counter() - t0) * 1000, 1),
        attempts=1,
    )


# ── LOG SEARCH TOOL ───────────────────────────────────────────────────────────

MOCK_LOGS = [
    {"ts": "14:32:01", "level": "ERROR", "message": "payment gateway timeout: upstream endpoint /v2/charge returned 504"},
    {"ts": "14:32:03", "level": "ERROR", "message": "payment gateway timeout: retry 1 failed"},
    {"ts": "14:32:05", "level": "ERROR", "message": "payment gateway timeout: retry 2 failed, circuit breaker open"},
    {"ts": "14:33:01", "level": "WARN",  "message": "checkout service degraded: 847 errors in last 60s"},
    {"ts": "14:35:00", "level": "INFO",  "message": "payment gateway failover initiated: switching to backup endpoint"},
]

def query_logs(
    query: str,
    time_range_h: int = 1,
    level: str = "ERROR",
    limit: int = 10,
) -> APIResult:
    """
    Searches application logs.
    In production: POST to Elasticsearch search API.
    """
    t0 = time.perf_counter()
    time.sleep(random.uniform(0.080, 0.120))

    q = query.lower()
    matching = [
        log for log in MOCK_LOGS
        if q in log["message"].lower()
        and (level == "ALL" or log["level"] == level or
             (level == "ERROR" and log["level"] in ("ERROR", "WARN")))
    ][:limit]

    first_ts = matching[0]["ts"] if matching else None

    return APIResult(
        tool_name="query_logs", success=True,
        output={
            "log_lines":        [f"[{l['ts']}] [{l['level']}] {l['message']}" for l in matching],
            "count":            len(matching),
            "first_occurrence": first_ts,
            "query":            query,
        },
        latency_ms=round((time.perf_counter() - t0) * 1000, 1),
        attempts=1,
    )


# ── MONITORING TOOL ───────────────────────────────────────────────────────────

def query_monitoring(
    metric: str,
    time_range_h: int = 1,
) -> APIResult:
    """
    Queries system metrics.
    In production: GET to Prometheus HTTP API:
        GET /api/v1/query?query={metric}
    """
    t0 = time.perf_counter()
    time.sleep(random.uniform(0.030, 0.060))

    METRICS = {
        "payment_gateway_error_rate": {"current": 0.82, "baseline": 0.002, "unit": "errors/req"},
        "checkout_latency_p99":       {"current": 4200, "baseline": 180,   "unit": "ms"},
        "active_users":               {"current": 1247, "baseline": 1200,  "unit": "users"},
        "kafka_consumer_lag":         {"current": 0,    "baseline": 0,     "unit": "messages"},
    }

    # Find matching metric
    m_lower = metric.lower()
    matched = None
    for key, val in METRICS.items():
        if any(part in m_lower for part in key.split("_")):
            matched = (key, val)
            break

    if not matched:
        matched = ("unknown", {"current": 0, "baseline": 0, "unit": "unknown"})

    key, val = matched
    spike_ratio = val["current"] / max(val["baseline"], 0.001)

    return APIResult(
        tool_name="query_monitoring", success=True,
        output={
            "metric":      key,
            "current":     val["current"],
            "baseline":    val["baseline"],
            "unit":        val["unit"],
            "spike_ratio": round(spike_ratio, 1),
            "status":      "CRITICAL" if spike_ratio > 10 else "WARNING" if spike_ratio > 2 else "OK",
        },
        latency_ms=round((time.perf_counter() - t0) * 1000, 1),
        attempts=1,
    )


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("API TOOL — External service integrations for agents")
    print("=" * 65)

    # Alert (dry run)
    print(f"\n[ALERT TOOL]  Dry run (no actual alert sent)")
    r = send_alert("Payment gateway outage: 847 errors", priority="high",
                   user_ids=["u_4821","u_7734"], dry_run=True)
    print(f"  Success: {r.success} | Dry run: {r.dry_run}")
    print(f"  Output:  {r.output}")

    # Airflow DAG trigger (dry run)
    print(f"\n[AIRFLOW TOOL]  Trigger failover DAG (dry run)")
    r = trigger_airflow_dag("payment_gateway_failover",
                            conf={"switch_to_backup": True}, dry_run=True)
    print(f"  Success: {r.success} | Dry run: {r.dry_run}")
    print(f"  Output:  {r.output}")

    # Log search
    print(f"\n[LOG TOOL]  Search for payment gateway errors")
    r = query_logs("payment gateway timeout", time_range_h=1)
    print(f"  Found: {r.output['count']} matching log lines")
    print(f"  First occurrence: {r.output['first_occurrence']}")
    for line in r.output['log_lines'][:2]:
        print(f"    {line}")

    # Monitoring
    print(f"\n[MONITORING TOOL]  Check payment gateway error rate")
    r = query_monitoring("payment_gateway_error_rate")
    print(f"  Current: {r.output['current']} {r.output['unit']}")
    print(f"  Baseline: {r.output['baseline']} {r.output['unit']}")
    print(f"  Spike ratio: {r.output['spike_ratio']}x")
    print(f"  Status: {r.output['status']}")

    # Unknown DAG (error handling)
    print(f"\n[ERROR HANDLING]  Trigger unknown DAG")
    r = trigger_airflow_dag("nonexistent_dag")
    print(f"  Success: {r.success}")
    print(f"  Error:   {r.error}")


if __name__ == "__main__":
    run()
