"""
Retrieval Monitor — Day 23: Observability for AI Systems
==========================================================
Tracks retrieval quality metrics for the vector search layer.

Monitors:
  - Precision@k against a golden test set
  - Average similarity scores
  - Embedding freshness
  - Empty result rate
  - Stale retrieval rate

In production: metrics exported to Prometheus, dashboards in Grafana.
"""

import time
import random
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from collections import deque


# ── MOCK EMBEDDING + SEARCH ───────────────────────────────────────────────────

def mock_embed(text: str, dim: int = 8) -> list[float]:
    random.seed(abs(hash(text)) % (2**32))
    v = [random.gauss(0, 1) for _ in range(dim)]
    n = math.sqrt(sum(x**2 for x in v))
    return [x/n for x in v]

def cosine(a, b):
    return round(sum(x*y for x,y in zip(a,b)), 4)


# ── GOLDEN TEST SET ───────────────────────────────────────────────────────────

GOLDEN_TEST_SET = [
    {
        "query":    "checkout errors and payment failures",
        "relevant": ["doc_001", "doc_002", "doc_003"],
        "description": "Should return checkout error events",
    },
    {
        "query":    "user upgrade intent pricing page",
        "relevant": ["doc_010", "doc_011"],
        "description": "Should return upgrade intent events",
    },
    {
        "query":    "churn risk high error rate",
        "relevant": ["doc_001", "doc_020", "doc_021"],
        "description": "Should return churn risk events",
    },
]


# ── RETRIEVAL METRICS ─────────────────────────────────────────────────────────

@dataclass
class RetrievalSnapshot:
    ts:                 str
    query:              str
    precision_at_k:     float
    avg_score:          float
    result_count:       int
    stale_results:      int
    embedding_age_p99_s:float
    latency_ms:         float


class RetrievalMonitor:
    """Tracks retrieval quality over time."""

    ALERT_THRESHOLDS = {
        "precision_at_k":      0.70,   # alert if < 0.70
        "avg_score":           0.65,   # alert if < 0.65
        "stale_rate":          0.10,   # alert if > 10%
        "empty_result_rate":   0.05,   # alert if > 5%
        "embedding_age_p99_s": 3600,   # alert if > 1 hour
    }

    def __init__(self, window_size: int = 100):
        self._snapshots:    list[RetrievalSnapshot] = []
        self._precision_window = deque(maxlen=window_size)
        self._score_window     = deque(maxlen=window_size)
        self._alerts:       list[dict] = []

    def record(self, snap: RetrievalSnapshot) -> None:
        self._snapshots.append(snap)
        self._precision_window.append(snap.precision_at_k)
        self._score_window.append(snap.avg_score)
        self._check_alerts(snap)

    def _check_alerts(self, snap: RetrievalSnapshot) -> None:
        avg_precision = sum(self._precision_window) / len(self._precision_window)
        avg_score     = sum(self._score_window) / len(self._score_window)

        if avg_precision < self.ALERT_THRESHOLDS["precision_at_k"]:
            self._fire("RETRIEVAL_PRECISION",
                f"Avg precision@k {avg_precision:.2f} < {self.ALERT_THRESHOLDS['precision_at_k']}")
        if avg_score < self.ALERT_THRESHOLDS["avg_score"]:
            self._fire("RETRIEVAL_SCORE",
                f"Avg similarity score {avg_score:.2f} < {self.ALERT_THRESHOLDS['avg_score']}")
        if snap.embedding_age_p99_s > self.ALERT_THRESHOLDS["embedding_age_p99_s"]:
            self._fire("EMBEDDING_STALE",
                f"Embedding age P99 {snap.embedding_age_p99_s:.0f}s > {self.ALERT_THRESHOLDS['embedding_age_p99_s']}s")

    def _fire(self, alert_type: str, message: str) -> None:
        recent = [a for a in self._alerts if a["type"] == alert_type]
        if recent and time.perf_counter() - recent[-1]["ts"] < 60:
            return
        self._alerts.append({"type": alert_type, "message": message, "ts": time.perf_counter()})
        print(f"  🔔 ALERT [{alert_type}]: {message}")

    def current_metrics(self) -> dict:
        if not self._snapshots:
            return {}
        return {
            "avg_precision_at_k": round(sum(self._precision_window)/len(self._precision_window), 3),
            "avg_similarity_score": round(sum(self._score_window)/len(self._score_window), 3),
            "total_queries":      len(self._snapshots),
            "alerts_fired":       len(self._alerts),
        }


# ── SIMULATED RETRIEVAL ───────────────────────────────────────────────────────

class MockVectorStore:
    def __init__(self, quality: str = "good"):
        self.quality = quality
        self._docs = {
            "doc_001": ("checkout error payment failure 500", 30),
            "doc_002": ("checkout error billing page timeout", 45),
            "doc_003": ("payment gateway failed transaction declined", 60),
            "doc_010": ("user clicked upgrade to pro pricing page", 20),
            "doc_011": ("user visited pricing page three times", 35),
            "doc_020": ("user churn risk high error rate free plan", 50),
            "doc_021": ("user at risk churning checkout failures", 40),
            "doc_099": ("user logged in session started", 15),
            "doc_100": ("user browsed documentation pages", 25),
        }

    def search(self, query: str, top_k: int = 4) -> list[dict]:
        time.sleep(random.uniform(0.040, 0.060))
        qv = mock_embed(query)

        results = []
        for doc_id, (text, age_s) in self._docs.items():
            score = cosine(qv, mock_embed(text))
            # Degrade quality if store is in bad state
            if self.quality == "degraded":
                score *= random.uniform(0.4, 0.7)
            results.append({"id": doc_id, "score": score, "age_s": age_s})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]


def run_precision_benchmark(store: MockVectorStore, monitor: RetrievalMonitor) -> None:
    """Runs the golden test set and records precision metrics."""
    for test in GOLDEN_TEST_SET:
        t0 = time.perf_counter()
        results = store.search(test["query"], top_k=4)
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)

        retrieved_ids = [r["id"] for r in results]
        relevant_ids  = set(test["relevant"])
        precision     = len(set(retrieved_ids) & relevant_ids) / 4
        avg_score     = sum(r["score"] for r in results) / len(results) if results else 0
        stale         = sum(1 for r in results if r["age_s"] > 3600)
        age_p99       = sorted(r["age_s"] for r in results)[int(len(results)*0.99)] if results else 0

        snap = RetrievalSnapshot(
            ts=datetime.now(timezone.utc).isoformat(),
            query=test["query"][:40],
            precision_at_k=round(precision, 3),
            avg_score=round(avg_score, 3),
            result_count=len(results),
            stale_results=stale,
            embedding_age_p99_s=age_p99,
            latency_ms=latency_ms,
        )
        monitor.record(snap)


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("RETRIEVAL MONITOR — Quality tracking for vector search")
    print("=" * 65)

    monitor = RetrievalMonitor()

    # Phase 1: Good retrieval
    print(f"\n[PHASE 1]  Healthy vector store (10 benchmark runs)")
    store_good = MockVectorStore(quality="good")
    for _ in range(10):
        run_precision_benchmark(store_good, monitor)

    metrics = monitor.current_metrics()
    print(f"  Avg precision@4:    {metrics['avg_precision_at_k']:.3f}")
    print(f"  Avg similarity:     {metrics['avg_similarity_score']:.3f}")
    print(f"  Alerts fired:       {metrics['alerts_fired']}")

    # Phase 2: Degraded retrieval
    print(f"\n[PHASE 2]  Degraded vector store (10 benchmark runs)")
    store_bad = MockVectorStore(quality="degraded")
    for _ in range(10):
        run_precision_benchmark(store_bad, monitor)

    metrics2 = monitor.current_metrics()
    print(f"  Avg precision@4:    {metrics2['avg_precision_at_k']:.3f}")
    print(f"  Avg similarity:     {metrics2['avg_similarity_score']:.3f}")
    print(f"  Alerts fired:       {metrics2['alerts_fired']}")

    print(f"\n{'='*65}")
    print(f"  Retrieval quality dropped from {metrics['avg_precision_at_k']:.2f} to {metrics2['avg_precision_at_k']:.2f}")
    print(f"  Observability detected this before users noticed.")
    print(f"{'='*65}")


if __name__ == "__main__":
    random.seed(42)
    run()
