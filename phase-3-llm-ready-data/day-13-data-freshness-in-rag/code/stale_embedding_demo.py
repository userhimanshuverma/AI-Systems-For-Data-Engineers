"""
Stale Embedding Demo — Day 13: Data Freshness in RAG
======================================================
Demonstrates what happens when embeddings are not updated
after the underlying data changes.

Scenario:
  - User u_4821 was healthy 4 hours ago (0 errors)
  - In the last 2 hours, they hit 8 checkout errors
  - Embedding pipeline runs every 4 hours (batch)
  - Vector store still reflects the old state

Result: LLM confidently says "no issues" when user is in crisis.
"""

import math
import random
import hashlib
from datetime import datetime, timezone, timedelta


# ── MOCK EMBEDDING ────────────────────────────────────────────────────────────

def mock_embed(text: str, dim: int = 16) -> list[float]:
    random.seed(abs(hash(text)) % (2**32))
    v = [random.gauss(0, 1) for _ in range(dim)]
    n = math.sqrt(sum(x**2 for x in v))
    return [x/n for x in v]

def cosine(a: list[float], b: list[float]) -> float:
    return round(sum(x*y for x,y in zip(a,b)), 4)


# ── STALE VECTOR STORE ────────────────────────────────────────────────────────

class StaleVectorStore:
    """
    Simulates a vector store that was last updated 4 hours ago.
    Contains embeddings of the OLD state of user u_4821.
    """
    def __init__(self):
        now = datetime.now(timezone.utc)
        # These embeddings were created 4 hours ago — STALE
        self._docs = [
            {
                "id":          "evt_old_001",
                "text":        "User u_4821 (free plan, at_risk) viewed /home. No errors. Session healthy.",
                "embedded_at": (now - timedelta(hours=4)).isoformat(),
                "metadata":    {"user_id": "u_4821", "errors": 0, "churn_risk": False},
            },
            {
                "id":          "evt_old_002",
                "text":        "User u_4821 (free plan) viewed /pricing. No issues detected.",
                "embedded_at": (now - timedelta(hours=4, minutes=5)).isoformat(),
                "metadata":    {"user_id": "u_4821", "errors": 0, "churn_risk": False},
            },
            {
                "id":          "evt_old_003",
                "text":        "User u_4821 browsed documentation. Normal session activity.",
                "embedded_at": (now - timedelta(hours=4, minutes=10)).isoformat(),
                "metadata":    {"user_id": "u_4821", "errors": 0, "churn_risk": False},
            },
        ]
        # Pre-compute vectors
        for doc in self._docs:
            doc["vector"] = mock_embed(doc["text"])

    def search(self, query: str, top_k: int = 3, uid: str = None) -> list[dict]:
        qv = mock_embed(query)
        results = [
            {**d, "score": cosine(qv, d["vector"])}
            for d in self._docs
            if uid is None or d["metadata"].get("user_id") == uid
        ]
        return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]

    def index_age_hours(self) -> float:
        now = datetime.now(timezone.utc)
        oldest = min(
            (now - datetime.fromisoformat(
                d["embedded_at"].replace("Z", "+00:00")
            )).total_seconds() / 3600
            for d in self._docs
        )
        return round(oldest, 1)


# ── WHAT ACTUALLY HAPPENED (last 2 hours) ────────────────────────────────────

RECENT_EVENTS = [
    "User u_4821 (free plan, at_risk) hit 500 error on /checkout at 14:32. Error 1 of 8.",
    "User u_4821 hit 500 error on /checkout at 14:35. Error 2 of 8.",
    "User u_4821 hit 500 error on /checkout at 14:38. Error 3 of 8.",
    "User u_4821 clicked 'Upgrade to Pro' on /pricing. Intent score: 0.82.",
    "User u_4821 hit 500 error on /checkout at 14:45. Error 4 of 8.",
    "User u_4821 submitted support ticket: 'checkout keeps failing'.",
    "User u_4821 hit 500 error on /checkout at 15:02. Error 5 of 8.",
    "User u_4821 hit 500 error on /checkout at 15:15. Error 6 of 8. Churn risk: TRUE.",
]

# These events are in Pinot (structured) but NOT in the vector store (stale)
PINOT_CURRENT = {
    "u_4821": {
        "errors_2h": 8, "error_rate": 0.80, "churn_risk": True,
        "intent_score": 0.82, "plan": "free", "segment": "at_risk",
        "last_active": "5 minutes ago",
    }
}


# ── MOCK LLM ──────────────────────────────────────────────────────────────────

def mock_llm_stale(query: str, retrieved_chunks: list[str]) -> str:
    """LLM response based on STALE retrieved context."""
    has_errors = any("error" in c.lower() for c in retrieved_chunks)
    if not has_errors:
        return (
            "User u_4821 appears to be browsing normally. "
            "No errors or issues detected in the retrieved context. "
            "No immediate action required."
        )
    return f"Some activity detected for u_4821. {retrieved_chunks[0][:60]}..."


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("STALE EMBEDDING DEMO — The danger of outdated vector stores")
    print("=" * 65)

    store = StaleVectorStore()
    query = "Is user u_4821 having checkout issues?"

    print(f"\n[SCENARIO]")
    print(f"  User u_4821 hit 8 checkout errors in the last 2 hours.")
    print(f"  Embedding pipeline last ran: {store.index_age_hours()} hours ago.")
    print(f"  Vector store reflects state from {store.index_age_hours()} hours ago.\n")

    print(f"[WHAT ACTUALLY HAPPENED (last 2 hours — in Pinot, NOT in vector store)]")
    for i, event in enumerate(RECENT_EVENTS[:4], 1):
        print(f"  [{i}] {event}")
    print(f"  ... and {len(RECENT_EVENTS)-4} more events")

    print(f"\n[PINOT METRICS (current, accurate)]")
    m = PINOT_CURRENT["u_4821"]
    print(f"  errors_2h={m['errors_2h']}, error_rate={m['error_rate']:.0%}, "
          f"churn_risk={m['churn_risk']}, intent={m['intent_score']}")

    print(f"\n[VECTOR STORE RETRIEVAL (stale — {store.index_age_hours()}h old)]")
    results = store.search(query, top_k=3, uid="u_4821")
    for r in results:
        age = store.index_age_hours()
        print(f"  score={r['score']:.4f}  [{age}h old]  {r['text'][:60]}...")

    print(f"\n[LLM RESPONSE (based on stale context)]")
    chunks = [r["text"] for r in results]
    response = mock_llm_stale(query, chunks)
    print(f"  \"{response}\"")
    print(f"  ❌ WRONG — user has 8 errors and is at HIGH churn risk")

    print(f"\n[ROOT CAUSE]")
    print(f"  Vector store is {store.index_age_hours()} hours old.")
    print(f"  8 critical events are in Pinot but NOT in the vector store.")
    print(f"  The LLM received accurate-looking but completely outdated context.")
    print(f"  This is a silent failure — no error was thrown.")

    print(f"\n{'='*65}")
    print(f"  LESSON: Batch embedding pipelines create freshness gaps.")
    print(f"  For support tooling, use event-driven embedding (< 5s lag).")
    print(f"  Run incremental_update.py to see the fix.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
