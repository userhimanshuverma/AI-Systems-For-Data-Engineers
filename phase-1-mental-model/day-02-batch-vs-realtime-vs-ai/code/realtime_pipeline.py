"""
Real-Time Pipeline — Day 02
=============================
Simulates a Kafka consumer that processes events as they arrive.

Pattern:
  - Events are published to a Kafka topic (simulated here as a generator)
  - A stream processor consumes each event immediately
  - Enriches with user metadata (simulates a lookup store like Redis)
  - Maintains a rolling in-memory state (simulates Flink state backend)
  - Emits alerts when thresholds are crossed

Key property: event-driven. Reacts within milliseconds of an event occurring.
"""

import time
import random
from datetime import datetime
from collections import defaultdict


# ── SIMULATED KAFKA PRODUCER ──────────────────────────────────────────────────

def kafka_topic(n_events: int = 20):
    """
    Simulates a Kafka topic as a generator.
    In production: confluent_kafka.Consumer.poll() or aiokafka.AIOKafkaConsumer
    Each yielded dict represents one Kafka message (key + value + timestamp).
    """
    event_types = ["page_view", "click", "error", "purchase", "logout"]
    users = ["u_001", "u_002", "u_003", "u_004"]
    pages = ["/home", "/pricing", "/checkout", "/docs", "/settings"]

    for i in range(n_events):
        yield {
            "offset": i,
            "key": random.choice(users),
            "value": {
                "user_id": random.choice(users),
                "event":   random.choice(event_types),
                "page":    random.choice(pages),
                "ts":      datetime.now().isoformat(),
                "session": f"sess_{random.randint(100, 999)}",
            },
            "partition": i % 3,
        }
        time.sleep(0.05)  # simulate ~20 events/sec


# ── ENRICHMENT (simulates Redis / feature store lookup) ───────────────────────

USER_STORE = {
    "u_001": {"plan": "free",  "country": "US", "signup_days_ago": 45},
    "u_002": {"plan": "pro",   "country": "UK", "signup_days_ago": 12},
    "u_003": {"plan": "free",  "country": "DE", "signup_days_ago": 3},
    "u_004": {"plan": "enterprise", "country": "SG", "signup_days_ago": 180},
}

def enrich(event: dict) -> dict:
    """
    Joins event with user profile.
    In production: Redis GET user:{id} or a feature store lookup.
    Latency target: < 5ms
    """
    profile = USER_STORE.get(event["user_id"], {"plan": "unknown", "country": "?", "signup_days_ago": 0})
    return {**event, **profile}


# ── STATEFUL PROCESSOR (simulates Flink operator) ─────────────────────────────

class SessionState:
    """
    Maintains per-user session state.
    In production: Flink ValueState / MapState backed by RocksDB.
    """
    def __init__(self):
        self._counts: dict[str, int] = defaultdict(int)
        self._errors: dict[str, int] = defaultdict(int)

    def update(self, event: dict) -> dict:
        uid = event["user_id"]
        self._counts[uid] += 1
        if event["event"] == "error":
            self._errors[uid] += 1
        return {
            "user_id":      uid,
            "event_count":  self._counts[uid],
            "error_count":  self._errors[uid],
            "error_rate":   round(self._errors[uid] / self._counts[uid], 2),
        }


# ── ALERT SINK ────────────────────────────────────────────────────────────────

ERROR_RATE_THRESHOLD = 0.3  # alert if >30% of events are errors

def check_alerts(state_snapshot: dict, event: dict) -> None:
    """
    Emits an alert if error rate crosses threshold.
    In production: publish to alert topic → PagerDuty / Slack webhook.
    """
    if state_snapshot["error_rate"] >= ERROR_RATE_THRESHOLD and state_snapshot["error_count"] >= 2:
        print(f"  ⚠️  ALERT: user {state_snapshot['user_id']} error rate "
              f"{state_snapshot['error_rate']:.0%} "
              f"({state_snapshot['error_count']}/{state_snapshot['event_count']} events)")


# ── STREAM PROCESSOR ──────────────────────────────────────────────────────────

def process_stream(topic, state: SessionState) -> None:
    """
    Main consumer loop. Processes each event as it arrives.
    In production: this is a Flink job or Kafka Streams topology.
    """
    print("[STREAM] Consumer started. Waiting for events...\n")

    for msg in topic:
        event = msg["value"]
        offset = msg["offset"]
        partition = msg["partition"]

        # Step 1: Enrich
        enriched = enrich(event)

        # Step 2: Update state
        snapshot = state.update(enriched)

        # Step 3: Log processed event
        print(
            f"  [p{partition}|off={offset:03d}] "
            f"{enriched['user_id']} ({enriched['plan']:12s}) "
            f"→ {enriched['event']:10s} "
            f"| errors: {snapshot['error_count']}/{snapshot['event_count']}"
        )

        # Step 4: Check alert conditions
        check_alerts(snapshot, enriched)

    print(f"\n[STREAM] Consumer finished. {offset + 1} events processed.")
    print(f"[STREAM] Latency: each event processed within ~50ms of arrival")
    print(f"[STREAM] Trigger: event-driven (no schedule, no waiting)")


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("[STREAM] Simulating Kafka topic: user.events")
    print("[STREAM] Partitions: 3 | Simulated rate: ~20 events/sec\n")

    state = SessionState()
    topic = kafka_topic(n_events=20)
    process_stream(topic, state)
