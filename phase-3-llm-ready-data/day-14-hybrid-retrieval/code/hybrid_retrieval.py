"""
Hybrid Retrieval — Day 14: Hybrid Retrieval
=============================================
Combines structured retrieval (Pinot) and semantic retrieval (Vector DB)
into a single context assembly pipeline for the LLM.

Flow:
  1. Parse query intent and entities
  2. Run Pinot SQL query (structured facts)
  3. Run vector similarity search (semantic context)
  4. Merge and deduplicate results
  5. Format into natural language context
  6. Pass to LLM with output format specification

This is the complete retrieval layer for a production RAG system.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from structured_query import query_user_metrics, query_at_risk_users
from semantic_search import build_store, VectorStore


# ── QUERY PARSER ──────────────────────────────────────────────────────────────

def parse_query(query: str) -> dict:
    """Extracts intent and entities from a natural language query."""
    q = query.lower()
    uid = next((u for u in ["u_4821","u_0012","u_7734","u_9901"] if u in q), None)
    intent = "general"
    if any(w in q for w in ["churn","risk","cancel","leave","struggling"]):
        intent = "churn_investigation"
    elif any(w in q for w in ["error","fail","broken","checkout","issue"]):
        intent = "error_investigation"
    elif any(w in q for w in ["upgrade","convert","purchase","intent"]):
        intent = "upgrade_investigation"
    return {"query": query, "user_id": uid, "intent": intent}


# ── CONTEXT MERGER ────────────────────────────────────────────────────────────

def format_structured(metrics: dict) -> str:
    """Converts Pinot metrics dict to natural language."""
    if not metrics:
        return "No structured metrics available."
    uid  = metrics["user_id"]
    plan = metrics["plan"]
    seg  = metrics["segment"]
    lines = [f"User {uid} ({plan} plan, {seg} segment) — structured metrics:"]
    lines.append(f"  - {metrics['session_errors']} errors, {metrics['error_rate']:.0%} error rate")
    lines.append(f"  - Visited /pricing {metrics['pricing_visits']} times")
    lines.append(f"  - Upgrade intent score: {metrics['intent_score']:.2f}")
    lines.append(f"  - Churn risk: {'TRUE' if metrics['churn_risk'] else 'FALSE'}")
    lines.append(f"  - Total events analyzed: {metrics['total_events']}")
    return "\n".join(lines)

def format_semantic(results: list[dict], max_chunks: int = 4) -> str:
    """Formats vector search results as a bullet list."""
    if not results:
        return "No semantic context available."
    lines = ["Relevant behavioral context (semantic search):"]
    for r in results[:max_chunks]:
        lines.append(f"  - {r['text']}")
    return "\n".join(lines)

def merge_context(
    structured_text: str,
    semantic_text: str,
    query: str,
    intent: str,
) -> dict:
    """Assembles the full LLM prompt from structured + semantic context."""
    system_prompt = (
        "You are a data analyst assistant for a SaaS platform. "
        "Answer questions about user behavior using ONLY the provided context. "
        "Do not invent data. Cite specific evidence. "
        "Respond in JSON: {summary, action, confidence (0-1), evidence (list of strings)}"
    )
    user_message = (
        f"[STRUCTURED METRICS — from Apache Pinot]\n{structured_text}\n\n"
        f"[SEMANTIC CONTEXT — from Vector DB]\n{semantic_text}\n\n"
        f"[QUESTION]\n{query}"
    )
    token_estimate = len(user_message) // 4
    return {
        "system":         system_prompt,
        "user":           user_message,
        "intent":         intent,
        "token_estimate": token_estimate,
    }


# ── MOCK LLM ──────────────────────────────────────────────────────────────────

def mock_llm(prompt: dict, metrics: dict | None) -> dict:
    """Mocks LLM response based on assembled hybrid context."""
    intent  = prompt["intent"]
    m       = metrics or {}
    errors  = m.get("session_errors", 0)
    rate    = m.get("error_rate", 0.0)
    intent_score = m.get("intent_score", 0.0)
    churn   = m.get("churn_risk", False)
    plan    = m.get("plan", "?")

    has_checkout = "checkout" in prompt["user"].lower()
    has_ticket   = "support ticket" in prompt["user"].lower()
    has_upgrade  = "upgrade" in prompt["user"].lower()

    if intent == "churn_investigation" and churn:
        summary = (
            f"User {m.get('user_id','?')} ({plan} plan) is at HIGH churn risk. "
            f"{errors} checkout errors ({rate:.0%} rate) are blocking a clear upgrade intent "
            f"(score: {intent_score:.2f})."
        )
        if has_ticket:
            summary += " They submitted a support ticket confirming the issue."
        action, confidence = "escalate_checkout_fix", 0.96

    elif intent == "error_investigation":
        summary = (
            f"User has {errors} errors ({rate:.0%} rate). "
            + ("Checkout page is the primary failure point. " if has_checkout else "")
            + ("Support ticket submitted. " if has_ticket else "")
        )
        action, confidence = "escalate_to_engineering", 0.93

    elif intent == "upgrade_investigation":
        summary = (
            f"User shows upgrade intent (score: {intent_score:.2f}). "
            + ("Visited /pricing multiple times. " if has_upgrade else "")
            + (f"Currently on {plan} plan. " if plan else "")
        )
        action = "send_upgrade_offer" if intent_score > 0.6 else "nurture_sequence"
        confidence = 0.88

    else:
        summary = f"User metrics: {errors} errors, {rate:.0%} rate, churn={churn}."
        action, confidence = "monitor", 0.70

    evidence = []
    if errors > 0:
        evidence.append(f"{errors} errors ({rate:.0%} rate) — from Pinot")
    if intent_score > 0.5:
        evidence.append(f"Upgrade intent score {intent_score:.2f} — from Pinot")
    if has_checkout:
        evidence.append("Checkout failure events — from Vector DB")
    if has_ticket:
        evidence.append("Support ticket: checkout failing — from Vector DB")
    if has_upgrade:
        evidence.append("Clicked 'Upgrade to Pro' — from Vector DB")

    return {
        "summary":    summary,
        "action":     action,
        "confidence": confidence,
        "evidence":   evidence,
    }


# ── HYBRID RETRIEVAL PIPELINE ─────────────────────────────────────────────────

def run_hybrid(query: str, store: VectorStore) -> dict:
    """Full hybrid retrieval pipeline: parse → retrieve → merge → LLM."""
    parsed = parse_query(query)
    uid    = parsed["user_id"]
    intent = parsed["intent"]

    print(f"\n{'─'*65}")
    print(f"Query:  \"{query}\"")
    print(f"Intent: {intent} | User: {uid}")

    # Step 1: Structured retrieval (Pinot)
    metrics = query_user_metrics(uid) if uid else None
    structured_text = format_structured(metrics)
    print(f"\n[PINOT]   Retrieved structured metrics")
    if metrics:
        print(f"  errors={metrics['session_errors']}, rate={metrics['error_rate']:.0%}, "
              f"churn={metrics['churn_risk']}, intent={metrics['intent_score']:.2f}")

    # Step 2: Semantic retrieval (Vector DB)
    sem_results = store.search(
        query,
        top_k=4,
        filter_fn=(lambda m: m["user_id"] == uid) if uid else None,
    )
    semantic_text = format_semantic(sem_results)
    print(f"\n[VECTOR]  Retrieved {len(sem_results)} semantic chunks")
    for r in sem_results[:2]:
        print(f"  score={r['score']:.4f}  {r['text'][:60]}...")

    # Step 3: Merge context
    prompt = merge_context(structured_text, semantic_text, query, intent)
    print(f"\n[MERGE]   Context assembled (~{prompt['token_estimate']} tokens)")

    # Step 4: LLM
    response = mock_llm(prompt, metrics)
    print(f"\n[LLM]     Response:")
    print(f"  Summary:    {response['summary']}")
    print(f"  Action:     {response['action']}")
    print(f"  Confidence: {response['confidence']:.0%}")
    print(f"  Evidence:")
    for e in response["evidence"]:
        print(f"    ✅ {e}")

    return response


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("HYBRID RETRIEVAL — Pinot + Vector DB → LLM")
    print("=" * 65)

    store = build_store()

    queries = [
        "Why is user u_4821 at risk of churning?",
        "What checkout errors has user u_4821 experienced?",
        "Is user u_4821 likely to upgrade their plan?",
    ]

    for query in queries:
        run_hybrid(query, store)

    # Comparison: vector-only vs hybrid
    print(f"\n{'='*65}")
    print(f"COMPARISON: Vector-Only vs Hybrid")
    print(f"{'='*65}")

    query = "Why is user u_4821 at risk of churning?"
    uid   = "u_4821"

    # Vector-only
    sem_only = store.search(query, top_k=4, filter_fn=lambda m: m["user_id"]==uid)
    print(f"\n[VECTOR ONLY]  Query: \"{query}\"")
    print(f"  Retrieved: {len(sem_only)} semantic chunks")
    print(f"  Missing:   error_rate, intent_score, churn_risk (no Pinot)")
    print(f"  LLM risk:  May hallucinate error counts without structured data")

    # Hybrid
    metrics = query_user_metrics(uid)
    print(f"\n[HYBRID]  Query: \"{query}\"")
    print(f"  Pinot:   error_rate={metrics['error_rate']:.0%}, "
          f"intent={metrics['intent_score']:.2f}, churn={metrics['churn_risk']}")
    print(f"  Vector:  {len(sem_only)} semantic chunks")
    print(f"  LLM:     Gets facts + story = complete, accurate response")

    print(f"\n{'='*65}")
    print(f"  KEY INSIGHT")
    print(f"  Pinot answers: how many, what rate, which users")
    print(f"  Vector DB answers: what happened, behavioral story")
    print(f"  Together: the LLM can be both accurate AND insightful")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
