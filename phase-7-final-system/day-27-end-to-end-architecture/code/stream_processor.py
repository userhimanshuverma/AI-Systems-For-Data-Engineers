"""
Day 27 — Stream Processor (Enrichment Layer Simulation)
========================================================
Simulates the stream processing tier that sits between Kafka ingestion
and downstream consumers (Apache Pinot, Vector DB, feature stores).

Architecture Role:
    Raw events are NEVER consumed directly by the intelligence layer.
    This processor enriches, transforms, and contextualizes events so
    downstream systems receive clean, query-ready data.

Production Stack:
    - Apache Flink / Kafka Streams / Spark Structured Streaming
    - Stateful processing with RocksDB-backed state stores
    - Exactly-once semantics via transactional producers
    - Watermark-based windowing for late-arriving events

Key Responsibilities:
    1. Schema validation and dead-letter routing
    2. User profile enrichment (join with profile store)
    3. Session windowing and aggregation
    4. Feature computation (real-time feature store writes)
    5. Routing to multiple sinks (Pinot, Vector DB, alerts)
"""

import json
import time
import random
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum


# ---------------------------------------------------------------------------
# Enrichment Data — Simulated External Lookups
# ---------------------------------------------------------------------------

USER_PROFILES = {}

def _init_profiles():
    """Pre-populate user profiles (simulates profile store / CRM lookup)."""
    tiers = ["free", "starter", "professional", "enterprise"]
    industries = ["fintech", "healthcare", "e-commerce", "saas", "media"]
    for i in range(1, 201):
        uid = f"user_{i:04d}"
        USER_PROFILES[uid] = {
            "tier": random.choice(tiers),
            "account_age_days": random.randint(1, 1200),
            "industry": random.choice(industries),
            "company_size": random.choice(["1-10", "11-50", "51-200", "201-1000", "1000+"]),
            "lifetime_revenue": round(random.uniform(0, 50000), 2),
            "health_score": round(random.uniform(0, 100), 1),
        }

_init_profiles()


# ---------------------------------------------------------------------------
# Processing Results
# ---------------------------------------------------------------------------

class SinkType(Enum):
    PINOT = "apache_pinot"
    VECTOR_DB = "vector_db"
    FEATURE_STORE = "feature_store"
    DEAD_LETTER = "dead_letter_queue"
    ALERT = "alert_stream"


@dataclass
class ProcessedRecord:
    """Output of stream processing — enriched and routed."""
    original_event: Dict
    enriched_fields: Dict = field(default_factory=dict)
    computed_features: Dict = field(default_factory=dict)
    sinks: List[str] = field(default_factory=list)
    processing_time_ms: float = 0.0
    window_key: str = ""
    is_valid: bool = True
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Stream Processor
# ---------------------------------------------------------------------------

class StreamProcessor:
    """
    Simulates a stateful stream processor with:
        - Schema validation
        - Profile enrichment (lookup join)
        - Session windowing
        - Feature computation
        - Multi-sink routing
    """

    REQUIRED_FIELDS = {"event_id", "event_type", "user_id", "timestamp"}
    SESSION_GAP = timedelta(minutes=30)

    def __init__(self):
        self.processed_count = 0
        self.error_count = 0
        self.sink_counts: Dict[str, int] = {s.value: 0 for s in SinkType}
        self.session_windows: Dict[str, List[Dict]] = {}  # user_id → events
        self.feature_store: Dict[str, Dict] = {}  # user_id → features

    # ── Core Processing Pipeline ──────────────────────────────────────────

    def process(self, raw_event: Dict) -> ProcessedRecord:
        """
        Full processing pipeline for a single event.
        Mirrors a Flink ProcessFunction with side outputs.
        """
        start = time.time()
        record = ProcessedRecord(original_event=raw_event)

        # Step 1: Schema validation
        if not self._validate(raw_event, record):
            record.sinks = [SinkType.DEAD_LETTER.value]
            self.sink_counts[SinkType.DEAD_LETTER.value] += 1
            self.error_count += 1
            record.processing_time_ms = (time.time() - start) * 1000
            return record

        user_id = raw_event["user_id"]

        # Step 2: Profile enrichment
        record.enriched_fields = self._enrich_profile(user_id)

        # Step 3: Session windowing
        record.window_key = self._update_session_window(user_id, raw_event)

        # Step 4: Compute real-time features
        record.computed_features = self._compute_features(user_id, raw_event)

        # Step 5: Route to sinks
        record.sinks = self._route(raw_event, record.enriched_fields)
        for sink in record.sinks:
            self.sink_counts[sink] += 1

        # Step 6: Check alert conditions
        if self._should_alert(raw_event, record.enriched_fields, record.computed_features):
            record.sinks.append(SinkType.ALERT.value)
            self.sink_counts[SinkType.ALERT.value] += 1

        record.processing_time_ms = (time.time() - start) * 1000
        self.processed_count += 1
        return record

    def process_batch(self, events: List[Dict]) -> List[ProcessedRecord]:
        """Process a batch of events (micro-batch semantics)."""
        return [self.process(e) for e in events]

    # ── Validation ────────────────────────────────────────────────────────

    def _validate(self, event: Dict, record: ProcessedRecord) -> bool:
        missing = self.REQUIRED_FIELDS - set(event.keys())
        if missing:
            record.is_valid = False
            record.error = f"Missing required fields: {missing}"
            return False
        if not event.get("user_id", "").startswith("user_"):
            record.is_valid = False
            record.error = f"Invalid user_id format: {event.get('user_id')}"
            return False
        return True

    # ── Enrichment ────────────────────────────────────────────────────────

    def _enrich_profile(self, user_id: str) -> Dict:
        """
        Lookup join against user profile store.
        In production: async lookup against Redis/DynamoDB with caching.
        """
        profile = USER_PROFILES.get(user_id, {})
        return {
            "user_tier": profile.get("tier", "unknown"),
            "account_age_days": profile.get("account_age_days", 0),
            "industry": profile.get("industry", "unknown"),
            "company_size": profile.get("company_size", "unknown"),
            "health_score": profile.get("health_score", 0.0),
            "is_high_value": profile.get("lifetime_revenue", 0) > 10000,
        }

    # ── Session Windowing ─────────────────────────────────────────────────

    def _update_session_window(self, user_id: str, event: Dict) -> str:
        """
        Session window with 30-minute gap.
        Groups events into logical user sessions for aggregation.
        """
        if user_id not in self.session_windows:
            self.session_windows[user_id] = []

        self.session_windows[user_id].append(event)

        # Trim old events outside session gap (simplified)
        if len(self.session_windows[user_id]) > 100:
            self.session_windows[user_id] = self.session_windows[user_id][-100:]

        session_id = event.get("session_id", "unknown")
        return f"{user_id}::{session_id}"

    # ── Feature Computation ───────────────────────────────────────────────

    def _compute_features(self, user_id: str, event: Dict) -> Dict:
        """
        Real-time feature computation for the feature store.
        These features power ML models and retrieval ranking.
        """
        if user_id not in self.feature_store:
            self.feature_store[user_id] = {
                "event_count_1h": 0,
                "unique_event_types_1h": set(),
                "error_rate_1h": 0.0,
                "avg_latency_ms": 0.0,
                "last_active": None,
                "_latency_sum": 0.0,
                "_latency_count": 0,
                "_error_count": 0,
            }

        features = self.feature_store[user_id]
        features["event_count_1h"] += 1
        features["unique_event_types_1h"].add(event.get("event_type", ""))
        features["last_active"] = event.get("timestamp")

        # Track latency for API calls
        props = event.get("properties", {})
        if "latency_ms" in props:
            features["_latency_sum"] += props["latency_ms"]
            features["_latency_count"] += 1
            features["avg_latency_ms"] = round(
                features["_latency_sum"] / features["_latency_count"], 1
            )

        # Track error rate
        if props.get("status_code", 200) >= 400:
            features["_error_count"] += 1
        features["error_rate_1h"] = round(
            features["_error_count"] / features["event_count_1h"], 3
        )

        # Return serializable version
        return {
            "event_count_1h": features["event_count_1h"],
            "unique_event_types_1h": len(features["unique_event_types_1h"]),
            "error_rate_1h": features["error_rate_1h"],
            "avg_latency_ms": features["avg_latency_ms"],
        }

    # ── Sink Routing ──────────────────────────────────────────────────────

    def _route(self, event: Dict, enriched: Dict) -> List[str]:
        """
        Determine which downstream sinks receive this event.
        Different event types go to different consumers.
        """
        sinks = [SinkType.PINOT.value]  # All valid events go to Pinot

        event_type = event.get("event_type", "")

        # Semantic events → Vector DB for embedding
        if event_type in ("support_ticket", "feature_used", "subscription_event"):
            sinks.append(SinkType.VECTOR_DB.value)

        # All events update feature store
        sinks.append(SinkType.FEATURE_STORE.value)

        return sinks

    # ── Alert Detection ───────────────────────────────────────────────────

    def _should_alert(self, event: Dict, enriched: Dict, features: Dict) -> bool:
        """
        Real-time alerting conditions.
        In production: routed to PagerDuty, Slack, or incident management.
        """
        props = event.get("properties", {})

        # High-value customer with critical support ticket
        if (event.get("event_type") == "support_ticket"
                and props.get("priority") == "critical"
                and enriched.get("is_high_value")):
            return True

        # Enterprise customer cancellation
        if (event.get("event_type") == "subscription_event"
                and props.get("action") == "cancel"
                and enriched.get("user_tier") == "enterprise"):
            return True

        # High error rate
        if features.get("error_rate_1h", 0) > 0.5 and features.get("event_count_1h", 0) > 5:
            return True

        return False

    # ── Metrics ───────────────────────────────────────────────────────────

    def get_metrics(self) -> Dict:
        return {
            "total_processed": self.processed_count,
            "total_errors": self.error_count,
            "error_rate": round(self.error_count / max(self.processed_count + self.error_count, 1), 4),
            "sink_distribution": dict(self.sink_counts),
            "active_sessions": len(self.session_windows),
            "feature_store_entries": len(self.feature_store),
        }


# ---------------------------------------------------------------------------
# Main — Demonstrate stream processing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from event_producer import EventProducer

    print("=" * 70)
    print("  STREAM PROCESSOR — Enrichment & Contextualization")
    print("=" * 70)

    # Produce events
    producer = EventProducer()
    raw_events = producer.produce_batch(100)

    # Process events
    processor = StreamProcessor()
    results = processor.process_batch([
        json.loads(e.serialize().decode()) for e in raw_events
    ])

    # Show sample results
    print("\n── Sample Processed Records ──")
    for r in results[:5]:
        print(f"\n  Event: {r.original_event['event_type']}")
        print(f"    User Tier    : {r.enriched_fields.get('user_tier')}")
        print(f"    High Value   : {r.enriched_fields.get('is_high_value')}")
        print(f"    Features     : {r.computed_features}")
        print(f"    Sinks        : {r.sinks}")
        print(f"    Latency      : {r.processing_time_ms:.2f} ms")

    # Show metrics
    metrics = processor.get_metrics()
    print("\n── Processor Metrics ──")
    print(f"  Processed     : {metrics['total_processed']}")
    print(f"  Errors        : {metrics['total_errors']}")
    print(f"  Error Rate    : {metrics['error_rate']:.2%}")
    print(f"  Active Sess.  : {metrics['active_sessions']}")
    print(f"  Feature Store : {metrics['feature_store_entries']} entries")
    print(f"\n  Sink Distribution:")
    for sink, count in sorted(metrics["sink_distribution"].items()):
        bar = "█" * min(count, 50)
        print(f"    {sink:20s} → {count:3d} {bar}")

    # Show alerts
    alerts = [r for r in results if "alert_stream" in r.sinks]
    print(f"\n── Alerts Triggered: {len(alerts)} ──")
    for a in alerts[:3]:
        print(f"    ⚠ {a.original_event['event_type']} for {a.original_event['user_id']}"
              f" (tier={a.enriched_fields.get('user_tier')})")

    print("\n✓ Stream processing complete.")
