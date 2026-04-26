"""
Event Producer — Day 03: The New Stack
========================================
Simulates an application publishing events to a Kafka topic.

In production:
    from confluent_kafka import Producer
    p = Producer({'bootstrap.servers': 'kafka:9092'})
    p.produce('user.events', key=user_id, value=json.dumps(event))
    p.flush()

Here we simulate the producer as a generator that yields messages,
demonstrating the event schema and publish pattern without requiring
a running Kafka cluster.
"""

import json
import random
import time
from datetime import datetime


# ── EVENT SCHEMA ──────────────────────────────────────────────────────────────
# Every event published to Kafka follows this schema.
# In production: enforce with Avro + Schema Registry.

def make_event(user_id: str, event_type: str, properties: dict) -> dict:
    return {
        "schema_version": "1.0",
        "event_id":       f"evt_{random.randint(100000, 999999)}",
        "user_id":        user_id,
        "event_type":     event_type,
        "ts":             datetime.now().isoformat(),
        "properties":     properties,
    }


# ── EVENT CATALOG ─────────────────────────────────────────────────────────────

EVENT_TEMPLATES = [
    ("page_view",  lambda: {"page": random.choice(["/home", "/pricing", "/docs", "/checkout", "/settings"])}),
    ("click",      lambda: {"element": random.choice(["cta_upgrade", "nav_pricing", "btn_signup", "link_docs"])}),
    ("error",      lambda: {"code": random.choice([400, 404, 500, 503]), "page": "/checkout"}),
    ("purchase",   lambda: {"plan": random.choice(["pro", "enterprise"]), "amount_usd": random.choice([49, 199, 499])}),
    ("logout",     lambda: {"session_duration_s": random.randint(30, 1800)}),
]

USERS = ["u_001", "u_002", "u_003", "u_004", "u_005"]


# ── SIMULATED KAFKA PRODUCER ──────────────────────────────────────────────────

class MockKafkaProducer:
    """
    Simulates confluent_kafka.Producer.
    Yields (topic, partition, key, value) tuples instead of actually publishing.
    """
    def __init__(self, topic: str, partitions: int = 3):
        self.topic = topic
        self.partitions = partitions
        self._offset = 0

    def produce(self, key: str, value: dict) -> dict:
        partition = hash(key) % self.partitions
        msg = {
            "topic":     self.topic,
            "partition": partition,
            "offset":    self._offset,
            "key":       key,
            "value":     value,
        }
        self._offset += 1
        return msg

    def flush(self):
        pass  # no-op in mock


# ── PRODUCER LOOP ─────────────────────────────────────────────────────────────

def run_producer(n_events: int = 15, rate_per_sec: float = 5.0) -> None:
    producer = MockKafkaProducer(topic="user.events", partitions=3)
    interval = 1.0 / rate_per_sec

    print(f"[PRODUCER] Topic: {producer.topic} | Partitions: {producer.partitions}")
    print(f"[PRODUCER] Publishing {n_events} events at ~{rate_per_sec}/sec\n")

    for i in range(n_events):
        user_id = random.choice(USERS)
        etype, props_fn = random.choice(EVENT_TEMPLATES)
        event = make_event(user_id, etype, props_fn())

        msg = producer.produce(key=user_id, value=event)

        print(
            f"  → [p{msg['partition']}|off={msg['offset']:04d}]  "
            f"{user_id}  {etype:12s}  "
            f"{json.dumps(event['properties'])}"
        )
        time.sleep(interval)

    producer.flush()
    print(f"\n[PRODUCER] {n_events} events published to '{producer.topic}'")
    print(f"[PRODUCER] Consumers can read from offset 0 to replay all events")


if __name__ == "__main__":
    run_producer(n_events=15, rate_per_sec=4.0)
