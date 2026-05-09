"""
Query Understanding — Day 15: Production RAG
Classifies query intent and extracts entities for retrieval routing.

No external dependencies. Run standalone:
    python query_understanding.py
"""

import re
import time


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

INTENT_PATTERNS = {
    "churn_analysis": [
        r"\bchurn\b", r"\bat.risk\b", r"\bchurn.risk\b", r"\blikely.to.leave\b",
        r"\bwill.cancel\b", r"\bretention.risk\b", r"\babout.to.leave\b",
        r"\bmost.at.risk\b", r"\bhighest.risk\b",
    ],
    "error_investigation": [
        r"\berror[s]?\b", r"\bfailure[s]?\b", r"\bcrash[es]?\b", r"\bexception[s]?\b",
        r"\bbug[s]?\b", r"\bbroken\b", r"\bnot.working\b", r"\bfailing\b",
        r"\btimeout[s]?\b", r"\b500\b", r"\b4xx\b", r"\bstack.trace\b",
    ],
    "upgrade_analysis": [
        r"\bupgrade[d]?\b", r"\bconvert[ed]?\b", r"\bpaid.plan\b", r"\bpro.plan\b",
        r"\bpremium\b", r"\bpurchase[d]?\b", r"\bsubscri[be|bed|ption]\b",
        r"\bwilling.to.pay\b", r"\bupgrade.intent\b",
    ],
    "retention_analysis": [
        r"\bretention\b", r"\bkeep\b", r"\bstick[y]?\b", r"\bengage[d|ment]?\b",
        r"\bactive.user[s]?\b", r"\bdau\b", r"\bmau\b", r"\bsession[s]?\b",
        r"\bfrequency\b", r"\bhabitual\b",
    ],
}


def classify_intent(query: str) -> str:
    """
    Classify the intent of a natural language query.

    Returns one of:
        churn_analysis       — questions about users at risk of leaving
        error_investigation  — questions about errors, failures, crashes
        upgrade_analysis     — questions about plan upgrades and conversions
        retention_analysis   — questions about engagement and retention
        general              — everything else

    Strategy: score each intent by counting pattern matches. Return the
    highest-scoring intent. Ties go to the first match in priority order.
    """
    query_lower = query.lower()
    scores = {intent: 0 for intent in INTENT_PATTERNS}

    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, query_lower):
                scores[intent] += 1

    best_intent = max(scores, key=lambda k: scores[k])
    if scores[best_intent] == 0:
        return "general"
    return best_intent


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

# Time range keywords → hours
TIME_PATTERNS = [
    (r"\blast\s+(\d+)\s+hour[s]?",   lambda m: int(m.group(1))),
    (r"\blast\s+(\d+)\s+day[s]?",    lambda m: int(m.group(1)) * 24),
    (r"\blast\s+(\d+)\s+week[s]?",   lambda m: int(m.group(1)) * 168),
    (r"\btoday\b",                    lambda m: 24),
    (r"\bthis\s+week\b",              lambda m: 168),
    (r"\bthis\s+month\b",             lambda m: 720),
    (r"\byesterday\b",                lambda m: 48),
    (r"\b(\d+)h\b",                   lambda m: int(m.group(1))),
    (r"\b(\d+)d\b",                   lambda m: int(m.group(1)) * 24),
]

PLAN_PATTERNS = {
    "free":       [r"\bfree.plan\b", r"\bfree.tier\b", r"\bfree.user[s]?\b", r"\bon.free\b"],
    "pro":        [r"\bpro.plan\b",  r"\bpro.user[s]?\b",  r"\bon.pro\b"],
    "enterprise": [r"\benterprise\b", r"\benterprise.plan\b"],
    "paid":       [r"\bpaid.plan\b", r"\bpaid.user[s]?\b", r"\bpaying\b"],
}

SEGMENT_PATTERNS = {
    "new_users":       [r"\bnew.user[s]?\b", r"\brecently.joined\b", r"\bjust.signed.up\b"],
    "power_users":     [r"\bpower.user[s]?\b", r"\bheavy.user[s]?\b", r"\bmost.active\b"],
    "inactive_users":  [r"\binactive\b", r"\bdormant\b", r"\bnot.active\b", r"\blapsed\b"],
    "trial_users":     [r"\btrial\b", r"\btrial.user[s]?\b", r"\bon.trial\b"],
}


def extract_entities(query: str) -> dict:
    """
    Extract structured entities from a natural language query.

    Returns a dict with:
        user_id         (str | None)   — specific user ID if mentioned
        time_range_hours (int)         — time window in hours (default: 24)
        plan_filter     (str | None)   — plan tier if mentioned
        segment_filter  (str | None)   — user segment if mentioned
    """
    query_lower = query.lower()
    entities = {
        "user_id": None,
        "time_range_hours": 24,   # default: last 24 hours
        "plan_filter": None,
        "segment_filter": None,
    }

    # User ID: look for patterns like u_4821, user_4821, user-4821, uid:4821
    uid_match = re.search(r"\b(u[_\-]?\d{3,6}|user[_\-]?\d{3,6}|uid[:\s]?\d{3,6})\b",
                          query, re.IGNORECASE)
    if uid_match:
        # Normalize to u_XXXX format
        raw = uid_match.group(1)
        digits = re.search(r"\d+", raw).group()
        entities["user_id"] = f"u_{digits}"

    # Time range: first match wins
    for pattern, extractor in TIME_PATTERNS:
        m = re.search(pattern, query_lower)
        if m:
            entities["time_range_hours"] = extractor(m)
            break

    # Plan filter: first match wins
    for plan, patterns in PLAN_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, query_lower):
                entities["plan_filter"] = plan
                break
        if entities["plan_filter"]:
            break

    # Segment filter: first match wins
    for segment, patterns in SEGMENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, query_lower):
                entities["segment_filter"] = segment
                break
        if entities["segment_filter"]:
            break

    return entities


# ---------------------------------------------------------------------------
# Retrieval plan builder
# ---------------------------------------------------------------------------

# Intent → retrieval strategy configuration
INTENT_RETRIEVAL_CONFIG = {
    "churn_analysis": {
        "use_pinot":          True,
        "use_vector":         True,
        "top_k":              5,
        "freshness_required": True,
        "vector_query_tmpl":  "user churn risk behavior errors disengagement {plan} {segment}",
    },
    "error_investigation": {
        "use_pinot":          True,
        "use_vector":         True,
        "top_k":              3,
        "freshness_required": True,
        "vector_query_tmpl":  "error failure crash exception {user_id} {plan}",
    },
    "upgrade_analysis": {
        "use_pinot":          True,
        "use_vector":         True,
        "top_k":              3,
        "freshness_required": False,
        "vector_query_tmpl":  "upgrade intent pricing page feature limit {plan} {segment}",
    },
    "retention_analysis": {
        "use_pinot":          True,
        "use_vector":         True,
        "top_k":              5,
        "freshness_required": False,
        "vector_query_tmpl":  "user engagement session activity retention {plan} {segment}",
    },
    "general": {
        "use_pinot":          False,
        "use_vector":         True,
        "top_k":              3,
        "freshness_required": False,
        "vector_query_tmpl":  "{query}",
    },
}


def build_retrieval_plan(intent: str, entities: dict, original_query: str = "") -> dict:
    """
    Build a retrieval plan based on classified intent and extracted entities.

    Returns a dict with:
        use_pinot          (bool)   — whether to query Pinot
        use_vector         (bool)   — whether to query vector store
        pinot_filters      (dict)   — filters to apply in Pinot query
        vector_query       (str)    — query string for vector search
        top_k              (int)    — number of vector results to retrieve
        freshness_required (bool)   — whether stale results are unacceptable
        time_range_hours   (int)    — time window for Pinot query
    """
    config = INTENT_RETRIEVAL_CONFIG.get(intent, INTENT_RETRIEVAL_CONFIG["general"])

    # Build Pinot filters from entities
    pinot_filters = {}
    if entities.get("plan_filter"):
        pinot_filters["plan"] = entities["plan_filter"]
    if entities.get("user_id"):
        pinot_filters["user_id"] = entities["user_id"]
    if intent in ("churn_analysis", "retention_analysis"):
        pinot_filters["churn_risk"] = True
    if intent == "error_investigation":
        pinot_filters["has_errors"] = True

    # Build vector query from template
    tmpl = config["vector_query_tmpl"]
    vector_query = tmpl.format(
        user_id=entities.get("user_id") or "",
        plan=entities.get("plan_filter") or "",
        segment=entities.get("segment_filter") or "",
        query=original_query,
    ).strip()
    # Clean up extra whitespace from empty substitutions
    vector_query = re.sub(r"\s+", " ", vector_query).strip()

    return {
        "use_pinot":          config["use_pinot"],
        "use_vector":         config["use_vector"],
        "pinot_filters":      pinot_filters,
        "vector_query":       vector_query,
        "top_k":              config["top_k"],
        "freshness_required": config["freshness_required"],
        "time_range_hours":   entities["time_range_hours"],
    }


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------

def understand_query(query: str) -> dict:
    """
    Full query understanding pipeline.

    Returns a dict with:
        query            — original query
        intent           — classified intent
        entities         — extracted entities
        retrieval_plan   — retrieval routing plan
        processing_ms    — time taken in milliseconds
    """
    t0 = time.perf_counter()
    intent = classify_intent(query)
    entities = extract_entities(query)
    plan = build_retrieval_plan(intent, entities, original_query=query)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    return {
        "query":          query,
        "intent":         intent,
        "entities":       entities,
        "retrieval_plan": plan,
        "processing_ms":  round(elapsed_ms, 2),
    }


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def _print_result(result: dict) -> None:
    q = result["query"]
    print(f"\n{'─'*70}")
    print(f"  Query   : {q}")
    print(f"  Intent  : {result['intent']}")
    e = result["entities"]
    print(f"  Entities: user_id={e['user_id']}, "
          f"time={e['time_range_hours']}h, "
          f"plan={e['plan_filter']}, "
          f"segment={e['segment_filter']}")
    p = result["retrieval_plan"]
    print(f"  Plan    : pinot={p['use_pinot']}, vector={p['use_vector']}, "
          f"top_k={p['top_k']}, fresh={p['freshness_required']}")
    print(f"  Filters : {p['pinot_filters']}")
    print(f"  VQuery  : {p['vector_query']}")
    print(f"  Time    : {result['processing_ms']}ms")


if __name__ == "__main__":
    print("=" * 70)
    print("  Query Understanding — Day 15: Production RAG")
    print("=" * 70)

    demo_queries = [
        "Which free-plan users are most at risk this week and why?",
        "Show me all errors for user u_4821 in the last 2 hours",
        "Which users are most likely to upgrade to pro this month?",
        "How engaged are our new users in the last 7 days?",
        "What is the system status?",
    ]

    results = []
    for query in demo_queries:
        result = understand_query(query)
        results.append(result)
        _print_result(result)

    print(f"\n{'─'*70}")
    print(f"\n  Summary: {len(results)} queries processed")
    intent_counts = {}
    for r in results:
        intent_counts[r["intent"]] = intent_counts.get(r["intent"], 0) + 1
    for intent, count in sorted(intent_counts.items()):
        print(f"    {intent:<25} {count} query/queries")

    # Verify all intents are classified (not all "general")
    non_general = [r for r in results if r["intent"] != "general"]
    assert len(non_general) >= 4, "Expected at least 4 non-general classifications"

    # Verify entity extraction
    error_result = results[1]
    assert error_result["entities"]["user_id"] == "u_4821", \
        f"Expected u_4821, got {error_result['entities']['user_id']}"
    assert error_result["entities"]["time_range_hours"] == 2, \
        f"Expected 2h, got {error_result['entities']['time_range_hours']}"

    free_result = results[0]
    assert free_result["entities"]["plan_filter"] == "free", \
        f"Expected free, got {free_result['entities']['plan_filter']}"
    assert free_result["entities"]["time_range_hours"] == 168, \
        f"Expected 168h (1 week), got {free_result['entities']['time_range_hours']}"

    print("\n  ✓ All assertions passed")
    print("=" * 70)
