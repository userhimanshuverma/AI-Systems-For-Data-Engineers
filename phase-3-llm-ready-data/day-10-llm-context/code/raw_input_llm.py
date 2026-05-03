"""
Raw Input LLM — Day 10: What LLMs Actually Need
=================================================
Demonstrates what happens when you pass raw structured data
directly to an LLM without context engineering.

This is the anti-pattern. The LLM receives:
  - A CSV/JSON dump of query results
  - All columns regardless of relevance
  - No natural language transformation
  - No context about what the numbers mean

The result: vague, low-confidence, non-actionable responses.
"""

import json
from datetime import datetime, timezone, timedelta


# ── SIMULATED PINOT QUERY RESULT ──────────────────────────────────────────────

def get_raw_pinot_result(user_id: str) -> list[dict]:
    """
    Simulates a raw Pinot query result:
    SELECT * FROM user_events WHERE user_id = 'u_4821' LIMIT 10
    Returns all columns, all rows — no filtering, no transformation.
    """
    now = datetime.now(timezone.utc)
    return [
        {
            "event_id":       "evt_a1b2c3",
            "schema_version": "1.0",
            "event_type":     "ui.page_view",
            "user_id":        user_id,
            "session_id":     "sess_9x8y7z",
            "ts":             (now - timedelta(minutes=15)).isoformat(),
            "page":           "/home",
            "error_code":     None,
            "plan":           "free",
            "country":        "US",
            "segment":        "at_risk",
            "lifetime_orders":0,
            "session_events": 1,
            "session_errors": 0,
            "pricing_visits": 0,
            "duration_s":     0,
            "error_rate":     0.0,
            "churn_risk":     False,
            "intent_score":   0.0,
            "is_high_value":  False,
        },
        {
            "event_id":       "evt_b2c3d4",
            "schema_version": "1.0",
            "event_type":     "ui.page_view",
            "user_id":        user_id,
            "session_id":     "sess_9x8y7z",
            "ts":             (now - timedelta(minutes=12)).isoformat(),
            "page":           "/pricing",
            "error_code":     None,
            "plan":           "free",
            "country":        "US",
            "segment":        "at_risk",
            "lifetime_orders":0,
            "session_events": 2,
            "session_errors": 0,
            "pricing_visits": 1,
            "duration_s":     180,
            "error_rate":     0.0,
            "churn_risk":     False,
            "intent_score":   0.25,
            "is_high_value":  False,
        },
        {
            "event_id":       "evt_c3d4e5",
            "schema_version": "1.0",
            "event_type":     "system.server_error",
            "user_id":        user_id,
            "session_id":     "sess_9x8y7z",
            "ts":             (now - timedelta(minutes=10)).isoformat(),
            "page":           "/checkout",
            "error_code":     500,
            "plan":           "free",
            "country":        "US",
            "segment":        "at_risk",
            "lifetime_orders":0,
            "session_events": 3,
            "session_errors": 1,
            "pricing_visits": 1,
            "duration_s":     300,
            "error_rate":     0.33,
            "churn_risk":     False,
            "intent_score":   0.25,
            "is_high_value":  False,
        },
        {
            "event_id":       "evt_d4e5f6",
            "schema_version": "1.0",
            "event_type":     "ui.page_view",
            "user_id":        user_id,
            "session_id":     "sess_9x8y7z",
            "ts":             (now - timedelta(minutes=8)).isoformat(),
            "page":           "/pricing",
            "error_code":     None,
            "plan":           "free",
            "country":        "US",
            "segment":        "at_risk",
            "lifetime_orders":0,
            "session_events": 4,
            "session_errors": 1,
            "pricing_visits": 2,
            "duration_s":     420,
            "error_rate":     0.25,
            "churn_risk":     False,
            "intent_score":   0.50,
            "is_high_value":  False,
        },
        {
            "event_id":       "evt_e5f6g7",
            "schema_version": "1.0",
            "event_type":     "system.server_error",
            "user_id":        user_id,
            "session_id":     "sess_9x8y7z",
            "ts":             (now - timedelta(minutes=6)).isoformat(),
            "page":           "/checkout",
            "error_code":     500,
            "plan":           "free",
            "country":        "US",
            "segment":        "at_risk",
            "lifetime_orders":0,
            "session_events": 5,
            "session_errors": 2,
            "pricing_visits": 2,
            "duration_s":     540,
            "error_rate":     0.40,
            "churn_risk":     True,
            "intent_score":   0.50,
            "is_high_value":  False,
        },
    ]


# ── RAW INPUT FORMATTER ───────────────────────────────────────────────────────

def format_as_csv(rows: list[dict]) -> str:
    """Formats rows as CSV — the most common anti-pattern."""
    if not rows:
        return ""
    headers = ",".join(rows[0].keys())
    data_rows = "\n".join(",".join(str(v) for v in row.values()) for row in rows)
    return f"{headers}\n{data_rows}"

def format_as_json(rows: list[dict]) -> str:
    """Formats rows as JSON array — slightly better but still raw."""
    return json.dumps(rows, indent=2, default=str)

def count_tokens_approx(text: str) -> int:
    """Approximates token count: ~4 chars per token."""
    return len(text) // 4


# ── MOCK LLM (simulates poor response from raw input) ────────────────────────

def mock_llm_raw(query: str, raw_input: str, format_type: str) -> dict:
    """
    Simulates an LLM response when given raw structured data.
    The response is technically correct but lacks synthesis and actionability.
    """
    # LLM can parse the data but produces shallow analysis
    return {
        "response": (
            f"Based on the {format_type} data provided, user u_4821 has experienced "
            f"server errors on the /checkout page with error code 500. "
            f"The churn_risk field is set to true in some records. "
            f"The user has visited the /pricing page. "
            f"The error_rate value increases across records."
        ),
        "issues": [
            "No synthesis — just restates field values",
            "No recommendation — doesn't say what to do",
            "No confidence — doesn't quantify certainty",
            "No prioritization — treats all signals equally",
            "Mentions field names (churn_risk, error_rate) — not natural language",
        ],
        "token_count": count_tokens_approx(raw_input),
        "quality": "POOR",
    }


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("RAW INPUT LLM — Anti-pattern: passing raw data to LLM")
    print("=" * 65)

    user_id = "u_4821"
    rows    = get_raw_pinot_result(user_id)
    query   = "Why is this user at risk of churning?"

    print(f"\n[QUERY]  \"{query}\"")
    print(f"[DATA]   {len(rows)} rows from Pinot, {len(rows[0])} columns each\n")

    # Approach 1: CSV dump
    csv_input = format_as_csv(rows)
    csv_tokens = count_tokens_approx(csv_input)
    print(f"[APPROACH 1]  CSV dump to LLM")
    print(f"  Input size: {len(csv_input)} chars (~{csv_tokens} tokens)")
    print(f"  First 200 chars: {csv_input[:200]}...")
    result = mock_llm_raw(query, csv_input, "CSV")
    print(f"\n  LLM Response:")
    print(f"  \"{result['response']}\"")
    print(f"\n  Problems:")
    for issue in result["issues"]:
        print(f"    ❌ {issue}")

    # Approach 2: JSON dump
    json_input = format_as_json(rows)
    json_tokens = count_tokens_approx(json_input)
    print(f"\n[APPROACH 2]  JSON dump to LLM")
    print(f"  Input size: {len(json_input)} chars (~{json_tokens} tokens)")
    result = mock_llm_raw(query, json_input, "JSON")
    print(f"\n  LLM Response:")
    print(f"  \"{result['response']}\"")
    print(f"\n  Problems:")
    for issue in result["issues"]:
        print(f"    ❌ {issue}")

    print(f"\n{'='*65}")
    print(f"  SUMMARY: Raw Input Anti-Pattern")
    print(f"  CSV tokens:  ~{csv_tokens}  |  JSON tokens: ~{json_tokens}")
    print(f"  LLM quality: POOR — technically correct, completely useless")
    print(f"  Root cause:  LLMs need context, not data dumps")
    print(f"  Solution:    Run context_builder.py to see the right approach")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
