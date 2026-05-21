"""
Day 28 — Stream Processing & Enrichment Layer
==============================================
Simulates stateful stream processing (Apache Flink/Kafka Streams).
Raw events are validated and enriched via lookup joins, grouped into logical 
user sessions (30-min window), and routed to specific downstream engines:
- Apache Pinot (real-time OLAP metrics)
- Vector DB queue (semantic behavior embedding)
- Feature Store (real-time feature telemetry)
- Dead Letter Queue (DLQ) for schema violations
"""

import json
import time
import random
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Set, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

from observability import logger, metrics
from failure_simulator import chaos_injector


# ---------------------------------------------------------------------------
# Enrichment Profiles (Simulated CRM / Billing Lookup)
# ---------------------------------------------------------------------------

USER_PROFILES: Dict[str, Dict] = {}

def _initialize_user_profiles():
    """Build profiles representing active high-value/premium accounts."""
    tiers = ["premium_business", "enterprise"]
    industries = ["finance", "e-commerce", "telecom", "biotech", "defense"]
    for i in range(1, 201):
        uid = f"usr_prem_{i:04d}"
        arr = random.choice([3600.0, 12000.0, 60000.0, 120000.0]) # MRR * 12
        USER_PROFILES[uid] = {
            "tier": "enterprise" if arr >= 60000 else "premium_business",
            "arr_usd": arr,
            "industry": random.choice(industries),
            "account_age_days": random.randint(30, 1500),
            "assigned_csm": f"CSM_{random.randint(1, 10)}",
            "contract_health_score": round(random.uniform(50.0, 100.0), 1),
        }

_initialize_user_profiles()


# ---------------------------------------------------------------------------
# Processing Sinks & Structs
# ---------------------------------------------------------------------------

class SinkType(Enum):
    PINOT = "pinot_olap_table"
    VECTOR_DB = "vector_embedding_queue"
    FEATURE_STORE = "redis_feature_store"
    DEAD_LETTER_QUEUE = "kafka_dlq_topic"
    INCIDENT_ALERT = "incident_alert_stream"


@dataclass
class EnrichedRecord:
    """Enriched, validated behavior record ready for downstream routing."""
    original_event: Dict
    enriched_fields: Dict = field(default_factory=dict)
    computed_features: Dict = field(default_factory=dict)
    sinks: List[str] = field(default_factory=list)
    processing_time_ms: float = 0.0
    session_id: str = ""
    is_valid: bool = True
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Stream Processor Implementation
# ---------------------------------------------------------------------------

class FlinkStreamProcessor:
    """Stateful enrichment and transformation engine."""

    REQUIRED_FIELDS = {"event_id", "event_type", "user_id", "timestamp"}
    SESSION_GAP = timedelta(minutes=30)

    def __init__(self):
        self.processed_count = 0
        self.sink_metrics: Dict[str, int] = {s.value: 0 for s in SinkType}
        # In-memory states (in Flink, these are RocksDB-backed state backends)
        self.user_session_state: Dict[str, List[Dict]] = {} 
        self.user_feature_state: Dict[str, Dict] = {}

    def process_event(self, raw_event: Dict) -> EnrichedRecord:
        """Process a single event through enrichment, sessionization, and routing."""
        start_time = time.time()
        record = EnrichedRecord(original_event=raw_event)

        # 1. Validation
        if not self._validate_schema(raw_event, record):
            record.sinks = [SinkType.DEAD_LETTER_QUEUE.value]
            self.sink_metrics[SinkType.DEAD_LETTER_QUEUE.value] += 1
            metrics.increment("stream_processor_invalid_events_total")
            record.processing_time_ms = (time.time() - start_time) * 1000
            return record

        user_id = raw_event["user_id"]

        # 2. Lookup Enrichment (Profile Join)
        record.enriched_fields = self._join_profile(user_id)

        # 3. Session Windowing
        record.session_id = raw_event.get("session_id", "unknown")
        self._update_session_windows(user_id, raw_event)

        # 4. Feature Computation
        record.computed_features = self._compute_rolling_metrics(user_id, raw_event)

        # 5. Routing Decisions
        record.sinks = self._route_event(raw_event, record)
        for sink in record.sinks:
            self.sink_metrics[sink] += 1
            metrics.increment("stream_processor_sink_writes_total", 1, {"sink": sink})

        # 6. Incident Check (e.g. Critical Billing issue for high value enterprise account)
        if self._check_incident_conditions(raw_event, record):
            record.sinks.append(SinkType.INCIDENT_ALERT.value)
            self.sink_metrics[SinkType.INCIDENT_ALERT.value] += 1
            metrics.increment("stream_processor_alerts_triggered_total")
            logger.warn(
                f"INCIDENT DETECTED: Churn risk trigger for user {user_id}",
                extra={"user_id": user_id, "event_type": raw_event.get("event_type")}
            )

        # Telemetry updates
        record.processing_time_ms = (time.time() - start_time) * 1000
        self.processed_count += 1
        
        metrics.increment("stream_processor_events_processed_total")
        metrics.observe("stream_processor_latency_ms", record.processing_time_ms)

        return record

    def process_batch(self, events: List[Dict]) -> List[EnrichedRecord]:
        """Process batch of events."""
        return [self.process_event(e) for e in events]

    def _validate_schema(self, event: Dict, record: EnrichedRecord) -> bool:
        """Enforce structure and non-null identifiers."""
        missing = self.REQUIRED_FIELDS - set(event.keys())
        if missing:
            record.is_valid = False
            record.error_message = f"Schema violation: missing fields: {missing}"
            return False
        
        if not event.get("user_id", "").startswith("usr_prem_"):
            record.is_valid = False
            record.error_message = f"Schema violation: invalid user ID format: {event.get('user_id')}"
            return False

        return True

    def _join_profile(self, user_id: str) -> Dict:
        """Enrich record by lookup against Redis user profile store."""
        profile = USER_PROFILES.get(user_id, {})
        return {
            "tier": profile.get("tier", "premium_business"),
            "arr_usd": profile.get("arr_usd", 3600.0),
            "industry": profile.get("industry", "unknown"),
            "contract_health_score": profile.get("contract_health_score", 75.0),
            "is_high_value": profile.get("arr_usd", 0.0) >= 60000.0
        }

    def _update_session_windows(self, user_id: str, event: Dict):
        """Append event to sliding window. Discards sessions after 30m inactivity."""
        if user_id not in self.user_session_state:
            self.user_session_state[user_id] = []
        
        self.user_session_state[user_id].append(event)
        
        # Evict old events past 30m window boundaries (in-memory mock simulation)
        if len(self.user_session_state[user_id]) > 50:
            self.user_session_state[user_id] = self.user_session_state[user_id][-50:]

    def _compute_rolling_metrics(self, user_id: str, event: Dict) -> Dict:
        """Compute user behavior feature states."""
        if user_id not in self.user_feature_state:
            self.user_feature_state[user_id] = {
                "rolling_activities": 0,
                "error_activities": 0,
                "billing_failures": 0,
                "sentiment_sum": 0.0,
                "ticket_count": 0,
                "features_active": set()
            }

        state = self.user_feature_state[user_id]
        state["rolling_activities"] += 1
        
        event_type = event.get("event_type")
        props = event.get("properties", {})

        if event_type == "feature_used":
            if not props.get("success", True):
                state["error_activities"] += 1
            state["features_active"].add(props.get("feature", "unknown"))
            
        elif event_type == "support_ticket":
            state["ticket_count"] += 1
            state["sentiment_sum"] += props.get("sentiment_score", 0.0)
            
        elif event_type == "billing_event":
            if props.get("action") == "payment_failed":
                state["billing_failures"] += 1

        # Derive features
        avg_sentiment = (state["sentiment_sum"] / state["ticket_count"]) if state["ticket_count"] > 0 else 0.0
        error_rate = (state["error_activities"] / state["rolling_activities"]) if state["rolling_activities"] > 0 else 0.0

        return {
            "rolling_activity_count": state["rolling_activities"],
            "session_error_rate": round(error_rate, 3),
            "billing_failure_count": state["billing_failures"],
            "avg_ticket_sentiment": round(avg_sentiment, 3),
            "unique_features_count": len(state["features_active"])
        }

    def _route_event(self, event: Dict, record: EnrichedRecord) -> List[str]:
        """Determine downstream storage routes based on event type."""
        sinks = [SinkType.PINOT.value] # Everything goes to OLAP analytics

        event_type = event.get("event_type")
        
        # High value billing failures, tickets, contractions trigger vector DB embedding
        if event_type in ("support_ticket", "billing_event", "team_contraction"):
            sinks.append(SinkType.VECTOR_DB.value)

        # Feature Store receives active feature updates
        sinks.append(SinkType.FEATURE_STORE.value)

        return [sink for sink in sinks]

    def _check_incident_conditions(self, event: Dict, record: EnrichedRecord) -> bool:
        """Trigger alerts on high risk indicators."""
        event_type = event.get("event_type")
        props = event.get("properties", {})
        enriched = record.enriched_fields
        features = record.computed_features

        # Condition 1: Enterprise Account Billing Failure
        if event_type == "billing_event" and props.get("action") == "payment_failed" and enriched.get("tier") == "enterprise":
            return True

        # Condition 2: Critical Support Ticket on high-value account with negative sentiment
        if event_type == "support_ticket" and props.get("priority") == "critical" and features.get("avg_ticket_sentiment", 0.0) < -0.3:
            return True

        # Condition 3: Team Contraction removing >3 seats on Enterprise
        if event_type == "team_contraction" and props.get("members_removed", 0) >= 3:
            return True

        return False

    def get_processor_metrics(self) -> Dict[str, Any]:
        """Telemetry details for observability metrics."""
        return {
            "processed": self.processed_count,
            "sinks": self.sink_metrics,
            "active_states": len(self.user_feature_state)
        }


if __name__ == "__main__":
    print("Testing Stream Processor...")
    processor = FlinkStreamProcessor()
    
    # Mock event
    sample_event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "billing_event",
        "user_id": "usr_prem_0005",
        "session_id": "sess_01",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "properties": {"action": "payment_failed", "amount_usd": 2499.0}
    }
    
    rec = processor.process_event(sample_event)
    print("Enriched Record:")
    print("  Tier:", rec.enriched_fields.get("tier"))
    print("  ARR:", rec.enriched_fields.get("arr_usd"))
    print("  Features:", rec.computed_features)
    print("  Routed Sinks:", rec.sinks)
