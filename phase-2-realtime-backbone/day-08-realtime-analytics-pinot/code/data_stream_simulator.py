"""
Data Stream Simulator — Day 08: Real-Time Analytics with Pinot
===============================================================
Simulates enriched events flowing from Kafka into Apache Pinot.
Generates realistic data that demonstrates Pinot's query capabilities.

This is the data generation layer. Run this first, then run
pinot_query_simulation.py to see queries against this data.
"""

import uuid
import random
from datetime import datetime, timezone, timedelta
from collections import defaultdict


# ── USER PROFILES ─────────────────────────────────────────────────────────────

USERS = {
    "u_4821": {"plan": "free",       "country": "US", "segment": "at_risk",  "lifetime_orders": 0},
    "u_0012": {"plan": "pro",        "country": "UK", "segment": "active",   "lifetime_orders": 4},
    "u_7734": {"plan": "free",       "country": "DE", "segment": "new",      "lifetime_orders": 0},
    "u_9901": {"plan": "enterprise", "country": "SG", "segment": "champion", "lifetime_orders": 18},
    "u_3344": {"plan": "free",       "country": "AU", "segment": "at_risk",  "lifetime_orders": 1},
    "u_5566": {"plan": "pro",        "country": "CA", "segment": "active",   "lifetime_orders": 7},
}

PAGES = ["/home", "/pricing", "/checkout", "/docs", "/settings", "/billing"]
EVENT_TYPES = [
    "ui.page_view", "ui.page_view", "ui.page_view",  # weighted higher
    "ui.button_click",
    "system.server_error", "system.server_error",    # weighted higher for demo
    "commerce.purchase",
    "auth.login",
]


# ── PINOT ROW BUILDER ─────────────────────────────────────────────────────────

class PinotRowBuilder:
    """
    Builds flat Pinot table rows from simulated events.
    Maintains per-session state to compute session-level columns.
    In production: Flink enrichment produces these rows before Pinot ingestion.
    """
    def __init__(self):
        self._sessions: dict[str, dict] = defaultdict(lambda: {
            "event_count":    0,
            "error_count":    0,
            "pricing_visits": 0,
            "start_ts":       None,
        })

    def build_row(self, user_id: str, event_type: str, page: str,
                  ts: datetime) -> dict:
        profile    = USERS[user_id]
        session_id = f"sess_{user_id[-4:]}"
        s          = self._sessions[session_id]

        # Update session state
        if s["start_ts"] is None:
            s["start_ts"] = ts
        s["event_count"] += 1
        if "error" in event_type:
            s["error_count"] += 1
        if page == "/pricing":
            s["pricing_visits"] += 1

        duration_s  = int((ts - s["start_ts"]).total_seconds()) if s["start_ts"] else 0
        error_rate  = round(s["error_count"] / max(s["event_count"], 1), 3)
        churn_risk  = error_rate >= 0.25 and profile["plan"] == "free"
        intent_score = round(min(s["pricing_visits"] * 0.25 + (0.15 if profile["segment"] == "at_risk" else 0), 1.0), 2)
        is_high_value = profile["lifetime_orders"] > 2 and duration_s > 300

        return {
            # Core event
            "event_id":       str(uuid.uuid4())[:8],
            "event_type":     event_type,
            "user_id":        user_id,
            "session_id":     session_id,
            "ts":             ts.isoformat(),
            "page":           page,
            "error_code":     500 if "error" in event_type else None,
            # Static enrichment
            "plan":           profile["plan"],
            "country":        profile["country"],
            "segment":        profile["segment"],
            "lifetime_orders":profile["lifetime_orders"],
            # Session state
            "session_events": s["event_count"],
            "session_errors": s["error_count"],
            "pricing_visits": s["pricing_visits"],
            "duration_s":     duration_s,
            # Derived features
            "error_rate":     error_rate,
            "churn_risk":     churn_risk,
            "intent_score":   intent_score,
            "is_high_value":  is_high_value,
        }


# ── STREAM GENERATOR ──────────────────────────────────────────────────────────

def generate_stream(n_events: int = 60, seed: int = 42) -> list[dict]:
    """
    Generates a realistic stream of enriched events.
    Returns a list of Pinot-ready rows.
    """
    random.seed(seed)
    builder = PinotRowBuilder()
    rows    = []
    now     = datetime.now(timezone.utc)

    # Generate events spread over the last 2 hours
    user_ids = list(USERS.keys())
    for i in range(n_events):
        user_id    = random.choice(user_ids)
        event_type = random.choice(EVENT_TYPES)
        page       = random.choice(PAGES)
        ts         = now - timedelta(seconds=random.randint(0, 7200))

        # u_4821 gets extra errors to demonstrate churn detection
        if user_id == "u_4821" and random.random() < 0.4:
            event_type = "system.server_error"
            page       = "/checkout"

        row = builder.build_row(user_id, event_type, page, ts)
        rows.append(row)

    # Sort by timestamp
    rows.sort(key=lambda r: r["ts"])
    return rows


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> list[dict]:
    print("=" * 65)
    print("DATA STREAM SIMULATOR — Generating Pinot table rows")
    print("=" * 65)

    rows = generate_stream(n_events=60)

    print(f"\n[STREAM]  {len(rows)} enriched events generated")
    print(f"[PINOT]   Table: user_events_realtime")
    print(f"[PINOT]   Columns: {len(rows[0])} (event fields + enrichment + derived)")

    print(f"\n[SAMPLE ROWS] (first 5)")
    print(f"  {'event_type':30s} {'user_id':8s} {'plan':6s} {'seg':10s} {'err':4s} {'rate':6s} {'churn':6s}")
    print(f"  {'-'*75}")
    for row in rows[:5]:
        print(
            f"  {row['event_type']:30s} "
            f"{row['user_id']:8s} "
            f"{row['plan']:6s} "
            f"{row['segment']:10s} "
            f"{row['session_errors']:4d} "
            f"{row['error_rate']:6.2f} "
            f"{'TRUE' if row['churn_risk'] else 'false':6s}"
        )

    # Summary stats
    churn_count  = sum(1 for r in rows if r["churn_risk"])
    intent_count = sum(1 for r in rows if r["intent_score"] > 0.5)
    error_count  = sum(1 for r in rows if r["event_type"] == "system.server_error")

    print(f"\n[STATS]")
    print(f"  Total events:          {len(rows)}")
    print(f"  Error events:          {error_count}")
    print(f"  Churn risk rows:       {churn_count}")
    print(f"  High intent rows:      {intent_count}")
    print(f"  Unique users:          {len(set(r['user_id'] for r in rows))}")
    print(f"\n[READY]  Data available for Pinot queries")

    return rows


if __name__ == "__main__":
    run()
