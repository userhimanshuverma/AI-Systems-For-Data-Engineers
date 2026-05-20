"""
Day 27 — Event Producer (Kafka Simulation)
===========================================
Simulates a Kafka-style event ingestion layer that produces structured
user-behavior events into partitioned topics.

Architecture Role:
    This is the ENTRY POINT of the entire AI system. Every downstream
    component — stream processing, analytics, retrieval, reasoning —
    depends on high-quality, schema-compliant events flowing in here.

Production Considerations:
    - Events are keyed by user_id for partition affinity (co-located processing)
    - Schema includes event_type, timestamp, metadata, and session context
    - Delivery guarantee: at-least-once (idempotent producer in real Kafka)
    - Back-pressure handling via configurable batch sizes and linger times
"""

import json
import time
import uuid
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict


# ---------------------------------------------------------------------------
# Event Schema
# ---------------------------------------------------------------------------

@dataclass
class UserEvent:
    """Schema-enforced event matching an Avro/Protobuf contract."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    user_id: str = ""
    session_id: str = ""
    timestamp: str = ""
    properties: Dict = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)

    def serialize(self) -> bytes:
        """Serialize to JSON bytes (production would use Avro/Protobuf)."""
        return json.dumps(asdict(self), ensure_ascii=False).encode("utf-8")

    @classmethod
    def deserialize(cls, raw: bytes) -> "UserEvent":
        data = json.loads(raw.decode("utf-8"))
        return cls(**data)


# ---------------------------------------------------------------------------
# Partition Strategy
# ---------------------------------------------------------------------------

def partition_key(user_id: str, num_partitions: int = 12) -> int:
    """
    Murmur-style hash partitioning (simplified).
    Ensures all events for the same user land on the same partition,
    enabling ordered per-user processing downstream.
    """
    hash_val = hash(user_id)
    return abs(hash_val) % num_partitions


# ---------------------------------------------------------------------------
# Event Templates — Realistic User Behavior
# ---------------------------------------------------------------------------

EVENT_TEMPLATES = [
    {
        "event_type": "page_view",
        "properties": lambda: {
            "page": random.choice(["/dashboard", "/pricing", "/settings", "/features", "/docs"]),
            "referrer": random.choice(["google", "direct", "email_campaign", "social"]),
            "load_time_ms": random.randint(120, 3500),
        },
    },
    {
        "event_type": "feature_used",
        "properties": lambda: {
            "feature": random.choice(["export_csv", "create_report", "invite_team", "api_call", "webhook_setup"]),
            "duration_ms": random.randint(500, 45000),
            "success": random.choice([True, True, True, False]),  # 75% success rate
        },
    },
    {
        "event_type": "subscription_event",
        "properties": lambda: {
            "action": random.choice(["upgrade", "downgrade", "cancel", "renew"]),
            "plan": random.choice(["starter", "professional", "enterprise"]),
            "mrr_delta": round(random.uniform(-500, 2000), 2),
        },
    },
    {
        "event_type": "support_ticket",
        "properties": lambda: {
            "category": random.choice(["billing", "bug_report", "feature_request", "onboarding"]),
            "priority": random.choice(["low", "medium", "high", "critical"]),
            "sentiment_score": round(random.uniform(-1.0, 1.0), 3),
        },
    },
    {
        "event_type": "api_call",
        "properties": lambda: {
            "endpoint": random.choice(["/v1/data", "/v1/users", "/v1/reports", "/v1/webhooks"]),
            "method": random.choice(["GET", "POST", "PUT", "DELETE"]),
            "status_code": random.choice([200, 200, 200, 201, 400, 429, 500]),
            "latency_ms": random.randint(10, 2500),
        },
    },
]

USER_POOL = [f"user_{i:04d}" for i in range(1, 201)]  # 200 simulated users
SESSION_POOL: Dict[str, str] = {}


def _get_session(user_id: str) -> str:
    """Maintain session affinity — 20% chance of new session."""
    if user_id not in SESSION_POOL or random.random() < 0.20:
        SESSION_POOL[user_id] = str(uuid.uuid4())[:8]
    return SESSION_POOL[user_id]


# ---------------------------------------------------------------------------
# Producer
# ---------------------------------------------------------------------------

class EventProducer:
    """
    Simulates a Kafka producer with batching and delivery tracking.

    In production this wraps confluent_kafka.Producer with:
        - Idempotent delivery (enable.idempotence=true)
        - Snappy compression
        - Acks=all for durability
        - Schema Registry integration
    """

    def __init__(self, topic: str = "user-events", num_partitions: int = 12):
        self.topic = topic
        self.num_partitions = num_partitions
        self.produced_count = 0
        self.delivery_log: List[Dict] = []

    def produce_event(self, event: Optional[UserEvent] = None) -> UserEvent:
        """Produce a single event to the topic."""
        if event is None:
            event = self._generate_random_event()

        partition = partition_key(event.user_id, self.num_partitions)
        offset = self.produced_count

        delivery_record = {
            "topic": self.topic,
            "partition": partition,
            "offset": offset,
            "key": event.user_id,
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "size_bytes": len(event.serialize()),
        }

        self.delivery_log.append(delivery_record)
        self.produced_count += 1
        return event

    def produce_batch(self, count: int = 50) -> List[UserEvent]:
        """
        Produce a batch of events.
        In production, this uses linger.ms and batch.size for throughput.
        """
        events = []
        for _ in range(count):
            events.append(self.produce_event())
        return events

    def _generate_random_event(self) -> UserEvent:
        template = random.choice(EVENT_TEMPLATES)
        user_id = random.choice(USER_POOL)
        return UserEvent(
            event_type=template["event_type"],
            user_id=user_id,
            session_id=_get_session(user_id),
            timestamp=datetime.now(timezone.utc).isoformat(),
            properties=template["properties"](),
            metadata={
                "sdk_version": "3.2.1",
                "platform": random.choice(["web", "ios", "android"]),
                "region": random.choice(["us-east-1", "eu-west-1", "ap-south-1"]),
            },
        )

    def get_metrics(self) -> Dict:
        """Producer-side metrics for observability."""
        if not self.delivery_log:
            return {"total_produced": 0}

        event_type_counts = {}
        partition_counts = {}
        total_bytes = 0

        for record in self.delivery_log:
            et = record["event_type"]
            event_type_counts[et] = event_type_counts.get(et, 0) + 1
            p = record["partition"]
            partition_counts[p] = partition_counts.get(p, 0) + 1
            total_bytes += record["size_bytes"]

        return {
            "total_produced": self.produced_count,
            "event_type_distribution": event_type_counts,
            "partition_distribution": partition_counts,
            "total_bytes": total_bytes,
            "avg_event_size_bytes": round(total_bytes / self.produced_count, 1),
        }


# ---------------------------------------------------------------------------
# Main — Demonstrate the producer
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("  EVENT PRODUCER — Kafka Ingestion Simulation")
    print("=" * 70)

    producer = EventProducer(topic="user-events", num_partitions=12)

    # Produce 100 events
    print("\n▸ Producing 100 events...")
    batch = producer.produce_batch(100)

    # Show sample events
    print("\n── Sample Events ──")
    for event in batch[:5]:
        print(f"  [{event.event_type:20s}] user={event.user_id}  "
              f"session={event.session_id}  props={json.dumps(event.properties)[:80]}")

    # Show metrics
    metrics = producer.get_metrics()
    print("\n── Producer Metrics ──")
    print(f"  Total Produced : {metrics['total_produced']}")
    print(f"  Total Bytes    : {metrics['total_bytes']:,}")
    print(f"  Avg Event Size : {metrics['avg_event_size_bytes']} bytes")
    print(f"\n  Event Distribution:")
    for et, count in sorted(metrics["event_type_distribution"].items()):
        print(f"    {et:25s} → {count}")
    print(f"\n  Partition Distribution:")
    for p, count in sorted(metrics["partition_distribution"].items()):
        bar = "█" * count
        print(f"    Partition {p:2d} → {count:3d} {bar}")

    print("\n✓ Event production complete.")
