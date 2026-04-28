"""
Kafka Consumer — Day 05: Event-Driven Systems
===============================================
Consumes events from a Kafka topic and processes them.

TWO MODES:
  1. Real Kafka (requires Docker setup from docker-compose.yml)
     Install: pip install confluent-kafka
     Run:     docker compose up -d
              python producer.py --mode real   (in another terminal)
              python consumer.py --mode real

  2. Mock mode (no dependencies, runs immediately)
     Run:     python consumer.py

The consumer demonstrates:
  - Reading events from a topic
  - Deserializing JSON payloads
  - Processing logic (enrich, filter, route)
  - Committing offsets (tracking position in the log)
  - Handling consumer group semantics
"""

import json
import sys
import time
import random
from datetime import datetime
from collections import defaultdict


# ── USER PROFILE STORE (simulates Redis / feature store lookup) ───────────────

PROFILES = {
    "u_001": {"plan": "free",       "country": "US", "segment": "at_risk"},
    "u_002": {"plan": "pro",        "country": "UK", "segment": "active"},
    "u_003": {"plan": "free",       "country": "DE", "segment": "new"},
    "u_004": {"plan": "enterprise", "country": "SG", "segment": "champion"},
    "u_005": {"plan": "pro",        "country": "AU", "segment": "active"},
}

def enrich(event: dict) -> dict:
    profile = PROFILES.get(event.get("user_id", ""), {})
    return {**event, "profile": profile}


# ── PROCESSING LOGIC ──────────────────────────────────────────────────────────

class EventProcessor:
    """
    Stateful event processor. Tracks per-user metrics across events.
    In production: this state lives in Flink's RocksDB state backend.
    """
    def __init__(self):
        self._counts:  dict[str, int] = defaultdict(int)
        self._errors:  dict[str, int] = defaultdict(int)
        self._alerts:  list[str]      = []

    def process(self, event: dict) -> dict:
        uid   = event.get("user_id", "unknown")
        etype = event.get("event_type", "unknown")

        self._counts[uid] += 1
        if etype == "server_error":
            self._errors[uid] += 1

        error_rate = self._errors[uid] / self._counts[uid]

        # Alert if error rate exceeds threshold (min 3 events)
        if self._counts[uid] >= 3 and error_rate >= 0.4:
            alert = f"HIGH_ERROR_RATE: user={uid} rate={error_rate:.0%} ({self._errors[uid]}/{self._counts[uid]})"
            if alert not in self._alerts:
                self._alerts.append(alert)
                print(f"  ⚠️  ALERT: {alert}")

        return {
            "user_id":    uid,
            "event_type": etype,
            "total":      self._counts[uid],
            "errors":     self._errors[uid],
            "error_rate": round(error_rate, 3),
        }

    def summary(self) -> None:
        print(f"\n[PROCESSOR] Session summary:")
        for uid in sorted(self._counts):
            print(f"  {uid}: {self._counts[uid]} events, {self._errors[uid]} errors")


# ── MOCK CONSUMER ─────────────────────────────────────────────────────────────

class MockConsumer:
    """
    Simulates confluent_kafka.Consumer without a running broker.
    Generates synthetic events to demonstrate consumer logic.
    """
    def __init__(self, topic: str, group_id: str, n_events: int = 20):
        self.topic    = topic
        self.group_id = group_id
        self._n       = n_events
        self._offset  = 0
        self._committed_offset = -1

        users  = ["u_001", "u_002", "u_003", "u_004", "u_005"]
        etypes = ["page_view", "button_click", "server_error",
                  "payment_processed", "session_start", "session_end"]
        props  = [{"page": "/checkout"}, {"element": "cta_upgrade"},
                  {"code": 500, "page": "/checkout"}, {"amount_usd": 49},
                  {"referrer": "google"}, {"duration_s": 300}]

        self._messages = []
        random.seed(42)
        for i in range(n_events):
            uid = random.choice(users)
            idx = random.randint(0, len(etypes) - 1)
            self._messages.append({
                "partition": hash(uid) % 3,
                "offset":    i,
                "key":       uid,
                "value": json.dumps({
                    "event_id":       f"evt_{i:05d}",
                    "schema_version": "1.0",
                    "event_type":     etypes[idx],
                    "user_id":        uid,
                    "properties":     props[idx],
                    "ts":             datetime.now().isoformat(),
                }).encode("utf-8"),
            })

    def poll(self, timeout: float = 1.0):
        if self._offset >= self._n:
            return None
        msg = self._messages[self._offset]
        self._offset += 1
        time.sleep(0.06)  # simulate ~60ms poll interval
        return type('Msg', (), {
            'error':     lambda s: None,
            'topic':     lambda s: self.topic,
            'partition': lambda s: msg['partition'],
            'offset':    lambda s: msg['offset'],
            'key':       lambda s: msg['key'].encode('utf-8'),
            'value':     lambda s: msg['value'],
        })()

    def commit(self, asynchronous: bool = True) -> None:
        self._committed_offset = self._offset - 1

    def close(self) -> None:
        print(f"  [CONSUMER] Closed. Committed offset: {self._committed_offset}")


# ── REAL CONSUMER ─────────────────────────────────────────────────────────────

def make_real_consumer(topic: str, group_id: str, bootstrap_servers: str = "localhost:9092"):
    try:
        from confluent_kafka import Consumer, KafkaError
    except ImportError:
        print("[ERROR] confluent-kafka not installed. Run: pip install confluent-kafka")
        sys.exit(1)

    conf = {
        "bootstrap.servers":        bootstrap_servers,
        "group.id":                 group_id,
        "auto.offset.reset":        "earliest",   # read from beginning if no committed offset
        "enable.auto.commit":       False,         # manual commit for exactly-once semantics
        "max.poll.interval.ms":     300000,
        "session.timeout.ms":       30000,
    }
    c = Consumer(conf)
    c.subscribe([topic])
    return c


# ── CONSUMER LOOP ─────────────────────────────────────────────────────────────

def run(mode: str = "mock", max_events: int = 20) -> None:
    topic    = "user.events"
    group_id = "day05-consumer-group"

    print(f"[CONSUMER] Mode: {mode.upper()}")
    print(f"[CONSUMER] Topic: {topic} | Group: {group_id}\n")

    consumer  = MockConsumer(topic, group_id, n_events=max_events) if mode == "mock" \
                else make_real_consumer(topic, group_id)
    processor = EventProcessor()
    processed = 0

    try:
        while True:
            msg = consumer.poll(timeout=1.0)

            if msg is None:
                if mode == "mock":
                    break  # mock consumer exhausted
                continue   # real consumer: keep polling

            if msg.error():
                print(f"  [ERROR] {msg.error()}")
                continue

            # Deserialize
            raw = json.loads(msg.value().decode("utf-8"))

            # Enrich
            enriched = enrich(raw)

            # Process
            state = processor.process(enriched)

            # Log
            profile = enriched.get("profile", {})
            print(
                f"  [p{msg.partition()}|off={msg.offset():04d}]  "
                f"{raw['user_id']} ({profile.get('plan','?'):12s})  "
                f"{raw['event_type']:20s}  "
                f"errors={state['errors']}/{state['total']}"
            )

            # Commit offset every 5 messages
            processed += 1
            if processed % 5 == 0:
                consumer.commit(asynchronous=True)
                print(f"  [CONSUMER] Offset committed at {msg.offset()}")

    except KeyboardInterrupt:
        print("\n[CONSUMER] Interrupted by user")
    finally:
        consumer.close()
        processor.summary()
        print(f"\n[CONSUMER] {processed} events processed")
        if mode == "mock":
            print(f"[CONSUMER] To use real Kafka: docker compose up -d && python consumer.py --mode real")


if __name__ == "__main__":
    mode = "mock"
    if "--mode" in sys.argv:
        idx = sys.argv.index("--mode")
        if idx + 1 < len(sys.argv):
            mode = sys.argv[idx + 1]

    run(mode=mode, max_events=20)
