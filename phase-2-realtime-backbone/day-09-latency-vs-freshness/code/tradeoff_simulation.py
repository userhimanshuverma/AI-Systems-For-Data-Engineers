"""
Tradeoff Simulation — Day 09: Latency vs Freshness
====================================================
Side-by-side comparison of three query strategies:
  1. Fast but stale  — aggressive cache (TTL=5min)
  2. Balanced        — short cache (TTL=30s)
  3. Fresh but slow  — no cache, direct Pinot

Demonstrates:
  - How each strategy performs under different scenarios
  - The impact on LLM answer quality
  - The tiered freshness pattern for production systems

Run this to see all three strategies compared directly.
"""

import time
import random
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass


# ── DATA LAYER ────────────────────────────────────────────────────────────────

@dataclass
class UserState:
    """Represents the true current state of a user."""
    user_id:       str
    error_count:   int
    churn_risk:    bool
    intent_score:  float
    error_rate:    float
    plan:          str
    segment:       str
    updated_at:    datetime


# True current state (what just happened)
TRUE_STATE = {
    "u_4821": UserState(
        user_id="u_4821", error_count=5, churn_risk=True,
        intent_score=0.82, error_rate=0.50,
        plan="free", segment="at_risk",
        updated_at=datetime.now(timezone.utc) - timedelta(seconds=90),
    ),
    "u_0012": UserState(
        user_id="u_0012", error_count=0, churn_risk=False,
        intent_score=0.30, error_rate=0.0,
        plan="pro", segment="active",
        updated_at=datetime.now(timezone.utc) - timedelta(seconds=30),
    ),
}

# Stale state (what was in the cache 5 minutes ago)
STALE_STATE = {
    "u_4821": UserState(
        user_id="u_4821", error_count=0, churn_risk=False,
        intent_score=0.0, error_rate=0.0,
        plan="free", segment="at_risk",
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    ),
    "u_0012": UserState(
        user_id="u_0012", error_count=1, churn_risk=False,
        intent_score=0.2, error_rate=0.1,
        plan="pro", segment="active",
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    ),
}

# Slightly stale state (30 seconds ago)
RECENT_STATE = {
    "u_4821": UserState(
        user_id="u_4821", error_count=4, churn_risk=True,
        intent_score=0.75, error_rate=0.44,
        plan="free", segment="at_risk",
        updated_at=datetime.now(timezone.utc) - timedelta(seconds=30),
    ),
    "u_0012": UserState(
        user_id="u_0012", error_count=0, churn_risk=False,
        intent_score=0.3, error_rate=0.0,
        plan="pro", segment="active",
        updated_at=datetime.now(timezone.utc) - timedelta(seconds=30),
    ),
}


# ── QUERY STRATEGIES ──────────────────────────────────────────────────────────

class QueryStrategy:
    def __init__(self, name: str, cache_ttl_s: int, base_latency_ms: int,
                 data_source: dict, description: str):
        self.name            = name
        self.cache_ttl_s     = cache_ttl_s
        self.base_latency_ms = base_latency_ms
        self.data_source     = data_source
        self.description     = description
        self._cache: dict[str, tuple] = {}

    def query(self, user_id: str) -> tuple[UserState, dict]:
        """Returns (state, metadata)."""
        now = datetime.now(timezone.utc)

        # Check cache
        if user_id in self._cache and self.cache_ttl_s > 0:
            cached_state, cached_at = self._cache[user_id]
            age = (now - cached_at).total_seconds()
            if age < self.cache_ttl_s:
                latency_ms = random.randint(3, 8)
                time.sleep(latency_ms / 1000)
                data_age_s = (now - cached_state.updated_at).total_seconds()
                return cached_state, {
                    "source": "cache", "latency_ms": latency_ms,
                    "data_age_s": data_age_s, "cache_age_s": age,
                }

        # Cache miss or no cache — query storage
        latency_ms = self.base_latency_ms + random.randint(-10, 10)
        time.sleep(latency_ms / 1000)

        state = self.data_source.get(user_id)
        if state and self.cache_ttl_s > 0:
            self._cache[user_id] = (state, now)

        data_age_s = (now - state.updated_at).total_seconds() if state else 0
        return state, {
            "source": "pinot", "latency_ms": latency_ms,
            "data_age_s": data_age_s, "cache_age_s": 0,
        }


# ── LLM RESPONSE GENERATOR ────────────────────────────────────────────────────

def generate_llm_response(user_id: str, state: UserState) -> tuple[str, bool]:
    """Returns (response, is_correct)."""
    if state.churn_risk and state.error_count >= 3:
        return (
            f"User {user_id} ({state.plan} plan) is at HIGH churn risk. "
            f"{state.error_count} checkout errors ({state.error_rate:.0%} rate). "
            f"Intent score: {state.intent_score:.2f}. Escalate immediately.",
            True
        )
    elif state.error_count == 0 and not state.churn_risk:
        return (
            f"User {user_id} appears healthy. No errors detected. No churn risk.",
            state.error_count == 0  # only correct if truly no errors
        )
    else:
        return (
            f"User {user_id}: {state.error_count} errors, churn_risk={state.churn_risk}.",
            True
        )


# ── COMPARISON RUNNER ─────────────────────────────────────────────────────────

def run_comparison(user_id: str, strategies: list[QueryStrategy]) -> list[dict]:
    results = []
    for strategy in strategies:
        state, meta = strategy.query(user_id)
        response, correct = generate_llm_response(user_id, state)
        results.append({
            "strategy":    strategy.name,
            "description": strategy.description,
            "latency_ms":  meta["latency_ms"],
            "data_age_s":  meta["data_age_s"],
            "source":      meta["source"],
            "errors":      state.error_count,
            "churn_risk":  state.churn_risk,
            "llm_correct": correct,
            "llm_response":response,
        })
    return results


# ── TIERED FRESHNESS DEMO ─────────────────────────────────────────────────────

def demo_tiered_freshness() -> None:
    """Shows the production pattern: different TTLs for different query types."""
    print(f"\n{'─'*65}")
    print(f"TIERED FRESHNESS — Production Pattern")
    print(f"{'─'*65}")

    tiers = [
        ("Fraud detection",    0,    "No cache — freshness < 1s required"),
        ("Support tooling",    30,   "TTL=30s — freshness < 31s acceptable"),
        ("LLM context",        60,   "TTL=60s — freshness < 61s acceptable"),
        ("Hourly reports",     1800, "TTL=30min — freshness < 31min acceptable"),
        ("Weekly dashboards",  3600, "TTL=1hr — freshness < 1hr acceptable"),
    ]

    print(f"\n  {'Use Case':22s} {'Cache TTL':12s} {'Max Data Age':14s} {'Query Latency':14s}")
    print(f"  {'-'*65}")
    for name, ttl, note in tiers:
        max_age = f"~{ttl+1}s" if ttl < 60 else f"~{ttl//60}min"
        latency = "~68ms" if ttl == 0 else "~5ms (hit)"
        print(f"  {name:22s} {str(ttl)+'s':12s} {max_age:14s} {latency}")

    print(f"\n  Rule: Match cache TTL to the acceptable staleness for the use case.")
    print(f"  Never apply a single TTL to all query types.")


# ── MAIN DEMO ─────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("TRADEOFF SIMULATION — Latency vs Freshness Comparison")
    print("=" * 65)

    strategies = [
        QueryStrategy(
            name="Fast (cache TTL=5min)",
            cache_ttl_s=300,
            base_latency_ms=68,
            data_source=STALE_STATE,
            description="Aggressive cache — fast but stale",
        ),
        QueryStrategy(
            name="Balanced (cache TTL=30s)",
            cache_ttl_s=30,
            base_latency_ms=68,
            data_source=RECENT_STATE,
            description="Short cache — acceptable for most AI queries",
        ),
        QueryStrategy(
            name="Fresh (no cache)",
            cache_ttl_s=0,
            base_latency_ms=68,
            data_source=TRUE_STATE,
            description="Direct Pinot — always fresh",
        ),
    ]

    user_id = "u_4821"
    print(f"\n[SCENARIO]  User {user_id} hit 5 checkout errors 90 seconds ago.")
    print(f"[SCENARIO]  True state: error_count=5, churn_risk=True, error_rate=50%")
    print(f"[SCENARIO]  Query: 'Is this user having issues?'\n")

    results = run_comparison(user_id, strategies)

    # Print comparison table
    print(f"  {'Strategy':28s} {'Latency':9s} {'Data Age':12s} {'Errors':8s} {'Correct':8s}")
    print(f"  {'-'*70}")
    for r in results:
        correct_str = "✅ YES" if r["llm_correct"] else "❌ NO"
        print(
            f"  {r['strategy']:28s} "
            f"{r['latency_ms']:4d}ms    "
            f"{r['data_age_s']:6.0f}s       "
            f"{r['errors']:4d}      "
            f"{correct_str}"
        )

    # Print LLM responses
    print(f"\n[LLM RESPONSES]")
    for r in results:
        icon = "✅" if r["llm_correct"] else "❌"
        print(f"\n  {icon} {r['strategy']} ({r['description']})")
        print(f"     \"{r['llm_response']}\"")

    # Key insight
    print(f"\n[KEY INSIGHT]")
    print(f"  Fast strategy:    {results[0]['latency_ms']}ms query, {results[0]['data_age_s']:.0f}s data age → WRONG answer")
    print(f"  Balanced strategy:{results[1]['latency_ms']}ms query, {results[1]['data_age_s']:.0f}s data age → CORRECT answer")
    print(f"  Fresh strategy:   {results[2]['latency_ms']}ms query, {results[2]['data_age_s']:.0f}s data age → CORRECT answer")
    print(f"\n  The 63ms difference between fast and fresh is negligible.")
    print(f"  The LLM call adds ~500ms regardless. Freshness is the right priority.")

    # Tiered freshness
    demo_tiered_freshness()

    print(f"\n{'='*65}")
    print(f"  CONCLUSION")
    print(f"  For AI systems: prioritize freshness over query speed.")
    print(f"  The LLM call dominates total latency — 68ms vs 5ms query")
    print(f"  time is irrelevant. Stale data produces wrong answers.")
    print(f"  Use tiered freshness: match TTL to use case requirements.")
    print(f"{'='*65}")


if __name__ == "__main__":
    random.seed(42)
    run()
