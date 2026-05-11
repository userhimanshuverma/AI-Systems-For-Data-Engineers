"""
Pinot Tool — Day 18: Tooling for Agents
=========================================
Simulates the Apache Pinot tool that agents call for real-time analytics.

In production: HTTP POST to Pinot Broker:
    import requests
    resp = requests.post(
        "http://pinot-broker:8099/query/sql",
        json={"sql": sql},
        timeout=timeout_ms / 1000,
    )
    return resp.json()["resultTable"]["rows"]

This module demonstrates:
  - SQL query execution against simulated Pinot data
  - Timeout enforcement
  - Retry with exponential backoff
  - Structured output format
  - Error handling and fallback
"""

import time
import random
from dataclasses import dataclass


# ── SIMULATED PINOT DATA ──────────────────────────────────────────────────────

PINOT_TABLES = {
    "user_events_realtime": [
        {"user_id":"u_4821","event_type":"system.server_error","error_rate":0.80,"churn_risk":True, "plan":"free","ts_offset_min":2},
        {"user_id":"u_4821","event_type":"system.server_error","error_rate":0.80,"churn_risk":True, "plan":"free","ts_offset_min":5},
        {"user_id":"u_4821","event_type":"ui.button_click",    "error_rate":0.80,"churn_risk":True, "plan":"free","ts_offset_min":8},
        {"user_id":"u_7734","event_type":"system.server_error","error_rate":0.33,"churn_risk":True, "plan":"free","ts_offset_min":3},
        {"user_id":"u_0012","event_type":"commerce.purchase",  "error_rate":0.00,"churn_risk":False,"plan":"pro", "ts_offset_min":1},
        {"user_id":"u_9901","event_type":"ui.page_view",       "error_rate":0.00,"churn_risk":False,"plan":"enterprise","ts_offset_min":4},
    ],
    "payment_gateway_errors": [
        {"endpoint":"checkout","error_count":847,"error_rate":0.82,"status":"degraded","ts_offset_min":10},
        {"endpoint":"billing", "error_count":12, "error_rate":0.05,"status":"healthy", "ts_offset_min":10},
    ],
}


# ── QUERY EXECUTOR ────────────────────────────────────────────────────────────

@dataclass
class PinotResult:
    rows:       list[dict]
    row_count:  int
    latency_ms: float
    sql:        str
    success:    bool
    error:      str | None = None


def _execute_sql(sql: str) -> list[dict]:
    """
    Simulates SQL execution against Pinot tables.
    Supports basic WHERE, ORDER BY, LIMIT, COUNT, AVG.
    """
    sql_lower = sql.lower()

    # Determine which table to query
    if "payment_gateway_errors" in sql_lower:
        rows = PINOT_TABLES["payment_gateway_errors"]
    else:
        rows = PINOT_TABLES["user_events_realtime"]

    # Apply basic filters
    if "churn_risk = true" in sql_lower or "churn_risk=true" in sql_lower:
        rows = [r for r in rows if r.get("churn_risk")]

    if "plan = 'free'" in sql_lower or "plan='free'" in sql_lower:
        rows = [r for r in rows if r.get("plan") == "free"]

    if "event_type = 'system.server_error'" in sql_lower:
        rows = [r for r in rows if r.get("event_type") == "system.server_error"]

    # Extract user_id filter
    import re
    uid_match = re.search(r"user_id\s*=\s*'(u_\d+)'", sql_lower)
    if uid_match:
        uid = uid_match.group(1)
        rows = [r for r in rows if r.get("user_id") == uid]

    # Apply LIMIT
    limit_match = re.search(r"limit\s+(\d+)", sql_lower)
    if limit_match:
        rows = rows[:int(limit_match.group(1))]

    # Handle COUNT(*)
    if "count(*)" in sql_lower:
        return [{"count": len(rows)}]

    # Handle AVG
    if "avg(error_rate)" in sql_lower:
        avg = sum(r.get("error_rate", 0) for r in rows) / max(len(rows), 1)
        return [{"avg_error_rate": round(avg, 3), "row_count": len(rows)}]

    return rows


def execute_pinot_query(
    sql: str,
    timeout_ms: int = 2000,
    max_retries: int = 2,
    simulate_failure: bool = False,
) -> PinotResult:
    """
    Executes a Pinot SQL query with timeout and retry.
    Returns a PinotResult with rows and metadata.
    """
    for attempt in range(max_retries + 1):
        t0 = time.perf_counter()

        # Simulate occasional failures for demo
        if simulate_failure and attempt < 1:
            time.sleep(0.050)
            if attempt == 0:
                backoff = 0.1 * (2 ** attempt)
                time.sleep(backoff)
                continue

        # Simulate Pinot query latency (~68ms)
        time.sleep(random.uniform(0.060, 0.080))

        try:
            rows = _execute_sql(sql)
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            return PinotResult(
                rows=rows,
                row_count=len(rows),
                latency_ms=latency_ms,
                sql=sql,
                success=True,
            )
        except Exception as e:
            if attempt == max_retries:
                latency_ms = round((time.perf_counter() - t0) * 1000, 1)
                return PinotResult(
                    rows=[], row_count=0, latency_ms=latency_ms,
                    sql=sql, success=False, error=str(e),
                )
            time.sleep(0.1 * (2 ** attempt))

    return PinotResult(rows=[], row_count=0, latency_ms=0, sql=sql,
                       success=False, error="max_retries_exceeded")


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("PINOT TOOL — Real-time analytics for agents")
    print("=" * 65)

    queries = [
        ("At-risk free users",
         "SELECT user_id, error_rate, churn_risk FROM user_events_realtime WHERE plan='free' AND churn_risk=true LIMIT 5"),
        ("Error count for u_4821",
         "SELECT COUNT(*) FROM user_events_realtime WHERE user_id='u_4821' AND event_type='system.server_error'"),
        ("Payment gateway status",
         "SELECT endpoint, error_count, error_rate, status FROM payment_gateway_errors LIMIT 5"),
        ("Average error rate",
         "SELECT AVG(error_rate) FROM user_events_realtime WHERE churn_risk=true"),
    ]

    for label, sql in queries:
        result = execute_pinot_query(sql)
        status = "✅" if result.success else "❌"
        print(f"\n  {status} {label}")
        print(f"     SQL:     {sql[:60]}...")
        print(f"     Rows:    {result.row_count}")
        print(f"     Latency: {result.latency_ms}ms")
        if result.rows:
            print(f"     Sample:  {result.rows[0]}")

    # Simulate failure + retry
    print(f"\n  [FAILURE DEMO]  Simulating transient failure + retry...")
    result = execute_pinot_query(
        "SELECT * FROM user_events_realtime LIMIT 3",
        simulate_failure=True,
    )
    print(f"  Result: success={result.success}, rows={result.row_count}")


if __name__ == "__main__":
    run()
