"""
LLM Simulation — Day 10: What LLMs Actually Need
==================================================
Side-by-side comparison of LLM output quality:
  1. Raw input (CSV/JSON dump) → poor response
  2. Context-engineered input  → actionable response

Also demonstrates:
  - Output format specification (JSON mode)
  - Multi-query routing (different intents, different context)
  - Token efficiency comparison

Run this to see the full before/after comparison.
"""

import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from raw_input_llm import get_raw_pinot_result, format_as_csv, count_tokens_approx
from context_builder import ContextBuilder, detect_intent


# ── MOCK LLM ──────────────────────────────────────────────────────────────────

def mock_llm(system_prompt: str, user_message: str, intent: str) -> dict:
    """
    Mocks an LLM API call.

    In production:
        from openai import OpenAI
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ]
        )
        return json.loads(response.choices[0].message.content)
    """
    # Simulate different response quality based on input quality
    if "Context about user" in user_message and "Recent activity" in user_message:
        # Context-engineered input → high quality response
        return _high_quality_response(user_message, intent)
    else:
        # Raw input → low quality response
        return _low_quality_response(user_message)


def _low_quality_response(raw_input: str) -> dict:
    """Simulates LLM response to raw structured data."""
    return {
        "summary":    "The user has experienced server errors on the checkout page. "
                      "The churn_risk field is set to true in some records. "
                      "The user has visited the pricing page.",
        "action":     "investigate",
        "confidence": 0.45,
        "evidence":   [
            "churn_risk = true in records",
            "error_code = 500 present",
            "pricing page visits detected",
        ],
        "_quality": "POOR",
        "_issues": [
            "Restates field names instead of interpreting them",
            "No synthesis across events",
            "Low confidence — model uncertain about raw data",
            "Generic action — 'investigate' is not actionable",
            "Evidence cites field names, not behavioral insights",
        ],
    }


def _high_quality_response(context: str, intent: str) -> dict:
    """Simulates LLM response to context-engineered input."""
    if intent == "churn_investigation":
        return {
            "summary":    "User u_4821 is at high churn risk due to repeated checkout "
                          "failures blocking a clear upgrade intent. They attempted to "
                          "upgrade multiple times but hit 500 errors each time.",
            "action":     "escalate_checkout_fix",
            "confidence": 0.94,
            "evidence":   [
                "5 checkout errors in current session (50% error rate)",
                "Visited /pricing 3 times — strong upgrade intent (score: 0.82)",
                "Clicked 'Upgrade to Pro' after each error — intent is clear",
                "Submitted support ticket about checkout failures",
            ],
            "_quality": "EXCELLENT",
        }
    elif intent == "error_investigation":
        return {
            "summary":    "User u_4821 is experiencing repeated 500 errors on /checkout. "
                          "The error rate is 50% across 10 session events, indicating "
                          "a systemic checkout failure, not a one-off issue.",
            "action":     "escalate_to_engineering",
            "confidence": 0.96,
            "evidence":   [
                "5 errors out of 10 session events (50% error rate)",
                "All errors are 500 on /checkout — same endpoint",
                "Errors occurred across multiple attempts — not transient",
            ],
            "_quality": "EXCELLENT",
        }
    else:
        return {
            "summary":    "User u_4821 (free plan, at_risk) shows high churn risk "
                          "with 50% error rate and strong upgrade intent blocked by "
                          "checkout failures.",
            "action":     "escalate_checkout_fix",
            "confidence": 0.91,
            "evidence":   [
                "50% error rate in current session",
                "Churn risk flag: TRUE",
                "Upgrade intent score: 0.82",
            ],
            "_quality": "GOOD",
        }


# ── COMPARISON RUNNER ─────────────────────────────────────────────────────────

def run_comparison(user_id: str, query: str) -> None:
    rows   = get_raw_pinot_result(user_id)
    intent = detect_intent(query)

    semantic_chunks = [
        f"User {user_id} hit 500 error on /checkout at 14:32 UTC",
        f"User {user_id} clicked 'Upgrade to Pro' on /pricing at 14:38 UTC",
        f"User {user_id} submitted support ticket: 'checkout keeps failing'",
    ]

    print(f"\n{'─'*65}")
    print(f"Query: \"{query}\"")
    print(f"Intent: {intent}")
    print(f"{'─'*65}")

    # ── APPROACH 1: Raw CSV input ──────────────────────────────────────────
    raw_input  = format_as_csv(rows)
    raw_tokens = count_tokens_approx(raw_input)

    raw_system = "You are a data analyst. Answer the question based on the data."
    raw_response = mock_llm(raw_system, raw_input, intent)

    print(f"\n[APPROACH 1]  Raw CSV → LLM")
    print(f"  Tokens:     ~{raw_tokens}")
    print(f"  Quality:    {raw_response['_quality']}")
    print(f"  Summary:    \"{raw_response['summary']}\"")
    print(f"  Action:     {raw_response['action']}")
    print(f"  Confidence: {raw_response['confidence']:.0%}")
    if "_issues" in raw_response:
        print(f"  Issues:")
        for issue in raw_response["_issues"]:
            print(f"    ❌ {issue}")

    # ── APPROACH 2: Context-engineered input ──────────────────────────────
    builder = ContextBuilder()
    ctx     = builder.build(user_id, query, rows, semantic_chunks)
    ctx_tokens = ctx["token_count"]

    ctx_response = mock_llm(ctx["prompt"]["system"], ctx["prompt"]["user"], intent)

    print(f"\n[APPROACH 2]  Context-Engineered → LLM")
    print(f"  Tokens:     ~{ctx_tokens}  ({ctx['token_savings']} fewer than raw)")
    print(f"  Quality:    {ctx_response['_quality']}")
    print(f"  Summary:    \"{ctx_response['summary']}\"")
    print(f"  Action:     {ctx_response['action']}")
    print(f"  Confidence: {ctx_response['confidence']:.0%}")
    print(f"  Evidence:")
    for e in ctx_response["evidence"]:
        print(f"    ✅ {e}")

    # ── COMPARISON ────────────────────────────────────────────────────────
    print(f"\n  {'Metric':20s} {'Raw Input':25s} {'Context-Engineered':25s}")
    print(f"  {'-'*70}")
    print(f"  {'Tokens':20s} {str(raw_tokens):25s} {str(ctx_tokens):25s}")
    print(f"  {'Quality':20s} {raw_response['_quality']:25s} {ctx_response['_quality']:25s}")
    print(f"  {'Confidence':20s} {raw_response['confidence']:.0%}{'':22s} {ctx_response['confidence']:.0%}")
    print(f"  {'Actionable':20s} {'❌ No':25s} {'✅ Yes':25s}")


# ── MULTI-QUERY DEMO ──────────────────────────────────────────────────────────

def run_multi_query_demo(user_id: str) -> None:
    """Shows how context selection changes based on query intent."""
    print(f"\n{'='*65}")
    print(f"MULTI-QUERY DEMO — Context adapts to query intent")
    print(f"{'='*65}")

    queries = [
        "Why is this user at risk of churning?",
        "What checkout errors has this user experienced?",
        "Is this user likely to upgrade their plan?",
    ]

    rows = get_raw_pinot_result(user_id)
    builder = ContextBuilder()

    for query in queries:
        intent = detect_intent(query)
        ctx    = builder.build(user_id, query, rows)
        print(f"\n  Query:   \"{query}\"")
        print(f"  Intent:  {intent}")
        print(f"  Signals: {ctx['signals_used']}")
        print(f"  Tokens:  ~{ctx['token_count']}")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("LLM SIMULATION — Raw Input vs Context-Engineered Input")
    print("=" * 65)

    user_id = "u_4821"

    # Main comparison
    run_comparison(user_id, "Why is this user at risk of churning?")

    # Multi-query demo
    run_multi_query_demo(user_id)

    # Key insight
    print(f"\n{'='*65}")
    print(f"  KEY INSIGHT")
    print(f"  Context engineering is not about the LLM — it's about the input.")
    print(f"  The same model produces dramatically different output quality")
    print(f"  depending on how the input is structured.")
    print(f"")
    print(f"  Raw input:   more tokens, worse quality, lower confidence")
    print(f"  Context:     fewer tokens, better quality, higher confidence")
    print(f"")
    print(f"  The data engineer's job in an AI system is to build the")
    print(f"  context builder — the bridge between data and the LLM.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
