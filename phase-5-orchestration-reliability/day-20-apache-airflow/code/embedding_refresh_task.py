"""
Embedding Refresh Task — Day 20: Airflow for AI Systems
=========================================================
Simulates the embedding refresh workflow that Airflow orchestrates.

This is the most critical orchestration target in an AI system.
Stale embeddings = wrong LLM answers. This task must:
  1. Run on schedule (every 30 minutes)
  2. Retry on failure (API timeouts, rate limits)
  3. Be idempotent (safe to re-run)
  4. Alert when it fails or misses SLA

Run this standalone to see the full refresh workflow.
"""

import time
import random
import hashlib
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field


# ── SIMULATED INFRASTRUCTURE ──────────────────────────────────────────────────

class MockPinot:
    """Simulates querying Pinot for changed documents."""
    def get_changed_documents(self, since: datetime) -> list[dict]:
        time.sleep(0.068)  # simulate ~68ms query
        # Simulate finding changed documents
        return [
            {"doc_id": f"evt_{i:05d}", "text": f"User u_{i%4+1:04d} performed action at {since.isoformat()}", "ts": since.isoformat()}
            for i in range(random.randint(50, 200))
        ]


class MockEmbeddingAPI:
    """Simulates calling an embedding API (OpenAI / local model)."""
    def __init__(self, failure_rate: float = 0.0):
        self.failure_rate = failure_rate
        self.call_count   = 0

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        time.sleep(0.050 + len(texts) * 0.0001)  # simulate latency

        if random.random() < self.failure_rate:
            raise TimeoutError(f"Embedding API timeout on call {self.call_count}")

        # Return mock vectors (real: 1536 dims)
        return [[random.gauss(0, 1) for _ in range(8)] for _ in texts]


class MockVectorStore:
    """Simulates upserting to Qdrant / Pinecone."""
    def __init__(self):
        self._store: dict[str, dict] = {}
        self._upsert_count = 0

    def upsert(self, doc_id: str, vector: list[float], metadata: dict) -> None:
        time.sleep(0.001)  # simulate ~1ms per upsert
        self._store[doc_id] = {"vector": vector, "metadata": metadata, "updated_at": datetime.now(timezone.utc).isoformat()}
        self._upsert_count += 1

    def count(self) -> int:
        return len(self._store)


# ── CONTENT HASH TRACKER ──────────────────────────────────────────────────────

class ContentHashStore:
    """Tracks content hashes to avoid unnecessary re-embedding."""
    def __init__(self):
        self._hashes: dict[str, str] = {}

    def has_changed(self, doc_id: str, text: str) -> bool:
        new_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        if self._hashes.get(doc_id) == new_hash:
            return False
        self._hashes[doc_id] = new_hash
        return True


# ── EMBEDDING REFRESH TASK ────────────────────────────────────────────────────

@dataclass
class RefreshResult:
    run_id:         str
    started_at:     str
    completed_at:   str
    docs_checked:   int
    docs_changed:   int
    docs_embedded:  int
    docs_skipped:   int
    api_calls:      int
    retries:        int
    success:        bool
    error:          str | None = None
    duration_s:     float = 0.0


def run_embedding_refresh(
    pinot: MockPinot,
    embedding_api: MockEmbeddingAPI,
    vector_store: MockVectorStore,
    hash_store: ContentHashStore,
    batch_size: int = 100,
    max_retries: int = 3,
) -> RefreshResult:
    """
    Runs one embedding refresh cycle.
    Idempotent: safe to re-run. Uses content hashing to skip unchanged docs.
    """
    run_id    = f"run_{int(time.time())}"
    started   = datetime.now(timezone.utc)
    retries   = 0
    api_calls = 0

    print(f"\n[REFRESH]  Run ID: {run_id}")
    print(f"[REFRESH]  Started: {started.strftime('%H:%M:%S')}")

    # Step 1: Detect changed documents
    since = started - timedelta(minutes=30)
    docs  = pinot.get_changed_documents(since=since)
    print(f"[STEP 1]   Detected {len(docs)} documents from Pinot")

    # Step 2: Filter to changed documents (content hash check)
    changed = [d for d in docs if hash_store.has_changed(d["doc_id"], d["text"])]
    skipped = len(docs) - len(changed)
    print(f"[STEP 2]   {len(changed)} changed, {skipped} skipped (hash unchanged)")

    if not changed:
        completed = datetime.now(timezone.utc)
        return RefreshResult(
            run_id=run_id, started_at=started.isoformat(),
            completed_at=completed.isoformat(),
            docs_checked=len(docs), docs_changed=0,
            docs_embedded=0, docs_skipped=skipped,
            api_calls=0, retries=0, success=True,
            duration_s=round((completed - started).total_seconds(), 2),
        )

    # Step 3: Generate embeddings in batches with retry
    embedded = 0
    for i in range(0, len(changed), batch_size):
        batch = changed[i:i + batch_size]
        texts = [d["text"] for d in batch]

        for attempt in range(max_retries + 1):
            try:
                vectors = embedding_api.embed_batch(texts)
                api_calls += 1

                # Step 4: Upsert to vector store (idempotent)
                for doc, vec in zip(batch, vectors):
                    vector_store.upsert(doc["doc_id"], vec, {"ts": doc["ts"]})

                embedded += len(batch)
                print(f"[STEP 3]   Batch {i//batch_size + 1}: embedded {len(batch)} docs "
                      f"(attempt {attempt + 1})")
                break

            except TimeoutError as e:
                retries += 1
                if attempt == max_retries:
                    completed = datetime.now(timezone.utc)
                    print(f"[STEP 3]   FAILED after {max_retries + 1} attempts: {e}")
                    return RefreshResult(
                        run_id=run_id, started_at=started.isoformat(),
                        completed_at=completed.isoformat(),
                        docs_checked=len(docs), docs_changed=len(changed),
                        docs_embedded=embedded, docs_skipped=skipped,
                        api_calls=api_calls, retries=retries,
                        success=False, error=str(e),
                        duration_s=round((completed - started).total_seconds(), 2),
                    )
                backoff = 0.1 * (2 ** attempt)
                print(f"[STEP 3]   Attempt {attempt + 1} failed, retrying in {backoff:.1f}s...")
                time.sleep(backoff)

    completed = datetime.now(timezone.utc)
    duration  = round((completed - started).total_seconds(), 2)
    print(f"[STEP 4]   Vector store now has {vector_store.count()} documents")
    print(f"[REFRESH]  Completed in {duration}s | embedded={embedded} | retries={retries}")

    return RefreshResult(
        run_id=run_id, started_at=started.isoformat(),
        completed_at=completed.isoformat(),
        docs_checked=len(docs), docs_changed=len(changed),
        docs_embedded=embedded, docs_skipped=skipped,
        api_calls=api_calls, retries=retries, success=True,
        duration_s=duration,
    )


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("EMBEDDING REFRESH TASK — Airflow-orchestrated workflow")
    print("=" * 65)

    pinot        = MockPinot()
    vector_store = MockVectorStore()
    hash_store   = ContentHashStore()

    # Run 1: Normal execution
    print("\n[RUN 1]  Normal execution (no failures)")
    api = MockEmbeddingAPI(failure_rate=0.0)
    result = run_embedding_refresh(pinot, api, vector_store, hash_store)
    print(f"\n  Result: success={result.success}, embedded={result.docs_embedded}, "
          f"skipped={result.docs_skipped}, duration={result.duration_s}s")

    # Run 2: Same documents — most should be skipped (idempotency)
    print("\n[RUN 2]  Re-run (idempotency check — most docs unchanged)")
    api2 = MockEmbeddingAPI(failure_rate=0.0)
    result2 = run_embedding_refresh(pinot, api2, vector_store, hash_store)
    print(f"\n  Result: success={result2.success}, embedded={result2.docs_embedded}, "
          f"skipped={result2.docs_skipped}")
    print(f"  Idempotency: {result2.docs_skipped} docs skipped (hash unchanged)")

    # Run 3: With API failures → retries
    print("\n[RUN 3]  With API failures (testing retry logic)")
    api3 = MockEmbeddingAPI(failure_rate=0.6)  # 60% failure rate
    hash_store3 = ContentHashStore()  # fresh hash store to force re-embedding
    result3 = run_embedding_refresh(pinot, api3, vector_store, hash_store3)
    print(f"\n  Result: success={result3.success}, retries={result3.retries}, "
          f"embedded={result3.docs_embedded}")

    print(f"\n{'='*65}")
    print(f"  Airflow orchestrates this task every 30 minutes.")
    print(f"  Retries handle transient API failures automatically.")
    print(f"  Content hashing prevents unnecessary re-embedding.")
    print(f"{'='*65}")


if __name__ == "__main__":
    random.seed(42)
    run()
