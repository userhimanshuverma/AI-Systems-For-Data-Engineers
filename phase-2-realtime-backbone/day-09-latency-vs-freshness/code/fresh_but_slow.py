"""
Fresh But Slow — Day 09: Latency vs Freshness
===============================================
Simulates a query system optimized for data freshness with no caching.

The system always queries Pinot directly, returning data that is
~1–2 seconds old. Query latency is ~68ms. No cache means no staleness.

For AI systems, this is the correct approach for time-sensitive queries.
The 68ms overhead is negligible compared to the LLM call (~500ms).

Run this alongside fast_but_stale.py to see the tradeoff.
"""

import time
import random
from datetime import datetime, timezone, timedelta


# ── SIMULATED PINOT DATA (fresh — reflects current state) ─────────────────────

def get_current_pinot_data(user_id: str) -> dict:
    """
    Simulates a direct Pinot query — no cache.
    Returns data that is ~1 second old (Pinot ingestion lag).
    In production: HTTP POST to Pinot Broker.
    """
    # Simulate Pinot ingestion lag: data is ~1 second old
    data_age_s = random.uniform(0.8, 1.5)

    # Current state (reflects recent events)
    current_data = {
        "u_4821": {
            "error_count":   5,    # ← CORRECT: 5 errors in last 2 minutes
            "churn_risk":    True,
            "intent_score":  0.82,
            "session_errors":5,
            "error_rate":    0.50,
            "pricing_visits":3,
            "plan":          "free",
            "segment":       "at_risk",
            "last_event_ts": (datetime.now(timezone.utc) - timedelta(seconds=data_age_s)).isoformat(),
        },
        "u_0012": {
            "error_count":   0,
            "churn_risk":    False,
            "intent_score":  0.3,
            "session_errors":0,
            "error_rate":    0.0,
            "pricing_visits":1,
            "plan":          "pro",
            "segment":       "active",
            "last_event_ts": (datetime.now(timezone.utc) - timedelta(seconds=data_age_s)).isoformat(),
        },
    }
    return current_data.get(user_id, {}), data_age_s


# ── FRESH QUERY SYSTEM ────────────────────────────────────────────────────────

class FreshButSlowSystem:
    """
    Query system that always reads directly from Pinot.
    No cache. Data is always ~1 second old.
    Query latency: ~68ms (Pinot P99).
    """
    def __init__(self):
        self._query_count = 0
        self._total_latency_ms = 0

    def query_user_metrics(self, user_id: str) -> dict:
        """
        Direct Pinot query — no cache.
        Always returns fresh data (~1s old).
        Latency: 50–90ms.
        """
        self._query_count += 1

        # Simulate Pinot query latency
        latency_ms = random.randint(55, 85)
        time.sleep(latency_ms / 1000)
        self._total_latency_ms += latency_ms

        data, data_age_s = get_current_pinot_data(user_id)

        return {
            **data,
            "_meta": {
                "source":     "pinot_direct",
                "latency_ms": latency_ms,
                "data_age_s": data_age_s,
                "fresh":      True,
            }
        }

    def avg_latency_ms(self) -> float:
        if self._query_count == 0:
            return 0
        return self._total_latency_ms / self._query_count

    def mock_llm_response(self, user_id: str, metrics: dict) -> str:
        """Generates an LLM response based on fresh metrics."""
        errors  = metrics.get("error_count", 0)
        churn   = metrics.get("churn_risk", False)
        rate    = metrics.get("error_rate", 0.0)
        intent  = metrics.get("intent_score", 0.0)
        plan    = metrics.get("plan", "?")
        segment = metrics.get("segment", "?")

        if churn and errors >= 3:
            return (
                f"User {user_id} ({plan} plan, {segment} segment) is at HIGH churn risk. "
                f"They hit {errors} checkout errors ({rate:.0%} error rate) in this session. "
                f"Upgrade intent score: {intent:.2f}. "
                f"Recommend: escalate checkout fix immediately + send targeted upgrade offer."
            )
        elif errors > 0:
            return (
                f"User {user_id} has {errors} errors ({rate:.0%} error rate). "
                f"Monitor closely. Churn risk: {'HIGH' if churn else 'LOW'}."
            )
        return f"User {user_id} ({plan} plan): no issues detected. Healthy session."


# ── PIPELINE DELAY SIMULATION ─────────────────────────────────────────────────

def simulate_pipeline_delay() -> dict:
    """
    Simulates the end-to-end pipeline delay from event to queryable data.
    Shows where latency accumulates in the Kafka → Flink → Pinot pipeline.
    """
    stages = [
        ("App → Kafka (publish)",          random.randint(3, 8)),
        ("Kafka → Flink (consumer poll)",  random.randint(10, 20)),
        ("Flink enrichment (Redis + state)",random.randint(8, 15)),
        ("Flink → Kafka (enriched topic)", random.randint(3, 7)),
        ("Kafka → Pinot (segment build)",  random.randint(700, 1100)),
    ]

    total = 0
    results = []
    for stage, ms in stages:
        total += ms
        results.append({"stage": stage, "latency_ms": ms, "cumulative_ms": total})

    return {"stages": results, "total_pipeline_ms": total}


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("FRESH BUT SLOW — No cache, direct Pinot queries")
    print("=" * 65)

    system = FreshButSlowSystem()

    print(f"\n[SCENARIO]  User u_4821 hit 5 checkout errors 2 minutes ago.")
    print(f"[SCENARIO]  Support agent asks: 'Is user u_4821 having issues?'")
    print(f"[SCENARIO]  No cache — every query goes directly to Pinot.\n")

    # Query 1
    print(f"[QUERY 1]  Direct Pinot query...")
    result = system.query_user_metrics("u_4821")
    meta   = result.pop("_meta")
    print(f"  Source:     {meta['source']}")
    print(f"  Latency:    {meta['latency_ms']}ms")
    print(f"  Data age:   {meta['data_age_s']:.2f} seconds  ← fresh!")
    print(f"  Metrics:    errors={result.get('error_count')}, churn_risk={result.get('churn_risk')}, rate={result.get('error_rate'):.0%}")
    llm = system.mock_llm_response("u_4821", result)
    print(f"  LLM output: \"{llm}\"")
    print(f"  ✅ CORRECT: Reflects actual current state")

    # Query 2
    print(f"\n[QUERY 2]  Second direct Pinot query...")
    result = system.query_user_metrics("u_4821")
    meta   = result.pop("_meta")
    print(f"  Source:     {meta['source']}")
    print(f"  Latency:    {meta['latency_ms']}ms")
    print(f"  Data age:   {meta['data_age_s']:.2f} seconds")
    print(f"  Metrics:    errors={result.get('error_count')}, churn_risk={result.get('churn_risk')}")
    print(f"  ✅ Still fresh — no cache to go stale")

    # Pipeline delay breakdown
    print(f"\n[PIPELINE DELAY]  Where does the ~1s data age come from?")
    pipeline = simulate_pipeline_delay()
    for s in pipeline["stages"]:
        bar = "█" * (s["latency_ms"] // 50)
        print(f"  {s['stage']:42s} +{s['latency_ms']:4d}ms  {bar}")
    print(f"  {'Total pipeline latency':42s}  {pipeline['total_pipeline_ms']}ms")
    print(f"  → Data is ~{pipeline['total_pipeline_ms']/1000:.1f}s old when it reaches Pinot")

    # Load test
    print(f"\n[LOAD TEST]  10 queries for u_4821...")
    for _ in range(10):
        system.query_user_metrics("u_4821")
    print(f"  Avg latency: {system.avg_latency_ms():.1f}ms per query")
    print(f"  No cache = no staleness, but every query hits Pinot")

    print(f"\n{'='*65}")
    print(f"  SUMMARY: Fresh But Slow")
    print(f"  Query latency:  ~68ms (direct Pinot)")
    print(f"  Data age:       ~1 second")
    print(f"  LLM accuracy:   ✅ CORRECT — reflects actual current state")
    print(f"  Verdict:        68ms overhead is negligible vs 500ms LLM call")
    print(f"                  For AI systems, freshness > speed")
    print(f"{'='*65}")


if __name__ == "__main__":
    random.seed(42)
    run()
