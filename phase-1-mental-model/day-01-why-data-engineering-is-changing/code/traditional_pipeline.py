"""
Traditional Data Pipeline — Day 01
===================================
A realistic ETL pipeline that:
  1. Extracts user events from a source (simulated DB query)
  2. Transforms them into aggregated metrics
  3. Loads the result into a data warehouse table

This is the classic pattern: scheduled, deterministic, SQL-centric.
The consumer at the end is a human reading a dashboard.
"""

import json
from datetime import datetime, timedelta
from typing import Generator


# ── EXTRACT ──────────────────────────────────────────────────────────────────

def extract_user_events(since: datetime) -> Generator[dict, None, None]:
    """
    Simulates pulling raw user events from a source database.
    In production: replace with a DB cursor, Airbyte sync, or Fivetran connector.
    """
    # Simulated raw event rows
    raw_events = [
        {"user_id": "u_001", "event": "page_view",  "ts": since + timedelta(minutes=2),  "page": "/home"},
        {"user_id": "u_002", "event": "signup",      "ts": since + timedelta(minutes=5),  "page": "/register"},
        {"user_id": "u_001", "event": "page_view",  "ts": since + timedelta(minutes=8),  "page": "/pricing"},
        {"user_id": "u_003", "event": "purchase",   "ts": since + timedelta(minutes=12), "page": "/checkout"},
        {"user_id": "u_002", "event": "page_view",  "ts": since + timedelta(minutes=15), "page": "/home"},
        {"user_id": "u_001", "event": "churn",      "ts": since + timedelta(minutes=20), "page": None},
    ]
    for event in raw_events:
        yield event


# ── TRANSFORM ─────────────────────────────────────────────────────────────────

def transform_events(events: list[dict]) -> list[dict]:
    """
    Aggregates raw events into per-user metrics.
    In production: this runs in Spark, dbt, or a SQL transformation layer.
    """
    user_metrics: dict[str, dict] = {}

    for event in events:
        uid = event["user_id"]
        if uid not in user_metrics:
            user_metrics[uid] = {
                "user_id": uid,
                "page_views": 0,
                "signed_up": False,
                "purchased": False,
                "churned": False,
                "last_seen": None,
            }

        m = user_metrics[uid]
        m["last_seen"] = event["ts"].isoformat()

        if event["event"] == "page_view":
            m["page_views"] += 1
        elif event["event"] == "signup":
            m["signed_up"] = True
        elif event["event"] == "purchase":
            m["purchased"] = True
        elif event["event"] == "churn":
            m["churned"] = True

    return list(user_metrics.values())


# ── LOAD ──────────────────────────────────────────────────────────────────────

def load_to_warehouse(records: list[dict]) -> None:
    """
    Writes aggregated records to the data warehouse.
    In production: INSERT INTO snowflake.analytics.user_metrics ...
    """
    print("\n[LOAD] Writing to warehouse table: analytics.user_metrics")
    print("-" * 60)
    for record in records:
        print(json.dumps(record, indent=2))
    print(f"\n[LOAD] {len(records)} records written.")


# ── PIPELINE RUNNER ───────────────────────────────────────────────────────────

def run_pipeline(batch_start: datetime) -> None:
    print(f"\n[PIPELINE] Starting batch run for window: {batch_start.isoformat()}")
    print("=" * 60)

    # Step 1: Extract
    print("[EXTRACT] Pulling events from source...")
    events = list(extract_user_events(since=batch_start))
    print(f"[EXTRACT] {len(events)} events pulled.")

    # Step 2: Transform
    print("\n[TRANSFORM] Aggregating user metrics...")
    metrics = transform_events(events)
    print(f"[TRANSFORM] {len(metrics)} user records produced.")

    # Step 3: Load
    load_to_warehouse(metrics)

    print("\n[PIPELINE] Batch complete.")
    print("Consumer: analyst runs SQL query → dashboard updates.")


if __name__ == "__main__":
    # Simulates a scheduled hourly run
    batch_window_start = datetime.now() - timedelta(hours=1)
    run_pipeline(batch_start=batch_window_start)
