"""
Without Pinot Query — Day 08: Real-Time Analytics with Pinot
=============================================================
Demonstrates what happens when you try to answer real-time analytical
questions WITHOUT Apache Pinot.

Two alternatives are simulated:
  1. Kafka Direct — scan the raw event log (no SQL, no aggregations)
  2. Batch Warehouse — query a warehouse that updates hourly

Both fail in different ways. This is why Pinot exists.
"""

import time
import random
from datetime import datetime, timezone, timedelta


# ── OPTION 1: KAFKA DIRECT ────────────────────────────────────────────────────

class KafkaDirectQuery:
    """
    Simulates trying to answer analytical questions by scanning Kafka directly.
    In production: you'd use a Kafka consumer to read all messages.
    This is what teams do before they have Pinot — and why it doesn't scale.
    """
    def __init__(self, n_events: int = 60):
        random.seed(42)
        self._events = self._generate_events(n_events)

    def _generate_events(self, n: int) -> list[dict]:
        users = ["u_4821", "u_0012", "u_7734", "u_9901"]
        etypes = ["ui.page_view", "system.server_error", "ui.button_click"]
        now = datetime.now(timezone.utc)
        events = []
        for i in range(n):
            events.append({
                "user_id":    random.choice(users),
                "event_type": random.choice(etypes),
                "ts":         (now - timedelta(seconds=random.randint(0, 7200))).isoformat(),
                "page":       random.choice(["/checkout", "/pricing", "/home"]),
            })
        return events

    def count_errors_for_user(self, user_id: str) -> dict:
        """
        Simulates scanning Kafka to count errors for a user.
        Problems:
          - Must read ALL messages to find the relevant ones
          - No SQL, no GROUP BY, no aggregation functions
          - Latency scales with topic size, not result size
          - Cannot filter by time without reading everything
        """
        print(f"\n[KAFKA DIRECT]  Scanning topic for user {user_id}...")
        print(f"[KAFKA DIRECT]  Reading {len(self._events)} messages from beginning...")

        # Simulate the time to scan all messages
        scan_time_ms = len(self._events) * 2  # 2ms per message
        time.sleep(scan_time_ms / 1000)

        # Manual aggregation (what you'd have to write yourself)
        errors = sum(
            1 for e in self._events
            if e["user_id"] == user_id and e["event_type"] == "system.server_error"
        )

        print(f"[KAFKA DIRECT]  Scanned {len(self._events)} messages")
        print(f"[KAFKA DIRECT]  Found {errors} errors for {user_id}")
        print(f"[KAFKA DIRECT]  Latency: ~{scan_time_ms}ms (scales with topic size)")
        print(f"[KAFKA DIRECT]  ❌ Cannot do GROUP BY, ORDER BY, or LIMIT")
        print(f"[KAFKA DIRECT]  ❌ Cannot filter by enriched fields (plan, segment)")
        print(f"[KAFKA DIRECT]  ❌ Latency grows as topic grows — unusable at scale")

        return {"user_id": user_id, "error_count": errors, "latency_ms": scan_time_ms}


# ── OPTION 2: BATCH WAREHOUSE ─────────────────────────────────────────────────

class BatchWarehouseQuery:
    """
    Simulates querying a data warehouse (Snowflake/BigQuery) that
    is updated by a batch pipeline running every hour.
    """
    def __init__(self):
        random.seed(42)
        # Simulate data that was loaded in the last batch run (1 hour ago)
        self._last_batch_run = datetime.now(timezone.utc) - timedelta(hours=1)
        self._data_age_minutes = 60 + random.randint(0, 30)  # 60-90 min stale

    def count_errors_for_user(self, user_id: str) -> dict:
        """
        Simulates a warehouse query.
        Problems:
          - Data is 60-90 minutes stale (last batch run)
          - A user who churned 5 minutes ago looks healthy
          - Query itself is fast, but the data is wrong
        """
        print(f"\n[BATCH WAREHOUSE]  Querying Snowflake for user {user_id}...")
        print(f"[BATCH WAREHOUSE]  Last batch run: {self._last_batch_run.strftime('%H:%M:%S')} UTC")
        print(f"[BATCH WAREHOUSE]  Data age: ~{self._data_age_minutes} minutes")

        # Simulate warehouse query latency (fast query, stale data)
        query_time_ms = random.randint(800, 3000)
        time.sleep(query_time_ms / 1000)

        # Return stale data — misses events from the last hour
        stale_errors = random.randint(0, 2)  # doesn't include recent errors

        print(f"[BATCH WAREHOUSE]  Query completed in {query_time_ms}ms")
        print(f"[BATCH WAREHOUSE]  Result: {stale_errors} errors (STALE — missing last {self._data_age_minutes} min)")
        print(f"[BATCH WAREHOUSE]  ❌ Data is {self._data_age_minutes} minutes old")
        print(f"[BATCH WAREHOUSE]  ❌ Events from the last hour are NOT included")
        print(f"[BATCH WAREHOUSE]  ❌ A user who just hit 5 errors looks healthy")

        return {
            "user_id":       user_id,
            "error_count":   stale_errors,
            "data_age_min":  self._data_age_minutes,
            "latency_ms":    query_time_ms,
            "warning":       f"Data is {self._data_age_minutes} minutes stale",
        }

    def get_churn_risk_users(self) -> dict:
        """
        Simulates getting at-risk users from a batch warehouse.
        The list is from the last batch run — potentially hours old.
        """
        print(f"\n[BATCH WAREHOUSE]  Getting churn risk users...")
        print(f"[BATCH WAREHOUSE]  Data age: ~{self._data_age_minutes} minutes")

        time.sleep(random.randint(2000, 8000) / 1000)  # 2-8 second query

        return {
            "at_risk_users":  ["u_4821", "u_7734"],  # stale list
            "data_age_min":   self._data_age_minutes,
            "warning":        "This list was computed in the last batch run. "
                              "Users who became at-risk in the last hour are NOT included.",
        }


# ── COMPARISON DEMO ───────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("WITHOUT PINOT — Two alternatives and why they fail")
    print("=" * 65)

    user_id = "u_4821"

    # Option 1: Kafka Direct
    print(f"\n{'─'*65}")
    print(f"OPTION 1: Kafka Direct Scan")
    print(f"{'─'*65}")
    kafka = KafkaDirectQuery(n_events=60)
    kafka_result = kafka.count_errors_for_user(user_id)

    # Option 2: Batch Warehouse
    print(f"\n{'─'*65}")
    print(f"OPTION 2: Batch Warehouse (Snowflake/BigQuery)")
    print(f"{'─'*65}")
    warehouse = BatchWarehouseQuery()
    warehouse_result = warehouse.count_errors_for_user(user_id)
    churn_result = warehouse.get_churn_risk_users()

    # Summary comparison
    print(f"\n{'='*65}")
    print(f"COMPARISON SUMMARY")
    print(f"{'='*65}")
    print(f"\n  {'Approach':25s} {'Latency':12s} {'Data Age':15s} {'SQL Support':12s}")
    print(f"  {'-'*65}")
    print(f"  {'Kafka Direct':25s} {'~120ms':12s} {'Real-time':15s} {'❌ None':12s}")
    print(f"  {'Batch Warehouse':25s} {'~2000ms':12s} {'60-90 min':15s} {'✅ Full':12s}")
    print(f"  {'Apache Pinot':25s} {'~68ms':12s} {'~1 second':15s} {'✅ Full':12s}")
    print(f"\n  Kafka Direct:    Fast but no SQL. Cannot aggregate. Unusable at scale.")
    print(f"  Batch Warehouse: Full SQL but stale data. Misses recent events.")
    print(f"  Apache Pinot:    Fast + full SQL + fresh data. Best of both worlds.")
    print(f"\n  → Pinot is the only option that satisfies all three requirements.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
