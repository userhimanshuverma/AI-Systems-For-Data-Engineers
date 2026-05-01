"""
Pinot Query Simulation — Day 08: Real-Time Analytics with Pinot
================================================================
Simulates Apache Pinot's query execution against enriched event data.
Demonstrates the 5 key query patterns used in AI data systems.

In production: queries go to the Pinot Broker via HTTP:
    import requests
    resp = requests.post(
        "http://localhost:8099/query/sql",
        json={"sql": query_string}
    )
    result = resp.json()

Here we simulate the same queries against an in-memory dataset
to demonstrate the patterns without requiring a running Pinot cluster.
"""

import time
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from data_stream_simulator import generate_stream


# ── IN-MEMORY PINOT SIMULATION ────────────────────────────────────────────────

class PinotTable:
    """
    Simulates a Pinot real-time table.
    Supports the query patterns used in AI data systems.
    In production: replace all methods with HTTP calls to Pinot Broker.
    """
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self._name = "user_events_realtime"

    def _parse_ago(self, ago_str: str) -> datetime:
        """Parses Pinot's ago() function: ago('1h'), ago('10m'), ago('7d')"""
        now = datetime.now(timezone.utc)
        val = int(ago_str[:-1])
        unit = ago_str[-1]
        if unit == 's': return now - timedelta(seconds=val)
        if unit == 'm': return now - timedelta(minutes=val)
        if unit == 'h': return now - timedelta(hours=val)
        if unit == 'd': return now - timedelta(days=val)
        return now

    def _filter_time(self, rows, ago_str):
        cutoff = self._parse_ago(ago_str)
        return [r for r in rows if datetime.fromisoformat(r["ts"]) >= cutoff]

    def query(self, sql: str, latency_ms: int = None) -> dict:
        """Executes a simulated Pinot query and returns results with metadata."""
        t0 = time.time()
        # Simulate Pinot's sub-second latency
        time.sleep((latency_ms or 68) / 1000)
        elapsed = int((time.time() - t0) * 1000)
        return {"sql": sql, "latency_ms": elapsed, "rows": []}

    # ── QUERY 1: Real-time error monitoring ──────────────────────────────────

    def q_error_monitoring(self, ago_str: str = "2h") -> list[dict]:
        """
        SELECT user_id, COUNT(*) as error_count
        FROM user_events_realtime
        WHERE event_type = 'system.server_error' AND ts > ago('2h')
        GROUP BY user_id ORDER BY error_count DESC LIMIT 10
        """
        rows = self._filter_time(self._rows, ago_str)
        rows = [r for r in rows if r["event_type"] == "system.server_error"]

        counts: dict[str, int] = {}
        for r in rows:
            counts[r["user_id"]] = counts.get(r["user_id"], 0) + 1

        result = [{"user_id": k, "error_count": v} for k, v in counts.items()]
        return sorted(result, key=lambda x: x["error_count"], reverse=True)[:10]

    # ── QUERY 2: Churn risk detection ────────────────────────────────────────

    def q_churn_risk(self, ago_str: str = "2h") -> list[dict]:
        """
        SELECT user_id, error_rate, intent_score, session_errors, plan
        FROM user_events_realtime
        WHERE churn_risk = true AND ts > ago('2h')
        ORDER BY error_rate DESC LIMIT 20
        """
        rows = self._filter_time(self._rows, ago_str)
        rows = [r for r in rows if r["churn_risk"]]

        # Deduplicate: take latest row per user
        seen: dict[str, dict] = {}
        for r in rows:
            uid = r["user_id"]
            if uid not in seen or r["ts"] > seen[uid]["ts"]:
                seen[uid] = r

        result = [
            {
                "user_id":       r["user_id"],
                "error_rate":    r["error_rate"],
                "intent_score":  r["intent_score"],
                "session_errors":r["session_errors"],
                "plan":          r["plan"],
            }
            for r in seen.values()
        ]
        return sorted(result, key=lambda x: x["error_rate"], reverse=True)[:20]

    # ── QUERY 3: Upgrade intent detection ────────────────────────────────────

    def q_upgrade_intent(self, min_score: float = 0.5, ago_str: str = "2h") -> list[dict]:
        """
        SELECT user_id, pricing_visits, intent_score, plan
        FROM user_events_realtime
        WHERE intent_score > 0.5 AND plan = 'free' AND ts > ago('2h')
        ORDER BY intent_score DESC LIMIT 10
        """
        rows = self._filter_time(self._rows, ago_str)
        rows = [r for r in rows if r["intent_score"] > min_score and r["plan"] == "free"]

        seen: dict[str, dict] = {}
        for r in rows:
            uid = r["user_id"]
            if uid not in seen or r["intent_score"] > seen[uid]["intent_score"]:
                seen[uid] = r

        result = [
            {
                "user_id":       r["user_id"],
                "pricing_visits":r["pricing_visits"],
                "intent_score":  r["intent_score"],
                "plan":          r["plan"],
            }
            for r in seen.values()
        ]
        return sorted(result, key=lambda x: x["intent_score"], reverse=True)[:10]

    # ── QUERY 4: User session summary (LLM context) ───────────────────────────

    def q_user_summary(self, user_id: str, ago_str: str = "7d") -> dict:
        """
        SELECT user_id, MAX(session_errors), MAX(error_rate),
               MAX(pricing_visits), MAX(intent_score), plan, segment
        FROM user_events_realtime
        WHERE user_id = 'u_4821' AND ts > ago('7d')
        GROUP BY user_id, plan, segment
        """
        rows = self._filter_time(self._rows, ago_str)
        rows = [r for r in rows if r["user_id"] == user_id]

        if not rows:
            return {}

        return {
            "user_id":        user_id,
            "plan":           rows[0]["plan"],
            "segment":        rows[0]["segment"],
            "country":        rows[0]["country"],
            "total_events":   len(rows),
            "max_errors":     max(r["session_errors"] for r in rows),
            "max_error_rate": max(r["error_rate"] for r in rows),
            "max_pricing_visits": max(r["pricing_visits"] for r in rows),
            "max_intent_score":   max(r["intent_score"] for r in rows),
            "churn_risk":     any(r["churn_risk"] for r in rows),
        }

    # ── QUERY 5: Page error funnel ────────────────────────────────────────────

    def q_page_errors(self, ago_str: str = "2h") -> list[dict]:
        """
        SELECT page, COUNT(*) as errors, COUNT(DISTINCT user_id) as affected_users
        FROM user_events_realtime
        WHERE event_type = 'system.server_error' AND ts > ago('2h')
        GROUP BY page ORDER BY errors DESC
        """
        rows = self._filter_time(self._rows, ago_str)
        rows = [r for r in rows if r["event_type"] == "system.server_error"]

        pages: dict[str, dict] = {}
        for r in rows:
            p = r["page"]
            if p not in pages:
                pages[p] = {"errors": 0, "users": set()}
            pages[p]["errors"] += 1
            pages[p]["users"].add(r["user_id"])

        result = [
            {"page": p, "errors": v["errors"], "affected_users": len(v["users"])}
            for p, v in pages.items()
        ]
        return sorted(result, key=lambda x: x["errors"], reverse=True)


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("PINOT QUERY SIMULATION — Sub-second analytics on fresh data")
    print("=" * 65)

    rows  = generate_stream(n_events=60, seed=42)
    pinot = PinotTable(rows)

    # Query 1: Error monitoring
    print(f"\n[QUERY 1]  Real-time error monitoring (last 2h)")
    print(f"  SQL: SELECT user_id, COUNT(*) as error_count")
    print(f"       FROM user_events_realtime")
    print(f"       WHERE event_type='system.server_error' AND ts > ago('2h')")
    print(f"       GROUP BY user_id ORDER BY error_count DESC LIMIT 10")
    t0 = time.time()
    result = pinot.q_error_monitoring("2h")
    ms = int((time.time() - t0) * 1000)
    print(f"  → {len(result)} users with errors | Latency: ~{ms}ms (simulated: 68ms)")
    for r in result[:5]:
        print(f"    {r['user_id']}: {r['error_count']} errors")

    # Query 2: Churn risk
    print(f"\n[QUERY 2]  Users at churn risk (last 2h)")
    print(f"  SQL: SELECT user_id, error_rate, intent_score")
    print(f"       FROM user_events_realtime")
    print(f"       WHERE churn_risk = true AND ts > ago('2h')")
    t0 = time.time()
    result = pinot.q_churn_risk("2h")
    ms = int((time.time() - t0) * 1000)
    print(f"  → {len(result)} at-risk users | Latency: ~{ms}ms")
    for r in result:
        print(f"    {r['user_id']} ({r['plan']:6s}): error_rate={r['error_rate']:.0%}  intent={r['intent_score']:.2f}")

    # Query 3: Upgrade intent
    print(f"\n[QUERY 3]  Free users with upgrade intent (last 2h)")
    print(f"  SQL: SELECT user_id, pricing_visits, intent_score")
    print(f"       FROM user_events_realtime")
    print(f"       WHERE intent_score > 0.5 AND plan = 'free' AND ts > ago('2h')")
    t0 = time.time()
    result = pinot.q_upgrade_intent(0.5, "2h")
    ms = int((time.time() - t0) * 1000)
    print(f"  → {len(result)} users with upgrade intent | Latency: ~{ms}ms")
    for r in result:
        print(f"    {r['user_id']}: pricing_visits={r['pricing_visits']}  intent={r['intent_score']:.2f}")

    # Query 4: User summary for LLM
    print(f"\n[QUERY 4]  User session summary for LLM context (u_4821, last 7d)")
    print(f"  SQL: SELECT MAX(session_errors), MAX(error_rate), MAX(intent_score)")
    print(f"       FROM user_events_realtime")
    print(f"       WHERE user_id = 'u_4821' AND ts > ago('7d')")
    t0 = time.time()
    summary = pinot.q_user_summary("u_4821", "7d")
    ms = int((time.time() - t0) * 1000)
    print(f"  → Latency: ~{ms}ms")
    for k, v in summary.items():
        print(f"    {k}: {v}")

    # Query 5: Page errors
    print(f"\n[QUERY 5]  Error funnel by page (last 2h)")
    print(f"  SQL: SELECT page, COUNT(*) as errors, COUNT(DISTINCT user_id)")
    print(f"       FROM user_events_realtime")
    print(f"       WHERE event_type='system.server_error' AND ts > ago('2h')")
    t0 = time.time()
    result = pinot.q_page_errors("2h")
    ms = int((time.time() - t0) * 1000)
    print(f"  → {len(result)} pages with errors | Latency: ~{ms}ms")
    for r in result:
        print(f"    {r['page']:20s}: {r['errors']} errors, {r['affected_users']} users")

    print(f"\n{'='*65}")
    print(f"  All 5 queries completed")
    print(f"  In production: same queries run against real Pinot cluster")
    print(f"  Pinot Broker: http://localhost:8099/query/sql")
    print(f"  Pinot UI:     http://localhost:9000")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
