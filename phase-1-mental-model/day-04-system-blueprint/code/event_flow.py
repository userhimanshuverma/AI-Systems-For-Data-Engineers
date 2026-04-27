"""
Event Flow — Day 04: System Blueprint
=======================================
Demonstrates the full write path of the system blueprint:

  Data Source → Kafka → Flink (enrich + route) → Pinot sink + Embedding sink

This is the data ingestion half of the system. Every user action
enters here and becomes queryable (Pinot) and retrievable (Vector Store)
within seconds.

Run this to see the write path end-to-end.
"""

import json
import time
import random
from datetime import datetime
from collections import defaultdict


# ── SIMULATED KAFKA ───────────────────────────────────────────────────────────

class KafkaTopic:
    """Simulates a Kafka topic with partitioned, ordered storage."""
    def __init__(self, name: str, partitions: int = 3):
        self.name = name
        self.partitions = partitions
        self._log: dict[int, list] = defaultdict(list)

    def publish(self, key: str, value: dict) -> dict:
        partition = hash(key) % self.partitions
        offset = len(self._log[partition])
        record = {"partition": partition, "offset": offset, "key": key, "value": value}
        self._log[partition].append(record)
        return record

    def consume(self):
        """Yields all records across all partitions in round-robin order."""
        iters = {p: iter(records) for p, records in self._log.items()}
        while iters:
            done = []
            for p, it in iters.items():
                try:
                    yield next(it)
                except StopIteration:
                    done.append(p)
            for p in done:
                del iters[p]
            if not iters:
                break

    def __len__(self):
        return sum(len(v) for v in self._log.values())


# ── USER PROFILE STORE (simulates Redis / feature store) ─────────────────────

PROFILES = {
    "u_001": {"plan": "free",       "country": "US", "segment": "at_risk"},
    "u_002": {"plan": "pro",        "country": "UK", "segment": "active"},
    "u_003": {"plan": "free",       "country": "DE", "segment": "new"},
    "u_004": {"plan": "enterprise", "country": "SG", "segment": "champion"},
}

def lookup_profile(user_id: str) -> dict:
    return PROFILES.get(user_id, {"plan": "unknown", "country": "?", "segment": "unknown"})


# ── FLINK OPERATOR (simulated) ────────────────────────────────────────────────

class FlinkProcessor:
    """
    Simulates a Flink KeyedProcessFunction.
    In production: a Flink job with DataStream API or Table API.
    """
    def __init__(self):
        self._session_state: dict[str, dict] = defaultdict(lambda: {"events": 0, "errors": 0})
        self.pinot_sink:  list[dict] = []
        self.embed_sink:  list[str]  = []

    def process(self, record: dict) -> None:
        event = record["value"]
        uid   = event["user_id"]
        etype = event["event_type"]

        # Step 1: Enrich with user profile
        profile = lookup_profile(uid)
        enriched = {**event, **profile}

        # Step 2: Update session state
        state = self._session_state[uid]
        state["events"] += 1
        if etype == "error":
            state["errors"] += 1

        # Step 3: Emit to Pinot sink (structured)
        self.pinot_sink.append({
            "user_id":    uid,
            "event_type": etype,
            "plan":       profile["plan"],
            "country":    profile["country"],
            "segment":    profile["segment"],
            "ts":         event["ts"],
            "error_rate": round(state["errors"] / state["events"], 3),
        })

        # Step 4: Emit to embedding sink (text for vectorization)
        text = (
            f"User {uid} ({profile['plan']} plan, {profile['country']}, "
            f"segment={profile['segment']}) performed '{etype}' "
            f"at {event['ts']}. Properties: {event.get('properties', {})}."
        )
        self.embed_sink.append(text)


# ── SINKS ─────────────────────────────────────────────────────────────────────

def pinot_write(rows: list[dict]) -> None:
    """Simulates Pinot real-time table ingestion."""
    print(f"\n[PINOT]  {len(rows)} rows written to user_events_realtime")
    print(f"[PINOT]  Sample: {json.dumps(rows[0])}" if rows else "")
    print(f"[PINOT]  Query: SELECT user_id, COUNT(*) FROM user_events_realtime")
    print(f"         WHERE event_type='error' AND ts > ago('1h') GROUP BY user_id")

def embedding_write(texts: list[str]) -> None:
    """Simulates the embedding pipeline receiving event texts."""
    print(f"\n[EMBED]  {len(texts)} event descriptions queued for vectorization")
    print(f"[EMBED]  Sample: \"{texts[0][:90]}...\"" if texts else "")
    print(f"[EMBED]  Next: embed → upsert to Qdrant (user_events namespace)")


# ── WRITE PATH RUNNER ─────────────────────────────────────────────────────────

def run_write_path(n_events: int = 12) -> None:
    print("=" * 60)
    print("[WRITE PATH] System Blueprint — Event Ingestion Flow")
    print("=" * 60)

    # Step 1: Produce events to Kafka
    topic = KafkaTopic("user.events", partitions=3)
    event_templates = [
        ("page_view",  {"page": "/pricing"}),
        ("click",      {"element": "cta_upgrade"}),
        ("error",      {"code": 500, "page": "/checkout"}),
        ("purchase",   {"plan": "pro", "amount_usd": 49}),
        ("page_view",  {"page": "/home"}),
    ]
    users = list(PROFILES.keys())

    print(f"\n[KAFKA]  Publishing {n_events} events to topic: {topic.name}")
    for i in range(n_events):
        uid = random.choice(users)
        etype, props = random.choice(event_templates)
        event = {"user_id": uid, "event_type": etype, "ts": datetime.now().isoformat(), "properties": props}
        rec = topic.publish(key=uid, value=event)
        print(f"  → [p{rec['partition']}|off={rec['offset']:03d}]  {uid}  {etype:12s}  {props}")
        time.sleep(0.05)

    print(f"\n[KAFKA]  {len(topic)} events stored across {topic.partitions} partitions")

    # Step 2: Flink consumes and processes
    print(f"\n[FLINK]  Stream processor consuming from {topic.name}...")
    flink = FlinkProcessor()
    for record in topic.consume():
        flink.process(record)

    print(f"[FLINK]  {len(flink.pinot_sink)} enriched events processed")

    # Step 3: Write to sinks
    pinot_write(flink.pinot_sink)
    embedding_write(flink.embed_sink)

    print(f"\n[WRITE PATH] Complete")
    print(f"  Data is now queryable in Pinot (SQL) and Vector Store (semantic)")
    print(f"  Latency from event publish to queryable: ~1-2 seconds")


if __name__ == "__main__":
    random.seed(42)
    run_write_path(n_events=12)
