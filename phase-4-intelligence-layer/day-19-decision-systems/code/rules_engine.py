"""
Rules Engine — Day 19: Decision Layer Design
=============================================
Layer 1 of the decision system. Applies deterministic business rules
before any ML or LLM processing.

Rules are:
  - Deterministic: same input → same output, always
  - Instant: microseconds per evaluation
  - Free: no compute cost
  - Auditable: every rule is explicit and traceable

Rules handle three outcomes:
  BLOCK      → skip this case entirely (inactive user, invalid data)
  FAST_TRACK → take immediate action without ML/LLM (critical error rate)
  PASS       → continue to ML layer
"""

from dataclasses import dataclass, field
from typing import Any
import time


# ── RULE RESULT ───────────────────────────────────────────────────────────────

@dataclass
class RuleResult:
    outcome:    str           # "block", "fast_track", "pass"
    action:     str           # what to do
    reason:     str           # which rule triggered
    confidence: float         # always 1.0 for rules (deterministic)
    rules_fired:list[str] = field(default_factory=list)
    latency_us: float = 0.0   # microseconds


# ── RULE DEFINITIONS ──────────────────────────────────────────────────────────

def rule_data_validation(user: dict) -> tuple[bool, str]:
    """Validates required fields are present and valid."""
    required = ["user_id", "error_rate", "plan", "intent_score", "days_since_last_event"]
    for field in required:
        if field not in user:
            return False, f"missing_field:{field}"
    if not (0.0 <= user["error_rate"] <= 1.0):
        return False, "invalid_error_rate"
    if user["plan"] not in ("free", "pro", "enterprise"):
        return False, "invalid_plan"
    return True, "ok"

def rule_inactive_user(user: dict) -> bool:
    """Block users who haven't been active in 30+ days."""
    return user.get("days_since_last_event", 0) > 30

def rule_critical_error_rate(user: dict) -> bool:
    """Fast-track users with critical error rates (>= 0.8)."""
    return user.get("error_rate", 0) >= 0.8

def rule_enterprise_exempt(user: dict) -> bool:
    """Enterprise users get different handling — skip standard churn rules."""
    return user.get("plan") == "enterprise"

def rule_churn_threshold(user: dict) -> bool:
    """Flag free-plan users with error rate above churn threshold."""
    return (
        user.get("error_rate", 0) >= 0.3 and
        user.get("plan") == "free"
    )

def rule_high_intent_blocker(user: dict) -> bool:
    """
    Fast-track users with very high intent + errors — they want to upgrade
    but are blocked. Needs immediate intervention.
    """
    return (
        user.get("intent_score", 0) >= 0.8 and
        user.get("error_rate", 0) >= 0.4
    )


# ── RULES ENGINE ──────────────────────────────────────────────────────────────

def apply_rules(user: dict) -> RuleResult:
    """
    Applies all rules in priority order.
    Returns the first matching rule's outcome.
    """
    t0 = time.perf_counter()
    rules_fired = []

    # Rule 0: Data validation (always first)
    valid, reason = rule_data_validation(user)
    rules_fired.append("data_validation")
    if not valid:
        return RuleResult(
            outcome="block", action="skip",
            reason=f"invalid_data:{reason}", confidence=1.0,
            rules_fired=rules_fired,
            latency_us=round((time.perf_counter() - t0) * 1e6, 2),
        )

    # Rule 1: Inactive user
    rules_fired.append("inactive_check")
    if rule_inactive_user(user):
        return RuleResult(
            outcome="block", action="skip",
            reason="inactive_user_30d", confidence=1.0,
            rules_fired=rules_fired,
            latency_us=round((time.perf_counter() - t0) * 1e6, 2),
        )

    # Rule 2: Enterprise exempt
    rules_fired.append("enterprise_check")
    if rule_enterprise_exempt(user):
        return RuleResult(
            outcome="block", action="enterprise_workflow",
            reason="enterprise_user_different_flow", confidence=1.0,
            rules_fired=rules_fired,
            latency_us=round((time.perf_counter() - t0) * 1e6, 2),
        )

    # Rule 3: Critical error rate → immediate alert
    rules_fired.append("critical_error_check")
    if rule_critical_error_rate(user):
        return RuleResult(
            outcome="fast_track", action="immediate_alert",
            reason="critical_error_rate_gte_0.8", confidence=1.0,
            rules_fired=rules_fired,
            latency_us=round((time.perf_counter() - t0) * 1e6, 2),
        )

    # Rule 4: High intent + errors → fast track for intervention
    rules_fired.append("high_intent_blocker_check")
    if rule_high_intent_blocker(user):
        return RuleResult(
            outcome="fast_track", action="priority_intervention",
            reason="high_intent_blocked_by_errors", confidence=1.0,
            rules_fired=rules_fired,
            latency_us=round((time.perf_counter() - t0) * 1e6, 2),
        )

    # Rule 5: Churn threshold → pass to ML
    rules_fired.append("churn_threshold_check")
    if rule_churn_threshold(user):
        return RuleResult(
            outcome="pass", action="continue_to_ml",
            reason="churn_threshold_exceeded", confidence=1.0,
            rules_fired=rules_fired,
            latency_us=round((time.perf_counter() - t0) * 1e6, 2),
        )

    # Default: within normal range
    rules_fired.append("default")
    return RuleResult(
        outcome="pass", action="continue_to_ml",
        reason="within_normal_range", confidence=1.0,
        rules_fired=rules_fired,
        latency_us=round((time.perf_counter() - t0) * 1e6, 2),
    )


# ── DEMO ──────────────────────────────────────────────────────────────────────

TEST_USERS = [
    {"user_id":"u_4821","error_rate":0.80,"plan":"free",       "intent_score":0.82,"days_since_last_event":2},
    {"user_id":"u_0012","error_rate":0.00,"plan":"pro",        "intent_score":0.30,"days_since_last_event":1},
    {"user_id":"u_7734","error_rate":0.33,"plan":"free",       "intent_score":0.40,"days_since_last_event":5},
    {"user_id":"u_9901","error_rate":0.00,"plan":"enterprise", "intent_score":0.10,"days_since_last_event":3},
    {"user_id":"u_5566","error_rate":0.10,"plan":"free",       "intent_score":0.20,"days_since_last_event":45},
    {"user_id":"u_3344","error_rate":0.45,"plan":"free",       "intent_score":0.85,"days_since_last_event":4},
    {"user_id":"u_bad", "error_rate":1.5, "plan":"free",       "intent_score":0.50,"days_since_last_event":1},
]

def run() -> None:
    print("=" * 65)
    print("RULES ENGINE — Layer 1: Deterministic decision logic")
    print("=" * 65)

    outcomes = {"block": 0, "fast_track": 0, "pass": 0}

    for user in TEST_USERS:
        result = apply_rules(user)
        outcomes[result.outcome] += 1
        icon = {"block":"🚫","fast_track":"⚡","pass":"✅"}[result.outcome]
        print(f"\n  {icon} {user['user_id']:8s}  outcome={result.outcome:12s}  "
              f"action={result.action:25s}  reason={result.reason}")
        print(f"     rules_fired={result.rules_fired}  latency={result.latency_us:.1f}μs")

    print(f"\n{'='*65}")
    print(f"  Summary: {outcomes}")
    print(f"  Rules execute in microseconds — no ML or LLM needed for these cases.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
