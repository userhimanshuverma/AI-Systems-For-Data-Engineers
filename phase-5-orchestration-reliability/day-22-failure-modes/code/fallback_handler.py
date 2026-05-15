"""
Fallback Handler — Day 22: Failure Modes in AI Systems
========================================================
Implements graceful degradation patterns for AI system components.

When a component fails, the system should:
  1. Not crash entirely
  2. Return a degraded but honest response
  3. Clearly indicate what data is unavailable
  4. Allow the LLM to reason with partial context

Patterns demonstrated:
  - Cached fallback (stale but available)
  - Partial response (some components available)
  - Rule-based fallback (no LLM needed)
  - Graceful degradation tiers
"""

import time
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum


# ── SYSTEM HEALTH ─────────────────────────────────────────────────────────────

class ComponentHealth(Enum):
    HEALTHY  = "healthy"
    DEGRADED = "degraded"
    DOWN     = "down"


@dataclass
class SystemHealth:
    pinot:        ComponentHealth = ComponentHealth.HEALTHY
    vector_store: ComponentHealth = ComponentHealth.HEALTHY
    llm_api:      ComponentHealth = ComponentHealth.HEALTHY
    embedding_api:ComponentHealth = ComponentHealth.HEALTHY


# ── CACHE STORE ───────────────────────────────────────────────────────────────

class CacheStore:
    """Simple TTL cache for fallback data."""
    def __init__(self):
        self._cache: dict[str, dict] = {}

    def set(self, key: str, value: dict, ttl_s: int = 300) -> None:
        self._cache[key] = {
            "value":      value,
            "expires_at": time.perf_counter() + ttl_s,
            "cached_at":  datetime.now(timezone.utc).isoformat(),
        }

    def get(self, key: str) -> tuple[dict | None, float]:
        """Returns (value, age_seconds). age=-1 if not found."""
        entry = self._cache.get(key)
        if not entry:
            return None, -1
        if time.perf_counter() > entry["expires_at"]:
            del self._cache[key]
            return None, -1
        age_s = time.perf_counter() - (entry["expires_at"] - 300)
        return entry["value"], round(age_s, 1)


# ── SIMULATED COMPONENTS ──────────────────────────────────────────────────────

def query_pinot(user_id: str, health: ComponentHealth) -> dict | None:
    if health == ComponentHealth.DOWN:
        raise ConnectionError("Pinot broker unavailable")
    if health == ComponentHealth.DEGRADED:
        time.sleep(0.500)  # slow
    time.sleep(0.068)
    return {"errors_7d": 5, "error_rate": 0.50, "churn_risk": True, "plan": "free"}

def search_vectors(user_id: str, health: ComponentHealth) -> list[str] | None:
    if health == ComponentHealth.DOWN:
        raise ConnectionError("Vector store unavailable")
    time.sleep(0.050)
    return ["User hit 500 error on /checkout", "User clicked Upgrade to Pro"]

def call_llm(context: str, health: ComponentHealth) -> dict | None:
    if health == ComponentHealth.DOWN:
        raise ConnectionError("LLM API unavailable")
    time.sleep(0.200)
    return {
        "summary":    "User is at HIGH churn risk due to checkout errors.",
        "action":     "escalate_checkout_fix",
        "confidence": 0.92,
    }


# ── FALLBACK HANDLER ──────────────────────────────────────────────────────────

@dataclass
class AnalysisResult:
    user_id:      str
    summary:      str
    action:       str
    confidence:   float
    degraded:     bool = False
    degraded_reason: str = ""
    components_used: list[str] = field(default_factory=list)
    data_age_s:   float = 0.0


def analyze_user_with_fallback(
    user_id: str,
    health: SystemHealth,
    cache: CacheStore,
) -> AnalysisResult:
    """
    Analyzes a user with graceful degradation.
    Returns the best possible response given available components.
    """
    metrics      = None
    chunks       = []
    metrics_stale = False
    data_age_s   = 0.0
    components   = []

    # ── Step 1: Get structured metrics (Pinot) ────────────────────────────
    try:
        metrics = query_pinot(user_id, health.pinot)
        cache.set(f"metrics:{user_id}", metrics, ttl_s=300)
        components.append("pinot")
    except ConnectionError:
        # Fallback: use cached metrics
        cached, age = cache.get(f"metrics:{user_id}")
        if cached:
            metrics       = cached
            metrics_stale = True
            data_age_s    = age
            components.append("pinot_cache")
        # else: no metrics available

    # ── Step 2: Get semantic context (Vector Store) ───────────────────────
    try:
        chunks = search_vectors(user_id, health.vector_store)
        components.append("vector_store")
    except ConnectionError:
        chunks = []  # no semantic context

    # ── Step 3: Determine degradation level ──────────────────────────────
    has_metrics = metrics is not None
    has_context = len(chunks) > 0

    if not has_metrics and not has_context:
        # Tier 4: Nothing available — rule-based fallback
        return AnalysisResult(
            user_id=user_id,
            summary="Analysis unavailable. All data sources are currently down.",
            action="retry_in_5_minutes",
            confidence=0.0,
            degraded=True,
            degraded_reason="pinot_down,vector_store_down",
            components_used=[],
        )

    # ── Step 4: Call LLM (or rule-based if LLM down) ─────────────────────
    context_str = ""
    if has_metrics:
        context_str += f"Metrics: {metrics}\n"
    if has_context:
        context_str += f"Context: {chunks}\n"
    if metrics_stale:
        context_str += f"[WARNING: metrics are {data_age_s:.0f}s old]\n"

    try:
        llm_result = call_llm(context_str, health.llm_api)
        components.append("llm")

        degraded = metrics_stale or not has_context
        reason   = []
        if metrics_stale:
            reason.append(f"stale_metrics_{data_age_s:.0f}s")
        if not has_context:
            reason.append("no_semantic_context")

        return AnalysisResult(
            user_id=user_id,
            summary=llm_result["summary"],
            action=llm_result["action"],
            confidence=llm_result["confidence"] * (0.7 if degraded else 1.0),
            degraded=degraded,
            degraded_reason=",".join(reason),
            components_used=components,
            data_age_s=data_age_s,
        )

    except ConnectionError:
        # Tier 3: LLM down — rule-based response from metrics
        if has_metrics:
            churn  = metrics.get("churn_risk", False)
            errors = metrics.get("errors_7d", 0)
            rate   = metrics.get("error_rate", 0.0)
            return AnalysisResult(
                user_id=user_id,
                summary=f"[RULE-BASED] User has {errors} errors ({rate:.0%} rate). "
                        f"Churn risk: {'HIGH' if churn else 'LOW'}. "
                        f"(LLM unavailable — using rule-based analysis)",
                action="escalate_checkout_fix" if churn else "monitor",
                confidence=0.65,
                degraded=True,
                degraded_reason="llm_down,rule_based_fallback",
                components_used=components,
                data_age_s=data_age_s,
            )

    return AnalysisResult(
        user_id=user_id,
        summary="Partial analysis only. Some components unavailable.",
        action="manual_review",
        confidence=0.3,
        degraded=True,
        degraded_reason="multiple_components_down",
        components_used=components,
    )


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("FALLBACK HANDLER — Graceful degradation tiers")
    print("=" * 65)

    cache = CacheStore()
    # Pre-populate cache with "old" metrics
    cache.set("metrics:u_4821",
              {"errors_7d": 3, "error_rate": 0.30, "churn_risk": True, "plan": "free"},
              ttl_s=300)

    scenarios = [
        ("All healthy",
         SystemHealth()),
        ("Pinot down (using cache)",
         SystemHealth(pinot=ComponentHealth.DOWN)),
        ("Vector store down (metrics only)",
         SystemHealth(vector_store=ComponentHealth.DOWN)),
        ("LLM down (rule-based fallback)",
         SystemHealth(llm_api=ComponentHealth.DOWN)),
        ("Pinot + Vector down (nothing available)",
         SystemHealth(pinot=ComponentHealth.DOWN, vector_store=ComponentHealth.DOWN)),
    ]

    for label, health in scenarios:
        print(f"\n  {'─'*60}")
        print(f"  Scenario: {label}")
        result = analyze_user_with_fallback("u_4821", health, cache)
        icon   = "⚠️ " if result.degraded else "✅"
        print(f"  {icon} Degraded: {result.degraded}")
        print(f"  Summary:    {result.summary[:70]}...")
        print(f"  Action:     {result.action}")
        print(f"  Confidence: {result.confidence:.0%}")
        print(f"  Components: {result.components_used}")
        if result.degraded_reason:
            print(f"  Reason:     {result.degraded_reason}")

    print(f"\n{'='*65}")
    print(f"  KEY: System never returns 503. Always returns best available response.")
    print(f"  Degraded flag tells caller to treat response with lower confidence.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
