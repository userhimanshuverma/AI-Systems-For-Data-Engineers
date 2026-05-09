"""
Intent Classifier — Day 16: Query Understanding Layer
======================================================
Classifies a natural language query into a known intent category.
Each intent maps to a different retrieval strategy.

Intent categories:
  error_investigation  → user has errors, need details + context
  churn_analysis       → identify at-risk users, need metrics + patterns
  upgrade_analysis     → identify upgrade candidates, need intent signals
  retention_analysis   → engagement patterns, need session data
  operational          → system health, real-time metrics only
  general              → fallback, semantic search only

In production: replace keyword matching with a fine-tuned classifier
or a lightweight LLM call (e.g., GPT-4o-mini with a classification prompt).
"""

import re
import time
from dataclasses import dataclass


# ── INTENT DEFINITIONS ────────────────────────────────────────────────────────

@dataclass
class IntentResult:
    intent:     str
    confidence: float
    signals:    list[str]   # keywords that triggered this classification
    latency_ms: float


# Keyword signals per intent (ordered by priority)
INTENT_SIGNALS: dict[str, list[str]] = {
    "error_investigation": [
        "error", "errors", "fail", "failing", "failed", "broken",
        "crash", "exception", "500", "404", "issue", "problem",
        "not working", "down", "outage",
    ],
    "churn_analysis": [
        "churn", "churning", "at risk", "risk", "cancel", "cancelling",
        "leaving", "drop off", "dropout", "disengaged", "inactive",
        "struggling", "frustrated",
    ],
    "upgrade_analysis": [
        "upgrade", "upgrading", "convert", "conversion", "purchase",
        "buy", "pro plan", "premium", "pricing", "intent", "likely to",
        "potential", "upsell",
    ],
    "retention_analysis": [
        "retain", "retention", "engaged", "engagement", "active",
        "activity", "session", "return", "coming back", "sticky",
        "new users", "onboarding",
    ],
    "operational": [
        "system status", "health", "uptime", "latency", "throughput",
        "current error rate", "live", "right now", "real-time",
        "monitoring", "alert", "incident",
    ],
}


def classify_intent(query: str) -> IntentResult:
    """
    Classifies query intent using keyword signal matching.

    In production: use a fine-tuned classifier or:
        from openai import OpenAI
        client = OpenAI()
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Classify this query into one of: "
                 "error_investigation, churn_analysis, upgrade_analysis, "
                 "retention_analysis, operational, general. Respond with just the label."},
                {"role": "user", "content": query}
            ]
        )
        intent = resp.choices[0].message.content.strip()
    """
    t0 = time.perf_counter()
    q  = query.lower()

    scores: dict[str, list[str]] = {intent: [] for intent in INTENT_SIGNALS}

    for intent, signals in INTENT_SIGNALS.items():
        for signal in signals:
            if signal in q:
                scores[intent].append(signal)

    # Find intent with most signal matches
    best_intent  = "general"
    best_signals = []
    best_count   = 0

    for intent, matched in scores.items():
        if len(matched) > best_count:
            best_count   = len(matched)
            best_intent  = intent
            best_signals = matched

    # Confidence: based on number of matched signals
    confidence = min(0.5 + best_count * 0.15, 0.95) if best_count > 0 else 0.40

    latency_ms = (time.perf_counter() - t0) * 1000

    return IntentResult(
        intent=best_intent,
        confidence=round(confidence, 2),
        signals=best_signals,
        latency_ms=round(latency_ms, 2),
    )


# ── INTENT METADATA ───────────────────────────────────────────────────────────

INTENT_METADATA = {
    "error_investigation": {
        "description":    "User has errors, need details and behavioral context",
        "use_pinot":      True,
        "use_vector":     True,
        "freshness":      "high",
        "freshness_sla":  5,      # seconds
        "top_k":          3,
        "token_budget":   200,
    },
    "churn_analysis": {
        "description":    "Identify at-risk users, need metrics and patterns",
        "use_pinot":      True,
        "use_vector":     True,
        "freshness":      "medium",
        "freshness_sla":  60,
        "top_k":          5,
        "token_budget":   400,
    },
    "upgrade_analysis": {
        "description":    "Identify upgrade candidates, need intent signals",
        "use_pinot":      True,
        "use_vector":     True,
        "freshness":      "low",
        "freshness_sla":  3600,
        "top_k":          3,
        "token_budget":   300,
    },
    "retention_analysis": {
        "description":    "Engagement patterns, need session data",
        "use_pinot":      True,
        "use_vector":     True,
        "freshness":      "low",
        "freshness_sla":  86400,
        "top_k":          5,
        "token_budget":   400,
    },
    "operational": {
        "description":    "System health, real-time metrics only",
        "use_pinot":      True,
        "use_vector":     False,
        "freshness":      "critical",
        "freshness_sla":  1,
        "top_k":          2,
        "token_budget":   100,
    },
    "general": {
        "description":    "Fallback, semantic search only",
        "use_pinot":      False,
        "use_vector":     True,
        "freshness":      "low",
        "freshness_sla":  3600,
        "top_k":          3,
        "token_budget":   200,
    },
}

def get_intent_metadata(intent: str) -> dict:
    return INTENT_METADATA.get(intent, INTENT_METADATA["general"])


# ── DEMO ──────────────────────────────────────────────────────────────────────

TEST_QUERIES = [
    "Show me all errors for user u_4821 in the last 2 hours",
    "Which free-plan users are most at risk this week?",
    "Who is most likely to upgrade to pro this month?",
    "How engaged are our new users in the last 7 days?",
    "What is the current system error rate?",
    "What happened with user u_0012?",
]

def run() -> None:
    print("=" * 65)
    print("INTENT CLASSIFIER — Query Understanding Layer")
    print("=" * 65)

    for query in TEST_QUERIES:
        result = classify_intent(query)
        meta   = get_intent_metadata(result.intent)
        print(f"\n  Query:      \"{query}\"")
        print(f"  Intent:     {result.intent} (confidence={result.confidence:.0%})")
        print(f"  Signals:    {result.signals or ['none — fallback to general']}")
        print(f"  Strategy:   pinot={meta['use_pinot']}, vector={meta['use_vector']}, "
              f"top_k={meta['top_k']}, freshness={meta['freshness']}")
        print(f"  Latency:    {result.latency_ms:.2f}ms")

    print(f"\n{'='*65}")
    print(f"  Intent classification adds < 2ms overhead.")
    print(f"  Without it: every query gets the same retrieval strategy.")
    print(f"  With it: each query gets the optimal retrieval plan.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
