"""
Day 28 — Hybrid Retrieval & Fusion Layer
========================================
Combines structured data analytics (Apache Pinot OLAP) with semantic behavior
searches (Vector DB) to assemble context.
Features:
1. SQL-like Pinot Querying: Fetches structured user health statistics.
2. Vector Search (HNSW simulation): Fetches semantic user behavior vectors.
3. Reciprocal Rank Fusion (RRF): Combines structured & unstructured ranks.
4. Semantic Cache: Memory lookup to bypass redundant database calls.
5. Fault Injection: Latency injection (Pinot) and Connection Outages (Vector DB).
"""

import time
import math
import random
import hashlib
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

from observability import logger, metrics
from failure_simulator import chaos_injector


# ---------------------------------------------------------------------------
# Apache Pinot Simulation (Structured Analytics OLAP)
# ---------------------------------------------------------------------------

class PinotStore:
    """Mock Apache Pinot OLAP DB for pre-aggregated, sub-100ms analytics."""

    def __init__(self):
        self._data = self._generate_analytics_data()

    def _generate_analytics_data(self) -> Dict[str, Dict]:
        """Generate tabular user telemetry data."""
        data = {}
        for i in range(1, 201):
            uid = f"usr_prem_{i:04d}"
            arr = random.choice([3600.0, 12000.0, 60000.0, 120000.0])
            data[uid] = {
                "user_id": uid,
                "tier": "enterprise" if arr >= 60000 else "premium_business",
                "arr_usd": arr,
                "total_events_7d": random.randint(50, 2500),
                "error_rate": round(random.uniform(0.0, 0.12), 4),
                "billing_failures": random.choices([0, 1, 2], weights=[90, 8, 2], k=1)[0],
                "avg_ticket_sentiment": round(random.uniform(-0.6, 0.4), 2),
                "churn_risk_score": round(random.uniform(0.0, 0.95), 3),
                "last_active_hours_ago": random.randint(0, 360),
            }
        return data

    def query(self, sql_query: str, params: Optional[Dict] = None) -> List[Dict]:
        """Execute mock SQL execution with injected latency."""
        # Inject Pinot latency spike (e.g. from index degradation or full table scan)
        delay = chaos_injector.get_pinot_latency()
        if delay > 0.1:
            logger.warn(f"Pinot index degraded: Executing analytical table scan. Delay: {delay:.2f}s")
            time.sleep(delay)
        else:
            time.sleep(delay) # Normal low latency

        metrics.observe("pinot_query_latency_seconds", delay)

        results = []
        if params and "user_id" in params:
            user_data = self._data.get(params["user_id"])
            if user_data:
                results = [user_data]
        elif params and "tier" in params:
            results = [v for v in self._data.values() if v["tier"] == params["tier"]]
        else:
            # Default: sorted by highest churn risk
            sorted_users = sorted(self._data.values(), key=lambda x: x["churn_risk_score"], reverse=True)
            results = sorted_users[:20]

        return results


# ---------------------------------------------------------------------------
# Vector DB Simulation (Semantic Behavioral Store)
# ---------------------------------------------------------------------------

class VectorStore:
    """Mock Vector database (e.g., Qdrant/Pinecone) storing behavioral embeddings."""

    def __init__(self, dimension: int = 128):
        self.dimension = dimension
        self._embeddings: Dict[str, Dict] = {}
        self._populate_vectors()

    def _populate_vectors(self):
        """Populate database with structured behavioral embeddings."""
        clusters = [
            "payment_delinquency", "api_throttling_failures", 
            "churn_pattern_inactive", "expansion_upgrade_healthy",
            "active_development_high_support", "team_churn_seat_reduction"
        ]
        
        for i in range(1, 201):
            uid = f"usr_prem_{i:04d}"
            cluster = random.choice(clusters)
            # Seed-based deterministic vector generation
            seed = hash(f"{uid}_{cluster}") % (2**31)
            rng = random.Random(seed)
            raw_vec = [rng.gauss(0, 1) for _ in range(self.dimension)]
            norm = math.sqrt(sum(x*x for x in raw_vec))
            normalized_vec = [x / norm for x in raw_vec]

            self._embeddings[uid] = {
                "vector": normalized_vec,
                "behavior_cluster": cluster,
                "metadata": {
                    "user_id": uid,
                    "embedding_date": "2026-05-20T12:00:00Z",
                    "model_version": "behavior-encoder-v4"
                }
            }

    def search(self, query_vector: List[float], top_k: int = 5) -> List[Dict]:
        """Perform similarity search with optional outage and drift injection."""
        if chaos_injector.is_vector_db_down():
            # Tripped outage simulation
            raise ConnectionError("Vector DB is unavailable: Connection Refused (500)")

        # Normal DB overhead latency
        time.sleep(random.uniform(0.005, 0.020))

        # Check if embeddings are stale (introducing drift)
        drift_factor = 0.35 if chaos_injector.is_embedding_stale() else 0.0

        scores = []
        for uid, entry in self._embeddings.items():
            similarity = self._cosine_similarity(query_vector, entry["vector"])
            # Apply drift penalty to mock stale database indexing accuracy loss
            similarity = max(0.0, similarity - drift_factor)
            
            scores.append({
                "user_id": uid,
                "score": round(similarity, 4),
                "behavior_cluster": entry["behavior_cluster"],
                "metadata": entry["metadata"]
            })

        scores.sort(key=lambda x: x["score"], reverse=True)
        return scores[:top_k]

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        return (dot / (norm_a * norm_b)) if (norm_a > 0 and norm_b > 0) else 0.0


# ---------------------------------------------------------------------------
# Query Understanding Layer
# ---------------------------------------------------------------------------

@dataclass
class RetrievalRequest:
    """Parsed structured intent plan for retrieval."""
    raw_query: str
    intent: str
    entities: Dict[str, Any]
    needs_structured: bool
    needs_semantic: bool


class QueryUnderstanding:
    """Parses raw text queries into execution plans."""

    INTENT_MAPPING = {
        "churn_analysis": ["churn", "risk", "cancel", "drop", "leaving"],
        "support_analysis": ["support", "ticket", "sentiment", "frustrated", "complaint"],
        "billing_analysis": ["billing", "payment", "invoice", "fail", "card"],
        "similar_users": ["similar", "pattern", "cohort", "cluster", "lookalike"]
    }

    def parse_query(self, query: str) -> RetrievalRequest:
        q_lower = query.lower()
        intent = "general_overview"
        best_matches = 0
        
        for name, keywords in self.INTENT_MAPPING.items():
            matches = sum(1 for kw in keywords if kw in q_lower)
            if matches > best_matches:
                best_matches = matches
                intent = name

        entities = {}
        # Simple Entity Extraction
        for i in range(1, 201):
            uid = f"usr_prem_{i:04d}"
            if uid in q_lower:
                entities["user_id"] = uid
                break

        # Churn and Similarity tasks require semantic behavioral retrieval
        needs_semantic = intent in ["similar_users", "churn_analysis"]
        needs_structured = True

        return RetrievalRequest(
            raw_query=query,
            intent=intent,
            entities=entities,
            needs_structured=needs_structured,
            needs_semantic=needs_semantic
        )


# ---------------------------------------------------------------------------
# Hybrid Retrieval Engine
# ---------------------------------------------------------------------------

@dataclass
class CombinedContext:
    """Unification structure containing multi-source retrieval outputs."""
    structured_results: List[Dict] = field(default_factory=list)
    semantic_results: List[Dict] = field(default_factory=list)
    fused_results: List[Dict] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class HybridRetrievalEngine:
    """Coordinates Pinot & Vector DB fetches and fuses them via RRF."""

    def __init__(self):
        self.pinot = PinotStore()
        self.vector_db = VectorStore()
        self.parser = QueryUnderstanding()
        self.semantic_cache: Dict[str, Tuple[CombinedContext, float]] = {}
        self.cache_ttl = 300.0 # 5 minutes

    def retrieve(self, query: str, force_refresh: bool = False) -> CombinedContext:
        """Execute hybrid retrieval utilizing reciprocal rank fusion."""
        start_time = time.time()
        metrics.increment("retrieval_queries_total")

        # Cache check
        cache_key = hashlib.md5(query.strip().lower().encode()).hexdigest()
        if not force_refresh and cache_key in self.semantic_cache:
            cached_data, cached_time = self.semantic_cache[cache_key]
            if (time.time() - cached_time) < self.cache_ttl:
                metrics.increment("retrieval_cache_hits_total")
                cached_data.metadata["cache_hit"] = True
                logger.info(f"Retrieval Cache Hit: {query}")
                return cached_data

        metrics.increment("retrieval_cache_misses_total")
        req = self.parser.parse_query(query)
        context = CombinedContext()

        # Structured query against Pinot
        if req.needs_structured:
            params = {}
            if "user_id" in req.entities:
                params["user_id"] = req.entities["user_id"]
            
            context.structured_results = self.pinot.query(req.raw_query, params)

        # Semantic query against Vector DB
        if req.needs_semantic:
            # Generate deterministic query vector based on intent/text
            seed = hash(query) % (2**31)
            rng = random.Random(seed)
            q_vector = [rng.gauss(0, 1) for _ in range(self.vector_db.dimension)]
            norm = math.sqrt(sum(x*x for x in q_vector))
            q_vector = [x / norm for x in q_vector]

            # This call raises an exception if the Vector DB outage chaos is active
            context.semantic_results = self.vector_db.search(q_vector, top_k=5)

        # Fusion
        context.fused_results = self._reciprocal_rank_fusion(
            context.structured_results, 
            context.semantic_results
        )

        overall_latency = (time.time() - start_time) * 1000
        metrics.observe("retrieval_latency_ms", overall_latency)

        context.metadata = {
            "query": query,
            "intent": req.intent,
            "cache_hit": False,
            "pinot_count": len(context.structured_results),
            "vector_count": len(context.semantic_results),
            "fused_count": len(context.fused_results),
            "latency_ms": round(overall_latency, 2)
        }

        # Cache writing
        self.semantic_cache[cache_key] = (context, time.time())
        return context

    def _reciprocal_rank_fusion(self, structured: List[Dict], semantic: List[Dict], k: int = 60) -> List[Dict]:
        """Merge ranked lists based on RRF logic."""
        rrf_scores: Dict[str, float] = {}
        data_lookup: Dict[str, Dict] = {}

        for rank, item in enumerate(structured):
            uid = item.get("user_id")
            if not uid: continue
            rrf_scores[uid] = rrf_scores.get(uid, 0.0) + 1.0 / (k + rank + 1)
            data_lookup[uid] = {**item, "sources": ["structured"]}

        for rank, item in enumerate(semantic):
            uid = item.get("user_id")
            if not uid: continue
            rrf_scores[uid] = rrf_scores.get(uid, 0.0) + 1.0 / (k + rank + 1)
            if uid in data_lookup:
                data_lookup[uid]["sources"].append("semantic")
                data_lookup[uid]["vector_similarity"] = item["score"]
                data_lookup[uid]["behavior_cluster"] = item["behavior_cluster"]
            else:
                data_lookup[uid] = {
                    "user_id": uid,
                    "sources": ["semantic"],
                    "vector_similarity": item["score"],
                    "behavior_cluster": item["behavior_cluster"]
                }

        sorted_rrf = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        
        fused = []
        for uid, score in sorted_rrf[:10]:
            record = data_lookup[uid]
            record["rrf_score"] = round(score, 6)
            fused.append(record)
        return fused

    def clear_cache(self):
        """Invalidate the cache."""
        self.semantic_cache.clear()


if __name__ == "__main__":
    print("Testing Hybrid Retrieval...")
    engine = HybridRetrievalEngine()
    
    res = engine.retrieve("Which enterprise accounts are at churn risk?")
    print("Fused Results count:", res.metadata["fused_count"])
    print("Fused Latency:", res.metadata["latency_ms"], "ms")
    print("Top Fused Item:", res.fused_results[0] if res.fused_results else "None")
