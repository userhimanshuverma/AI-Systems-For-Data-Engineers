"""
Hallucination Demo — Day 22: Failure Modes in AI Systems
==========================================================
Demonstrates three types of hallucination in production RAG systems:

1. Model hallucination — LLM invents facts not in context
2. Retrieval-induced hallucination — LLM reasons over wrong context
3. Stale-context reasoning — LLM reasons over outdated context

Also demonstrates output validation to detect hallucinations.
"""

import re
import time
import random
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta


# ── CONTEXT TYPES ─────────────────────────────────────────────────────────────

@dataclass
class RetrievalContext:
    structured_metrics: dict
    semantic_chunks:    list[str]
    context_age_s:      float   # how old is this context?
    user_id:            str


# ── MOCK LLM ──────────────────────────────────────────────────────────────────

def mock_llm(context: RetrievalContext, query: str, mode: str = "normal") -> dict:
    """
    Simulates LLM responses in different failure modes.
    mode: "normal" | "hallucinate" | "stale" | "noisy"
    """
    time.sleep(0.100)
    m = context.structured_metrics
    chunks = context.semantic_chunks

    if mode == "normal":
        # Correct reasoning over correct context
        errors = m.get("errors_7d", 0)
        rate   = m.get("error_rate", 0.0)
        churn  = m.get("churn_risk", False)
        return {
            "summary":    f"User {context.user_id} has {errors} errors ({rate:.0%} rate). "
                          f"Churn risk: {'HIGH' if churn else 'LOW'}.",
            "action":     "escalate_checkout_fix" if churn else "monitor",
            "confidence": 0.92,
            "evidence":   [f"{errors} errors in 7 days", f"Error rate: {rate:.0%}"],
            "grounded":   True,
        }

    elif mode == "hallucinate":
        # LLM invents facts not in context (model hallucination)
        return {
            "summary":    f"User {context.user_id} has had 47 errors over the past month, "
                          f"indicating a persistent infrastructure issue affecting their account. "
                          f"Their error rate of 89% is the highest in their cohort.",
            "action":     "escalate_to_infrastructure_team",
            "confidence": 0.88,
            "evidence":   ["47 errors over past month", "89% error rate", "highest in cohort"],
            "grounded":   False,  # these numbers are NOT in the context
        }

    elif mode == "stale":
        # LLM reasons correctly over stale context (stale-context reasoning)
        # Context is 4 hours old — misses recent errors
        return {
            "summary":    f"User {context.user_id} appears healthy. "
                          f"No errors detected in recent activity. "
                          f"Engagement is normal. No action required.",
            "action":     "no_action",
            "confidence": 0.91,
            "evidence":   ["0 errors in context", "normal engagement"],
            "grounded":   True,  # grounded in context, but context is stale
            "context_age_s": context.context_age_s,
        }

    elif mode == "noisy":
        # LLM confused by wrong user's data in context
        return {
            "summary":    f"User {context.user_id} recently upgraded to the pro plan "
                          f"and is showing strong engagement. No churn risk detected.",
            "action":     "no_action",
            "confidence": 0.85,
            "evidence":   ["upgraded to pro plan", "strong engagement"],
            "grounded":   False,  # evidence is from wrong user in context
        }

    return {"summary": "Unknown mode", "confidence": 0.0, "grounded": False}


# ── OUTPUT VALIDATOR ──────────────────────────────────────────────────────────

def validate_output(output: dict, context: RetrievalContext) -> tuple[bool, list[str]]:
    """
    Validates LLM output for hallucinations and grounding issues.
    Returns (is_valid, list_of_issues).
    """
    issues = []

    # Check 1: Confidence threshold
    if output.get("confidence", 0) < 0.6:
        issues.append(f"LOW_CONFIDENCE: {output.get('confidence', 0):.2f} < 0.6")

    # Check 2: Context freshness
    age_s = context.context_age_s
    if age_s > 3600:  # > 1 hour
        issues.append(f"STALE_CONTEXT: context is {age_s/3600:.1f}h old (SLA: 1h)")

    # Check 3: Number grounding — check cited numbers appear in context
    summary = output.get("summary", "")
    cited_numbers = [int(n) for n in re.findall(r'\b(\d+)\b', summary) if int(n) > 1]
    context_numbers = [
        int(n) for n in re.findall(r'\b(\d+)\b',
            str(context.structured_metrics) + " ".join(context.semantic_chunks))
        if int(n) > 1
    ]
    for num in cited_numbers:
        if num not in context_numbers:
            issues.append(f"UNGROUNDED_NUMBER: {num} not found in context")

    # Check 4: User ID consistency
    uid = context.user_id
    for chunk in context.semantic_chunks:
        if "u_" in chunk and uid not in chunk:
            # Found a different user's data in context
            other_uid = re.search(r'u_\d+', chunk)
            if other_uid and other_uid.group(0) != uid:
                issues.append(f"WRONG_USER_IN_CONTEXT: found {other_uid.group(0)}, expected {uid}")
                break

    return len(issues) == 0, issues


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("HALLUCINATION DEMO — AI failure modes in production")
    print("=" * 65)

    # Correct context
    correct_ctx = RetrievalContext(
        user_id="u_4821",
        structured_metrics={"errors_7d": 5, "error_rate": 0.50, "churn_risk": True},
        semantic_chunks=[
            "User u_4821 hit 500 error on /checkout at 14:32",
            "User u_4821 clicked Upgrade to Pro. Intent: 0.82.",
        ],
        context_age_s=30,  # 30 seconds old — fresh
    )

    # Stale context (4 hours old, before errors occurred)
    stale_ctx = RetrievalContext(
        user_id="u_4821",
        structured_metrics={"errors_7d": 0, "error_rate": 0.0, "churn_risk": False},
        semantic_chunks=[
            "User u_4821 viewed /home. Normal session.",
            "User u_4821 browsed documentation.",
        ],
        context_age_s=14400,  # 4 hours old — stale
    )

    # Noisy context (contains wrong user's data)
    noisy_ctx = RetrievalContext(
        user_id="u_4821",
        structured_metrics={"errors_7d": 5, "error_rate": 0.50, "churn_risk": True},
        semantic_chunks=[
            "User u_4821 hit 500 error on /checkout",
            "User u_9901 upgraded to pro plan",  # ← WRONG USER
        ],
        context_age_s=30,
    )

    scenarios = [
        ("Normal (correct context + correct reasoning)", correct_ctx, "normal"),
        ("Model hallucination (invents facts)", correct_ctx, "hallucinate"),
        ("Stale context reasoning (4h old data)", stale_ctx, "stale"),
        ("Noisy context (wrong user's data)", noisy_ctx, "noisy"),
    ]

    for label, ctx, mode in scenarios:
        print(f"\n{'─'*65}")
        print(f"  Scenario: {label}")
        output = mock_llm(ctx, "Why is this user at risk?", mode=mode)
        valid, issues = validate_output(output, ctx)

        icon = "✅" if valid else "❌"
        print(f"  {icon} Valid: {valid}")
        print(f"  Summary: {output['summary'][:80]}...")
        print(f"  Confidence: {output['confidence']:.0%}")
        if issues:
            print(f"  Issues detected:")
            for issue in issues:
                print(f"    ⚠️  {issue}")
        else:
            print(f"  No issues detected")

    print(f"\n{'='*65}")
    print(f"  KEY: Validation catches hallucinations before they reach users.")
    print(f"  Stale context is the hardest to detect — requires freshness monitoring.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
