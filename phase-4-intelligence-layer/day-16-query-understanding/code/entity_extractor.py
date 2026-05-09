"""
Entity Extractor — Day 16: Query Understanding Layer
=====================================================
Extracts structured entities from a natural language query.

Entities extracted:
  user_id:      specific user reference (e.g., "u_4821")
  time_range_h: time window in hours
  plan_filter:  plan tier mentioned (free, pro, enterprise)
  segment:      user segment mentioned
  event_type:   type of event referenced
  risk_flag:    whether churn/risk is mentioned

In production: use spaCy NER, a fine-tuned model, or an LLM extraction call.
"""

import re
import time
from dataclasses import dataclass, field


# ── ENTITY RESULT ─────────────────────────────────────────────────────────────

@dataclass
class EntityResult:
    user_id:      str | None
    time_range_h: float
    plan_filter:  str | None
    segment:      str | None
    event_type:   str | None
    risk_flag:    bool
    raw_time_ref: str | None   # the original time phrase found
    latency_ms:   float


# ── TIME REFERENCE PATTERNS ───────────────────────────────────────────────────

TIME_PATTERNS: list[tuple[str, float]] = [
    # (regex pattern, hours)
    (r"last\s+(\d+)\s+second",   lambda m: int(m.group(1)) / 3600),
    (r"last\s+(\d+)\s+minute",   lambda m: int(m.group(1)) / 60),
    (r"last\s+(\d+)\s+hour",     lambda m: float(m.group(1))),
    (r"last\s+(\d+)\s+day",      lambda m: int(m.group(1)) * 24),
    (r"last\s+(\d+)\s+week",     lambda m: int(m.group(1)) * 168),
    (r"last\s+(\d+)\s+month",    lambda m: int(m.group(1)) * 720),
    (r"past\s+(\d+)\s+hour",     lambda m: float(m.group(1))),
    (r"past\s+(\d+)\s+day",      lambda m: int(m.group(1)) * 24),
    (r"in\s+the\s+last\s+(\d+)\s+hour", lambda m: float(m.group(1))),
    (r"in\s+the\s+last\s+(\d+)\s+day",  lambda m: int(m.group(1)) * 24),
    # Named time references
    (r"\bjust\s+now\b",          0.25),    # 15 minutes
    (r"\brecently\b",            2.0),
    (r"\btoday\b",               24.0),
    (r"\bthis\s+week\b",         168.0),
    (r"\bthis\s+month\b",        720.0),
    (r"\blast\s+week\b",         168.0),
    (r"\blast\s+month\b",        720.0),
    (r"\bthis\s+quarter\b",      2160.0),
    (r"\blast\s+quarter\b",      2160.0),
    (r"\bthis\s+year\b",         8760.0),
]

DEFAULT_TIME_H = 24.0  # default: last 24 hours


def extract_time_range(query: str) -> tuple[float, str | None]:
    """Returns (hours, raw_phrase_matched)."""
    q = query.lower()
    for pattern, value in TIME_PATTERNS:
        m = re.search(pattern, q)
        if m:
            hours = value(m) if callable(value) else value
            return round(hours, 2), m.group(0)
    return DEFAULT_TIME_H, None


# ── USER ID PATTERNS ──────────────────────────────────────────────────────────

USER_ID_PATTERN = re.compile(r"\bu_\d{4}\b")

def extract_user_id(query: str) -> str | None:
    match = USER_ID_PATTERN.search(query)
    return match.group(0) if match else None


# ── PLAN FILTER ───────────────────────────────────────────────────────────────

PLAN_KEYWORDS = {
    "free":       ["free plan", "free tier", "free users", "free-plan"],
    "pro":        ["pro plan", "pro tier", "pro users", "pro-plan"],
    "enterprise": ["enterprise plan", "enterprise tier", "enterprise users"],
}

def extract_plan(query: str) -> str | None:
    q = query.lower()
    for plan, keywords in PLAN_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            return plan
    return None


# ── SEGMENT FILTER ────────────────────────────────────────────────────────────

SEGMENT_KEYWORDS = {
    "at_risk":   ["at risk", "at-risk", "high risk", "churn risk"],
    "new_users": ["new users", "new user", "recently signed up", "onboarding"],
    "active":    ["active users", "engaged users", "power users"],
    "champion":  ["champion", "top users", "best customers"],
}

def extract_segment(query: str) -> str | None:
    q = query.lower()
    for segment, keywords in SEGMENT_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            return segment
    return None


# ── EVENT TYPE ────────────────────────────────────────────────────────────────

EVENT_TYPE_KEYWORDS = {
    "error":    ["error", "errors", "fail", "crash", "500", "exception"],
    "purchase": ["purchase", "bought", "payment", "checkout", "upgrade"],
    "session":  ["session", "visit", "page view", "browsing"],
    "login":    ["login", "sign in", "auth"],
}

def extract_event_type(query: str) -> str | None:
    q = query.lower()
    for etype, keywords in EVENT_TYPE_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            return etype
    return None


# ── RISK FLAG ─────────────────────────────────────────────────────────────────

RISK_KEYWORDS = ["at risk", "churn", "risk", "struggling", "frustrated", "cancel"]

def extract_risk_flag(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in RISK_KEYWORDS)


# ── MAIN EXTRACTOR ────────────────────────────────────────────────────────────

def extract_entities(query: str) -> EntityResult:
    """
    Extracts all structured entities from a natural language query.
    Returns an EntityResult with all extracted fields.
    """
    t0 = time.perf_counter()

    time_h, raw_time = extract_time_range(query)

    result = EntityResult(
        user_id=      extract_user_id(query),
        time_range_h= time_h,
        plan_filter=  extract_plan(query),
        segment=      extract_segment(query),
        event_type=   extract_event_type(query),
        risk_flag=    extract_risk_flag(query),
        raw_time_ref= raw_time,
        latency_ms=   round((time.perf_counter() - t0) * 1000, 2),
    )
    return result


# ── DEMO ──────────────────────────────────────────────────────────────────────

TEST_QUERIES = [
    "Show me all errors for user u_4821 in the last 2 hours",
    "Which free-plan users are most at risk this week?",
    "Who is most likely to upgrade to pro this month?",
    "How engaged are our new users in the last 7 days?",
    "What happened with user u_0012 recently?",
    "Show me enterprise users who purchased this quarter",
]

def run() -> None:
    print("=" * 65)
    print("ENTITY EXTRACTOR — Query Understanding Layer")
    print("=" * 65)

    for query in TEST_QUERIES:
        e = extract_entities(query)
        print(f"\n  Query:      \"{query}\"")
        print(f"  user_id:    {e.user_id or 'None (all users)'}")
        print(f"  time_range: {e.time_range_h}h  (from: '{e.raw_time_ref or 'default'}')")
        print(f"  plan:       {e.plan_filter or 'None'}")
        print(f"  segment:    {e.segment or 'None'}")
        print(f"  event_type: {e.event_type or 'None'}")
        print(f"  risk_flag:  {e.risk_flag}")
        print(f"  latency:    {e.latency_ms:.2f}ms")

    print(f"\n{'='*65}")
    print(f"  Entity extraction adds < 1ms overhead.")
    print(f"  Extracted entities drive Pinot filter construction.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
