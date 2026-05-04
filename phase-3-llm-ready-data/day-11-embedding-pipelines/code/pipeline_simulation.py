"""
Pipeline Simulation — Day 11: Embedding Pipelines
===================================================
End-to-end simulation of the full embedding pipeline:

  Kafka events → Text conversion → Embedding → Vector DB → Retrieval → LLM context

Also demonstrates:
  - Pinot integration: structured metrics + semantic retrieval combined
  - Re-embedding on content change
  - The full RAG retrieval flow

Run this to see the complete pipeline from event to LLM context.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from embedding_generator import EmbeddingPipeline, event_to_text, mock_embed
from similarity_search import VectorStore, EmbeddingDocument, cosine_similarity


# ── SIMULATED KAFKA STREAM ────────────────────────────────────────────────────

KAFKA_EVENTS = [
    # u_4821 — checkout errors + upgrade intent
    {
        "event_id": "evt_a001", "event_type": "ui.page_view",
        "user_id": "u_4821", "ts": "2026-04-27T14:20:01Z",
        "context": {"page": "/home"},
        "user_profile": {"plan": "free", "segment": "at_risk"},
        "session_state": {"error_count": 0, "pricing_visits": 0},
        "derived_features": {"error_rate": 0.0, "churn_risk": False, "intent_score": 0.0},
    },
    {
        "event_id": "evt_a002", "event_type": "ui.page_view",
        "user_id": "u_4821", "ts": "2026-04-27T14:23:01Z",
        "context": {"page": "/pricing"},
        "user_profile": {"plan": "free", "segment": "at_risk"},
        "session_state": {"error_count": 0, "pricing_visits": 1},
        "derived_features": {"error_rate": 0.0, "churn_risk": False, "intent_score": 0.25},
    },
    {
        "event_id": "evt_a003", "event_type": "system.server_error",
        "user_id": "u_4821", "ts": "2026-04-27T14:32:01Z",
        "context": {"page": "/checkout", "error_code": 500},
        "user_profile": {"plan": "free", "segment": "at_risk"},
        "session_state": {"error_count": 1, "pricing_visits": 1},
        "derived_features": {"error_rate": 0.33, "churn_risk": False, "intent_score": 0.25},
    },
    {
        "event_id": "evt_a004", "event_type": "ui.page_view",
        "user_id": "u_4821", "ts": "2026-04-27T14:35:01Z",
        "context": {"page": "/pricing"},
        "user_profile": {"plan": "free", "segment": "at_risk"},
        "session_state": {"error_count": 1, "pricing_visits": 2},
        "derived_features": {"error_rate": 0.25, "churn_risk": False, "intent_score": 0.50},
    },
    {
        "event_id": "evt_a005", "event_type": "system.server_error",
        "user_id": "u_4821", "ts": "2026-04-27T14:38:01Z",
        "context": {"page": "/checkout", "error_code": 500},
        "user_profile": {"plan": "free", "segment": "at_risk"},
        "session_state": {"error_count": 2, "pricing_visits": 2},
        "derived_features": {"error_rate": 0.40, "churn_risk": True, "intent_score": 0.50},
    },
    {
        "event_id": "evt_a006", "event_type": "ui.button_click",
        "user_id": "u_4821", "ts": "2026-04-27T14:40:01Z",
        "context": {"page": "/pricing", "element_text": "Upgrade to Pro"},
        "user_profile": {"plan": "free", "segment": "at_risk"},
        "session_state": {"error_count": 2, "pricing_visits": 3},
        "derived_features": {"error_rate": 0.33, "churn_risk": True, "intent_score": 0.82},
    },
    # u_0012 — healthy user
    {
        "event_id": "evt_b001", "event_type": "commerce.purchase",
        "user_id": "u_0012", "ts": "2026-04-27T15:10:01Z",
        "context": {"page": "/checkout"},
        "user_profile": {"plan": "pro", "segment": "active"},
        "session_state": {"error_count": 0, "pricing_visits": 1},
        "derived_features": {"error_rate": 0.0, "churn_risk": False, "intent_score": 0.3},
    },
]

# Simulated Pinot metrics (structured data)
PINOT_METRICS = {
    "u_4821": {
        "total_events_7d": 24, "errors_7d": 5, "error_rate": 0.50,
        "pricing_visits": 3, "intent_score": 0.82, "churn_risk": True,
        "plan": "free", "segment": "at_risk",
    },
    "u_0012": {
        "total_events_7d": 42, "errors_7d": 0, "error_rate": 0.0,
        "pricing_visits": 1, "intent_score": 0.3, "churn_risk": False,
        "plan": "pro", "segment": "active",
    },
}


# ── MOCK LLM ──────────────────────────────────────────────────────────────────

def mock_llm(query: str, context_chunks: list[str], metrics: dict) -> str:
    """Mocks LLM reasoning over retrieved context + structured metrics."""
    errors = metrics.get("errors_7d", 0)
    rate   = metrics.get("error_rate", 0.0)
    intent = metrics.get("intent_score", 0.0)
    churn  = metrics.get("churn_risk", False)
    plan   = metrics.get("plan", "?")

    has_checkout = any("checkout" in c.lower() or "error" in c.lower() for c in context_chunks)
    has_intent   = any("upgrade" in c.lower() or "pricing" in c.lower() for c in context_chunks)

    if churn and has_checkout:
        return (
            f"User is at HIGH churn risk. {errors} checkout errors ({rate:.0%} rate) "
            f"in last 7 days. "
            + (f"Strong upgrade intent (score: {intent:.2f}) blocked by checkout failures. " if has_intent else "")
            + f"Recommend: escalate checkout fix + send targeted upgrade offer."
        )
    return f"User ({plan} plan): {errors} errors, churn_risk={churn}. Monitor."


# ── FULL PIPELINE ─────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("PIPELINE SIMULATION — Kafka → Embedding → Vector DB → LLM")
    print("=" * 65)

    # ── PHASE 1: Ingest and embed ──────────────────────────────────────────
    print(f"\n[PHASE 1]  Ingesting {len(KAFKA_EVENTS)} events from Kafka\n")

    pipeline = EmbeddingPipeline()
    store    = VectorStore("user_events")

    for event in KAFKA_EVENTS:
        doc = pipeline.process(event)
        if doc:
            store.upsert(doc)
            print(f"  ✅ {event['event_id']}  {event['event_type']:30s}  → embedded + stored")

    print(f"\n  Pipeline stats: {pipeline.stats()}")
    print(f"  Vector store:   {len(store)} documents indexed")

    # ── PHASE 2: Re-embedding on content change ────────────────────────────
    print(f"\n[PHASE 2]  Simulating content change (churn_risk updated)")
    updated_event = {**KAFKA_EVENTS[2]}  # evt_a003
    updated_event["derived_features"]["churn_risk"] = True  # was False
    updated_event["derived_features"]["error_rate"] = 0.50  # updated

    doc = pipeline.process(updated_event)
    if doc:
        store.upsert(doc)
        print(f"  ✅ evt_a003 re-embedded (content changed)")
    else:
        print(f"  ⏭  evt_a003 skipped (content unchanged)")

    # ── PHASE 3: Retrieval for LLM context ────────────────────────────────
    print(f"\n[PHASE 3]  Retrieval for support query")
    query   = "Why is user u_4821 having checkout issues?"
    user_id = "u_4821"

    print(f"  Query:  \"{query}\"")
    print(f"  Filter: user_id = {user_id}\n")

    results = store.search(
        query_text=query,
        top_k=4,
        filter_fn=lambda m: m.get("user_id") == user_id,
    )

    print(f"  Top-{len(results)} semantic matches:")
    for r in results:
        print(f"    score={r['score']:.4f}  {r['text'][:65]}...")

    # ── PHASE 4: Combine with Pinot metrics ───────────────────────────────
    print(f"\n[PHASE 4]  Combining semantic results with Pinot metrics")
    metrics = PINOT_METRICS.get(user_id, {})
    print(f"  Pinot metrics: {metrics}")

    # ── PHASE 5: LLM response ─────────────────────────────────────────────
    print(f"\n[PHASE 5]  LLM reasoning over combined context")
    context_chunks = [r["text"] for r in results]
    response = mock_llm(query, context_chunks, metrics)

    print(f"\n  LLM Response:")
    print(f"  \"{response}\"")

    # ── PHASE 6: Keyword search comparison ────────────────────────────────
    print(f"\n[PHASE 6]  Keyword search vs semantic search comparison")
    keyword = "checkout"
    keyword_matches = [
        d for d in store._docs
        if keyword in d.text.lower() and d.metadata.get("user_id") == user_id
    ]
    print(f"  Keyword search '{keyword}': {len(keyword_matches)} matches")
    print(f"  Semantic search 'checkout issues': {len(results)} matches")
    print(f"  Semantic found {len(results) - len(keyword_matches)} additional relevant docs")
    print(f"  (e.g., 'upgrade intent' docs that relate to checkout frustration)")

    print(f"\n{'='*65}")
    print(f"  PIPELINE COMPLETE")
    print(f"  Events ingested:    {len(KAFKA_EVENTS)}")
    print(f"  Vectors stored:     {len(store)}")
    print(f"  Retrieval results:  {len(results)}")
    print(f"  LLM context:        semantic + structured (Pinot)")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
