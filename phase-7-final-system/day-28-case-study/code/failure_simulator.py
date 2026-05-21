"""
Day 28 — Production Failure & Chaos Simulator
=============================================
Controls injection of infrastructure failure modes:
1. Latency Spikes: Pinpoints slow database indexes.
2. Network Outages: Simulates downstream service downtime.
3. Rate Limiting (HTTP 429): Simulates upstream LLM throttle.
4. Data Drift / Stale Embeddings: Returns degraded vector search results.
5. Thundering Herd (Retry Storm): Overloads the system when active.
"""

import random
from typing import Dict, Any


class FailureSimulator:
    """Manages failure injection states and triggers for chaos testing."""

    def __init__(self):
        self.kafka_lag_active = False
        self.pinot_latency_spike = False
        self.vector_db_outage = False
        self.llm_rate_limit_active = False
        self.stale_embeddings = False
        self.retry_storm_active = False

    def reset(self):
        """Reset all injected failures to normal operational parameters."""
        self.kafka_lag_active = False
        self.pinot_latency_spike = False
        self.vector_db_outage = False
        self.llm_rate_limit_active = False
        self.stale_embeddings = False
        self.retry_storm_active = False

    def get_kafka_latency(self) -> float:
        """Return raw delay in seconds for message processing in Kafka."""
        if self.kafka_lag_active:
            # High queue lag: Flink processing delayed
            return random.uniform(0.5, 1.5)
        return random.uniform(0.005, 0.02)

    def get_pinot_latency(self) -> float:
        """Return analytics query delay in seconds."""
        if self.pinot_latency_spike:
            # Latency spike simulating table scan instead of Star-Tree index
            return random.uniform(1.2, 2.5)
        return random.uniform(0.015, 0.05)

    def is_vector_db_down(self) -> bool:
        """Simulate connection failures to Vector DB."""
        return self.vector_db_outage

    def is_llm_rate_limited(self) -> bool:
        """Determine if an LLM API call should throw a 429 error."""
        if self.llm_rate_limit_active:
            # 50% chance of throwing a 429 when rate limit mode is active
            return random.random() < 0.5
        return False

    def is_embedding_stale(self) -> bool:
        """Check if behavioral embeddings have decayed, inducing search drift."""
        return self.stale_embeddings

    def get_llm_base_latency(self, model_tier: str) -> float:
        """Return typical model inference base latency."""
        base = 0.2 if model_tier == "utility" else 0.8
        if self.retry_storm_active:
            # Model queue delays increase under storm conditions
            return base + random.uniform(0.8, 1.5)
        return base + random.uniform(0.1, 0.3)

    def get_status(self) -> Dict[str, bool]:
        """Return status representation of injected faults."""
        return {
            "kafka_lag": self.kafka_lag_active,
            "pinot_latency_spike": self.pinot_latency_spike,
            "vector_db_outage": self.vector_db_outage,
            "llm_rate_limit": self.llm_rate_limit_active,
            "stale_embeddings": self.stale_embeddings,
            "retry_storm": self.retry_storm_active
        }


# Global simulator instance
chaos_injector = FailureSimulator()
