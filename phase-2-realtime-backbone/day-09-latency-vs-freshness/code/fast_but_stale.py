"""
Fast But Stale — Day 09: Latency vs Freshness
===============================================
Simulates a query system optimized for low latency using aggressive caching.

The system responds quickly (5–15ms) but serves data that may be
minutes old. For AI systems, this produces confidently wrong answers.

Pattern:
  - Query result cache with 5-minute TTL
  - Cache hit: ~5ms response, data up to 5 minutes old
  - Cache miss: ~68ms response, then cached for 5 minutes

Run this alongside fresh_but_slow.py to see the tradeoff.
"""

import time
import random
from datetime import datetime, timezone, timedelta


# ── SIMULATED DATA STORE ──────────────────────────────────────────────────────

# Simulates what Pinot has — enriched event data
# In this scenario, the last batch/sync was 4.5 minutes ago
_DATA_LAST_UPDATED = datetime.now(timezone.utc) - timedelta(minutes=4, seconds=30)

_PINOT_DATA = {
    "u_4821": {
        "error_count":   0,   # ← STALE: user actually has 5 errors right now
        "churn_risk":    False,
        "intent_score":  0.0,
        "last_event_ts": (_DATA_LAST_UPDATED - timedelta(minutes=2)).isoformat(),
        "plan":          "free",
        "segment":       "at_risk",
    },
    "u_0012": {
        "error_count":   1,
        "churn_risk":    False,
        "intent_score":  0.3,
        "last_event_ts": (_DATA_LAST_UPDATED - timedelta(minutes=1)).isoformat(),
        "plan":          "pro",
        "segment":       "active",
    },
}

# What ACTUALLY happened in the last 5 minutes (not yet in cache)
_RECENT_EVENTS = {
    "u_4821": {
        "error_count":   5,   # ← REAL: 5 checkout errors in last 2 minutes
        "churn_risk":    True,
        "intent_score":  0.82,
        "last_event_ts": datetime.now(timezone.utc).isoformat(),
    }
}


# ── QUERY CACHE ───────────────────────────────────────────────────────────────

class QueryCache:
    """
    Simulates a query result cache with configurable TTL.
    In production: Redis with SETEX, or an application-level LRU cache.
    """
    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self._cache: dict[str, dict] = {}
        self._hits   = 0
        self._misses = 0

    def get(self, key: str) -> dict | None:
        if key in self._cache:
            entry = self._cache[key]
            age = (datetime.now(timezone.utc) - entry["cached_at"]).total_seconds()
            if age < self.ttl:
                self._hits += 1
                return entry["data"]
            else:
                del self._cache[key]
        self._misses += 1
        return None

    def set(self, key: str, data: dict) -> None:
        self._cache[key] = {"data": data, "cached_at": datetime.now(timezone.utc)}

    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits":     self._hits,
            "misses":   self._misses,
            "hit_rate": f"{self._hits/max(total,1):.0%}",
        }


# ── FAST QUERY SYSTEM ─────────────────────────────────────────────────────────

class FastButStaleSystem:
    """
    Query system optimized for low latency via aggressive caching.
    Fast responses, but data may be minutes old.
    """
    def __init__(self, cache_ttl_seconds: int = 300):
        self.cache = QueryCache(ttl_seconds=cache_ttl_seconds)
        self._query_count = 0

    def query_user_metrics(self, user_id: str) -> dict:
        """
        Returns user metrics. Checks cache first.
        Cache hit: ~5ms. Cache miss: ~68ms (then cached).
        """
        self._query_count += 1
        cache_key = f"user_metrics:{user_id}"

        # Check cache
        cached = self.cache.get(cache_key)
        if cached:
            latency_ms = random.randint(3, 8)
            time.sleep(latency_ms / 1000)
            return {
                **cached,
                "_meta": {
                    "source":     "cache",
                    "latency_ms": latency_ms,
                    "data_age_s": (datetime.now(timezone.utc) - _DATA_LAST_UPDATED).total_seconds(),
                    "fresh":      False,
                }
            }

        # Cache miss — query Pinot
        latency_ms = random.randint(60, 80)
        time.sleep(latency_ms / 1000)

        data = _PINOT_DATA.get(user_id, {})
        self.cache.set(cache_key, data)

        return {
            **data,
            "_meta": {
                "source":     "pinot",
                "latency_ms": latency_ms,
                "data_age_s": (datetime.now(timezone.utc) - _DATA_LAST_UPDATED).total_seconds(),
                "fresh":      False,
            }
        }

    def mock_llm_response(self, user_id: str, metrics: dict) -> str:
        """Generates an LLM response based on (potentially stale) metrics."""
        errors = metrics.get("error_count", 0)
        churn  = metrics.get("churn_risk", False)
        plan   = metrics.get("plan", "?")

        if errors == 0 and not churn:
            return (
                f"User {user_id} ({plan} plan) appears healthy. "
                f"No errors detected. No churn risk identified. "
                f"No immediate action required."
            )
        return f"User {user_id}: {errors} errors, churn_risk={churn}."


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("FAST BUT STALE — Cache TTL=5min, optimized for low latency")
    print("=" * 65)

    system = FastButStaleSystem(cache_ttl_seconds=300)

    print(f"\n[SCENARIO]  User u_4821 hit 5 checkout errors 2 minutes ago.")
    print(f"[SCENARIO]  Support agent asks: 'Is user u_4821 having issues?'")
    print(f"[SCENARIO]  Cache was last populated 4.5 minutes ago (before the errors).\n")

    # Query 1: cache miss (first query)
    print(f"[QUERY 1]  First query (cache miss)...")
    result = system.query_user_metrics("u_4821")
    meta   = result.pop("_meta")
    print(f"  Source:     {meta['source']}")
    print(f"  Latency:    {meta['latency_ms']}ms")
    print(f"  Data age:   {meta['data_age_s']:.0f} seconds ({meta['data_age_s']/60:.1f} minutes)")
    print(f"  Metrics:    errors={result.get('error_count')}, churn_risk={result.get('churn_risk')}")
    llm = system.mock_llm_response("u_4821", result)
    print(f"  LLM output: \"{llm}\"")
    print(f"  ❌ WRONG: User actually has 5 errors and is at HIGH churn risk")

    # Query 2: cache hit
    print(f"\n[QUERY 2]  Second query (cache hit)...")
    result = system.query_user_metrics("u_4821")
    meta   = result.pop("_meta")
    print(f"  Source:     {meta['source']}")
    print(f"  Latency:    {meta['latency_ms']}ms  ← faster!")
    print(f"  Data age:   {meta['data_age_s']:.0f} seconds ({meta['data_age_s']/60:.1f} minutes)")
    print(f"  Metrics:    errors={result.get('error_count')}, churn_risk={result.get('churn_risk')}")
    llm = system.mock_llm_response("u_4821", result)
    print(f"  LLM output: \"{llm}\"")
    print(f"  ❌ STILL WRONG: Cache serves the same stale data")

    # Multiple queries to show cache performance
    print(f"\n[LOAD TEST]  10 queries for u_4821...")
    latencies = []
    for _ in range(10):
        r = system.query_user_metrics("u_4821")
        latencies.append(r["_meta"]["latency_ms"] if "_meta" in r else 5)

    stats = system.cache.stats()
    print(f"  Cache stats: {stats}")
    print(f"  Avg latency: {sum(latencies)/len(latencies):.1f}ms")

    print(f"\n{'='*65}")
    print(f"  SUMMARY: Fast But Stale")
    print(f"  Query latency:  ~5ms (cache hit)")
    print(f"  Data age:       ~4.5 minutes")
    print(f"  LLM accuracy:   ❌ WRONG — user has 5 errors, system says 0")
    print(f"  Verdict:        Optimizing for speed produced a wrong AI answer")
    print(f"{'='*65}")


if __name__ == "__main__":
    random.seed(42)
    run()
