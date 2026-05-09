"""
Query Pipeline — Day 16: Query Understanding Layer
===================================================
End-to-end query understanding pipeline:
  Raw query → Intent → Entities → Retrieval Plan → (mock) Retrieval → LLM

Demonstrates the full query understanding flow and shows how
different queries produce different retrieval strategies.
"""

import time
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from intent_classifier import classify_intent, get_intent_metadata
from entity_extractor  import extract_entities
from retrieval_router  import build_retrieval_plan, RetrievalPlan


# ── MOCK RETRIEVAL (simulates Pinot + Vector DB) ──────────────────────────────

MOCK_PINOT_DATA = {
    "u_4821": {"errors": 5, "error_rate": 0.50, "intent": 0.82, "churn": True,  "plan": "free"},
    "u_0012": {"errors": 0, "error_rate": 0.00, "intent": 0.30, "churn": False, "plan": "pro"},
    "u_7734": {"errors": 2, "error_rate": 0.33, "intent": 0.40, "churn": True,  "plan": "free"},
    "u_9901": {"errors": 0, "error_rate": 0.00, "intent": 0.10, "churn": False, "plan": "enterprise"},
}

MOCK_VECTOR_DOCS = [
    {"user_id": "u_4821", "text": "User u_4821 hit 500 error on /checkout. Churn risk: TRUE."},
    {"user_id": "u_4821", "text": "User u_4821 clicked Upgrade to Pro. Intent: 0.82."},
    {"user_id": "u_4821", "text": "Support ticket: checkout keeps failing."},
    {"user_id": "u_7734", "text": "User u_7734 hit 500 error on /checkout. First error."},
    {"user_id": "u_7734", "text": "User u_7734 visited /pricing twice. Moderate intent."},
    {"user_id": "u_0012", "text": "User u_0012 purchased enterprise tier. Payment processed."},
]

def mock_retrieve(plan: RetrievalPlan) -> dict:
    """Simulates retrieval based on the plan."""
    time.sleep(0.05)  # simulate ~50ms retrieval latency

    structured = {}
    semantic   = []

    if plan.use_pinot:
        uid = plan.pinot_filters.get("user_id")
        if uid:
            structured = {uid: MOCK_PINOT_DATA.get(uid, {})}
        else:
            # Multi-user: filter by plan and churn_risk
            plan_f = plan.pinot_filters.get("plan")
            churn_f = plan.pinot_filters.get("churn_risk")
            structured = {
                uid: data for uid, data in MOCK_PINOT_DATA.items()
                if (plan_f is None or data["plan"] == plan_f)
                and (churn_f is None or data["churn"] == churn_f)
            }

    if plan.use_vector:
        uid = plan.vector_filter.get("user_id")
        docs = [d for d in MOCK_VECTOR_DOCS if uid is None or d["user_id"] == uid]
        semantic = docs[:plan.top_k]

    return {"structured": structured, "semantic": semantic}


# ── MOCK LLM ──────────────────────────────────────────────────────────────────

def mock_llm(plan: RetrievalPlan, retrieved: dict) -> dict:
    """Generates a mock LLM response based on retrieved context."""
    time.sleep(0.08)  # simulate ~80ms LLM latency

    structured = retrieved["structured"]
    semantic   = retrieved["semantic"]
    intent     = plan.intent

    if intent == "error_investigation":
        uid  = plan.pinot_filters.get("user_id", "unknown")
        data = structured.get(uid, {})
        return {
            "summary":    f"User {uid} has {data.get('errors',0)} errors "
                          f"({data.get('error_rate',0):.0%} rate). "
                          f"Checkout failures are the primary issue.",
            "action":     "escalate_to_engineering",
            "confidence": 0.92,
            "evidence":   [c["text"] for c in semantic[:2]],
        }

    elif intent == "churn_analysis":
        at_risk = [(uid, d) for uid, d in structured.items() if d.get("churn")]
        at_risk.sort(key=lambda x: x[1].get("error_rate", 0), reverse=True)
        top = at_risk[:3]
        return {
            "summary":    f"{len(at_risk)} free-plan users at churn risk. "
                          + (f"Top risk: {top[0][0]} ({top[0][1]['error_rate']:.0%} error rate)." if top else ""),
            "action":     "trigger_retention_workflow",
            "confidence": 0.87,
            "evidence":   [c["text"] for c in semantic[:2]],
        }

    elif intent == "upgrade_analysis":
        candidates = [(uid, d) for uid, d in structured.items() if d.get("intent", 0) > 0.5]
        candidates.sort(key=lambda x: x[1].get("intent", 0), reverse=True)
        top = candidates[:2]
        return {
            "summary":    f"{len(candidates)} users with upgrade intent > 0.5. "
                          + (f"Top candidate: {top[0][0]} (intent={top[0][1]['intent']:.2f})." if top else ""),
            "action":     "send_upgrade_offer",
            "confidence": 0.79,
            "evidence":   [c["text"] for c in semantic[:2]],
        }

    else:
        return {
            "summary":    "Query processed. See retrieved context for details.",
            "action":     "review",
            "confidence": 0.65,
            "evidence":   [c["text"] for c in semantic[:2]],
        }


# ── FULL PIPELINE ─────────────────────────────────────────────────────────────

def run_pipeline(query: str) -> dict:
    """Runs the full query understanding → retrieval → LLM pipeline."""
    t0 = time.perf_counter()

    # Step 1: Build retrieval plan
    plan = build_retrieval_plan(query)
    t_plan = (time.perf_counter() - t0) * 1000

    # Step 2: Retrieve
    retrieved = mock_retrieve(plan)
    t_retrieve = (time.perf_counter() - t0) * 1000

    # Step 3: LLM
    response = mock_llm(plan, retrieved)
    t_total = (time.perf_counter() - t0) * 1000

    return {
        "query":     query,
        "plan":      plan,
        "response":  response,
        "timing": {
            "understanding_ms": round(t_plan, 1),
            "retrieval_ms":     round(t_retrieve - t_plan, 1),
            "llm_ms":           round(t_total - t_retrieve, 1),
            "total_ms":         round(t_total, 1),
        },
        "retrieved_counts": {
            "structured": len(retrieved["structured"]),
            "semantic":   len(retrieved["semantic"]),
        },
    }


# ── DEMO ──────────────────────────────────────────────────────────────────────

DEMO_QUERIES = [
    "Show me all errors for user u_4821 in the last 2 hours",
    "Which free-plan users are most at risk this week?",
    "Who is most likely to upgrade to pro this month?",
]

def run() -> None:
    print("=" * 65)
    print("QUERY PIPELINE — End-to-End Query Understanding")
    print("=" * 65)

    for query in DEMO_QUERIES:
        result = run_pipeline(query)
        plan   = result["plan"]
        resp   = result["response"]
        timing = result["timing"]
        counts = result["retrieved_counts"]

        print(f"\n{'─'*65}")
        print(f"  Query:      \"{query}\"")
        print(f"  Intent:     {plan.intent} ({plan.confidence:.0%} confidence)")
        print(f"  Plan:       pinot={plan.use_pinot}, vector={plan.use_vector}, "
              f"top_k={plan.top_k}, freshness={plan.freshness_sla_s}s")
        print(f"  Retrieved:  {counts['structured']} structured, {counts['semantic']} semantic")
        print(f"  Timing:     understanding={timing['understanding_ms']}ms, "
              f"retrieval={timing['retrieval_ms']}ms, "
              f"llm={timing['llm_ms']}ms, "
              f"total={timing['total_ms']}ms")
        print(f"  Response:")
        print(f"    Summary:    {resp['summary']}")
        print(f"    Action:     {resp['action']}")
        print(f"    Confidence: {resp['confidence']:.0%}")
        if resp["evidence"]:
            print(f"    Evidence:   {resp['evidence'][0][:60]}...")

    # Show routing difference
    print(f"\n{'='*65}")
    print(f"  ROUTING COMPARISON")
    print(f"  {'Query type':25s} {'Pinot':6s} {'Vector':7s} {'top_k':6s} {'Freshness':10s}")
    print(f"  {'-'*60}")
    for query in DEMO_QUERIES:
        plan = build_retrieval_plan(query)
        print(f"  {plan.intent:25s} {'✅' if plan.use_pinot else '❌':6s} "
              f"{'✅' if plan.use_vector else '❌':7s} "
              f"{plan.top_k:6d} {plan.freshness_sla_s:>6d}s")

    print(f"\n  Each query type gets a different, optimized retrieval strategy.")
    print(f"  Without query understanding: all queries get the same treatment.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
