"""
Batch Pipeline — Day 02
========================
Scheduled ETL that processes a fixed window of user events.

Pattern:
  - Triggered by a scheduler (cron / Airflow)
  - Reads a bounded dataset (yesterday's events)
  - Transforms and aggregates
  - Writes to a data warehouse table

Key property: deterministic. Same input window → same output. Always.
"""

from datetime import datetime, timedelta
from typing import Generator
import json


# ── CONFIG ────────────────────────────────────────────────────────────────────

BATCH_WINDOW_HOURS = 24  # process the last 24 hours of data


# ── EXTRACT ───────────────────────────────────────────────────────────────────

def extract(window_start: datetime, window_end: datetime) -> Generator[dict, None, None]:
    """
    Reads raw events for the given time window.
    In production: SELECT * FROM events WHERE ts BETWEEN :start AND :end
    """
    simulated_events = [
        {"user_id": "u_001", "event": "page_view",  "ts": window_start + timedelta(minutes=10), "page": "/home"},
        {"user_id": "u_002", "event": "page_view",  "ts": window_start + timedelta(minutes=15), "page": "/pricing"},
        {"user_id": "u_001", "event": "purchase",   "ts": window_start + timedelta(minutes=40), "page": "/checkout"},
        {"user_id": "u_003", "event": "signup",     "ts": window_start + timedelta(minutes=60), "page": "/register"},
        {"user_id": "u_002", "event": "churn",      "ts": window_start + timedelta(minutes=90), "page": None},
        {"user_id": "u_003", "event": "page_view",  "ts": window_start + timedelta(minutes=120),"page": "/home"},
        {"user_id": "u_001", "event": "page_view",  "ts": window_start + timedelta(minutes=200),"page": "/docs"},
    ]
    for event in simulated_events:
        if window_start <= event["ts"] < window_end:
            yield event


# ── TRANSFORM ─────────────────────────────────────────────────────────────────

def transform(events: list[dict]) -> list[dict]:
    """
    Aggregates raw events into per-user daily metrics.
    In production: this is a dbt model or a Spark job.
    """
    agg: dict[str, dict] = {}

    for e in events:
        uid = e["user_id"]
        if uid not in agg:
            agg[uid] = {
                "user_id": uid,
                "page_views": 0,
                "signed_up": False,
                "purchased": False,
                "churned": False,
                "first_seen": e["ts"].isoformat(),
                "last_seen": e["ts"].isoformat(),
            }
        m = agg[uid]
        m["last_seen"] = e["ts"].isoformat()

        match e["event"]:
            case "page_view": m["page_views"] += 1
            case "signup":    m["signed_up"] = True
            case "purchase":  m["purchased"] = True
            case "churn":     m["churned"] = True

    return list(agg.values())


# ── LOAD ──────────────────────────────────────────────────────────────────────

def load(records: list[dict], table: str = "analytics.user_daily_metrics") -> None:
    """
    Writes aggregated records to the warehouse.
    In production: INSERT INTO snowflake.<table> or BigQuery MERGE.
    """
    print(f"\n[LOAD] → {table}")
    print(f"{'─' * 50}")
    for r in records:
        print(json.dumps(r))
    print(f"\n  {len(records)} records written.")


# ── PIPELINE ──────────────────────────────────────────────────────────────────

def run(reference_time: datetime | None = None) -> None:
    ref = reference_time or datetime.utcnow()
    window_end   = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start = window_end - timedelta(hours=BATCH_WINDOW_HOURS)

    print(f"[BATCH] Window: {window_start.date()} → {window_end.date()}")
    print(f"[BATCH] Trigger: scheduled (cron)")

    # Extract
    events = list(extract(window_start, window_end))
    print(f"[EXTRACT] {len(events)} events in window")

    # Transform
    records = transform(events)
    print(f"[TRANSFORM] {len(records)} user records aggregated")

    # Load
    load(records)

    print(f"\n[BATCH] Complete. Next run: {(window_end + timedelta(days=1)).date()} 00:00 UTC")
    print(f"[BATCH] Latency: up to {BATCH_WINDOW_HOURS}h (data is stale by design)")


if __name__ == "__main__":
    run(reference_time=datetime(2026, 4, 25, 6, 0, 0))
