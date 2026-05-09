"""
Hybrid Retrieval — Day 15: Production RAG
Runs structured (Pinot) and semantic (Vector DB) retrieval in parallel.

No external dependencies. Run standalone:
    python hybrid_retrieval.py
"""

import math
import time
import random
import hashlib
from typing import Optional


# ---------------------------------------------------------------------------
# Simulated Pinot Store
# ---------------------------------------------------------------------------

# Seed data: realistic user metrics table
_PINOT_USER_METRICS = [
    {
        "user_id": "u_4821", "plan": "free",       "error_rate": 0.34,
        "session_count": 2,  "last_active_hours_ago": 18, "churn_risk_score": 0.91,
        "churn_risk": True,  "has_errors": True,   "page_views": 12,
        "checkout_errors": 3, "support_tickets": 2,
    },
    {
        "user_id": "u_3302", "plan": "free",       "error_rate": 0.21,
        "session_count": 4,  "last_active_hours_ago": 6,  "churn_risk_score": 0.78,
        "churn_risk": True,  "has_errors": True,   "page_views": 28,
        "checkout_errors": 1, "support_tickets": 1,
    },
    {
        "user_id": "u_7741", "plan": "free",       "error_rate": 0.18,
        "session_count": 1,  "last_active_hours_ago": 42, "churn_risk_score": 0.72,
        "churn_risk": True,  "has_errors": True,   "page_views": 5,
        "checkout_errors": 0, "support_tickets": 0,
    },
    {
        "user_id": "u_1190", "plan": "free",       "error_rate": 0.09,
        "session_count": 7,  "last_active_hours_ago": 2,  "churn_risk_score": 0.61,
        "churn_risk": True,  "has_errors": False,  "page_views": 44,
        "checkout_errors": 0, "support_tickets": 0,
    },
    {
        "user_id": "u_5503", "plan": "free",       "error_rate": 0.05,
        "session_count": 12, "last_active_hours_ago": 1,  "churn_risk_score": 0.44,
        "churn_risk": False, "has_errors": False,  "page_views": 67,
        "checkout_errors": 0, "support_tickets": 0,
    },
    {
        "user_id": "u_8812", "plan": "pro",        "error_rate": 0.02,
        "session_count": 22, "last_active_hours_ago": 0,  "churn_risk_score": 0.12,
        "churn_risk": False, "has_errors": False,  "page_views": 134,
        "checkout_errors": 0, "support_tickets": 0,
    },
    {
        "user_id": "u_2244", "plan": "pro",        "error_rate": 0.31,
        "session_count": 3,  "last_active_hours_ago": 8,  "churn_risk_score": 0.67,
        "churn_risk": True,  "has_errors": True,   "page_views": 19,
        "checkout_errors": 2, "support_tickets": 1,
    },
    {
        "user_id": "u_6677", "plan": "enterprise", "error_rate": 0.00,
        "session_count": 45, "last_active_hours_ago": 0,  "churn_risk_score": 0.05,
        "churn_risk": False, "has_errors": False,  "page_views": 289,
        "checkout_errors": 0, "support_tickets": 0,
    },
    {
        "user_id": "u_9901", "plan": "free",       "error_rate": 0.44,
        "session_count": 1,  "last_active_hours_ago": 72, "churn_risk_score": 0.88,
        "churn_risk": True,  "has_errors": True,   "page_views": 3,
        "checkout_errors": 4, "support_tickets": 3,
    },
    {
        "user_id": "u_0055", "plan": "free",       "error_rate": 0.12,
        "session_count": 9,  "last_active_hours_ago": 3,  "churn_risk_score": 0.55,
        "churn_risk": True,  "has_errors": False,  "page_views": 51,
        "checkout_errors": 0, "support_tickets": 0,
    },
]

# Error funnel data
_PINOT_ERROR_FUNNEL = [
    {"step": "page_load",    "events": 10000, "errors": 12,  "error_rate": 0.0012},
    {"step": "login",        "events": 8200,  "errors": 34,  "error_rate": 0.0041},
    {"step": "search",       "events": 6100,  "errors": 18,  "error_rate": 0.0030},
    {"step": "add_to_cart",  "events": 3400,  "errors": 67,  "error_rate": 0.0197},
    {"step": "checkout",     "events": 1800,  "errors": 312, "error_rate": 0.1733},
    {"step": "payment",      "events": 1200,  "errors": 189, "error_rate": 0.1575},
    {"step": "confirmation", "events": 1011,  "errors": 4,   "error_rate": 0.0040},
]


class PinotStore:
    """
    Simulated Apache Pinot store for structured retrieval.

    In production this would execute SQL queries against a real Pinot cluster.
    Here we simulate the query execution with in-memory filtering.
    """

    def __init__(self, latency_ms: float = 45.0):
        """
        Args:
            latency_ms: Simulated query latency in milliseconds.
        """
        self._data = _PINOT_USER_METRICS
        self._funnel = _PINOT_ERROR_FUNNEL
        self._latency_ms = latency_ms

    def _simulate_latency(self) -> None:
        """Simulate Pinot query latency with slight jitter."""
        jitter = random.uniform(-5, 10)
        time.sleep(max(0, self._latency_ms + jitter) / 1000)

    def query_user_metrics(self, user_id: str) -> Optional[dict]:
        """
        Retrieve metrics for a specific user.

        Equivalent SQL:
            SELECT * FROM user_metrics WHERE user_id = '{user_id}' LIMIT 1
        """
        self._simulate_latency()
        for row in self._data:
            if row["user_id"] == user_id:
                return dict(row)
        return None

    def query_at_risk_users(
        self,
        limit: int = 10,
        plan_filter: Optional[str] = None,
        churn_risk: bool = True,
        time_range_hours: int = 168,
    ) -> list:
        """
        Retrieve top at-risk users ordered by churn_risk_score DESC.

        Equivalent SQL:
            SELECT user_id, plan, error_rate, session_count,
                   last_active_hours_ago, churn_risk_score
            FROM user_metrics
            WHERE churn_risk = {churn_risk}
              AND (plan = '{plan_filter}' OR plan_filter IS NULL)
              AND last_active_hours_ago <= {time_range_hours}
            ORDER BY churn_risk_score DESC
            LIMIT {limit}
        """
        self._simulate_latency()
        results = []
        for row in self._data:
            if churn_risk and not row["churn_risk"]:
                continue
            if plan_filter and row["plan"] != plan_filter:
                continue
            if row["last_active_hours_ago"] > time_range_hours:
                continue
            results.append(dict(row))

        results.sort(key=lambda r: r["churn_risk_score"], reverse=True)
        return results[:limit]

    def query_error_funnel(self) -> list:
        """
        Retrieve error funnel metrics across all checkout steps.

        Equivalent SQL:
            SELECT step, events, errors, error_rate
            FROM error_funnel
            ORDER BY error_rate DESC
        """
        self._simulate_latency()
        return sorted(self._funnel, key=lambda r: r["error_rate"], reverse=True)

    def query_users_with_errors(
        self,
        user_id: Optional[str] = None,
        plan_filter: Optional[str] = None,
        limit: int = 10,
    ) -> list:
        """
        Retrieve users who have errors, optionally filtered.

        Equivalent SQL:
            SELECT user_id, plan, error_rate, checkout_errors, support_tickets
            FROM user_metrics
            WHERE has_errors = true
              AND (user_id = '{user_id}' OR user_id IS NULL)
              AND (plan = '{plan_filter}' OR plan_filter IS NULL)
            ORDER BY error_rate DESC
            LIMIT {limit}
        """
        self._simulate_latency()
        results = []
        for row in self._data:
            if not row["has_errors"]:
                continue
            if user_id and row["user_id"] != user_id:
                continue
            if plan_filter and row["plan"] != plan_filter:
                continue
            results.append(dict(row))

        results.sort(key=lambda r: r["error_rate"], reverse=True)
        return results[:limit]


# ---------------------------------------------------------------------------
# Simulated Vector Store
# ---------------------------------------------------------------------------

def _mock_embed(text: str) -> list:
    """
    Deterministic mock embedding using character-level hashing.

    Produces a 16-dimensional unit vector. Same text always produces the
    same vector. Similar texts produce similar vectors (approximately).

    In production: replace with OpenAI text-embedding-3-small or similar.
    """
    dim = 16
    vec = [0.0] * dim

    # Hash-based component: deterministic per text
    h = hashlib.md5(text.lower().encode()).digest()
    for i in range(dim):
        vec[i] += (h[i] - 128) / 128.0

    # Word-overlap component: similar texts get similar vectors
    words = set(re.sub(r"[^a-z0-9\s]", "", text.lower()).split())
    for word in words:
        wh = hashlib.md5(word.encode()).digest()
        for i in range(dim):
            vec[i] += (wh[i % 16] - 128) / 512.0

    # Normalize to unit vector
    magnitude = math.sqrt(sum(x * x for x in vec))
    if magnitude > 0:
        vec = [x / magnitude for x in vec]

    return vec


import re


def _cosine_similarity(a: list, b: list) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# Seed documents: realistic event descriptions for a SaaS product
_SEED_DOCUMENTS = [
    {
        "event_id": "evt_001",
        "user_id":  "u_4821",
        "text":     "User u_4821 (free plan) hit checkout error: payment gateway timeout. "
                    "Third occurrence in 2 hours. User viewed /pricing page after error.",
        "event_type": "checkout_error",
        "ts_hours_ago": 1.5,
        "plan": "free",
    },
    {
        "event_id": "evt_002",
        "user_id":  "u_4821",
        "text":     "User u_4821 submitted support ticket: 'Cannot complete purchase, "
                    "keeps failing at payment step.' Severity: high.",
        "event_type": "support_ticket",
        "ts_hours_ago": 1.0,
        "plan": "free",
    },
    {
        "event_id": "evt_003",
        "user_id":  "u_3302",
        "text":     "User u_3302 (free plan) reached feature limit on data exports. "
                    "Viewed /upgrade page for 4 minutes but did not convert.",
        "event_type": "feature_limit",
        "ts_hours_ago": 3.0,
        "plan": "free",
    },
    {
        "event_id": "evt_004",
        "user_id":  "u_3302",
        "text":     "User u_3302 hit checkout error during upgrade attempt. "
                    "Payment declined. User abandoned session.",
        "event_type": "checkout_error",
        "ts_hours_ago": 2.5,
        "plan": "free",
    },
    {
        "event_id": "evt_005",
        "user_id":  "u_9901",
        "text":     "User u_9901 (free plan) has 4 checkout errors and 3 support tickets "
                    "in the last 72 hours. Last session: 3 days ago. High churn risk.",
        "event_type": "churn_signal",
        "ts_hours_ago": 4.0,
        "plan": "free",
    },
    {
        "event_id": "evt_006",
        "user_id":  "u_7741",
        "text":     "User u_7741 (free plan) has been inactive for 42 hours. "
                    "Last action: viewed /features comparison page. No errors recorded.",
        "event_type": "inactivity",
        "ts_hours_ago": 42.0,
        "plan": "free",
    },
    {
        "event_id": "evt_007",
        "user_id":  "u_8812",
        "text":     "User u_8812 (pro plan) completed 22 sessions this week. "
                    "Heavy API usage, no errors. Engaged with advanced analytics features.",
        "event_type": "engagement",
        "ts_hours_ago": 0.5,
        "plan": "pro",
    },
    {
        "event_id": "evt_008",
        "user_id":  "u_2244",
        "text":     "User u_2244 (pro plan) hit 2 checkout errors when attempting to "
                    "add team members. Submitted support ticket about billing issue.",
        "event_type": "checkout_error",
        "ts_hours_ago": 6.0,
        "plan": "pro",
    },
    {
        "event_id": "evt_009",
        "user_id":  "u_1190",
        "text":     "User u_1190 (free plan) has 7 sessions this week with 44 page views. "
                    "Consistently views /pricing and /compare pages. Upgrade intent signal.",
        "event_type": "upgrade_intent",
        "ts_hours_ago": 2.0,
        "plan": "free",
    },
    {
        "event_id": "evt_010",
        "user_id":  "u_5503",
        "text":     "User u_5503 (free plan) is highly active: 12 sessions, 67 page views. "
                    "No errors. Engages with collaboration features daily. Low churn risk.",
        "event_type": "engagement",
        "ts_hours_ago": 1.0,
        "plan": "free",
    },
]


class VectorStore:
    """
    Simulated vector store for semantic retrieval.

    Stores documents as (vector, metadata) pairs. Supports:
    - upsert: add or update a document
    - search: cosine similarity search with optional metadata filter
    - mock_embed: deterministic embedding for demo purposes

    In production: replace with Pinecone, Weaviate, Qdrant, or pgvector.
    """

    def __init__(self, latency_ms: float = 35.0):
        """
        Args:
            latency_ms: Simulated search latency in milliseconds.
        """
        self._store: dict = {}   # event_id → {vector, metadata, text}
        self._latency_ms = latency_ms

    def _simulate_latency(self) -> None:
        jitter = random.uniform(-5, 8)
        time.sleep(max(0, self._latency_ms + jitter) / 1000)

    @staticmethod
    def mock_embed(text: str) -> list:
        """Deterministic mock embedding. See _mock_embed for details."""
        return _mock_embed(text)

    def upsert(self, event_id: str, text: str, metadata: dict) -> None:
        """
        Add or update a document in the vector store.

        Args:
            event_id: Unique document identifier.
            text:     Document text to embed.
            metadata: Arbitrary metadata dict (user_id, plan, ts_hours_ago, etc.)
        """
        vector = self.mock_embed(text)
        self._store[event_id] = {
            "event_id": event_id,
            "vector":   vector,
            "text":     text,
            "metadata": metadata,
        }

    def search(
        self,
        query: str,
        top_k: int = 5,
        metadata_filter: Optional[dict] = None,
    ) -> list:
        """
        Semantic search: return top-k documents by cosine similarity.

        Args:
            query:           Natural language query string.
            top_k:           Number of results to return.
            metadata_filter: Optional dict of metadata key→value filters.
                             All specified keys must match (AND logic).

        Returns:
            List of dicts: {event_id, text, metadata, score}
            Sorted by score descending.
        """
        self._simulate_latency()

        if not self._store:
            return []

        query_vec = self.mock_embed(query)
        results = []

        for doc in self._store.values():
            # Apply metadata filter
            if metadata_filter:
                match = all(
                    doc["metadata"].get(k) == v
                    for k, v in metadata_filter.items()
                )
                if not match:
                    continue

            score = _cosine_similarity(query_vec, doc["vector"])
            results.append({
                "event_id": doc["event_id"],
                "text":     doc["text"],
                "metadata": doc["metadata"],
                "score":    round(score, 4),
            })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def size(self) -> int:
        return len(self._store)


def build_default_vector_store() -> VectorStore:
    """Build and seed a VectorStore with the 10 default event documents."""
    vs = VectorStore()
    for doc in _SEED_DOCUMENTS:
        vs.upsert(
            event_id=doc["event_id"],
            text=doc["text"],
            metadata={
                "user_id":      doc["user_id"],
                "event_type":   doc["event_type"],
                "ts_hours_ago": doc["ts_hours_ago"],
                "plan":         doc["plan"],
            },
        )
    return vs


# ---------------------------------------------------------------------------
# Hybrid Retriever
# ---------------------------------------------------------------------------

class HybridRetriever:
    """
    Runs structured (Pinot) and semantic (Vector DB) retrieval in parallel
    and combines the results.

    In production, the parallel execution would use asyncio or a thread pool.
    Here we simulate parallelism by running both and reporting combined timing.
    """

    def __init__(self, pinot: PinotStore, vector: VectorStore):
        self._pinot = pinot
        self._vector = vector

    def retrieve(
        self,
        retrieval_plan: dict,
        user_id: Optional[str] = None,
    ) -> dict:
        """
        Execute hybrid retrieval based on a retrieval plan.

        Args:
            retrieval_plan: Output of build_retrieval_plan() from query_understanding.
            user_id:        Optional specific user to retrieve for.

        Returns:
            {
                structured_results: list of Pinot rows,
                semantic_results:   list of vector search results,
                retrieval_ms:       total retrieval time in ms,
                pinot_ms:           Pinot query time in ms,
                vector_ms:          vector search time in ms,
            }
        """
        t_total_start = time.perf_counter()

        structured_results = []
        semantic_results = []
        pinot_ms = 0.0
        vector_ms = 0.0

        # --- Structured retrieval (Pinot) ---
        if retrieval_plan.get("use_pinot", False):
            t_pinot = time.perf_counter()
            filters = retrieval_plan.get("pinot_filters", {})
            uid = user_id or filters.get("user_id")

            if uid:
                # Single-user lookup
                row = self._pinot.query_user_metrics(uid)
                if row:
                    structured_results = [row]
            elif filters.get("has_errors"):
                # Error investigation
                structured_results = self._pinot.query_users_with_errors(
                    plan_filter=filters.get("plan"),
                    limit=retrieval_plan.get("top_k", 10),
                )
            else:
                # At-risk users (churn/retention)
                structured_results = self._pinot.query_at_risk_users(
                    limit=retrieval_plan.get("top_k", 10),
                    plan_filter=filters.get("plan"),
                    churn_risk=filters.get("churn_risk", False),
                    time_range_hours=retrieval_plan.get("time_range_hours", 168),
                )
            pinot_ms = (time.perf_counter() - t_pinot) * 1000

        # --- Semantic retrieval (Vector Store) ---
        if retrieval_plan.get("use_vector", False):
            t_vec = time.perf_counter()
            vector_query = retrieval_plan.get("vector_query", "")
            top_k = retrieval_plan.get("top_k", 5)

            # Build metadata filter
            meta_filter = {}
            if user_id:
                meta_filter["user_id"] = user_id
            elif retrieval_plan.get("pinot_filters", {}).get("plan"):
                meta_filter["plan"] = retrieval_plan["pinot_filters"]["plan"]

            semantic_results = self._vector.search(
                query=vector_query,
                top_k=top_k,
                metadata_filter=meta_filter if meta_filter else None,
            )
            vector_ms = (time.perf_counter() - t_vec) * 1000

        total_ms = (time.perf_counter() - t_total_start) * 1000

        return {
            "structured_results": structured_results,
            "semantic_results":   semantic_results,
            "retrieval_ms":       round(total_ms, 2),
            "pinot_ms":           round(pinot_ms, 2),
            "vector_ms":          round(vector_ms, 2),
        }


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("  Hybrid Retrieval — Day 15: Production RAG")
    print("=" * 70)

    # Build stores
    pinot = PinotStore(latency_ms=40)
    vector = build_default_vector_store()
    retriever = HybridRetriever(pinot, vector)

    print(f"\n  Vector store seeded with {vector.size()} documents")

    # --- Demo 1: Churn analysis for free-plan users ---
    print(f"\n{'─'*70}")
    print("  Demo 1: Churn analysis — free-plan users at risk this week")
    plan_1 = {
        "use_pinot":          True,
        "use_vector":         True,
        "pinot_filters":      {"plan": "free", "churn_risk": True},
        "vector_query":       "free plan user churn risk behavior errors disengagement",
        "top_k":              5,
        "freshness_required": True,
        "time_range_hours":   168,
    }
    r1 = retriever.retrieve(plan_1)
    print(f"\n  Pinot results ({len(r1['structured_results'])} rows, {r1['pinot_ms']:.1f}ms):")
    for row in r1["structured_results"][:3]:
        print(f"    {row['user_id']} | plan={row['plan']} | "
              f"churn_risk={row['churn_risk_score']:.2f} | "
              f"errors={row['error_rate']:.2f} | "
              f"last_active={row['last_active_hours_ago']}h ago")
    print(f"\n  Vector results ({len(r1['semantic_results'])} chunks, {r1['vector_ms']:.1f}ms):")
    for chunk in r1["semantic_results"][:3]:
        print(f"    [{chunk['event_id']}] score={chunk['score']:.3f} | "
              f"{chunk['text'][:70]}...")
    print(f"\n  Total retrieval: {r1['retrieval_ms']:.1f}ms")

    # --- Demo 2: Error investigation for specific user ---
    print(f"\n{'─'*70}")
    print("  Demo 2: Error investigation — user u_4821")
    plan_2 = {
        "use_pinot":          True,
        "use_vector":         True,
        "pinot_filters":      {"user_id": "u_4821", "has_errors": True},
        "vector_query":       "error failure crash exception u_4821",
        "top_k":              3,
        "freshness_required": True,
        "time_range_hours":   2,
    }
    r2 = retriever.retrieve(plan_2, user_id="u_4821")
    print(f"\n  Pinot results ({len(r2['structured_results'])} rows, {r2['pinot_ms']:.1f}ms):")
    for row in r2["structured_results"]:
        print(f"    {row['user_id']} | error_rate={row['error_rate']:.2f} | "
              f"checkout_errors={row['checkout_errors']} | "
              f"support_tickets={row['support_tickets']}")
    print(f"\n  Vector results ({len(r2['semantic_results'])} chunks, {r2['vector_ms']:.1f}ms):")
    for chunk in r2["semantic_results"]:
        print(f"    [{chunk['event_id']}] score={chunk['score']:.3f} | "
              f"{chunk['text'][:70]}...")
    print(f"\n  Total retrieval: {r2['retrieval_ms']:.1f}ms")

    # --- Demo 3: Upgrade analysis (vector only) ---
    print(f"\n{'─'*70}")
    print("  Demo 3: Upgrade analysis — users showing upgrade intent")
    plan_3 = {
        "use_pinot":          True,
        "use_vector":         True,
        "pinot_filters":      {"plan": "free"},
        "vector_query":       "upgrade intent pricing page feature limit free plan",
        "top_k":              3,
        "freshness_required": False,
        "time_range_hours":   720,
    }
    r3 = retriever.retrieve(plan_3)
    print(f"\n  Pinot results ({len(r3['structured_results'])} rows, {r3['pinot_ms']:.1f}ms):")
    for row in r3["structured_results"][:3]:
        print(f"    {row['user_id']} | sessions={row['session_count']} | "
              f"page_views={row['page_views']} | "
              f"churn_risk={row['churn_risk_score']:.2f}")
    print(f"\n  Vector results ({len(r3['semantic_results'])} chunks, {r3['vector_ms']:.1f}ms):")
    for chunk in r3["semantic_results"]:
        print(f"    [{chunk['event_id']}] score={chunk['score']:.3f} | "
              f"{chunk['text'][:70]}...")
    print(f"\n  Total retrieval: {r3['retrieval_ms']:.1f}ms")

    # Assertions
    assert len(r1["structured_results"]) > 0, "Demo 1: expected Pinot results"
    assert len(r1["semantic_results"]) > 0,   "Demo 1: expected vector results"
    assert len(r2["structured_results"]) > 0, "Demo 2: expected Pinot results for u_4821"
    assert r2["structured_results"][0]["user_id"] == "u_4821", \
        "Demo 2: expected u_4821 in results"
    assert len(r3["semantic_results"]) > 0,   "Demo 3: expected vector results"

    print(f"\n{'─'*70}")
    print("  ✓ All assertions passed")
    print("=" * 70)
