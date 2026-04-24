"""
AI-Enabled Pipeline — Day 01
==============================
The same user analytics use case, rebuilt for an AI system.

Flow:
  1. Events arrive in real-time (simulated Kafka consumer)
  2. Each event is enriched with user context
  3. Enriched events are converted to text and embedded (mocked)
  4. Embeddings are stored in a vector store (in-memory mock)
  5. A query comes in: "Why did user u_001 churn?"
  6. Retrieval layer finds the most relevant events
  7. LLM reasoning layer generates an explanation (mocked)

The LLM doesn't run SQL. It reasons over retrieved context.
"""

import json
import math
import random
from datetime import datetime, timedelta
from typing import Any


# ── MOCK EMBEDDING ────────────────────────────────────────────────────────────

def embed(text: str) -> list[float]:
    """
    Mocks a text embedding model (e.g., OpenAI text-embedding-3-small).
    In production: call openai.embeddings.create() or a local model.
    Returns a 8-dim vector for demo purposes (real models use 1536 dims).
    """
    random.seed(hash(text) % (2**32))
    raw = [random.gauss(0, 1) for _ in range(8)]
    norm = math.sqrt(sum(x**2 for x in raw))
    return [x / norm for x in raw]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot  # vectors are already normalized


# ── IN-MEMORY VECTOR STORE ────────────────────────────────────────────────────

class VectorStore:
    """
    Minimal in-memory vector store.
    In production: replace with Pinecone, Qdrant, Weaviate, or pgvector.
    """
    def __init__(self):
        self._store: list[dict] = []

    def upsert(self, doc_id: str, text: str, metadata: dict) -> None:
        vector = embed(text)
        self._store.append({
            "id": doc_id,
            "text": text,
            "vector": vector,
            "metadata": metadata,
        })

    def query(self, query_text: str, top_k: int = 5, filter_user: str = None) -> list[dict]:
        query_vector = embed(query_text)
        results = []
        for doc in self._store:
            if filter_user and doc["metadata"].get("user_id") != filter_user:
                continue
            score = cosine_similarity(query_vector, doc["vector"])
            results.append({**doc, "score": score})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]


# ── STEP 1: INGEST (simulated Kafka consumer) ─────────────────────────────────

def consume_events(since: datetime):
    """
    Simulates consuming events from a Kafka topic in real-time.
    In production: use confluent-kafka or aiokafka consumer.
    """
    events = [
        {"user_id": "u_001", "event": "page_view",  "ts": since + timedelta(minutes=2),  "page": "/home"},
        {"user_id": "u_001", "event": "page_view",  "ts": since + timedelta(minutes=5),  "page": "/pricing"},
        {"user_id": "u_001", "event": "page_view",  "ts": since + timedelta(minutes=7),  "page": "/pricing"},
        {"user_id": "u_001", "event": "support_ticket", "ts": since + timedelta(minutes=10),
         "message": "Your pricing is too expensive compared to competitors."},
        {"user_id": "u_001", "event": "churn",      "ts": since + timedelta(minutes=20), "page": None},
        {"user_id": "u_002", "event": "signup",     "ts": since + timedelta(minutes=3),  "page": "/register"},
        {"user_id": "u_002", "event": "purchase",   "ts": since + timedelta(minutes=9),  "page": "/checkout"},
    ]
    return events


# ── STEP 2: ENRICH ────────────────────────────────────────────────────────────

USER_PROFILES = {
    "u_001": {"plan": "free", "signup_date": "2024-11-01", "country": "US"},
    "u_002": {"plan": "pro",  "signup_date": "2025-01-15", "country": "UK"},
}

def enrich_event(event: dict) -> dict:
    """
    Joins event with user profile metadata.
    In production: lookup from Redis, Postgres, or a feature store.
    """
    profile = USER_PROFILES.get(event["user_id"], {})
    return {**event, "user_profile": profile}


# ── STEP 3: CONVERT TO TEXT + EMBED ──────────────────────────────────────────

def event_to_text(event: dict) -> str:
    """
    Converts a structured event into a natural language description.
    This is what gets embedded and stored in the vector store.
    """
    ts = event["ts"].strftime("%Y-%m-%d %H:%M")
    profile = event.get("user_profile", {})
    base = (
        f"User {event['user_id']} ({profile.get('plan','unknown')} plan, {profile.get('country','?')}) "
        f"performed '{event['event']}' at {ts}."
    )
    if event.get("page"):
        base += f" Page: {event['page']}."
    if event.get("message"):
        base += f" Message: \"{event['message']}\""
    return base


# ── STEP 4: STORE IN VECTOR DB ────────────────────────────────────────────────

def index_events(events: list[dict], store: VectorStore) -> None:
    print("\n[INDEX] Embedding and storing events in vector store...")
    for i, event in enumerate(events):
        enriched = enrich_event(event)
        text = event_to_text(enriched)
        store.upsert(
            doc_id=f"evt_{i}",
            text=text,
            metadata={"user_id": event["user_id"], "event_type": event["event"]},
        )
        print(f"  ✓ Indexed: {text[:80]}...")
    print(f"[INDEX] {len(events)} events indexed.")


# ── STEP 5+6: RETRIEVE ────────────────────────────────────────────────────────

def retrieve_context(query: str, user_id: str, store: VectorStore, top_k: int = 4) -> list[str]:
    print(f"\n[RETRIEVE] Query: \"{query}\"")
    print(f"[RETRIEVE] Filtering for user: {user_id}")
    results = store.query(query, top_k=top_k, filter_user=user_id)
    context_chunks = [r["text"] for r in results]
    print(f"[RETRIEVE] {len(context_chunks)} relevant chunks found.")
    return context_chunks


# ── STEP 7: LLM REASONING (mocked) ───────────────────────────────────────────

def llm_reason(query: str, context: list[str]) -> str:
    """
    Mocks an LLM call with retrieved context.
    In production:
        from openai import OpenAI
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a data analyst. Answer based only on the provided context."},
                {"role": "user", "content": f"Context:\n{chr(10).join(context)}\n\nQuestion: {query}"}
            ]
        )
        return response.choices[0].message.content
    """
    context_str = "\n".join(f"  - {c}" for c in context)
    # Deterministic mock response based on context content
    has_support = any("support_ticket" in c for c in context)
    has_pricing = any("pricing" in c.lower() for c in context)

    reasoning = "Based on the retrieved user activity:\n"
    if has_pricing:
        reasoning += "  • User visited /pricing multiple times, indicating price evaluation.\n"
    if has_support:
        reasoning += "  • User submitted a support ticket citing pricing concerns vs competitors.\n"
    reasoning += "  • User was on the free plan with no conversion to paid.\n"
    reasoning += "\nLikely churn reason: Price sensitivity. User evaluated pricing, found it uncompetitive, and left without converting."
    return reasoning


# ── PIPELINE RUNNER ───────────────────────────────────────────────────────────

def run_ai_pipeline(query: str, target_user: str) -> None:
    print("\n[AI PIPELINE] Starting event-driven AI system")
    print("=" * 60)

    store = VectorStore()
    since = datetime.now() - timedelta(hours=1)

    # Step 1: Consume real-time events
    print("\n[INGEST] Consuming events from Kafka stream...")
    events = consume_events(since=since)
    print(f"[INGEST] {len(events)} events received.")

    # Steps 2–4: Enrich, embed, index
    index_events(events, store)

    # Steps 5–6: Retrieve relevant context
    context = retrieve_context(query, user_id=target_user, store=store)

    # Step 7: LLM reasoning
    print(f"\n[REASON] Sending context to LLM...")
    print(f"[REASON] Context chunks:\n" + "\n".join(f"  [{i+1}] {c}" for i, c in enumerate(context)))
    answer = llm_reason(query, context)

    print("\n[OUTPUT] LLM Response:")
    print("-" * 60)
    print(answer)
    print("-" * 60)
    print("\n[AI PIPELINE] Complete. No SQL written. No dashboard opened.")
    print("The system reasoned over data and produced an explanation.")


if __name__ == "__main__":
    run_ai_pipeline(
        query="Why did this user churn?",
        target_user="u_001",
    )
