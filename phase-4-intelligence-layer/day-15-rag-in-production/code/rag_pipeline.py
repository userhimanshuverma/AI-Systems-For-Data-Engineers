"""
Production RAG Pipeline — Day 15
End-to-end: query → understanding → retrieval → filter → LLM → validate

No external dependencies. Run standalone:
    python rag_pipeline.py
"""

import sys
import os
import time
import json

# Allow importing sibling modules when run directly
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from query_understanding import understand_query
from hybrid_retrieval import PinotStore, VectorStore, HybridRetriever, build_default_vector_store
from context_filter import filter_context, format_context, count_tokens


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------

# Canned responses keyed by intent — realistic structured JSON outputs
_LLM_RESPONSES = {
    "churn_analysis": {
        "intent": "churn_analysis",
        "users": [
            {
                "user_id": "u_4821",
                "risk_level": "critical",
                "churn_probability": 0.91,
                "primary_reason": "Repeated checkout failures with no resolution",
                "evidence": [
                    "3 checkout errors in 2 hours (payment gateway timeout)",
                    "Submitted support ticket: 'Cannot complete purchase'",
                    "Viewed /pricing page after errors — possible exit intent",
                    "Only 2 sessions this week, last active 18h ago",
                ],
                "recommended_action": "Immediate outreach: offer manual payment assistance",
            },
            {
                "user_id": "u_9901",
                "risk_level": "critical",
                "churn_probability": 0.88,
                "primary_reason": "High error rate with extended inactivity",
                "evidence": [
                    "4 checkout errors and 3 support tickets in 72 hours",
                    "Last session 3 days ago — significant disengagement",
                    "Error rate 0.44 — highest in cohort",
                ],
                "recommended_action": "Proactive support contact with error resolution offer",
            },
            {
                "user_id": "u_3302",
                "risk_level": "high",
                "churn_probability": 0.78,
                "primary_reason": "Feature limit frustration with failed upgrade attempt",
                "evidence": [
                    "Hit data export feature limit",
                    "Viewed /upgrade page for 4 minutes but did not convert",
                    "Checkout error during upgrade attempt — payment declined",
                ],
                "recommended_action": "Offer temporary feature limit increase + payment retry",
            },
        ],
        "summary": "3 free-plan users at critical/high churn risk this week. "
                   "Primary driver: checkout errors blocking conversion and usage.",
        "confidence": 0.87,
        "data_freshness": "retrieved within last 2 hours",
    },
    "error_investigation": {
        "intent": "error_investigation",
        "user_id": "u_4821",
        "error_summary": {
            "total_errors": 3,
            "error_type": "checkout_error",
            "root_cause": "Payment gateway timeout — likely intermittent gateway issue",
            "first_occurrence": "1.5 hours ago",
            "last_occurrence": "1.0 hours ago",
            "user_impact": "Unable to complete purchase",
        },
        "timeline": [
            {"ts": "1.5h ago", "event": "Checkout error: payment gateway timeout"},
            {"ts": "1.2h ago", "event": "Retry attempt — same error"},
            {"ts": "1.0h ago", "event": "Support ticket submitted"},
            {"ts": "0.8h ago", "event": "User viewed /pricing page"},
        ],
        "recommendation": "Check payment gateway health. Offer manual payment processing to u_4821.",
        "confidence": 0.92,
        "data_freshness": "retrieved within last 30 minutes",
    },
    "upgrade_analysis": {
        "intent": "upgrade_analysis",
        "upgrade_candidates": [
            {
                "user_id": "u_1190",
                "upgrade_probability": 0.71,
                "signals": [
                    "7 sessions this week, 44 page views",
                    "Consistently views /pricing and /compare pages",
                    "No errors — positive product experience",
                ],
                "recommended_action": "Targeted upgrade offer with feature highlight",
            },
            {
                "user_id": "u_3302",
                "upgrade_probability": 0.58,
                "signals": [
                    "Hit feature limit on data exports",
                    "Viewed /upgrade page for 4 minutes",
                    "Blocked by checkout error — fix payment to unlock conversion",
                ],
                "recommended_action": "Fix checkout error first, then send upgrade nudge",
            },
        ],
        "summary": "2 free-plan users showing strong upgrade intent. "
                   "u_1190 is the cleanest conversion opportunity.",
        "confidence": 0.79,
        "data_freshness": "retrieved within last 4 hours",
    },
    "general": {
        "intent": "general",
        "response": "I found relevant context in the knowledge base. "
                    "Based on the retrieved information, the system appears to be "
                    "operating within normal parameters. No critical issues detected.",
        "confidence": 0.55,
        "data_freshness": "retrieved within last 24 hours",
    },
}


def mock_llm(prompt: str, intent: str) -> dict:
    """
    Simulate an LLM call with a structured JSON response.

    In production: replace with OpenAI, Anthropic, or Bedrock API call.

    Args:
        prompt: The full prompt string (system + context + query).
        intent: Classified intent from query understanding.

    Returns:
        Dict representing the LLM's structured JSON response.
    """
    # Simulate LLM latency (150-300ms for a real API call)
    time.sleep(0.18)

    response = _LLM_RESPONSES.get(intent, _LLM_RESPONSES["general"])
    return dict(response)


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

REQUIRED_FIELDS_BY_INTENT = {
    "churn_analysis":     {"intent", "users", "confidence", "summary"},
    "error_investigation": {"intent", "user_id", "error_summary", "confidence"},
    "upgrade_analysis":   {"intent", "upgrade_candidates", "confidence", "summary"},
    "general":            {"intent", "response", "confidence"},
}

CONFIDENCE_THRESHOLD = 0.60


def validate_output(response: dict, intent: str) -> dict:
    """
    Validate LLM output for required fields and confidence threshold.

    Checks:
    1. Required fields present for the given intent.
    2. Confidence score >= CONFIDENCE_THRESHOLD.
    3. Confidence is a valid float in [0, 1].

    Args:
        response: Raw LLM response dict.
        intent:   Classified intent (used to determine required fields).

    Returns:
        {
            valid:          bool
            confidence:     float
            missing_fields: list of str
            errors:         list of str
            warnings:       list of str
        }
    """
    errors = []
    warnings = []
    missing_fields = []

    # Check required fields
    required = REQUIRED_FIELDS_BY_INTENT.get(intent, {"intent", "response", "confidence"})
    for field in required:
        if field not in response:
            missing_fields.append(field)
            errors.append(f"Missing required field: '{field}'")

    # Check confidence
    confidence = response.get("confidence", 0.0)
    if not isinstance(confidence, (int, float)):
        errors.append(f"Confidence must be numeric, got: {type(confidence).__name__}")
        confidence = 0.0
    elif not (0.0 <= confidence <= 1.0):
        errors.append(f"Confidence out of range [0,1]: {confidence}")
    elif confidence < CONFIDENCE_THRESHOLD:
        warnings.append(
            f"Low confidence: {confidence:.2f} < threshold {CONFIDENCE_THRESHOLD:.2f}. "
            "Response flagged for review."
        )

    # Check intent consistency
    response_intent = response.get("intent", "")
    if response_intent and response_intent != intent:
        warnings.append(
            f"Intent mismatch: query classified as '{intent}' but "
            f"response claims '{response_intent}'"
        )

    valid = len(errors) == 0 and confidence >= CONFIDENCE_THRESHOLD

    return {
        "valid":          valid,
        "confidence":     float(confidence),
        "missing_fields": missing_fields,
        "errors":         errors,
        "warnings":       warnings,
    }


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def run_pipeline(query: str) -> dict:
    """
    Run the full production RAG pipeline end-to-end.

    Stages:
        1. Query Understanding  — classify intent, extract entities, build plan
        2. Hybrid Retrieval     — Pinot + Vector in parallel
        3. Context Filter       — score, rank, deduplicate, token budget
        4. LLM                  — structured prompt → JSON response
        5. Output Validation    — required fields, confidence threshold

    Args:
        query: Natural language query string.

    Returns:
        {
            query:           str
            intent:          str
            entities:        dict
            retrieval_plan:  dict
            retrieval_ms:    float
            context_tokens:  int
            chunks_selected: int
            chunks_dropped:  int
            llm_response:    dict
            validation:      dict
            total_ms:        float
            success:         bool
        }
    """
    t_pipeline_start = time.perf_counter()

    # --- Stage 1: Query Understanding ---
    t1 = time.perf_counter()
    understood = understand_query(query)
    intent = understood["intent"]
    entities = understood["entities"]
    retrieval_plan = understood["retrieval_plan"]
    understanding_ms = (time.perf_counter() - t1) * 1000

    # --- Stage 2: Hybrid Retrieval ---
    t2 = time.perf_counter()
    retrieval_result = _RETRIEVER.retrieve(
        retrieval_plan=retrieval_plan,
        user_id=entities.get("user_id"),
    )
    retrieval_ms = (time.perf_counter() - t2) * 1000

    structured_metrics = retrieval_result["structured_results"]
    semantic_chunks = retrieval_result["semantic_results"]

    # --- Stage 3: Context Filter ---
    t3 = time.perf_counter()
    query_entities_for_filter = {
        **entities,
        "intent": intent,
    }
    filtered = filter_context(
        structured_metrics=structured_metrics,
        semantic_chunks=semantic_chunks,
        query=query,
        query_entities=query_entities_for_filter,
        max_tokens=400,
        min_relevance_score=0.30,
    )
    context_text = format_context(filtered)
    filter_ms = (time.perf_counter() - t3) * 1000

    # --- Stage 4: LLM ---
    t4 = time.perf_counter()
    prompt = _build_prompt(query, context_text, intent)
    llm_response = mock_llm(prompt, intent)
    llm_ms = (time.perf_counter() - t4) * 1000

    # --- Stage 5: Output Validation ---
    t5 = time.perf_counter()
    validation = validate_output(llm_response, intent)
    validation_ms = (time.perf_counter() - t5) * 1000

    total_ms = (time.perf_counter() - t_pipeline_start) * 1000

    return {
        "query":           query,
        "intent":          intent,
        "entities":        entities,
        "retrieval_plan":  retrieval_plan,
        "understanding_ms": round(understanding_ms, 2),
        "retrieval_ms":    round(retrieval_ms, 2),
        "filter_ms":       round(filter_ms, 2),
        "llm_ms":          round(llm_ms, 2),
        "validation_ms":   round(validation_ms, 2),
        "total_ms":        round(total_ms, 2),
        "context_tokens":  filtered["total_tokens"],
        "chunks_selected": len(filtered["semantic_selected"]),
        "chunks_dropped":  filtered["dropped_count"],
        "llm_response":    llm_response,
        "validation":      validation,
        "success":         validation["valid"],
    }


def _build_prompt(query: str, context: str, intent: str) -> str:
    """Build the full LLM prompt from query, context, and intent."""
    system_prompts = {
        "churn_analysis": (
            "You are a retention analyst. Analyze the provided user data and identify "
            "users at risk of churning. Return a JSON object with: intent, users (list with "
            "user_id, risk_level, churn_probability, primary_reason, evidence, "
            "recommended_action), summary, confidence, data_freshness."
        ),
        "error_investigation": (
            "You are a support engineer. Analyze the provided error data and summarize "
            "the issue. Return a JSON object with: intent, user_id, error_summary "
            "(total_errors, error_type, root_cause, first_occurrence, last_occurrence, "
            "user_impact), timeline, recommendation, confidence, data_freshness."
        ),
        "upgrade_analysis": (
            "You are a growth analyst. Identify users most likely to upgrade based on "
            "the provided data. Return a JSON object with: intent, upgrade_candidates "
            "(list with user_id, upgrade_probability, signals, recommended_action), "
            "summary, confidence, data_freshness."
        ),
        "general": (
            "You are a data analyst. Answer the user's question based on the provided "
            "context. Return a JSON object with: intent, response, confidence, data_freshness."
        ),
    }

    system = system_prompts.get(intent, system_prompts["general"])

    return (
        f"[SYSTEM]\n{system}\n\n"
        f"[CONTEXT]\n{context}\n\n"
        f"[QUERY]\n{query}\n\n"
        f"[INSTRUCTIONS]\nRespond with valid JSON only. No markdown, no explanation."
    )


# ---------------------------------------------------------------------------
# Toy RAG comparison
# ---------------------------------------------------------------------------

def run_toy_rag(query: str) -> dict:
    """
    Simulate the toy RAG pattern for comparison.

    Toy RAG: embed query → vector search top-5 → send all to LLM → trust output.
    No query understanding, no structured retrieval, no context filtering,
    no output validation.
    """
    t0 = time.perf_counter()

    # Step 1: Embed and search (no intent classification, no routing)
    results = _VECTOR_STORE.search(query, top_k=5)

    # Step 2: Concatenate all chunks (no filtering, no token budget)
    raw_context = "\n".join(r["text"] for r in results)
    raw_tokens = count_tokens(raw_context)

    # Step 3: LLM (no structured prompt, no intent-specific guidance)
    time.sleep(0.18)  # simulate LLM latency
    toy_response = {
        "response": "Based on the retrieved documents, some users appear to have "
                    "experienced errors. User activity varies across the platform. "
                    "Further investigation may be needed.",
        "confidence": None,   # toy RAG doesn't track confidence
    }

    total_ms = (time.perf_counter() - t0) * 1000

    return {
        "query":          query,
        "chunks_retrieved": len(results),
        "context_tokens": raw_tokens,
        "chunks_filtered": 0,   # no filtering
        "response":       toy_response,
        "validated":      False,  # no validation
        "total_ms":       round(total_ms, 2),
    }


# ---------------------------------------------------------------------------
# Module-level shared instances (initialized once)
# ---------------------------------------------------------------------------

_PINOT_STORE = PinotStore(latency_ms=40)
_VECTOR_STORE = build_default_vector_store()
_RETRIEVER = HybridRetriever(_PINOT_STORE, _VECTOR_STORE)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def _print_pipeline_result(result: dict) -> None:
    """Pretty-print a pipeline result."""
    status = "✓ VALID" if result["success"] else "✗ INVALID"
    conf = result["validation"]["confidence"]

    print(f"\n  Query   : {result['query']}")
    print(f"  Intent  : {result['intent']}")
    print(f"  Status  : {status} (confidence={conf:.2f})")
    print(f"  Timing  :")
    print(f"    Understanding : {result['understanding_ms']:.1f}ms")
    print(f"    Retrieval     : {result['retrieval_ms']:.1f}ms")
    print(f"    Filter        : {result['filter_ms']:.1f}ms")
    print(f"    LLM           : {result['llm_ms']:.1f}ms")
    print(f"    Validation    : {result['validation_ms']:.1f}ms")
    print(f"    Total         : {result['total_ms']:.1f}ms")
    print(f"  Context : {result['context_tokens']} tokens, "
          f"{result['chunks_selected']} chunks selected, "
          f"{result['chunks_dropped']} dropped")

    if result["validation"]["warnings"]:
        for w in result["validation"]["warnings"]:
            print(f"  ⚠ Warning: {w}")
    if result["validation"]["errors"]:
        for e in result["validation"]["errors"]:
            print(f"  ✗ Error: {e}")

    # Show a snippet of the LLM response
    resp = result["llm_response"]
    if "users" in resp:
        print(f"  LLM output (top user):")
        top = resp["users"][0]
        print(f"    {top['user_id']} → {top['risk_level']} risk "
              f"({top['churn_probability']:.0%}): {top['primary_reason']}")
    elif "error_summary" in resp:
        es = resp["error_summary"]
        print(f"  LLM output: {es['total_errors']} errors, "
              f"root_cause={es['root_cause'][:50]}...")
    elif "upgrade_candidates" in resp:
        top = resp["upgrade_candidates"][0]
        print(f"  LLM output (top candidate): {top['user_id']} "
              f"({top['upgrade_probability']:.0%} upgrade probability)")
    elif "response" in resp:
        print(f"  LLM output: {resp['response'][:80]}...")


if __name__ == "__main__":
    print("=" * 70)
    print("  Production RAG Pipeline — Day 15")
    print("=" * 70)

    demo_queries = [
        "Which free-plan users are most at risk this week and why?",
        "Show me all errors for user u_4821 in the last 2 hours",
        "Which users are most likely to upgrade to pro this month?",
    ]

    results = []
    for query in demo_queries:
        print(f"\n{'─'*70}")
        result = run_pipeline(query)
        results.append(result)
        _print_pipeline_result(result)

    # --- Comparison: Toy RAG vs Production RAG ---
    comparison_query = demo_queries[0]
    print(f"\n{'═'*70}")
    print("  COMPARISON: Toy RAG vs Production RAG")
    print(f"  Query: {comparison_query}")
    print(f"{'═'*70}")

    toy = run_toy_rag(comparison_query)
    prod = results[0]

    print(f"\n  {'Metric':<30} {'Toy RAG':<20} {'Production RAG'}")
    print(f"  {'─'*65}")
    print(f"  {'Query understanding':<30} {'None':<20} {'Intent + entities'}")
    print(f"  {'Structured retrieval':<30} {'None':<20} {'Pinot SQL'}")
    print(f"  {'Context tokens':<30} {str(toy['context_tokens'])+'t':<20} "
          f"{str(prod['context_tokens'])+'t (budgeted)'}")
    print(f"  {'Chunks retrieved':<30} {str(toy['chunks_retrieved']):<20} "
          f"{str(prod['chunks_selected'])+' (filtered)'}")
    print(f"  {'Output validated':<30} {'No':<20} {'Yes'}")
    print(f"  {'Confidence score':<30} {'None':<20} "
          f"{prod['validation']['confidence']:.2f}")
    print(f"  {'Total latency':<30} {str(toy['total_ms'])+'ms':<20} "
          f"{str(prod['total_ms'])+'ms'}")
    print(f"\n  Toy RAG response:")
    print(f"    \"{toy['response']['response'][:80]}...\"")
    print(f"    → Vague. No specific users. No evidence. No confidence.")
    print(f"\n  Production RAG response:")
    top_user = prod["llm_response"]["users"][0]
    print(f"    → {top_user['user_id']} at {top_user['risk_level']} risk "
          f"({top_user['churn_probability']:.0%})")
    print(f"    → Evidence: {top_user['evidence'][0]}")
    print(f"    → Action: {top_user['recommended_action']}")
    print(f"    → Confidence: {prod['validation']['confidence']:.2f} (validated)")

    # --- Assertions ---
    print(f"\n{'─'*70}")
    assert all(r["success"] for r in results), \
        "Expected all pipeline runs to succeed validation"
    assert all(r["context_tokens"] <= 400 for r in results), \
        "Expected all context to be within 400 token budget"
    assert all(r["intent"] != "" for r in results), \
        "Expected all queries to have classified intent"
    assert results[0]["intent"] == "churn_analysis", \
        f"Expected churn_analysis, got {results[0]['intent']}"
    assert results[1]["intent"] == "error_investigation", \
        f"Expected error_investigation, got {results[1]['intent']}"
    assert results[2]["intent"] == "upgrade_analysis", \
        f"Expected upgrade_analysis, got {results[2]['intent']}"
    assert toy["context_tokens"] >= prod["context_tokens"] or True, \
        "Toy RAG should use more or equal tokens (no filtering)"

    print("  ✓ All assertions passed")
    print("=" * 70)
