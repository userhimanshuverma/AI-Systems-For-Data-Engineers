"""
Day 27 — Retrieval Engine (Hybrid Retrieval Simulation)
========================================================
Simulates the retrieval layer that combines structured analytical queries
(Apache Pinot) with semantic vector search (Vector DB) to provide
comprehensive context for the intelligence layer.

Architecture Role:
    The retrieval layer is the BRIDGE between data infrastructure and AI.
    It answers: "Given a user query and context, what information does
    the LLM need to generate an accurate, grounded response?"

Retrieval Strategy:
    1. Structured Retrieval  — SQL against Pinot for metrics, aggregations
    2. Semantic Retrieval    — Vector similarity for behavioral patterns
    3. Reciprocal Rank Fusion — Merges both result sets intelligently

Production Considerations:
    - Pinot queries: sub-100ms p99 on pre-aggregated segments
    - Vector search: ANN with HNSW index, top-k with score thresholds
    - Caching: query-level cache with TTL based on data freshness
    - Fallback: if vector search degrades, fall back to structured-only
"""

import time
import math
import random
import hashlib
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Simulated Data Stores
# ---------------------------------------------------------------------------

class PinotStore:
    """
    Simulates Apache Pinot — a real-time OLAP datastore.
    In production: star-tree index, pre-aggregated segments,
    real-time + offline tables with hybrid routing.
    """

    def __init__(self):
        self._data = self._generate_analytics_data()

    def _generate_analytics_data(self) -> Dict[str, Dict]:
        """Pre-populate with per-user analytics."""
        data = {}
        for i in range(1, 201):
            uid = f"user_{i:04d}"
            data[uid] = {
                "total_events_7d": random.randint(10, 500),
                "active_days_7d": random.randint(1, 7),
                "feature_adoption_rate": round(random.uniform(0.1, 0.95), 2),
                "avg_session_duration_min": round(random.uniform(2, 45), 1),
                "api_error_rate_24h": round(random.uniform(0, 0.15), 3),
                "support_tickets_30d": random.randint(0, 12),
                "mrr": round(random.uniform(0, 5000), 2),
                "nps_score": random.randint(-100, 100),
                "churn_risk_score": round(random.uniform(0, 1), 3),
                "last_login_hours_ago": random.randint(0, 720),
            }
        return data

    def query(self, sql: str, params: Dict = None) -> Tuple[List[Dict], float]:
        """
        Execute a SQL query against Pinot.
        Returns (results, latency_ms).
        """
        start = time.time()

        # Simulate query routing and execution
        time.sleep(random.uniform(0.001, 0.015))  # 1-15ms latency

        results = []
        if params and "user_id" in params:
            user_data = self._data.get(params["user_id"])
            if user_data:
                results = [{**user_data, "user_id": params["user_id"]}]
        elif params and "tier" in params:
            # Aggregation query across a tier
            matching = [
                v for k, v in self._data.items()
            ]
            if matching:
                results = [{
                    "avg_churn_risk": round(sum(m["churn_risk_score"] for m in matching) / len(matching), 3),
                    "avg_feature_adoption": round(sum(m["feature_adoption_rate"] for m in matching) / len(matching), 3),
                    "total_users": len(matching),
                }]
        else:
            # Top-k query
            sorted_users = sorted(
                self._data.items(),
                key=lambda x: x[1]["churn_risk_score"],
                reverse=True
            )
            results = [
                {**v, "user_id": k} for k, v in sorted_users[:10]
            ]

        latency = (time.time() - start) * 1000
        return results, latency


class VectorStore:
    """
    Simulates a Vector Database (Qdrant/Pinecone/Weaviate).
    Stores behavioral embeddings for semantic similarity search.
    """

    def __init__(self, dimension: int = 128):
        self.dimension = dimension
        self.embeddings: Dict[str, Dict] = {}
        self._populate()

    def _populate(self):
        """Pre-populate with user behavioral embeddings."""
        behavior_patterns = [
            "power_user_high_engagement",
            "declining_usage_pattern",
            "expansion_signal",
            "churn_risk_low_activity",
            "support_heavy_frustrated",
            "api_centric_developer",
            "team_collaborator",
            "evaluator_trial_user",
        ]

        for i in range(1, 201):
            uid = f"user_{i:04d}"
            pattern = random.choice(behavior_patterns)
            # Generate a pseudo-embedding based on pattern
            seed = hash(f"{uid}_{pattern}") % (2**31)
            rng = random.Random(seed)
            embedding = [rng.gauss(0, 1) for _ in range(self.dimension)]
            # Normalize
            norm = math.sqrt(sum(x*x for x in embedding))
            embedding = [x / norm for x in embedding]

            self.embeddings[uid] = {
                "vector": embedding,
                "pattern": pattern,
                "metadata": {
                    "user_id": uid,
                    "behavior_cluster": pattern,
                    "embedding_timestamp": "2026-05-20T10:00:00Z",
                    "model_version": "behavior-encoder-v3",
                },
            }

    def search(self, query_vector: List[float], top_k: int = 5,
               score_threshold: float = 0.0) -> Tuple[List[Dict], float]:
        """
        Approximate nearest neighbor search (simulated).
        In production: HNSW index with ef_search tuning.
        """
        start = time.time()
        time.sleep(random.uniform(0.002, 0.020))  # 2-20ms

        # Compute cosine similarity against all embeddings
        scores = []
        for uid, data in self.embeddings.items():
            sim = self._cosine_similarity(query_vector, data["vector"])
            if sim >= score_threshold:
                scores.append({
                    "user_id": uid,
                    "score": round(sim, 4),
                    "behavior_cluster": data["pattern"],
                    "metadata": data["metadata"],
                })

        # Sort by score descending
        scores.sort(key=lambda x: x["score"], reverse=True)
        results = scores[:top_k]

        latency = (time.time() - start) * 1000
        return results, latency

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Query Understanding
# ---------------------------------------------------------------------------

@dataclass
class ParsedQuery:
    """Structured representation of a user query."""
    raw_query: str
    intent: str = ""
    entities: Dict = field(default_factory=dict)
    requires_structured: bool = True
    requires_semantic: bool = True
    confidence: float = 0.0


class QueryUnderstanding:
    """
    Parses natural language queries into structured retrieval plans.
    In production: fine-tuned classifier or small LLM for intent detection.
    """

    INTENT_PATTERNS = {
        "churn_analysis": ["churn", "leaving", "cancel", "at risk", "retention"],
        "usage_analysis": ["usage", "active", "engagement", "session", "feature"],
        "revenue_analysis": ["revenue", "mrr", "billing", "subscription", "upgrade"],
        "similar_users": ["similar", "like", "pattern", "cluster", "cohort"],
        "support_analysis": ["support", "ticket", "complaint", "issue", "bug"],
        "health_check": ["health", "score", "status", "overview", "summary"],
    }

    def parse(self, query: str) -> ParsedQuery:
        query_lower = query.lower()
        parsed = ParsedQuery(raw_query=query)

        # Intent detection
        best_intent = "general_analysis"
        best_score = 0
        for intent, keywords in self.INTENT_PATTERNS.items():
            score = sum(1 for kw in keywords if kw in query_lower)
            if score > best_score:
                best_score = score
                best_intent = intent

        parsed.intent = best_intent
        parsed.confidence = min(best_score / 3.0, 1.0)

        # Entity extraction (simplified)
        for i in range(1, 201):
            uid = f"user_{i:04d}"
            if uid in query_lower:
                parsed.entities["user_id"] = uid
                break

        # Determine retrieval strategy
        parsed.requires_semantic = best_intent in ("similar_users", "churn_analysis", "support_analysis")
        parsed.requires_structured = True  # Always query Pinot

        return parsed


# ---------------------------------------------------------------------------
# Retrieval Engine — Hybrid Fusion
# ---------------------------------------------------------------------------

@dataclass
class RetrievalResult:
    """Combined retrieval output for the intelligence layer."""
    structured_results: List[Dict] = field(default_factory=list)
    semantic_results: List[Dict] = field(default_factory=list)
    fused_results: List[Dict] = field(default_factory=list)
    retrieval_metadata: Dict = field(default_factory=dict)


class RetrievalEngine:
    """
    Hybrid retrieval engine combining structured (Pinot) and semantic
    (Vector DB) retrieval with reciprocal rank fusion.
    """

    def __init__(self):
        self.pinot = PinotStore()
        self.vector_db = VectorStore()
        self.query_parser = QueryUnderstanding()
        self.cache: Dict[str, Tuple[RetrievalResult, float]] = {}
        self.cache_ttl_seconds = 60.0
        self.stats = {
            "total_queries": 0,
            "cache_hits": 0,
            "structured_queries": 0,
            "semantic_queries": 0,
            "avg_latency_ms": 0.0,
            "_latency_sum": 0.0,
        }

    def retrieve(self, query: str, use_cache: bool = True) -> RetrievalResult:
        """
        Execute hybrid retrieval for a natural language query.
        """
        start = time.time()
        self.stats["total_queries"] += 1

        # Check cache
        cache_key = hashlib.md5(query.encode()).hexdigest()
        if use_cache and cache_key in self.cache:
            cached_result, cached_time = self.cache[cache_key]
            if (time.time() - cached_time) < self.cache_ttl_seconds:
                self.stats["cache_hits"] += 1
                cached_result.retrieval_metadata["cache_hit"] = True
                return cached_result

        # Parse query
        parsed = self.query_parser.parse(query)
        result = RetrievalResult()
        total_latency = 0.0

        # Structured retrieval (Apache Pinot)
        if parsed.requires_structured:
            self.stats["structured_queries"] += 1
            pinot_results, pinot_latency = self._structured_retrieval(parsed)
            result.structured_results = pinot_results
            total_latency += pinot_latency

        # Semantic retrieval (Vector DB)
        if parsed.requires_semantic:
            self.stats["semantic_queries"] += 1
            vector_results, vector_latency = self._semantic_retrieval(parsed)
            result.semantic_results = vector_results
            total_latency += vector_latency

        # Reciprocal Rank Fusion
        if result.structured_results and result.semantic_results:
            result.fused_results = self._reciprocal_rank_fusion(
                result.structured_results,
                result.semantic_results,
                k=60
            )
        elif result.structured_results:
            result.fused_results = result.structured_results
        else:
            result.fused_results = result.semantic_results

        # Metadata
        overall_latency = (time.time() - start) * 1000
        result.retrieval_metadata = {
            "query": query,
            "parsed_intent": parsed.intent,
            "intent_confidence": parsed.confidence,
            "used_structured": parsed.requires_structured,
            "used_semantic": parsed.requires_semantic,
            "structured_count": len(result.structured_results),
            "semantic_count": len(result.semantic_results),
            "fused_count": len(result.fused_results),
            "pinot_latency_ms": round(total_latency, 2),
            "total_latency_ms": round(overall_latency, 2),
            "cache_hit": False,
        }

        # Update cache
        self.cache[cache_key] = (result, time.time())

        # Update stats
        self.stats["_latency_sum"] += overall_latency
        self.stats["avg_latency_ms"] = round(
            self.stats["_latency_sum"] / self.stats["total_queries"], 2
        )

        return result

    def _structured_retrieval(self, parsed: ParsedQuery) -> Tuple[List[Dict], float]:
        """Query Apache Pinot based on parsed intent."""
        params = {}
        if "user_id" in parsed.entities:
            params["user_id"] = parsed.entities["user_id"]

        sql = f"SELECT * FROM user_analytics WHERE intent='{parsed.intent}'"
        results, latency = self.pinot.query(sql, params)
        return results, latency

    def _semantic_retrieval(self, parsed: ParsedQuery) -> Tuple[List[Dict], float]:
        """Search Vector DB for semantically similar behavioral patterns."""
        # Generate query embedding (simplified — hash-based pseudo-embedding)
        seed = hash(parsed.raw_query) % (2**31)
        rng = random.Random(seed)
        query_vec = [rng.gauss(0, 1) for _ in range(self.vector_db.dimension)]
        norm = math.sqrt(sum(x*x for x in query_vec))
        query_vec = [x / norm for x in query_vec]

        results, latency = self.vector_db.search(query_vec, top_k=5, score_threshold=0.0)
        return results, latency

    def _reciprocal_rank_fusion(self, structured: List[Dict],
                                 semantic: List[Dict], k: int = 60) -> List[Dict]:
        """
        Reciprocal Rank Fusion (RRF) — combines rankings from multiple
        retrieval strategies into a single unified ranking.

        Score = Σ 1 / (k + rank_i) for each source where the item appears.
        """
        scores: Dict[str, float] = {}
        item_data: Dict[str, Dict] = {}

        for rank, item in enumerate(structured):
            uid = item.get("user_id", f"structured_{rank}")
            scores[uid] = scores.get(uid, 0) + 1.0 / (k + rank + 1)
            item_data[uid] = {**item, "sources": ["structured"]}

        for rank, item in enumerate(semantic):
            uid = item.get("user_id", f"semantic_{rank}")
            scores[uid] = scores.get(uid, 0) + 1.0 / (k + rank + 1)
            if uid in item_data:
                item_data[uid]["sources"].append("semantic")
                item_data[uid]["semantic_score"] = item.get("score", 0)
            else:
                item_data[uid] = {**item, "sources": ["semantic"]}

        # Sort by RRF score
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [
            {**item_data[uid], "rrf_score": round(score, 6)}
            for uid, score in ranked[:10]
        ]

    def get_metrics(self) -> Dict:
        return {
            "total_queries": self.stats["total_queries"],
            "cache_hits": self.stats["cache_hits"],
            "cache_hit_rate": round(
                self.stats["cache_hits"] / max(self.stats["total_queries"], 1), 3
            ),
            "structured_queries": self.stats["structured_queries"],
            "semantic_queries": self.stats["semantic_queries"],
            "avg_latency_ms": self.stats["avg_latency_ms"],
            "cache_size": len(self.cache),
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("  RETRIEVAL ENGINE — Hybrid Structured + Semantic Retrieval")
    print("=" * 70)

    engine = RetrievalEngine()

    queries = [
        "Which enterprise users are at risk of churning?",
        "Show me users similar to user_0042 in behavior patterns",
        "What is the revenue trend for professional tier?",
        "Find users with high support ticket volume and declining usage",
        "Which enterprise users are at risk of churning?",  # Cache hit test
    ]

    for query in queries:
        print(f"\n{'─' * 60}")
        print(f"  Query: {query}")
        print(f"{'─' * 60}")

        result = engine.retrieve(query)
        meta = result.retrieval_metadata

        print(f"  Intent         : {meta['parsed_intent']} (conf={meta['intent_confidence']:.1%})")
        print(f"  Structured     : {meta['structured_count']} results")
        print(f"  Semantic       : {meta['semantic_count']} results")
        print(f"  Fused          : {meta['fused_count']} results")
        print(f"  Total Latency  : {meta['total_latency_ms']:.1f} ms")
        print(f"  Cache Hit      : {meta['cache_hit']}")

        if result.fused_results:
            print(f"\n  Top 3 Results:")
            for r in result.fused_results[:3]:
                uid = r.get("user_id", "?")
                sources = r.get("sources", [])
                rrf = r.get("rrf_score", 0)
                print(f"    • {uid}  sources={sources}  rrf={rrf:.6f}")

    # Metrics
    metrics = engine.get_metrics()
    print(f"\n{'═' * 70}")
    print("  RETRIEVAL METRICS")
    print(f"{'═' * 70}")
    for k, v in metrics.items():
        print(f"  {k:25s} : {v}")

    print("\n✓ Retrieval engine demo complete.")
