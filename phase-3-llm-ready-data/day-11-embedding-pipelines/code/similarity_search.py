"""
Similarity Search — Day 11: Embedding Pipelines
=================================================
Demonstrates how vector similarity search works:
  - Cosine similarity between vectors
  - Top-k nearest neighbor search
  - Metadata filtering
  - Why semantic search finds what keyword search misses

This is the retrieval half of the embedding pipeline.
The embedding generator produces vectors; this module searches them.
"""

import math
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from embedding_generator import mock_embed, EmbeddingDocument


# ── SIMILARITY METRICS ────────────────────────────────────────────────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    Cosine similarity between two unit vectors.
    Range: -1 (opposite) to 1 (identical).
    For normalized vectors: dot product = cosine similarity.

    In production: vector DBs compute this natively using HNSW index.
    """
    return round(sum(x * y for x, y in zip(a, b)), 4)

def euclidean_distance(a: list[float], b: list[float]) -> float:
    """
    Euclidean (L2) distance between two vectors.
    Smaller = more similar. Used by some vector DBs.
    """
    return round(math.sqrt(sum((x - y)**2 for x, y in zip(a, b))), 4)


# ── IN-MEMORY VECTOR STORE ────────────────────────────────────────────────────

class VectorStore:
    """
    In-memory vector store simulating Qdrant / Pinecone / pgvector.

    Production differences:
    - Qdrant: HNSW index, rich payload filtering, self-hosted
    - Pinecone: managed, serverless, simple API
    - pgvector: Postgres extension, good for < 1M vectors
    - All use approximate nearest neighbor (ANN) search for speed
    """
    def __init__(self, name: str):
        self.name  = name
        self._docs: list[EmbeddingDocument] = []

    def upsert(self, doc: EmbeddingDocument) -> None:
        """Insert or update a document by ID."""
        # Remove existing doc with same ID (update)
        self._docs = [d for d in self._docs if d.doc_id != doc.doc_id]
        self._docs.append(doc)

    def search(
        self,
        query_text: str,
        top_k: int = 4,
        filter_fn=None,
        min_score: float = 0.0,
    ) -> list[dict]:
        """
        Semantic similarity search.
        Returns top-k most similar documents to the query.

        filter_fn: optional function(metadata) -> bool for metadata filtering
        min_score: minimum cosine similarity threshold
        """
        query_vec = mock_embed(query_text)
        results   = []

        for doc in self._docs:
            if filter_fn and not filter_fn(doc.metadata):
                continue
            score = cosine_similarity(query_vec, doc.vector)
            if score >= min_score:
                results.append({
                    "doc_id":   doc.doc_id,
                    "text":     doc.text,
                    "score":    score,
                    "metadata": doc.metadata,
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def delete(self, doc_id: str) -> bool:
        before = len(self._docs)
        self._docs = [d for d in self._docs if d.doc_id != doc_id]
        return len(self._docs) < before

    def __len__(self):
        return len(self._docs)


# ── DEMO DATA ─────────────────────────────────────────────────────────────────

SAMPLE_TEXTS = [
    # Checkout/payment cluster
    ("doc_001", "u_4821", "User u_4821 (free plan) hit 500 error on /checkout at 14:32. Churn risk: TRUE."),
    ("doc_002", "u_4821", "Payment failed during upgrade attempt for user u_4821. Error on billing page."),
    ("doc_003", "u_4821", "Support ticket from u_4821: checkout keeps failing with server error."),
    ("doc_004", "u_4821", "Transaction declined for user u_4821 on /checkout. 3rd failure this session."),
    # Upgrade/intent cluster
    ("doc_005", "u_4821", "User u_4821 clicked Upgrade to Pro on /pricing. Intent score: 0.82."),
    ("doc_006", "u_4821", "User u_4821 visited /pricing 3 times. Strong upgrade intent detected."),
    # Different user
    ("doc_007", "u_0012", "User u_0012 (pro plan) successfully purchased enterprise tier."),
    ("doc_008", "u_0012", "User u_0012 completed checkout. Payment processed successfully."),
    # Navigation cluster
    ("doc_009", "u_4821", "User u_4821 viewed /home page. Session started from Google search."),
    ("doc_010", "u_4821", "User u_4821 logged in. Session duration: 8 minutes."),
]


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> VectorStore:
    print("=" * 65)
    print("SIMILARITY SEARCH — Semantic retrieval demonstration")
    print("=" * 65)

    # Build vector store
    store = VectorStore("user_events")
    for doc_id, user_id, text in SAMPLE_TEXTS:
        doc = EmbeddingDocument(
            doc_id=doc_id,
            text=text,
            metadata={"user_id": user_id, "text": text},
        )
        store.upsert(doc)

    print(f"\n[STORE]  {len(store)} documents indexed\n")

    # ── DEMO 1: Semantic search finds what keyword search misses ──────────
    print(f"[DEMO 1]  Query: 'checkout problems'")
    print(f"          Keyword search would only find docs containing 'checkout'")
    print(f"          Semantic search finds by meaning:\n")

    results = store.search("checkout problems", top_k=4)
    for r in results:
        print(f"  score={r['score']:.4f}  {r['text'][:65]}...")

    # ── DEMO 2: Metadata filtering ────────────────────────────────────────
    print(f"\n[DEMO 2]  Same query, filtered to user u_4821 only:")
    results = store.search(
        "checkout problems",
        top_k=4,
        filter_fn=lambda m: m.get("user_id") == "u_4821",
    )
    for r in results:
        print(f"  score={r['score']:.4f}  [{r['metadata']['user_id']}]  {r['text'][:55]}...")

    # ── DEMO 3: Different query, different cluster ─────────────────────────
    print(f"\n[DEMO 3]  Query: 'user wants to upgrade plan'")
    results = store.search("user wants to upgrade plan", top_k=3)
    for r in results:
        print(f"  score={r['score']:.4f}  {r['text'][:65]}...")

    # ── DEMO 4: Direct similarity comparison ──────────────────────────────
    print(f"\n[DEMO 4]  Direct cosine similarity between specific texts:")
    pairs = [
        ("checkout error", "payment failed"),
        ("checkout error", "user upgraded plan"),
        ("checkout error", "500 on /checkout"),
        ("user logged in", "session started"),
    ]
    for a, b in pairs:
        va = mock_embed(a)
        vb = mock_embed(b)
        sim = cosine_similarity(va, vb)
        label = "SIMILAR" if sim > 0.5 else "DIFFERENT"
        print(f"  '{a}' ↔ '{b}': {sim:.4f}  [{label}]")

    print(f"\n[KEY INSIGHT]")
    print(f"  Semantic search finds 'payment failed' when you query 'checkout error'")
    print(f"  because both describe the same problem — even with no shared words.")
    print(f"  Keyword search would miss this entirely.")

    return store


if __name__ == "__main__":
    run()
