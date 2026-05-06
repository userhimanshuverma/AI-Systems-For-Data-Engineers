"""
Update Pipeline — Day 12: Vector Storage Design
=================================================
Demonstrates three update strategies for keeping vector stores current:
  1. Content hash tracking  — incremental, re-embed only changed docs
  2. Full collection rebuild — for model upgrades or major changes
  3. Versioned collections  — zero-downtime model migration

Shows why stale embeddings are dangerous and how to detect them.
"""

import hashlib
import math
import random
from datetime import datetime, timezone


# ── MOCK EMBEDDING ────────────────────────────────────────────────────────────

def mock_embed_v1(text: str, dim: int = 16) -> list[float]:
    """Simulates text-embedding-ada-002 (old model)."""
    random.seed(abs(hash("v1:" + text)) % (2**32))
    v = [random.gauss(0, 1) for _ in range(dim)]
    n = math.sqrt(sum(x**2 for x in v))
    return [x/n for x in v]

def mock_embed_v2(text: str, dim: int = 16) -> list[float]:
    """Simulates text-embedding-3-small (new model). Different vector space."""
    random.seed(abs(hash("v2:" + text)) % (2**32))
    v = [random.gauss(0, 1) for _ in range(dim)]
    n = math.sqrt(sum(x**2 for x in v))
    return [x/n for x in v]

def cosine(a: list[float], b: list[float]) -> float:
    return round(sum(x*y for x,y in zip(a,b)), 4)

def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ── VECTOR STORE ──────────────────────────────────────────────────────────────

class VectorCollection:
    def __init__(self, name: str, model_version: str):
        self.name          = name
        self.model_version = model_version
        self._docs: dict[str, dict] = {}

    def upsert(self, doc_id: str, vector: list[float], text: str,
               metadata: dict, chash: str) -> None:
        self._docs[doc_id] = {
            "vector": vector, "text": text,
            "metadata": metadata, "hash": chash,
            "model_version": self.model_version,
        }

    def search(self, query_vec: list[float], top_k: int = 3,
               filter_fn=None) -> list[dict]:
        results = []
        for doc_id, doc in self._docs.items():
            if filter_fn and not filter_fn(doc["metadata"]):
                continue
            score = cosine(query_vec, doc["vector"])
            results.append({"id": doc_id, "score": score, "text": doc["text"],
                             "model": doc["model_version"]})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def get_hash(self, doc_id: str) -> str | None:
        return self._docs.get(doc_id, {}).get("hash")

    def __len__(self):
        return len(self._docs)


# ── STRATEGY 1: CONTENT HASH TRACKING ────────────────────────────────────────

class HashTracker:
    """Tracks content hashes to detect when re-embedding is needed."""
    def __init__(self):
        self._hashes: dict[str, str] = {}

    def needs_reembed(self, doc_id: str, text: str) -> bool:
        new_hash = content_hash(text)
        return self._hashes.get(doc_id) != new_hash

    def update(self, doc_id: str, text: str) -> None:
        self._hashes[doc_id] = content_hash(text)

    def get(self, doc_id: str) -> str | None:
        return self._hashes.get(doc_id)


def demo_hash_tracking() -> None:
    print(f"\n{'─'*65}")
    print(f"STRATEGY 1: Content Hash Tracking (Incremental Updates)")
    print(f"{'─'*65}")

    collection = VectorCollection("user_events", model_version="te3-small-v1")
    tracker    = HashTracker()
    embed_fn   = mock_embed_v2

    # Initial events
    events_v1 = [
        ("evt_001", "u_4821", "User u_4821 (free) hit error on /checkout. Churn: FALSE."),
        ("evt_002", "u_4821", "User u_4821 viewed /pricing page."),
        ("evt_003", "u_0012", "User u_0012 (pro) completed purchase."),
    ]

    print(f"\n[INITIAL LOAD]  Embedding {len(events_v1)} events")
    for doc_id, uid, text in events_v1:
        if tracker.needs_reembed(doc_id, text):
            vec = embed_fn(text)
            collection.upsert(doc_id, vec, text, {"user_id": uid}, content_hash(text))
            tracker.update(doc_id, text)
            print(f"  ✅ Embedded: {doc_id}  hash={content_hash(text)}")

    # Enrichment update: evt_001 churn_risk changed to TRUE
    events_v2 = [
        ("evt_001", "u_4821", "User u_4821 (free) hit error on /checkout. Churn: TRUE."),  # changed!
        ("evt_002", "u_4821", "User u_4821 viewed /pricing page."),                         # unchanged
        ("evt_003", "u_0012", "User u_0012 (pro) completed purchase."),                     # unchanged
    ]

    print(f"\n[UPDATE CHECK]  Checking {len(events_v2)} events for changes")
    reembedded = 0
    skipped    = 0
    for doc_id, uid, text in events_v2:
        if tracker.needs_reembed(doc_id, text):
            vec = embed_fn(text)
            collection.upsert(doc_id, vec, text, {"user_id": uid}, content_hash(text))
            tracker.update(doc_id, text)
            print(f"  ✅ Re-embedded: {doc_id}  (content changed)")
            reembedded += 1
        else:
            print(f"  ⏭  Skipped:     {doc_id}  (content unchanged)")
            skipped += 1

    print(f"\n  Re-embedded: {reembedded} | Skipped: {skipped}")
    print(f"  Cost savings: {skipped}/{len(events_v2)} = {skipped/len(events_v2):.0%} fewer API calls")


# ── STRATEGY 2: FULL COLLECTION REBUILD ──────────────────────────────────────

def demo_full_rebuild() -> None:
    print(f"\n{'─'*65}")
    print(f"STRATEGY 2: Full Collection Rebuild (Model Upgrade)")
    print(f"{'─'*65}")

    # Old collection with v1 model
    old_collection = VectorCollection("user_events_v1", model_version="ada-002")
    events = [
        ("evt_001", "u_4821", "User u_4821 hit error on /checkout."),
        ("evt_002", "u_4821", "User u_4821 clicked Upgrade to Pro."),
        ("evt_003", "u_0012", "User u_0012 completed purchase."),
    ]

    print(f"\n[OLD COLLECTION]  Embedding with model: ada-002")
    for doc_id, uid, text in events:
        vec = mock_embed_v1(text)
        old_collection.upsert(doc_id, vec, text, {"user_id": uid}, content_hash(text))
        print(f"  {doc_id}: vector[0]={vec[0]:.4f} (ada-002)")

    # Demonstrate the problem: mixing models
    print(f"\n[PROBLEM]  Query with new model against old embeddings:")
    query_v2 = mock_embed_v2("checkout errors")  # new model
    results  = old_collection.search(query_v2, top_k=2)
    print(f"  Query vector (v2 model) vs document vectors (v1 model)")
    for r in results:
        print(f"  score={r['score']:.4f}  [{r['model']}]  {r['text'][:50]}...")
    print(f"  ❌ Scores are meaningless — models produce incompatible vector spaces")

    # Rebuild with new model
    print(f"\n[REBUILD]  Creating new collection with model: te3-small")
    new_collection = VectorCollection("user_events_v2", model_version="te3-small-v1")
    for doc_id, uid, text in events:
        vec = mock_embed_v2(text)
        new_collection.upsert(doc_id, vec, text, {"user_id": uid}, content_hash(text))
        print(f"  {doc_id}: vector[0]={vec[0]:.4f} (te3-small)")

    # Query with new model against new collection
    print(f"\n[AFTER REBUILD]  Query with new model against new embeddings:")
    results = new_collection.search(query_v2, top_k=2)
    for r in results:
        print(f"  score={r['score']:.4f}  [{r['model']}]  {r['text'][:50]}...")
    print(f"  ✅ Scores are meaningful — same model for query and documents")


# ── STRATEGY 3: VERSIONED COLLECTIONS ────────────────────────────────────────

def demo_versioned_migration() -> None:
    print(f"\n{'─'*65}")
    print(f"STRATEGY 3: Versioned Collections (Zero-Downtime Migration)")
    print(f"{'─'*65}")

    v1 = VectorCollection("user_events_v1", "ada-002")
    v2 = VectorCollection("user_events_v2", "te3-small-v1")

    events = [
        ("evt_001", "u_4821", "User u_4821 hit error on /checkout."),
        ("evt_002", "u_4821", "User u_4821 clicked Upgrade to Pro."),
    ]

    # Phase 1: v1 is live, start building v2
    print(f"\n[PHASE 1]  v1 is live. Building v2 in parallel.")
    for doc_id, uid, text in events:
        v1.upsert(doc_id, mock_embed_v1(text), text, {"user_id": uid}, content_hash(text))
        v2.upsert(doc_id, mock_embed_v2(text), text, {"user_id": uid}, content_hash(text))
    print(f"  v1: {len(v1)} docs | v2: {len(v2)} docs")
    print(f"  Queries still routed to v1 (stable)")

    # Phase 2: New events go to both
    new_event = ("evt_003", "u_4821", "User u_4821 submitted support ticket.")
    v1.upsert(new_event[0], mock_embed_v1(new_event[2]), new_event[2],
              {"user_id": new_event[1]}, content_hash(new_event[2]))
    v2.upsert(new_event[0], mock_embed_v2(new_event[2]), new_event[2],
              {"user_id": new_event[1]}, content_hash(new_event[2]))
    print(f"\n[PHASE 2]  New events written to both collections.")
    print(f"  v1: {len(v1)} docs | v2: {len(v2)} docs")

    # Phase 3: v2 is complete, cut over
    print(f"\n[PHASE 3]  v2 complete. Cutting over queries to v2.")
    print(f"  Queries now routed to v2 (new model)")
    print(f"  v1 can be deleted after validation period")
    print(f"  ✅ Zero downtime — no gap in query service")


# ── STALE EMBEDDING DEMO ──────────────────────────────────────────────────────

def demo_stale_embeddings() -> None:
    print(f"\n{'─'*65}")
    print(f"STALE EMBEDDING DANGER — Silent wrong results")
    print(f"{'─'*65}")

    collection = VectorCollection("user_events", "te3-small-v1")

    # Original event: churn_risk = False
    original_text = "User u_4821 (free) hit error on /checkout. Churn risk: FALSE."
    collection.upsert("evt_001", mock_embed_v2(original_text), original_text,
                      {"user_id": "u_4821"}, content_hash(original_text))

    # Enrichment updated: churn_risk = True (but embedding NOT updated)
    updated_text = "User u_4821 (free) hit error on /checkout. Churn risk: TRUE."

    print(f"\n[SCENARIO]  Enrichment updated churn_risk: FALSE → TRUE")
    print(f"[SCENARIO]  Embedding NOT updated (stale)")

    query = "users at high churn risk"
    qvec  = mock_embed_v2(query)
    results = collection.search(qvec, top_k=1)

    print(f"\n[QUERY]  '{query}'")
    print(f"  Result: score={results[0]['score']:.4f}  \"{results[0]['text']}\"")
    print(f"  ❌ WRONG: Returns 'Churn risk: FALSE' — stale embedding")
    print(f"  ❌ LLM will say 'no churn risk' when there actually is one")
    print(f"\n  Solution: Content hash tracking detects this change")
    print(f"  Old hash: {content_hash(original_text)}")
    print(f"  New hash: {content_hash(updated_text)}")
    print(f"  Hash changed: {content_hash(original_text) != content_hash(updated_text)}")
    print(f"  → Re-embed triggered automatically")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("UPDATE PIPELINE — Keeping vector stores current")
    print("=" * 65)

    demo_hash_tracking()
    demo_full_rebuild()
    demo_versioned_migration()
    demo_stale_embeddings()

    print(f"\n{'='*65}")
    print(f"  SUMMARY")
    print(f"  Hash tracking:      incremental, low cost, handles enrichment changes")
    print(f"  Full rebuild:       high cost, required for model upgrades")
    print(f"  Versioned cutover:  zero downtime, required for production migrations")
    print(f"  Stale embeddings:   silently return wrong results — most dangerous failure")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
