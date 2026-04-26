"""
Stream Processor — Day 03: The New Stack
==========================================
Simulates a Flink stream processing job that:
  1. Consumes events from a Kafka topic (simulated)
  2. Enriches each event with user profile data
  3. Maintains per-user session state (simulates Flink ValueState)
  4. Detects anomalies (error spike within a session)
  5. Emits enriched events to two sinks:
       - Pinot sink (structured, queryable)
       - Embedding sink (text description for vector indexing)

In production: this is a Flink job defined as a DataStream pipeline.
The operator logic here maps directly to Flink's KeyedProcessFunction.
"""

import time
import random
from datetime import datetime
from collections import defaultdict


# ── SIMULATED USER PROFILE STORE ─────────────────────────────────────────────
# In production: Redis lookup or Flink async I/O against a feature store.

USER_PROFILES = {
    "u_001": {"plan": "free",       "country": "US", "signup_days_ago": 45,  "segment": "at_risk"},
    "u_002": {"plan": "pro",        "country": "UK", "signup_days_ago": 12,  "segment": "active"},
    "u_003": {"plan": "free",       "country": "DE", "signup_days_ago": 3,   "segment": "new"},
    "u_004": {"plan": "enterprise", "country": "SG", "signup_days_ago": 180, "segment": "champion"},
    "u_005": {"plan": "pro",        "country": "AU", "signup_days_ago": 60,  "segment": "active"},
}

def lookup_profile(user_id: str) -> dict:
    return USER_PROFILES.get(user_id, {"plan": "unknown", "country": "?", "signup_days_ago": 0, "segment": "unknown"})


# ── SESSION STATE ─────────────────────────────────────────────────────────────
# Simulates Flink per-key state (keyed by user_id).
# In production: Flink ValueState / MapState backed by RocksDB.

class SessionState:
    def __init__(self):
        self._events:  dict[str, int] = defaultdict(int)
        self._errors:  dict[str, int] = defaultdict(int)
        self._last_ts: dict[str, str] = {}

    def update(self, user_id: str, event_type: str, ts: str) -> dict:
        self._events[user_id] += 1
        if event_type == "error":
            self._errors[user_id] += 1
        self._last_ts[user_id] = ts
        return {
            "total_events": self._events[user_id],
            "error_count":  self._errors[user_id],
            "error_rate":   round(self._errors[user_id] / self._events[user_id], 3),
        }


# ── ANOMALY DETECTOR ──────────────────────────────────────────────────────────

ERROR_RATE_THRESHOLD = 0.35  # alert if >35% of events are errors (min 3 events)

def detect_anomaly(user_id: str, state_snap: dict) -> str | None:
    if state_snap["total_events"] >= 3 and state_snap["error_rate"] >= ERROR_RATE_THRESHOLD:
        return (
            f"HIGH_ERROR_RATE: user={user_id} "
            f"rate={state_snap['error_rate']:.0%} "
            f"({state_snap['error_count']}/{state_snap['total_events']} events)"
        )
    return None


# ── OUTPUT SINKS ──────────────────────────────────────────────────────────────

class PinotSink:
    """
    Simulates writing enriched events to Apache Pinot.
    In production: Pinot real-time table ingests from Kafka directly via connector.
    This sink represents the enriched Kafka topic that Pinot reads from.
    """
    def __init__(self):
        self._rows: list[dict] = []

    def write(self, row: dict) -> None:
        self._rows.append(row)

    def summary(self) -> None:
        print(f"\n[PINOT SINK] {len(self._rows)} rows written to user_events_realtime table")
        print(f"[PINOT SINK] Sample query: SELECT user_id, COUNT(*) FROM user_events_realtime")
        print(f"             WHERE event_type='error' AND ts > ago('1h') GROUP BY user_id")


class EmbeddingSink:
    """
    Simulates emitting event text to the embedding pipeline.
    In production: publish to a Kafka topic consumed by the embedding service.
    """
    def __init__(self):
        self._texts: list[str] = []

    def write(self, text: str) -> None:
        self._texts.append(text)

    def summary(self) -> None:
        print(f"\n[EMBED SINK] {len(self._texts)} event descriptions queued for embedding")
        print(f"[EMBED SINK] Sample: \"{self._texts[0][:80]}...\"" if self._texts else "")


# ── STREAM PROCESSOR ──────────────────────────────────────────────────────────

def event_to_text(enriched: dict) -> str:
    """Converts an enriched event to a natural language description for embedding."""
    p = enriched["profile"]
    return (
        f"User {enriched['user_id']} ({p['plan']} plan, {p['country']}, segment={p['segment']}) "
        f"performed '{enriched['event_type']}' at {enriched['ts']}. "
        f"Properties: {enriched['properties']}."
    )


def process(events: list[dict]) -> None:
    state   = SessionState()
    pinot   = PinotSink()
    embed   = EmbeddingSink()

    print("[FLINK] Stream processor started")
    print(f"[FLINK] Processing {len(events)} events\n")

    for i, raw in enumerate(events):
        uid   = raw["user_id"]
        etype = raw["event_type"]
        ts    = raw["ts"]

        # Step 1: Enrich
        profile = lookup_profile(uid)
        enriched = {**raw, "profile": profile}

        # Step 2: Update state
        snap = state.update(uid, etype, ts)

        # Step 3: Emit to Pinot sink
        pinot_row = {
            "user_id":    uid,
            "event_type": etype,
            "plan":       profile["plan"],
            "country":    profile["country"],
            "segment":    profile["segment"],
            "ts":         ts,
            "error_rate": snap["error_rate"],
        }
        pinot.write(pinot_row)

        # Step 4: Emit to embedding sink
        embed.write(event_to_text(enriched))

        # Step 5: Anomaly detection
        alert = detect_anomaly(uid, snap)
        alert_str = f"  ⚠️  ALERT: {alert}" if alert else ""

        print(
            f"  [evt {i:02d}]  {uid} ({profile['plan']:12s})  "
            f"{etype:12s}  errors={snap['error_count']}/{snap['total_events']}"
            f"{alert_str}"
        )

        time.sleep(0.04)

    pinot.summary()
    embed.summary()
    print(f"\n[FLINK] Processing complete")


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Simulate events arriving from Kafka
    random.seed(42)
    users  = ["u_001", "u_002", "u_003", "u_004", "u_005"]
    etypes = ["page_view", "click", "error", "purchase", "logout"]
    props  = [{"page": "/checkout"}, {"element": "cta_upgrade"}, {"code": 500}, {"plan": "pro"}, {}]

    events = []
    for _ in range(18):
        uid = random.choice(users)
        idx = random.randint(0, len(etypes)-1)
        events.append({
            "user_id":    uid,
            "event_type": etypes[idx],
            "ts":         datetime.now().isoformat(),
            "properties": props[idx],
        })

    process(events)
