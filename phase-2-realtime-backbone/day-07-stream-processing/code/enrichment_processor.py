"""
Enrichment Processor — Day 07: Stream Processing
==================================================
Simulates a Flink stream processing job that enriches raw events
with three types of context before they reach storage:

  1. Static enrichment  — user profile from a lookup store (Redis)
  2. Behavioral enrichment — session state (event count, errors, pages)
  3. Derived features   — computed signals (error rate, churn flag, intent score)

This is the core of the enrichment layer. In production, this logic
runs inside a Flink KeyedProcessFunction, keyed by session_id.

Run this after raw_stream.py to see the transformation.
"""

from collections import defaultdict
from datetime import datetime, timezone


# ── STATIC LOOKUP STORE (simulates Redis) ─────────────────────────────────────

USER_PROFILES = {
    "u_4821": {"plan": "free",       "country": "US", "segment": "at_risk",  "lifetime_orders": 0},
    "u_0012": {"plan": "pro",        "country": "UK", "segment": "active",   "lifetime_orders": 4},
    "u_7734": {"plan": "free",       "country": "DE", "segment": "new",      "lifetime_orders": 0},
    "u_9901": {"plan": "enterprise", "country": "SG", "segment": "champion", "lifetime_orders": 18},
}

def redis_get_user(user_id: str) -> dict:
    """
    Simulates Redis GET user:{user_id}.
    In production: redis_client.hgetall(f"user:{user_id}")
    Latency target: < 5ms
    """
    return USER_PROFILES.get(user_id, {
        "plan": "unknown", "country": "?", "segment": "unknown", "lifetime_orders": 0
    })


# ── SESSION STATE (simulates Flink per-key state) ─────────────────────────────

class SessionState:
    """
    Maintains per-session state across events.
    In production: Flink ValueState / MapState backed by RocksDB.
    Keyed by session_id — all events for a session go to the same operator.
    """
    def __init__(self):
        self._state: dict[str, dict] = defaultdict(lambda: {
            "event_count":    0,
            "error_count":    0,
            "pricing_visits": 0,
            "pages_visited":  [],
            "start_ts":       None,
            "last_ts":        None,
        })

    def update(self, session_id: str, event: dict) -> dict:
        s = self._state[session_id]
        ts = event["ts"]

        # Initialize session start time
        if s["start_ts"] is None:
            s["start_ts"] = ts

        s["last_ts"]      = ts
        s["event_count"] += 1

        etype = event["event_type"]
        page  = event.get("context", {}).get("page", "")

        if "error" in etype:
            s["error_count"] += 1

        if page and page not in s["pages_visited"]:
            s["pages_visited"].append(page)

        if page == "/pricing":
            s["pricing_visits"] += 1

        # Approximate session duration (seconds between first and last event)
        # In production: use event-time watermarks for accurate duration
        s["duration_s"] = len(s["pages_visited"]) * 45  # rough approximation

        return dict(s)  # return a copy


# ── DERIVED FEATURE COMPUTATION ───────────────────────────────────────────────

def compute_derived_features(profile: dict, session: dict) -> dict:
    """
    Computes higher-level signals from static profile + session state.
    These are the features the LLM uses to make specific, confident statements.
    """
    event_count = max(session["event_count"], 1)
    error_count = session["error_count"]
    error_rate  = round(error_count / event_count, 3)

    # Churn risk: high error rate on free plan
    churn_risk = (
        error_rate >= 0.25
        and profile.get("plan") == "free"
    )

    # Upgrade intent: pricing page visits + segment signal
    pricing_visits = session["pricing_visits"]
    intent_base    = min(pricing_visits * 0.25, 0.75)
    intent_bonus   = 0.15 if profile.get("segment") == "at_risk" else 0.0
    intent_score   = round(min(intent_base + intent_bonus, 1.0), 2)

    # High-value session: experienced user with long session
    is_high_value = (
        profile.get("lifetime_orders", 0) > 2
        and session["duration_s"] > 300
    )

    return {
        "error_rate":      error_rate,
        "churn_risk":      churn_risk,
        "intent_score":    intent_score,
        "is_high_value":   is_high_value,
    }


# ── ENRICHMENT OPERATOR ───────────────────────────────────────────────────────

class EnrichmentOperator:
    """
    Simulates a Flink KeyedProcessFunction.
    Applies all three enrichment types to each incoming event.
    """
    def __init__(self):
        self.session_state = SessionState()

    def process(self, raw_event: dict) -> dict:
        uid        = raw_event["user_id"]
        session_id = raw_event["session_id"]

        # Step 1: Static enrichment
        profile = redis_get_user(uid)

        # Step 2: Session state update
        session = self.session_state.update(session_id, raw_event)

        # Step 3: Derived features
        derived = compute_derived_features(profile, session)

        # Assemble enriched event
        return {
            **raw_event,
            "user_profile":  profile,
            "session_state": {
                "event_count":    session["event_count"],
                "error_count":    session["error_count"],
                "pricing_visits": session["pricing_visits"],
                "pages_visited":  session["pages_visited"],
                "duration_s":     session["duration_s"],
            },
            "derived_features": derived,
        }


# ── EVENT → TEXT (for embedding) ──────────────────────────────────────────────

def event_to_text_enriched(event: dict) -> str:
    """
    Converts an enriched event to a rich natural language description.
    This is what gets embedded and stored in the vector store.
    """
    uid     = event["user_id"]
    etype   = event["event_type"]
    ts      = event["ts"][:16].replace("T", " ")
    ctx     = event.get("context", {})
    profile = event.get("user_profile", {})
    session = event.get("session_state", {})
    derived = event.get("derived_features", {})

    text = (
        f"User {uid} ({profile.get('plan','?')} plan, {profile.get('country','?')}, "
        f"segment={profile.get('segment','?')}) performed '{etype}' at {ts} UTC."
    )
    if ctx.get("page"):
        text += f" Page: {ctx['page']}."
    if ctx.get("error_code"):
        text += f" Error {ctx['error_code']}."
    if session.get("event_count"):
        text += (
            f" Session: {session['event_count']} events, "
            f"{session['error_count']} errors "
            f"({derived.get('error_rate',0):.0%} error rate), "
            f"/pricing visited {session['pricing_visits']}x."
        )
    if derived.get("churn_risk"):
        text += " Churn risk: TRUE."
    if derived.get("intent_score", 0) > 0.5:
        text += f" Upgrade intent score: {derived['intent_score']}."

    return text


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run(events: list[dict] | None = None) -> list[dict]:
    """
    Processes a list of raw events through the enrichment pipeline.
    Returns the list of enriched events.
    """
    if events is None:
        # Import raw stream if not provided
        import sys, os
        sys.path.insert(0, os.path.dirname(__file__))
        from raw_stream import generate_raw_stream
        events = generate_raw_stream("u_4821")

    print("=" * 65)
    print("ENRICHMENT PROCESSOR — Adding context to raw events")
    print("=" * 65)

    operator = EnrichmentOperator()
    enriched_events = []

    print(f"\n[FLINK]  Processing {len(events)} events through enrichment operator\n")

    for i, raw in enumerate(events):
        enriched = operator.process(raw)
        enriched_events.append(enriched)

        derived  = enriched["derived_features"]
        session  = enriched["session_state"]
        profile  = enriched["user_profile"]

        alert = " ⚠️  CHURN RISK" if derived["churn_risk"] else ""
        print(
            f"  [{i+1:02d}] {raw['event_type']:30s}  "
            f"errors={session['error_count']}/{session['event_count']}  "
            f"rate={derived['error_rate']:.0%}  "
            f"intent={derived['intent_score']:.2f}"
            f"{alert}"
        )

    print(f"\n[ENRICHMENT]  Static fields added:    plan, country, segment, lifetime_orders")
    print(f"[ENRICHMENT]  Session fields added:   event_count, error_count, pricing_visits, duration_s")
    print(f"[ENRICHMENT]  Derived fields added:   error_rate, churn_risk, intent_score, is_high_value")

    print(f"\n[EMBEDDING TEXT]  Sample enriched texts:")
    for e in enriched_events[3:6]:  # show the interesting ones
        print(f"  \"{event_to_text_enriched(e)}\"")
        print()

    return enriched_events


if __name__ == "__main__":
    run()
