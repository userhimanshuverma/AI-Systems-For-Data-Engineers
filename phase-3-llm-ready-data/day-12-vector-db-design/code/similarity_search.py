"""
Similarity Search — Day 12: Vector Storage Design
===================================================
Demonstrates vector store operations with metadata filtering,
HNSW-style search simulation, and the impact of index configuration.

Shows:
  - Upsert with metadata
  - Filtered search (user_id, event_type, date range)
  - Score thresholding
  - Collection management (namespaces, TTL)
"""

import math
import random
import time
from datetime import datetime, timezone, timedelta


# ── MOCK EMBEDDING ────────────────────────────────────────────────────────────

def mock_embed(text: str, dim: int = 16) -> list[float]:
    random.seed(abs(hash(text)) % (2**32))
    v = [random.gauss(0, 1) for _ in range(dim)]
    n = math.sqrt(sum(x**2 for x in v))
    return [x/n for x in v]

def cosine(a: list[float], b: list[float]) -> float:
    return round(sum(x*y for x,y in zip(a,b)), 4)


# ── VECTOR STORE ──────────────────────────────────────────────────────────────

class VectorStore:
    """
    In-memory vector store simulating Qdrant / Pinecone.

    Key design decisions demonstrated:
    - HNSW-style search (simulated with brute force for clarity)
    - Metadata filtering before similarity computation
    - Upsert semantics (insert or update by ID)
    - Collection namespacing
    - TTL-based cleanup
    """
    def __init__(self, name: str, dim: int = 16):
        self.name = name
        self.dim  = dim
        self._docs: dict[str, dict] = {}  # id → {vector, payload}
        self._search_count = 0
        self._total_search_ms = 0

    def upsert(self, doc_id: str, text: str, metadata: dict) -> None:
        """Insert or update a document. Uses doc_id for deduplication."""
        self._docs[doc_id] = {
            "id":      doc_id,
            "vector":  mock_embed(text),
            "payload": {**metadata, "text": text},
        }

    def upsert_batch(self, docs: list[dict]) -> int:
        """Batch upsert. Returns number of documents upserted."""
        for doc in docs:
            self.upsert(doc["id"], doc["text"], doc["metadata"])
        return len(docs)

    def search(
        self,
        query_text: str,
        top_k: int = 4,
        filter_fn=None,
        min_score: float = 0.0,
    ) -> list[dict]:
        """
        ANN search with optional metadata filtering.
        In production: HNSW index makes this O(log n) instead of O(n).
        """
        t0 = time.time()
        qvec = mock_embed(query_text)

        results = []
        for doc in self._docs.values():
            if filter_fn and not filter_fn(doc["payload"]):
                continue
            score = cosine(qvec, doc["vector"])
            if score >= min_score:
                results.append({
                    "id":    doc["id"],
                    "score": score,
                    "text":  doc["payload"]["text"],
                    "meta":  {k: v for k, v in doc["payload"].items() if k != "text"},
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        elapsed_ms = int((time.time() - t0) * 1000)
        self._search_count += 1
        self._total_search_ms += elapsed_ms

        return results[:top_k]

    def delete(self, doc_id: str) -> bool:
        if doc_id in self._docs:
            del self._docs[doc_id]
            return True
        return False

    def cleanup_by_ttl(self, max_age_days: int) -> int:
        """Remove documents older than max_age_days. Returns count deleted."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        to_delete = [
            doc_id for doc_id, doc in self._docs.items()
            if doc["payload"].get("ts", "9999") < cutoff
        ]
        for doc_id in to_delete:
            del self._docs[doc_id]
        return len(to_delete)

    def stats(self) -> dict:
        avg_ms = self._total_search_ms / max(self._search_count, 1)
        return {
            "documents":    len(self._docs),
            "searches":     self._search_count,
            "avg_latency_ms": round(avg_ms, 2),
        }

    def __len__(self):
        return len(self._docs)


# ── SAMPLE DATA ───────────────────────────────────────────────────────────────

def build_sample_store() -> VectorStore:
    now = datetime.now(timezone.utc)
    store = VectorStore("user_events")

    docs = [
        # u_4821 — checkout errors
        ("evt_001", "u_4821", "error",   "User u_4821 (free) hit 500 error on /checkout at 14:32. Churn: TRUE.",
         now - timedelta(hours=2)),
        ("evt_002", "u_4821", "error",   "User u_4821 (free) hit 500 error on /checkout at 14:38. Error rate: 50%.",
         now - timedelta(hours=1, minutes=50)),
        ("evt_003", "u_4821", "click",   "User u_4821 clicked Upgrade to Pro on /pricing. Intent: 0.82.",
         now - timedelta(hours=1, minutes=40)),
        ("evt_004", "u_4821", "ticket",  "Support ticket from u_4821: checkout keeps failing with server error.",
         now - timedelta(hours=1)),
        ("evt_005", "u_4821", "view",    "User u_4821 viewed /pricing page 3 times. Strong upgrade intent.",
         now - timedelta(hours=3)),
        # u_0012 — healthy user
        ("evt_006", "u_0012", "purchase","User u_0012 (pro) completed purchase on /checkout. Payment successful.",
         now - timedelta(hours=4)),
        ("evt_007", "u_0012", "view",    "User u_0012 viewed /docs page. Active session.",
         now - timedelta(hours=2)),
        # Old events (for TTL demo)
        ("evt_old1","u_4821", "view",    "User u_4821 viewed /home 10 days ago.",
         now - timedelta(days=10)),
        ("evt_old2","u_4821", "error",   "User u_4821 hit error 15 days ago.",
         now - timedelta(days=15)),
    ]

    for doc_id, user_id, etype, text, ts in docs:
        store.upsert(doc_id, text, {
            "user_id":    user_id,
            "event_type": etype,
            "ts":         ts.isoformat(),
            "plan":       "free" if user_id == "u_4821" else "pro",
            "churn_risk": user_id == "u_4821",
        })

    return store


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("SIMILARITY SEARCH — Vector store operations")
    print("=" * 65)

    store = build_sample_store()
    print(f"\n[STORE]  {len(store)} documents indexed\n")

    # ── DEMO 1: Unfiltered search ──────────────────────────────────────────
    print("[DEMO 1]  Unfiltered search: 'checkout errors'")
    results = store.search("checkout errors", top_k=4)
    for r in results:
        print(f"  score={r['score']:.4f}  [{r['meta']['user_id']}]  {r['text'][:55]}...")

    # ── DEMO 2: Filtered by user_id ────────────────────────────────────────
    print(f"\n[DEMO 2]  Filtered search: user_id = u_4821 only")
    results = store.search(
        "checkout errors",
        top_k=4,
        filter_fn=lambda m: m.get("user_id") == "u_4821",
    )
    for r in results:
        print(f"  score={r['score']:.4f}  [{r['meta']['user_id']}]  {r['text'][:55]}...")

    # ── DEMO 3: Filtered by event_type ────────────────────────────────────
    print(f"\n[DEMO 3]  Filtered search: event_type = error only")
    results = store.search(
        "checkout problems",
        top_k=4,
        filter_fn=lambda m: m.get("event_type") == "error",
    )
    for r in results:
        print(f"  score={r['score']:.4f}  [{r['meta']['event_type']}]  {r['text'][:55]}...")

    # ── DEMO 4: Filtered by churn_risk ────────────────────────────────────
    print(f"\n[DEMO 4]  Filtered search: churn_risk = True only")
    results = store.search(
        "user at risk",
        top_k=4,
        filter_fn=lambda m: m.get("churn_risk") is True,
    )
    for r in results:
        print(f"  score={r['score']:.4f}  churn={r['meta']['churn_risk']}  {r['text'][:50]}...")

    # ── DEMO 5: TTL cleanup ────────────────────────────────────────────────
    print(f"\n[DEMO 5]  TTL cleanup: remove documents older than 7 days")
    print(f"  Before cleanup: {len(store)} documents")
    deleted = store.cleanup_by_ttl(max_age_days=7)
    print(f"  Deleted: {deleted} old documents")
    print(f"  After cleanup: {len(store)} documents")

    # ── Stats ──────────────────────────────────────────────────────────────
    print(f"\n[STATS]  {store.stats()}")
    print(f"\n[KEY INSIGHT]")
    print(f"  Metadata filtering is essential — without it, results include")
    print(f"  documents from other users and irrelevant event types.")
    print(f"  Always filter by user_id + date range for production queries.")


if __name__ == "__main__":
    run()
