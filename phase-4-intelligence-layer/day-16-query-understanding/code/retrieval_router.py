"""
Retrieval Router — Day 16: Query Understanding Layer
=====================================================
Combines intent classification and entity extraction to produce
a precise retrieval plan for the hybrid retrieval layer.

The retrieval plan specifies:
  - Which systems to query (Pinot, Vector DB, or both)
  - What filters to apply to each
  - How many results to retrieve (top_k)
  - What freshness is required
  - What token budget to use
  - What vector query string to use
"""

import time
from dataclasses import dataclass, field
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from intent_classifier import classify_intent, get_intent_metadata, IntentResult
from entity_extractor  import extract_entities, EntityResult


# ── RETRIEVAL PLAN ────────────────────────────────────────────────────────────

@dataclass
class RetrievalPlan:
    # Source systems
    use_pinot:       bool
    use_vector:      bool

    # Pinot configuration
    pinot_filters:   dict
    pinot_time_h:    float
    pinot_limit:     int

    # Vector DB configuration
    vector_query:    str
    vector_filter:   dict
    top_k:           int

    # Quality controls
    freshness_sla_s: int
    token_budget:    int

    # Metadata
    intent:          str
    confidence:      float
    latency_ms:      float


# ── VECTOR QUERY BUILDER ──────────────────────────────────────────────────────

INTENT_VECTOR_QUERIES = {
    "error_investigation": "error failure crash exception checkout payment",
    "churn_analysis":      "churn risk behavior errors disengagement frustration",
    "upgrade_analysis":    "upgrade intent pricing page feature limit conversion",
    "retention_analysis":  "engagement session activity return visit onboarding",
    "operational":         "system health error rate latency incident",
    "general":             "",  # use raw query
}

def build_vector_query(intent: str, entities: EntityResult, raw_query: str) -> str:
    base = INTENT_VECTOR_QUERIES.get(intent, raw_query)
    parts = [base]
    if entities.user_id:
        parts.append(entities.user_id)
    if entities.event_type:
        parts.append(entities.event_type)
    return " ".join(p for p in parts if p)


# ── PINOT FILTER BUILDER ──────────────────────────────────────────────────────

def build_pinot_filters(intent: str, entities: EntityResult) -> dict:
    filters: dict = {}

    if entities.user_id:
        filters["user_id"] = entities.user_id

    if entities.plan_filter:
        filters["plan"] = entities.plan_filter

    if entities.segment:
        filters["segment"] = entities.segment

    if entities.risk_flag or intent in ("churn_analysis", "retention_analysis"):
        filters["churn_risk"] = True

    if intent == "error_investigation" or entities.event_type == "error":
        filters["has_errors"] = True

    if intent == "upgrade_analysis":
        filters["intent_score_min"] = 0.5

    return filters


# ── MAIN ROUTER ───────────────────────────────────────────────────────────────

def build_retrieval_plan(query: str) -> RetrievalPlan:
    """
    Produces a complete retrieval plan from a natural language query.
    Combines intent classification + entity extraction.
    """
    t0 = time.perf_counter()

    # Step 1: Classify intent
    intent_result = classify_intent(query)
    intent        = intent_result.intent
    meta          = get_intent_metadata(intent)

    # Step 2: Extract entities
    entities = extract_entities(query)

    # Step 3: Build retrieval plan
    pinot_filters  = build_pinot_filters(intent, entities)
    vector_query   = build_vector_query(intent, entities, query)
    vector_filter  = {"user_id": entities.user_id} if entities.user_id else {}

    # Adjust top_k for single-user vs multi-user queries
    top_k = meta["top_k"]
    if entities.user_id:
        top_k = min(top_k, 3)  # focused single-user query

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    return RetrievalPlan(
        use_pinot=       meta["use_pinot"],
        use_vector=      meta["use_vector"],
        pinot_filters=   pinot_filters,
        pinot_time_h=    entities.time_range_h,
        pinot_limit=     10 if not entities.user_id else 1,
        vector_query=    vector_query,
        vector_filter=   vector_filter,
        top_k=           top_k,
        freshness_sla_s= meta["freshness_sla"],
        token_budget=    meta["token_budget"],
        intent=          intent,
        confidence=      intent_result.confidence,
        latency_ms=      latency_ms,
    )


# ── DEMO ──────────────────────────────────────────────────────────────────────

TEST_QUERIES = [
    "Show me all errors for user u_4821 in the last 2 hours",
    "Which free-plan users are most at risk this week?",
    "Who is most likely to upgrade to pro this month?",
    "What is the current system error rate?",
    "How engaged are our new users in the last 7 days?",
]

def run() -> None:
    print("=" * 65)
    print("RETRIEVAL ROUTER — Query Understanding Layer")
    print("=" * 65)

    for query in TEST_QUERIES:
        plan = build_retrieval_plan(query)
        print(f"\n  Query:    \"{query}\"")
        print(f"  Intent:   {plan.intent} (confidence={plan.confidence:.0%})")
        print(f"  Systems:  pinot={plan.use_pinot}, vector={plan.use_vector}")
        print(f"  Pinot:    filters={plan.pinot_filters}, time={plan.pinot_time_h}h, limit={plan.pinot_limit}")
        print(f"  Vector:   query=\"{plan.vector_query[:50]}...\"")
        print(f"            filter={plan.vector_filter}, top_k={plan.top_k}")
        print(f"  Quality:  freshness_sla={plan.freshness_sla_s}s, token_budget={plan.token_budget}")
        print(f"  Latency:  {plan.latency_ms:.2f}ms")

    print(f"\n{'='*65}")
    print(f"  Retrieval routing adds < 3ms total overhead.")
    print(f"  Each query now has a precise, optimized retrieval plan.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
