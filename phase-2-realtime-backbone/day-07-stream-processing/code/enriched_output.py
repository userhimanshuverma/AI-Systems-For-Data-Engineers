"""
Enriched Output — Day 07: Stream Processing
=============================================
Shows the final enriched data as it would appear in:
  1. Apache Pinot (structured, queryable)
  2. Vector Store (embedding text)
  3. LLM context (assembled for reasoning)

This is the end-to-end demonstration of the enrichment pipeline's value.
Run this after raw_stream.py and enrichment_processor.py to see the
complete before/after comparison.
"""

import json
import math
import random
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from raw_stream import generate_raw_stream
from enrichment_processor import run as enrich_events, event_to_text_enriched


# ── MOCK VECTOR STORE ─────────────────────────────────────────────────────────

def embed(text: str, dim: int = 16) -> list[float]:
    random.seed(hash(text) % (2**32))
    v = [random.gauss(0, 1) for _ in range(dim)]
    n = math.sqrt(sum(x**2 for x in v))
    return [round(x/n, 4) for x in v]

def cosine(a, b):
    return round(sum(x*y for x,y in zip(a,b)), 4)

class VectorStore:
    def __init__(self):
        self._docs = []
    def upsert(self, doc_id, text, meta):
        self._docs.append({"id": doc_id, "text": text, "vec": embed(text), "meta": meta})
    def query(self, q, top_k=3, uid=None):
        qv = embed(q)
        results = [
            {**d, "score": cosine(qv, d["vec"])}
            for d in self._docs
            if uid is None or d["meta"].get("user_id") == uid
        ]
        return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]


# ── PINOT TABLE SIMULATION ────────────────────────────────────────────────────

def to_pinot_row(event: dict) -> dict:
    """
    Flattens an enriched event into a Pinot table row.
    In production: Pinot ingests from Kafka via a real-time connector.
    The schema maps nested JSON fields to flat columns.
    """
    ctx     = event.get("context", {})
    profile = event.get("user_profile", {})
    session = event.get("session_state", {})
    derived = event.get("derived_features", {})

    return {
        # Core event fields
        "event_id":       event["event_id"][:8] + "...",
        "event_type":     event["event_type"],
        "user_id":        event["user_id"],
        "session_id":     event["session_id"],
        "ts":             event["ts"][:19],
        "page":           ctx.get("page", ""),
        "error_code":     ctx.get("error_code", None),
        # Static enrichment
        "plan":           profile.get("plan", ""),
        "country":        profile.get("country", ""),
        "segment":        profile.get("segment", ""),
        "lifetime_orders":profile.get("lifetime_orders", 0),
        # Session state
        "session_events": session.get("event_count", 0),
        "session_errors": session.get("error_count", 0),
        "pricing_visits": session.get("pricing_visits", 0),
        "duration_s":     session.get("duration_s", 0),
        # Derived features
        "error_rate":     derived.get("error_rate", 0.0),
        "churn_risk":     derived.get("churn_risk", False),
        "intent_score":   derived.get("intent_score", 0.0),
        "is_high_value":  derived.get("is_high_value", False),
    }


# ── MOCK LLM ──────────────────────────────────────────────────────────────────

def mock_llm(query: str, chunks: list[str], metrics: dict) -> str:
    """Mocks LLM reasoning over retrieved context."""
    churn   = metrics.get("churn_risk", False)
    errors  = metrics.get("session_errors", 0)
    rate    = metrics.get("error_rate", 0.0)
    intent  = metrics.get("intent_score", 0.0)
    plan    = metrics.get("plan", "?")
    segment = metrics.get("segment", "?")

    if "churn" in query.lower() or "risk" in query.lower():
        if churn:
            return (
                f"User u_4821 ({plan} plan, {segment} segment) is at HIGH churn risk. "
                f"They hit {errors} checkout errors ({rate:.0%} error rate) and visited "
                f"/pricing multiple times without converting. "
                f"Upgrade intent score: {intent:.2f}. "
                f"Recommend: escalate checkout fix + send targeted upgrade offer."
            )
        return f"User u_4821 shows moderate risk. Error rate: {rate:.0%}. Monitor closely."

    return f"User u_4821: {errors} errors, {rate:.0%} error rate, intent={intent:.2f}."


# ── FULL PIPELINE DEMO ────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("ENRICHED OUTPUT — End-to-End Pipeline Result")
    print("=" * 65)

    # Step 1: Generate raw events
    raw_events = generate_raw_stream("u_4821")

    # Step 2: Enrich (suppress intermediate output)
    import io
    from contextlib import redirect_stdout
    with redirect_stdout(io.StringIO()):
        enriched_events = enrich_events(raw_events)

    print(f"\n[PIPELINE]  {len(raw_events)} raw events → {len(enriched_events)} enriched events")

    # Step 3: Show Pinot table
    pinot_rows = [to_pinot_row(e) for e in enriched_events]
    print(f"\n[PINOT]  user_events_enriched table ({len(pinot_rows)} rows, 20 columns)")
    print(f"  {'event_type':30s} {'plan':6s} {'seg':10s} {'err':4s} {'rate':6s} {'churn':6s} {'intent':7s}")
    print(f"  {'-'*75}")
    for row in pinot_rows:
        print(
            f"  {row['event_type']:30s} "
            f"{row['plan']:6s} "
            f"{row['segment']:10s} "
            f"{row['session_errors']:4d} "
            f"{row['error_rate']:6.2f} "
            f"{'TRUE ':6s}" if row['churn_risk'] else
            f"  {row['event_type']:30s} "
            f"{row['plan']:6s} "
            f"{row['segment']:10s} "
            f"{row['session_errors']:4d} "
            f"{row['error_rate']:6.2f} "
            f"{'false ':6s}",
            f"{row['intent_score']:7.2f}"
        )

    # Step 4: Pinot query simulation
    print(f"\n[PINOT QUERY]  SELECT * WHERE churn_risk=true AND intent_score > 0.5")
    high_risk = [r for r in pinot_rows if r["churn_risk"] and r["intent_score"] > 0.5]
    print(f"  → {len(high_risk)} rows match (users at churn risk with upgrade intent)")

    # Step 5: Vector store
    store = VectorStore()
    for i, e in enumerate(enriched_events):
        text = event_to_text_enriched(e)
        store.upsert(f"doc_{i:03d}", text, {"user_id": e["user_id"]})

    print(f"\n[VECTOR STORE]  {len(store._docs)} enriched event vectors indexed")

    query = "checkout errors and churn risk"
    results = store.query(query, top_k=3, uid="u_4821")
    print(f"\n[VECTOR QUERY]  '{query}'")
    for i, r in enumerate(results):
        print(f"  [{i+1}] score={r['score']:.4f}  {r['text'][:80]}...")

    # Step 6: LLM response
    last_row = pinot_rows[-1]
    llm_response = mock_llm(
        "Why is user u_4821 at risk of churning?",
        [r["text"] for r in results],
        last_row,
    )

    print(f"\n[LLM QUERY]   'Why is user u_4821 at risk of churning?'")
    print(f"[LLM RESPONSE]")
    print(f"  {llm_response}")

    # Step 7: Comparison summary
    print(f"\n{'='*65}")
    print(f"  BEFORE enrichment: 7 columns, generic embedding, no LLM context")
    print(f"  AFTER  enrichment: 20 columns, specific embedding, actionable LLM output")
    print(f"  Enrichment cost:   paid once at ingest — free at every query")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
