"""
Retrieval Pipeline — Day 03: The New Stack
============================================
Demonstrates the retrieval layer: the bridge between raw data and the LLM.

Flow:
  1. Documents (event descriptions) are embedded and stored in a vector store
  2. A query arrives
  3. Query is embedded using the same model
  4. Vector store returns top-k semantically similar documents
  5. Structured store (Pinot/SQL) returns hard metrics for the same entity
  6. Both results are assembled into a context object for the LLM

This is the core of RAG (Retrieval-Augmented Generation).
The LLM never sees raw data — only the assembled context.
"""

import math
import random
from datetime import datetime, timedelta


# ── EMBEDDING MODEL (mocked) ──────────────────────────────────────────────────

EMBEDDING_DIM = 32  # real models: 1536 (OpenAI) or 768 (many open-source)

def embed(text: str) -> list[float]:
    """
    Mocks text-embedding-3-small or similar.
    In production:
        from openai import OpenAI
        client = OpenAI()
        resp = client.embeddings.create(input=text, model="text-embedding-3-small")
        return resp.data[0].embedding
    """
    random.seed(hash(text) % (2**32))
    vec = [random.gauss(0, 1) for _ in range(EMBEDDING_DIM)]
    norm = math.sqrt(sum(x**2 for x in vec))
    return [x / norm for x in vec]

def cosine_sim(a: list[float], b: list[float]) -> float:
    return round(sum(x*y for x,y in zip(a,b)), 4)


# ── VECTOR STORE ──────────────────────────────────────────────────────────────

class VectorStore:
    """
    In-memory vector store. Simulates Pinecone / Qdrant / pgvector.

    Production differences:
    - Pinecone: managed, serverless, simple upsert/query API
    - Qdrant: self-hosted, rich payload filtering, HNSW index
    - pgvector: Postgres extension, good for <1M vectors
    """
    def __init__(self, name: str):
        self.name = name
        self._index: list[dict] = []

    def upsert(self, doc_id: str, text: str, metadata: dict) -> None:
        self._index.append({
            "id":       doc_id,
            "text":     text,
            "vector":   embed(text),
            "metadata": metadata,
        })

    def query(
        self,
        query_text: str,
        top_k: int = 4,
        filter_fn=None,
        min_score: float = 0.0,
    ) -> list[dict]:
        qv = embed(query_text)
        results = []
        for doc in self._index:
            if filter_fn and not filter_fn(doc["metadata"]):
                continue
            score = cosine_sim(qv, doc["vector"])
            if score >= min_score:
                results.append({**doc, "score": score})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def __len__(self):
        return len(self._index)


# ── STRUCTURED STORE (simulates Pinot query result) ───────────────────────────

PINOT_METRICS = {
    "u_001": {"page_views_7d": 14, "errors_7d": 3, "purchases_7d": 0, "plan": "free",  "churn_risk": "high",   "last_active": "2h ago"},
    "u_002": {"page_views_7d": 42, "errors_7d": 0, "purchases_7d": 2, "plan": "pro",   "churn_risk": "low",    "last_active": "10m ago"},
    "u_003": {"page_views_7d": 5,  "errors_7d": 1, "purchases_7d": 0, "plan": "free",  "churn_risk": "medium", "last_active": "1d ago"},
    "u_004": {"page_views_7d": 88, "errors_7d": 0, "purchases_7d": 5, "plan": "enterprise", "churn_risk": "low", "last_active": "5m ago"},
}

def query_pinot(user_id: str) -> dict | None:
    """
    Simulates: SELECT * FROM user_metrics_7d WHERE user_id = :uid
    In production: HTTP request to Pinot broker or JDBC connection.
    """
    return PINOT_METRICS.get(user_id)


# ── SEED VECTOR STORE ─────────────────────────────────────────────────────────

def seed_store(store: VectorStore) -> None:
    now = datetime.now()
    events = [
        ("u_001", "page_view",    "/pricing",  now - timedelta(days=1, hours=3)),
        ("u_001", "page_view",    "/pricing",  now - timedelta(days=1, hours=1)),
        ("u_001", "error",        "/checkout", now - timedelta(hours=22)),
        ("u_001", "error",        "/checkout", now - timedelta(hours=20)),
        ("u_001", "support_msg",  "Checkout keeps failing with 500 error", now - timedelta(hours=18)),
        ("u_001", "page_view",    "/home",     now - timedelta(hours=8)),
        ("u_002", "purchase",     "/checkout", now - timedelta(days=2)),
        ("u_002", "page_view",    "/docs",     now - timedelta(hours=4)),
        ("u_002", "click",        "cta_upgrade", now - timedelta(hours=1)),
        ("u_003", "signup",       "/register", now - timedelta(days=3)),
        ("u_003", "page_view",    "/home",     now - timedelta(hours=28)),
        ("u_004", "purchase",     "/checkout", now - timedelta(hours=6)),
        ("u_004", "page_view",    "/docs",     now - timedelta(hours=2)),
    ]
    for i, (uid, etype, detail, ts) in enumerate(events):
        text = (
            f"User {uid} performed '{etype}' "
            f"involving '{detail}' "
            f"at {ts.strftime('%Y-%m-%d %H:%M')}."
        )
        store.upsert(
            doc_id=f"doc_{i:03d}",
            text=text,
            metadata={"user_id": uid, "event_type": etype},
        )


# ── RETRIEVAL PIPELINE ────────────────────────────────────────────────────────

def retrieve(
    query: str,
    user_id: str | None,
    store: VectorStore,
    top_k: int = 4,
) -> dict:
    """
    Hybrid retrieval: vector similarity + structured metrics.
    Returns an assembled context dict ready for the LLM.
    """
    # Vector retrieval
    filter_fn = (lambda m: m["user_id"] == user_id) if user_id else None
    vector_results = store.query(query, top_k=top_k, filter_fn=filter_fn)

    # Structured retrieval
    structured = query_pinot(user_id) if user_id else None

    return {
        "query":      query,
        "user_id":    user_id,
        "chunks":     [{"text": r["text"], "score": r["score"]} for r in vector_results],
        "metrics":    structured,
        "chunk_count": len(vector_results),
    }


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run(query: str, user_id: str) -> dict:
    store = VectorStore(name="user_events")
    seed_store(store)

    print(f"\n{'='*60}")
    print(f"[RETRIEVAL] Query: \"{query}\"")
    print(f"[RETRIEVAL] User filter: {user_id}")
    print(f"[RETRIEVAL] Index size: {len(store)} documents")

    ctx = retrieve(query, user_id, store)

    print(f"\n[VECTOR]  {ctx['chunk_count']} chunks retrieved:")
    for i, c in enumerate(ctx["chunks"]):
        print(f"  [{i+1}] score={c['score']:.4f}  {c['text'][:70]}...")

    print(f"\n[PINOT]   Structured metrics: {ctx['metrics']}")
    print(f"\n[CONTEXT] Ready for LLM — {ctx['chunk_count']} chunks + structured metrics")
    return ctx


if __name__ == "__main__":
    run("What checkout errors has this user experienced?", "u_001")
    run("Is this user likely to upgrade their plan?", "u_002")
