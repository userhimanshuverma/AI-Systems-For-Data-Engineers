"""
Day 28 — Ingestion Backbone (Kafka Simulation)
==============================================
Simulates a multi-topic, partitioned Apache Kafka broker.
Ensures partition affinity by hashing `user_id` so all events for a specific 
premium user land on the same stream partition, guaranteeing ordering.

Integrates with the chaos injector to simulate ingestion lag.
"""

import json
import time
import uuid
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

from observability import logger, metrics
from failure_simulator import chaos_injector


@dataclass
class UserEvent:
    """Schema-enforced event representing user behavior telemetry."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    user_id: str = ""
    session_id: str = ""
    timestamp: str = ""
    properties: Dict = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)

    def serialize(self) -> bytes:
        return json.dumps(asdict(self), ensure_ascii=False).encode("utf-8")

    @classmethod
    def deserialize(cls, raw: bytes) -> "UserEvent":
        data = json.loads(raw.decode("utf-8"))
        return cls(**data)


def hash_partition(user_id: str, num_partitions: int = 12) -> int:
    """
    Hash-based partition router.
    Guarantees that a user's events are processed sequentially in a single partition.
    """
    # Simple deterministic hash function
    hash_val = sum(ord(char) for char in user_id)
    return hash_val % num_partitions


# ---------------------------------------------------------------------------
# Churn Intelligence Event Templates
# ---------------------------------------------------------------------------

EVENT_TEMPLATES = [
    {
        "event_type": "page_view",
        "properties": lambda: {
            "page": random.choice(["/dashboard", "/billing", "/settings", "/export-portal", "/api-keys"]),
            "referrer": random.choice(["direct", "adwords", "organic", "churn_notification"]),
            "load_time_ms": random.randint(100, 4000),
        }
    },
    {
        "event_type": "feature_used",
        "properties": lambda: {
            "feature": random.choice(["bulk_export", "automated_audit", "query_builder", "team_invite"]),
            "duration_ms": random.randint(200, 60000),
            "success": random.choices([True, False], weights=[94, 6], k=1)[0],
        }
    },
    {
        "event_type": "support_ticket",
        "properties": lambda: {
            "category": random.choice(["billing", "data_loss", "slow_queries", "integration"]),
            "priority": random.choices(["low", "medium", "high", "critical"], weights=[50, 30, 15, 5], k=1)[0],
            "sentiment_score": round(random.uniform(-0.9, 0.2), 2),
        }
    },
    {
        "event_type": "billing_event",
        "properties": lambda: {
            "action": random.choices(["payment_failed", "invoice_retry", "downgrade_request", "card_update"], weights=[60, 20, 10, 10], k=1)[0],
            "amount_usd": random.choice([299.0, 999.0, 2499.0]),
        }
    },
    {
        "event_type": "team_contraction",
        "properties": lambda: {
            "members_removed": random.randint(1, 5),
            "remaining_seats": random.randint(3, 45),
        }
    }
]

# 200 Premium Users pool
PREMIUM_USERS = [f"usr_prem_{i:04d}" for i in range(1, 201)]
SESSION_CACHE: Dict[str, str] = {}


def _get_active_session(user_id: str) -> str:
    """Retrieve session token with 15% probability of session renewal."""
    if user_id not in SESSION_CACHE or random.random() < 0.15:
        SESSION_CACHE[user_id] = str(uuid.uuid4())[:8]
    return SESSION_CACHE[user_id]


class KafkaEventStream:
    """Simulates Kafka message broker ingestion."""

    def __init__(self, topic: str = "user-activity-telemetry", num_partitions: int = 12):
        self.topic = topic
        self.num_partitions = num_partitions
        self.produced_count = 0
        self.partition_offsets: Dict[int, int] = {i: 0 for i in range(num_partitions)}

    def produce_event(self, event: Optional[UserEvent] = None) -> Dict[str, Any]:
        """Send event to the Kafka broker. Tracks partitions and offsets."""
        if event is None:
            event = self._generate_telemetry()

        # Simulate Kafka lag delay if injected
        lag_delay = chaos_injector.get_kafka_latency()
        if lag_delay > 0.1:
            time.sleep(lag_delay)

        partition = hash_partition(event.user_id, self.num_partitions)
        offset = self.partition_offsets[partition]
        self.partition_offsets[partition] += 1
        self.produced_count += 1

        # Record metrics in collector
        metrics.increment("kafka_messages_produced_total", 1, {"topic": self.topic})
        metrics.increment(f"kafka_partition_{partition}_messages_total")
        metrics.observe("kafka_producer_latency_seconds", lag_delay)

        meta = {
            "topic": self.topic,
            "partition": partition,
            "offset": offset,
            "timestamp": event.timestamp,
            "key": event.user_id,
            "latency_sec": lag_delay
        }
        
        logger.info(
            f"Kafka Ingestion SUCCESS: Topic={self.topic} Partition={partition} Offset={offset}",
            extra={"event_id": event.event_id, "event_type": event.event_type, "user_id": event.user_id}
        )

        return {"event": event, "metadata": meta}

    def produce_batch(self, batch_size: int = 20) -> List[Dict[str, Any]]:
        """Simulate high-throughput batch ingestion."""
        records = []
        for _ in range(batch_size):
            records.append(self.produce_event())
        return records

    def _generate_telemetry(self) -> UserEvent:
        template = random.choice(EVENT_TEMPLATES)
        user_id = random.choice(PREMIUM_USERS)
        return UserEvent(
            event_type=template["event_type"],
            user_id=user_id,
            session_id=_get_active_session(user_id),
            timestamp=datetime.now(timezone.utc).isoformat(),
            properties=template["properties"](),
            metadata={
                "env": "production",
                "client_ip": f"192.168.10.{random.randint(1, 254)}",
                "collector_agent": "k8s-fluent-bit-daemon"
            }
        )

    def get_stream_metrics(self) -> Dict[str, Any]:
        """Return status logs of partitions and total traffic size."""
        return {
            "topic": self.topic,
            "total_produced": self.produced_count,
            "partitions": self.num_partitions,
            "offsets": self.partition_offsets
        }


if __name__ == "__main__":
    print("Initializing Kafka Stream Broker...")
    stream = KafkaEventStream()
    batch = stream.produce_batch(5)
    print(f"Produced batch of {len(batch)} events successfully.")
    print("Stream metrics:", stream.get_stream_metrics())
