"""
Kafka Producer — Day 05: Event-Driven Systems
===============================================
Publishes user activity events to a Kafka topic.

TWO MODES:
  1. Real Kafka (requires Docker setup from docker-compose.yml)
     Install: pip install confluent-kafka
     Run:     docker compose up -d  (from day-05 folder)
              python producer.py --mode real

  2. Mock mode (no dependencies, runs immediately)
     Run:     python producer.py
              python producer.py --mode mock

The event schema and logic are identical in both modes.
"""

import json
import sys
import time
import uuid
import random
from datetime import datetime, timezone

# ── EVENT SCHEMA ──────────────────────────────────────────────────────────────

def make_event(user_id: str, event_type: str, properties: dict) -> dict:
    """
    Canonical event schema for this system.
    In production: enforce with Avro + Schema Registry (Day 06).
    """
    return {
        "event_id":      str(uuid.uuid4()),
        "schema_version": "1.0",
        "event_type":    event_type,
        "user_id":       user_id,
        "properties":    properties,
        "ts":            datetime.now(timezone.utc).isoformat(),
    }

# ── EVENT CATALOG ─────────────────────────────────────────────────────────────

USERS = ["u_001", "u_002", "u_003", "u_004", "u_005"]

EVENT_TEMPLATES = [
    ("page_view",         lambda: {"page": random.choice(["/home", "/pricing", "/docs", "/checkout"])}),
    ("button_click",      lambda: {"element": random.choice(["cta_upgrade", "nav_pricing", "btn_signup"])}),
    ("server_error",      lambda: {"code": random.choice([400, 500, 503]), "page": "/checkout"}),
    ("payment_processed", lambda: {"amount_usd": random.choice([49, 199, 499]), "plan": "pro", "status": "success"}),
    ("session_start",     lambda: {"referrer": random.choice(["google", "direct", "email"])}),
    ("session_end",       lambda: {"duration_s": random.randint(30, 1800)}),
]

# ── MOCK PRODUCER ─────────────────────────────────────────────────────────────

class MockProducer:
    """
    Simulates confluent_kafka.Producer without requiring a running broker.
    Prints what would be published to Kafka.
    """
    def __init__(self, topic: str, partitions: int = 3):
        self.topic = topic
        self.partitions = partitions
        self._offset = 0
        self._published = 0

    def produce(self, key: str, value: dict, on_delivery=None) -> None:
        partition = hash(key) % self.partitions
        serialized = json.dumps(value)
        print(
            f"  [MOCK→KAFKA]  topic={self.topic}  "
            f"partition={partition}  offset={self._offset:05d}  "
            f"key={key}  event_type={value['event_type']}"
        )
        self._offset += 1
        self._published += 1
        if on_delivery:
            on_delivery(None, type('Msg', (), {'topic': lambda s: self.topic,
                                               'partition': lambda s: partition,
                                               'offset': lambda s: self._offset - 1})())

    def flush(self) -> None:
        print(f"  [MOCK→KAFKA]  flush() — {self._published} messages delivered")

# ── REAL PRODUCER ─────────────────────────────────────────────────────────────

def make_real_producer(bootstrap_servers: str = "localhost:9092"):
    """
    Creates a real confluent_kafka.Producer.
    Requires: pip install confluent-kafka
              docker compose up -d (from day-05 folder)
    """
    try:
        from confluent_kafka import Producer
    except ImportError:
        print("[ERROR] confluent-kafka not installed.")
        print("        Run: pip install confluent-kafka")
        sys.exit(1)

    conf = {
        "bootstrap.servers": bootstrap_servers,
        "acks":              "all",          # wait for all replicas to ack
        "retries":           3,
        "linger.ms":         5,              # batch events for 5ms before sending
        "compression.type":  "snappy",       # compress batches
    }
    return Producer(conf)

def delivery_report(err, msg):
    if err:
        print(f"  [ERROR] Delivery failed: {err}")
    else:
        print(
            f"  [KAFKA]  Delivered → topic={msg.topic()}  "
            f"partition={msg.partition()}  offset={msg.offset()}"
        )

# ── PRODUCER LOOP ─────────────────────────────────────────────────────────────

def run(mode: str = "mock", n_events: int = 15, rate_per_sec: float = 3.0) -> None:
    topic = "user.events"
    interval = 1.0 / rate_per_sec

    print(f"[PRODUCER] Mode: {mode.upper()}")
    print(f"[PRODUCER] Topic: {topic} | Events: {n_events} | Rate: {rate_per_sec}/sec\n")

    if mode == "real":
        producer = make_real_producer()
        def publish(key, value):
            producer.produce(
                topic=topic,
                key=key.encode("utf-8"),
                value=json.dumps(value).encode("utf-8"),
                on_delivery=delivery_report,
            )
            producer.poll(0)  # trigger delivery callbacks
    else:
        producer = MockProducer(topic=topic, partitions=3)
        def publish(key, value):
            producer.produce(key=key, value=value)

    for i in range(n_events):
        user_id = random.choice(USERS)
        etype, props_fn = random.choice(EVENT_TEMPLATES)
        event = make_event(user_id, etype, props_fn())
        publish(key=user_id, value=event)
        time.sleep(interval)

    if mode == "real":
        producer.flush()
        print(f"\n[PRODUCER] {n_events} events flushed to Kafka broker")
    else:
        producer.flush()
        print(f"\n[PRODUCER] {n_events} events published (mock mode)")
        print(f"[PRODUCER] To use real Kafka: docker compose up -d && python producer.py --mode real")


if __name__ == "__main__":
    mode = "mock"
    if "--mode" in sys.argv:
        idx = sys.argv.index("--mode")
        if idx + 1 < len(sys.argv):
            mode = sys.argv[idx + 1]

    random.seed(None)
    run(mode=mode, n_events=15, rate_per_sec=3.0)
