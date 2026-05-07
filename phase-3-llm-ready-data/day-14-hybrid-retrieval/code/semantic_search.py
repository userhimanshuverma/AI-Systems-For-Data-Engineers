"""
Semantic Search — Day 14: Hybrid Retrieval
===========================================
Simulates vector DB semantic retrieval for the hybrid retrieval layer.

Vector DB's role: answer "what happened" and "what does this mean" questions
by finding semantically similar event descriptions and behavioral narratives.

In production: HTTP to Qdrant or Pinecone:
    from qdrant_client import QdrantClient
    client = QdrantClient("localhost", port=6333)
    results = client.search(
        collection_name="user_events",
        query_vector=embed(query),
        query_filter=Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=uid))]),
        limit=top_k
    )
"""

import math
import random


# ── MOCK EMBEDDING ────────────────────────────────────────────────────────────

def mock_embed(text: str, dim: int = 24) -> list[float]:
    """Deterministic mock embedding. Same text → same vector."""
    random.seed(abs(hash(text)) % (2**32))
    v = [random.gauss(0, 1) for _ in range(dim)]
    n = math.sqrt(sum(x**2 for x in v))
    return [x/n for x in v]

def cosine(a: list[float], b: list[float]) -> float:
    return round(sum(x*y for x,y in zip(a,b)), 4)


# ── VECTOR STORE ──────────────────────────────────────────────────────────────

class VectorStore:
    def __init__(self):
        self._docs: list[dict] = []

    def upsert(self, doc_id: str, text: str, metadata: dict) -> None:
        self._docs = [d for d in self._docs if d["id"] != doc_id]
        self._docs.append({
            "id": doc_id, "text": text,
            "vector": mock_embed(text), "metadata": metadata,
        })

    def search(self, query: str, top_k: int = 4,
               filter_fn=None, min_score: float = -1.0) -> list[dict]:
        qv = mock_embed(query)
        results = [
            {**d, "score": cosine(qv, d["vector"])}
            for d in self._docs
            if filter_fn is None or filter_fn(d["metadata"])
        ]
        results = [r for r in results if r["score"] >= min_score]
        return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]

    def __len__(self): return len(self._docs)


# ── SEED DATA ─────────────────────────────────────────────────────────────────

SEMANTIC_DOCS = [
    # u_4821 — checkout errors + upgrade intent
    ("sem_001","u_4821","User u_4821 (free plan, at_risk) hit 500 error on /checkout at 14:32. Session: 5 errors (50% rate). Churn risk: TRUE."),
    ("sem_002","u_4821","User u_4821 clicked 'Upgrade to Pro' on /pricing at 14:38. Upgrade intent score: 0.82. Visited /pricing 3 times."),
    ("sem_003","u_4821","Support ticket from u_4821: 'checkout keeps failing with server error. Very frustrated.'"),
    ("sem_004","u_4821","User u_4821 hit 500 error on /checkout at 14:45. 3rd error this session. Churn risk escalating."),
    ("sem_005","u_4821","User u_4821 viewed /home. Session started from Google search. No issues at session start."),
    # u_0012 — healthy pro user
    ("sem_006","u_0012","User u_0012 (pro plan) successfully purchased enterprise tier. Payment processed."),
    ("sem_007","u_0012","User u_0012 browsed documentation. Active session, no errors."),
    # u_7734 — new user with moderate issues
    ("sem_008","u_7734","User u_7734 (free plan, new) hit 500 error on /checkout. First error this session."),
    ("sem_009","u_7734","User u_7734 visited /pricing twice. Moderate upgrade intent detected."),
    # Cross-user: similar past incidents
    ("sem_010","u_9901","Historical: User u_9901 had checkout errors 3 months ago. Resolved by engineering fix. User retained."),
]

def build_store() -> VectorStore:
    store = VectorStore()
    for doc_id, user_id, text in SEMANTIC_DOCS:
        store.upsert(doc_id, text, {"user_id": user_id, "text": text})
    return store


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> VectorStore:
    print("=" * 65)
    print("SEMANTIC SEARCH — Vector DB simulation")
    print("=" * 65)

    store = build_store()
    print(f"\n[STORE]  {len(store)} documents indexed\n")

    # Query 1: Checkout issues for specific user
    print(f"[QUERY 1]  'checkout errors and payment failures' (user u_4821)")
    results = store.search(
        "checkout errors and payment failures",
        top_k=4,
        filter_fn=lambda m: m["user_id"] == "u_4821",
    )
    for r in results:
        print(f"  score={r['score']:.4f}  {r['text'][:65]}...")

    # Query 2: Upgrade intent
    print(f"\n[QUERY 2]  'user wants to upgrade plan' (user u_4821)")
    results = store.search(
        "user wants to upgrade plan",
        top_k=3,
        filter_fn=lambda m: m["user_id"] == "u_4821",
    )
    for r in results:
        print(f"  score={r['score']:.4f}  {r['text'][:65]}...")

    # Query 3: Cross-user similar incidents (no filter)
    print(f"\n[QUERY 3]  'checkout errors resolved by engineering' (all users)")
    results = store.search("checkout errors resolved by engineering", top_k=3)
    for r in results:
        print(f"  score={r['score']:.4f}  [{r['metadata']['user_id']}]  {r['text'][:55]}...")

    print(f"\n[VECTOR DB ROLE]")
    print(f"  ✅ Answers: what happened, behavioral narrative, similar incidents")
    print(f"  ❌ Cannot: compute exact counts, rates, or aggregations")
    print(f"  → Pair with Pinot for complete hybrid retrieval")

    return store


if __name__ == "__main__":
    run()
