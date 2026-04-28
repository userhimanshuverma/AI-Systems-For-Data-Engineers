"""
Stream Simulation — Day 05: Event-Driven Systems
==================================================
A self-contained simulation of the full Kafka event-driven pipeline.
No dependencies. No Docker. Runs immediately.

Simulates:
  1. Multiple producers publishing events concurrently
  2. Kafka broker (partitioned log with offset tracking)
  3. Multiple consumer groups reading independently
  4. Stream processing (enrich, detect, route)
  5. Output sinks (Pinot, Vector Store, Alert)

This is the mental model made concrete. Every concept from the README
is visible in the output.
"""

import json
import sys
import random
from datetime import datetime
from collections import defaultdict


# ── KAFKA BROKER SIMULATION ───────────────────────────────────────────────────

class KafkaBroker:
    """
    Simulates a single Kafka broker with multiple topics.
    Each topic has N partitions. Each partition is an ordered log.
    """
    def __init__(self):
        self._topics: dict[str, dict[int, list]] = {}

    def create_topic(self, name: str, partitions: int = 3) -> None:
        if name not in self._topics:
            self._topics[name] = {p: [] for p in range(partitions)}
            print(f"[BROKER]  Topic created: {name} ({partitions} partitions)")

    def publish(self, topic: str, key: str, value: dict) -> dict:
        if topic not in self._topics:
            self.create_topic(topic)
        partitions = self._topics[topic]
        partition = hash(key) % len(partitions)
        offset = len(partitions[partition])
        record = {
            "topic":     topic,
            "partition": partition,
            "offset":    offset,
            "key":       key,
            "value":     value,
            "ts":        datetime.now().isoformat(),
        }
        partitions[partition].append(record)
        return record

    def consume_from(self, topic: str, partition: int, offset: int) -> list:
        if topic not in self._topics:
            return []
        log = self._topics[topic].get(partition, [])
        return log[offset:]

    def topic_size(self, topic: str) -> int:
        if topic not in self._topics:
            return 0
        return sum(len(p) for p in self._topics[topic].values())

    def partition_count(self, topic: str) -> int:
        return len(self._topics.get(topic, {}))


# ── CONSUMER GROUP ────────────────────────────────────────────────────────────

class ConsumerGroup:
    """
    Simulates a Kafka consumer group.
    Tracks committed offsets per partition.
    """
    def __init__(self, group_id: str, broker: KafkaBroker, topic: str):
        self.group_id = group_id
        self.broker   = broker
        self.topic    = topic
        self._offsets: dict[int, int] = defaultdict(int)

    def poll(self) -> list[dict]:
        """Returns all new records since last committed offset."""
        records = []
        n_partitions = self.broker.partition_count(self.topic)
        for p in range(n_partitions):
            new = self.broker.consume_from(self.topic, p, self._offsets[p])
            records.extend(new)
            self._offsets[p] += len(new)
        return records

    def committed_offsets(self) -> dict:
        return dict(self._offsets)


# ── PRODUCERS ─────────────────────────────────────────────────────────────────

USERS = ["u_001", "u_002", "u_003", "u_004"]
PROFILES = {
    "u_001": {"plan": "free",       "segment": "at_risk"},
    "u_002": {"plan": "pro",        "segment": "active"},
    "u_003": {"plan": "free",       "segment": "new"},
    "u_004": {"plan": "enterprise", "segment": "champion"},
}

def produce_events(broker: KafkaBroker, n: int = 20) -> None:
    """Simulates the web app publishing user events."""
    templates = [
        ("page_view",    {"page": "/pricing"}),
        ("page_view",    {"page": "/checkout"}),
        ("button_click", {"element": "cta_upgrade"}),
        ("server_error", {"code": 500, "page": "/checkout"}),
        ("server_error", {"code": 500, "page": "/checkout"}),  # weighted higher
        ("payment_processed", {"amount_usd": 49, "plan": "pro"}),
        ("session_end",  {"duration_s": 420}),
    ]
    for i in range(n):
        uid = random.choice(USERS)
        etype, props = random.choice(templates)
        event = {
            "event_id":   f"evt_{i:05d}",
            "event_type": etype,
            "user_id":    uid,
            "properties": props,
        }
        rec = broker.publish("user.events", key=uid, value=event)


# ── STREAM PROCESSOR (Consumer Group 1) ──────────────────────────────────────

class StreamProcessor:
    """
    Simulates a Flink job consuming from user.events.
    Enriches events, detects anomalies, routes to sinks.
    """
    def __init__(self, broker: KafkaBroker):
        self.group   = ConsumerGroup("flink-enrichment", broker, "user.events")
        self._state: dict[str, dict] = defaultdict(lambda: {"events": 0, "errors": 0})
        self.pinot_sink:  list[dict] = []
        self.embed_sink:  list[str]  = []
        self.alert_sink:  list[str]  = []

    def run_once(self) -> int:
        records = self.group.poll()
        for rec in records:
            event = rec["value"]
            uid   = event["user_id"]
            etype = event["event_type"]

            # Enrich
            profile = PROFILES.get(uid, {})
            enriched = {**event, **profile}

            # Update state
            s = self._state[uid]
            s["events"] += 1
            if etype == "server_error":
                s["errors"] += 1

            # Pinot sink
            self.pinot_sink.append({
                "user_id":    uid,
                "event_type": etype,
                "plan":       profile.get("plan", "?"),
                "segment":    profile.get("segment", "?"),
                "partition":  rec["partition"],
                "offset":     rec["offset"],
            })

            # Embedding sink
            self.embed_sink.append(
                f"User {uid} ({profile.get('plan','?')} plan) "
                f"performed '{etype}' at {rec['ts']}."
            )

            # Alert detection
            if s["events"] >= 3:
                rate = s["errors"] / s["events"]
                if rate >= 0.5:
                    alert = f"HIGH_ERROR_RATE: {uid} {rate:.0%} ({s['errors']}/{s['events']})"
                    if alert not in self.alert_sink:
                        self.alert_sink.append(alert)

        return len(records)


# ── ALERT CONSUMER (Consumer Group 2) ────────────────────────────────────────

class AlertConsumer:
    """
    Independent consumer group — reads the same topic for alerting.
    Demonstrates fan-out: same events, different consumer, different purpose.
    """
    def __init__(self, broker: KafkaBroker):
        self.group  = ConsumerGroup("alert-service", broker, "user.events")
        self._fired: set[str] = set()
        self._error_counts: dict[str, int] = defaultdict(int)

    def run_once(self) -> list[str]:
        alerts = []
        for rec in self.group.poll():
            event = rec["value"]
            if event["event_type"] == "server_error":
                uid = event["user_id"]
                self._error_counts[uid] += 1
                if self._error_counts[uid] == 3:
                    alert = f"ALERT→PagerDuty: user {uid} hit 3 errors"
                    if alert not in self._fired:
                        self._fired.add(alert)
                        alerts.append(alert)
        return alerts


# ── SIMULATION RUNNER ─────────────────────────────────────────────────────────

def run_simulation(n_events: int = 24) -> None:
    print("=" * 65)
    print("  Kafka Event-Driven System — Full Pipeline Simulation")
    print("=" * 65)

    broker    = KafkaBroker()
    processor = StreamProcessor(broker)
    alerter   = AlertConsumer(broker)

    # Phase 1: Produce events
    print(f"\n[PHASE 1]  Producing {n_events} events to Kafka...\n")
    produce_events(broker, n=n_events)
    total = broker.topic_size("user.events")
    print(f"\n[KAFKA]    {total} events stored across "
          f"{broker.partition_count('user.events')} partitions")

    # Phase 2: Consumer groups process independently
    print(f"\n[PHASE 2]  Consumer groups processing...\n")

    # Flink enrichment consumer
    processed = processor.run_once()
    print(f"[FLINK]    Processed {processed} events")
    print(f"[FLINK]    → Pinot sink:     {len(processor.pinot_sink)} rows")
    print(f"[FLINK]    → Embedding sink: {len(processor.embed_sink)} texts")
    if processor.alert_sink:
        for a in processor.alert_sink:
            print(f"[FLINK]    ⚠️  {a}")

    # Alert consumer (independent — reads same events from offset 0)
    alerts = alerter.run_once()
    print(f"\n[ALERTS]   Alert consumer processed independently")
    for a in alerts:
        print(f"[ALERTS]   🔔 {a}")
    if not alerts:
        print(f"[ALERTS]   No threshold breaches detected")

    # Phase 3: Show offset independence
    print(f"\n[PHASE 3]  Consumer group offsets (independent tracking):")
    print(f"  flink-enrichment: {processor.group.committed_offsets()}")
    print(f"  alert-service:    {alerter.group.committed_offsets()}")
    print(f"  → Both groups read the same events independently")
    print(f"  → Neither affects the other's position in the log")

    # Phase 4: Sample output
    print(f"\n[PHASE 4]  Sample Pinot rows (first 3):")
    for row in processor.pinot_sink[:3]:
        print(f"  {json.dumps(row)}")

    print(f"\n[PHASE 4]  Sample embedding texts (first 2):")
    for text in processor.embed_sink[:2]:
        print(f"  \"{text}\"")

    # Summary
    print(f"\n{'='*65}")
    print(f"  Simulation complete")
    print(f"  Events produced:    {total}")
    print(f"  Pinot rows:         {len(processor.pinot_sink)}")
    print(f"  Embedding texts:    {len(processor.embed_sink)}")
    print(f"  Alerts fired:       {len(alerts)}")
    print(f"  Consumer groups:    2 (independent, no interference)")
    print(f"{'='*65}")


if __name__ == "__main__":
    random.seed(7)
    run_simulation(n_events=24)
