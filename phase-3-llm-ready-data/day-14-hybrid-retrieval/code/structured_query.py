"""
Structured Query — Day 14: Hybrid Retrieval
=============================================
Simulates Apache Pinot structured queries for the hybrid retrieval layer.

Pinot's role: answer "what" and "how much" questions with exact, computable
answers. Error counts, rates, flags, aggregations, time-window analysis.

In production: HTTP POST to Pinot Broker:
    import requests
    resp = requests.post(
        "http://localhost:8099/query/sql",
        json={"sql": query_string}
    )
    result = resp.json()["resultTable"]["rows"]
"""

import random
from datetime import datetime, timezone, timedelta


# ── SIMULATED PINOT DATA ──────────────────────────────────────────────────────

PINOT_TABLE = [
    # u_4821 — at-risk free user with checkout errors
    {"user_id":"u_4821","event_type":"system.server_error","ts_offset_h":0.5,
     "plan":"free","segment":"at_risk","error_rate":0.50,"churn_risk":True,
     "intent_score":0.82,"pricing_visits":3,"session_errors":5,"page":"/checkout"},
    {"user_id":"u_4821","event_type":"ui.button_click","ts_offset_h":0.8,
     "plan":"free","segment":"at_risk","error_rate":0.50,"churn_risk":True,
     "intent_score":0.82,"pricing_visits":3,"session_errors":5,"page":"/pricing"},
    {"user_id":"u_4821","event_type":"ui.page_view","ts_offset_h":1.2,
     "plan":"free","segment":"at_risk","error_rate":0.50,"churn_risk":True,
     "intent_score":0.82,"pricing_visits":3,"session_errors":5,"page":"/home"},
    # u_0012 — healthy pro user
    {"user_id":"u_0012","event_type":"commerce.purchase","ts_offset_h":0.3,
     "plan":"pro","segment":"active","error_rate":0.0,"churn_risk":False,
     "intent_score":0.3,"pricing_visits":1,"session_errors":0,"page":"/checkout"},
    {"user_id":"u_0012","event_type":"ui.page_view","ts_offset_h":0.6,
     "plan":"pro","segment":"active","error_rate":0.0,"churn_risk":False,
     "intent_score":0.3,"pricing_visits":1,"session_errors":0,"page":"/docs"},
    # u_7734 — new free user, moderate risk
    {"user_id":"u_7734","event_type":"system.server_error","ts_offset_h":0.2,
     "plan":"free","segment":"new","error_rate":0.33,"churn_risk":True,
     "intent_score":0.40,"pricing_visits":2,"session_errors":2,"page":"/checkout"},
    {"user_id":"u_7734","event_type":"ui.page_view","ts_offset_h":0.4,
     "plan":"free","segment":"new","error_rate":0.33,"churn_risk":True,
     "intent_score":0.40,"pricing_visits":2,"session_errors":2,"page":"/pricing"},
    # u_9901 — enterprise champion
    {"user_id":"u_9901","event_type":"commerce.purchase","ts_offset_h":0.1,
     "plan":"enterprise","segment":"champion","error_rate":0.0,"churn_risk":False,
     "intent_score":0.1,"pricing_visits":0,"session_errors":0,"page":"/checkout"},
]

def _get_rows(hours_back: float = 7*24) -> list[dict]:
    """Returns rows within the time window."""
    return [r for r in PINOT_TABLE if r["ts_offset_h"] <= hours_back]


# ── QUERY FUNCTIONS ───────────────────────────────────────────────────────────

def query_user_metrics(user_id: str, hours_back: float = 7*24) -> dict | None:
    """
    SELECT user_id, MAX(error_rate), MAX(intent_score), BOOL_OR(churn_risk),
           MAX(pricing_visits), MAX(session_errors), plan, segment
    FROM user_events_realtime
    WHERE user_id = :uid AND ts > ago(:hours_back)
    GROUP BY user_id, plan, segment
    """
    rows = [r for r in _get_rows(hours_back) if r["user_id"] == user_id]
    if not rows:
        return None
    return {
        "user_id":        user_id,
        "plan":           rows[0]["plan"],
        "segment":        rows[0]["segment"],
        "error_rate":     max(r["error_rate"] for r in rows),
        "intent_score":   max(r["intent_score"] for r in rows),
        "churn_risk":     any(r["churn_risk"] for r in rows),
        "pricing_visits": max(r["pricing_visits"] for r in rows),
        "session_errors": max(r["session_errors"] for r in rows),
        "total_events":   len(rows),
    }

def query_at_risk_users(hours_back: float = 24, limit: int = 10) -> list[dict]:
    """
    SELECT user_id, MAX(error_rate) AS error_rate, MAX(intent_score) AS intent
    FROM user_events_realtime
    WHERE churn_risk = true AND ts > ago(:hours_back)
    GROUP BY user_id
    ORDER BY error_rate DESC
    LIMIT :limit
    """
    rows = [r for r in _get_rows(hours_back) if r["churn_risk"]]
    # Aggregate per user
    by_user: dict[str, dict] = {}
    for r in rows:
        uid = r["user_id"]
        if uid not in by_user or r["error_rate"] > by_user[uid]["error_rate"]:
            by_user[uid] = {
                "user_id":      uid,
                "plan":         r["plan"],
                "error_rate":   r["error_rate"],
                "intent_score": r["intent_score"],
                "session_errors": r["session_errors"],
            }
    return sorted(by_user.values(), key=lambda x: x["error_rate"], reverse=True)[:limit]

def query_error_funnel(hours_back: float = 1) -> list[dict]:
    """
    SELECT page, COUNT(*) AS errors, COUNT(DISTINCT user_id) AS affected_users
    FROM user_events_realtime
    WHERE event_type = 'system.server_error' AND ts > ago(:hours_back)
    GROUP BY page ORDER BY errors DESC
    """
    rows = [r for r in _get_rows(hours_back) if r["event_type"] == "system.server_error"]
    pages: dict[str, dict] = {}
    for r in rows:
        p = r["page"]
        if p not in pages:
            pages[p] = {"page": p, "errors": 0, "users": set()}
        pages[p]["errors"] += 1
        pages[p]["users"].add(r["user_id"])
    result = [{"page": p, "errors": v["errors"], "affected_users": len(v["users"])}
              for p, v in pages.items()]
    return sorted(result, key=lambda x: x["errors"], reverse=True)

def query_upgrade_intent(min_intent: float = 0.5, plan: str = "free") -> list[dict]:
    """
    SELECT user_id, MAX(intent_score), MAX(pricing_visits)
    FROM user_events_realtime
    WHERE intent_score > :min_intent AND plan = :plan
    GROUP BY user_id ORDER BY intent_score DESC
    """
    rows = [r for r in _get_rows() if r["intent_score"] > min_intent and r["plan"] == plan]
    by_user: dict[str, dict] = {}
    for r in rows:
        uid = r["user_id"]
        if uid not in by_user or r["intent_score"] > by_user[uid]["intent_score"]:
            by_user[uid] = {
                "user_id":       uid,
                "intent_score":  r["intent_score"],
                "pricing_visits":r["pricing_visits"],
                "plan":          r["plan"],
            }
    return sorted(by_user.values(), key=lambda x: x["intent_score"], reverse=True)


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("STRUCTURED QUERY — Apache Pinot simulation")
    print("=" * 65)

    print(f"\n[QUERY 1]  User metrics for u_4821 (last 7 days)")
    metrics = query_user_metrics("u_4821")
    if metrics:
        for k, v in metrics.items():
            print(f"  {k}: {v}")

    print(f"\n[QUERY 2]  At-risk users (last 24h)")
    at_risk = query_at_risk_users(hours_back=24)
    print(f"  {'user_id':8s} {'plan':6s} {'error_rate':12s} {'intent':8s} {'errors':6s}")
    print(f"  {'-'*45}")
    for r in at_risk:
        print(f"  {r['user_id']:8s} {r['plan']:6s} {r['error_rate']:12.0%} "
              f"{r['intent_score']:8.2f} {r['session_errors']:6d}")

    print(f"\n[QUERY 3]  Error funnel by page (last 1h)")
    funnel = query_error_funnel(hours_back=1)
    for r in funnel:
        print(f"  {r['page']:20s}: {r['errors']} errors, {r['affected_users']} users")

    print(f"\n[QUERY 4]  Free users with upgrade intent > 0.5")
    intent_users = query_upgrade_intent(min_intent=0.5, plan="free")
    for r in intent_users:
        print(f"  {r['user_id']}: intent={r['intent_score']:.2f}, "
              f"pricing_visits={r['pricing_visits']}")

    print(f"\n[PINOT ROLE]")
    print(f"  ✅ Answers: how many, what rate, which users, time windows")
    print(f"  ❌ Cannot: find behavioral narratives, match unstructured text")
    print(f"  → Pair with vector DB for complete hybrid retrieval")


if __name__ == "__main__":
    run()
