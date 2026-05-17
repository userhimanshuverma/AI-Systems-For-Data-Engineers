"""
Hallucination Detector — Day 23: Observability for AI Systems
==============================================================
Validates LLM outputs for grounding, consistency, and quality.

Checks:
  1. Number grounding — cited numbers appear in context
  2. Confidence threshold — response confidence >= minimum
  3. User ID consistency — response refers to correct user
  4. Action validity — recommended action is in allowed set
  5. Reasoning consistency — same query produces consistent actions

In production: runs on every LLM response before delivery.
Metrics exported to Prometheus. Low-confidence responses flagged for review.
"""

import re
import time
import random
from dataclasses import dataclass, field
from collections import defaultdict, Counter


# ── VALIDATION RESULT ─────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    passed:          bool
    confidence:      float
    grounding_score: float   # 0.0-1.0: fraction of cited facts in context
    issues:          list[str] = field(default_factory=list)
    latency_ms:      float = 0.0

    @property
    def hallucination_detected(self) -> bool:
        return any("UNGROUNDED" in i or "WRONG_USER" in i for i in self.issues)


# ── HALLUCINATION DETECTOR ────────────────────────────────────────────────────

ALLOWED_ACTIONS = {
    "escalate_checkout_fix", "send_retention_email", "trigger_retention_workflow",
    "send_upgrade_offer", "no_action", "monitor", "manual_review",
    "escalate_to_engineering", "add_to_monitoring_cohort",
}

def detect_hallucination(
    output: dict,
    context: dict,
    user_id: str,
    min_confidence: float = 0.60,
) -> ValidationResult:
    """
    Validates an LLM output for hallucinations and quality issues.
    Returns a ValidationResult with detailed issue list.
    """
    t0     = time.perf_counter()
    issues = []

    summary    = output.get("summary", "")
    action     = output.get("action", "")
    confidence = output.get("confidence", 0.0)
    evidence   = output.get("evidence", [])

    # Check 1: Confidence threshold
    if confidence < min_confidence:
        issues.append(f"LOW_CONFIDENCE:{confidence:.2f}<{min_confidence}")

    # Check 2: Action validity
    if action and action not in ALLOWED_ACTIONS:
        issues.append(f"INVALID_ACTION:{action}")

    # Check 3: Number grounding
    context_str = str(context.get("metrics", {})) + " ".join(context.get("chunks", []))
    cited_nums  = [int(n) for n in re.findall(r'\b(\d+)\b', summary) if 1 < int(n) < 10000]
    ctx_nums    = [int(n) for n in re.findall(r'\b(\d+)\b', context_str) if 1 < int(n) < 10000]

    ungrounded = [n for n in cited_nums if n not in ctx_nums]
    for n in ungrounded:
        issues.append(f"UNGROUNDED_NUMBER:{n}")

    grounding_score = 1.0 - (len(ungrounded) / max(len(cited_nums), 1))

    # Check 4: User ID consistency
    if user_id and user_id not in summary and len(summary) > 20:
        # Check if a different user ID appears
        other_users = re.findall(r'u_\d{4}', summary)
        for uid in other_users:
            if uid != user_id:
                issues.append(f"WRONG_USER_REFERENCE:{uid}!={user_id}")

    # Check 5: Evidence grounding
    for ev in evidence:
        ev_nums = [int(n) for n in re.findall(r'\b(\d+)\b', ev) if 1 < int(n) < 10000]
        for n in ev_nums:
            if n not in ctx_nums:
                issues.append(f"UNGROUNDED_EVIDENCE:{n}")
                break

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    passed     = len(issues) == 0

    return ValidationResult(
        passed=passed,
        confidence=confidence,
        grounding_score=round(grounding_score, 3),
        issues=issues,
        latency_ms=latency_ms,
    )


# ── CONSISTENCY CHECKER ───────────────────────────────────────────────────────

class ConsistencyChecker:
    """
    Checks that the same query produces consistent actions over time.
    High inconsistency = LLM is non-deterministic on this query type.
    """
    def __init__(self, window: int = 10):
        self._history: dict[str, list[str]] = defaultdict(list)
        self._window = window

    def record(self, query_type: str, action: str) -> float:
        """Records an action and returns consistency score (0-1)."""
        history = self._history[query_type]
        history.append(action)
        if len(history) > self._window:
            history.pop(0)

        if len(history) < 2:
            return 1.0

        most_common = Counter(history).most_common(1)[0][1]
        return round(most_common / len(history), 3)

    def get_consistency(self, query_type: str) -> float:
        history = self._history.get(query_type, [])
        if len(history) < 2:
            return 1.0
        most_common = Counter(history).most_common(1)[0][1]
        return round(most_common / len(history), 3)


# ── METRICS TRACKER ───────────────────────────────────────────────────────────

class HallucinationMetrics:
    def __init__(self):
        self._total         = 0
        self._hallucinations= 0
        self._low_conf      = 0
        self._grounding_sum = 0.0
        self._conf_sum      = 0.0

    def record(self, result: ValidationResult) -> None:
        self._total          += 1
        self._grounding_sum  += result.grounding_score
        self._conf_sum       += result.confidence
        if result.hallucination_detected:
            self._hallucinations += 1
        if result.confidence < 0.6:
            self._low_conf += 1

    def summary(self) -> dict:
        n = max(self._total, 1)
        return {
            "total_responses":    self._total,
            "hallucination_rate": round(self._hallucinations / n, 3),
            "low_confidence_rate":round(self._low_conf / n, 3),
            "avg_grounding_score":round(self._grounding_sum / n, 3),
            "avg_confidence":     round(self._conf_sum / n, 3),
        }


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("HALLUCINATION DETECTOR — LLM output validation")
    print("=" * 65)

    random.seed(42)
    metrics     = HallucinationMetrics()
    consistency = ConsistencyChecker()

    context = {
        "metrics": {"errors_7d": 5, "error_rate": 0.50, "churn_risk": True},
        "chunks":  ["User u_4821 hit 500 error on /checkout",
                    "User u_4821 clicked Upgrade to Pro"],
    }

    test_outputs = [
        # Good output
        {"summary": "User u_4821 has 5 errors (50% rate). Churn risk: HIGH.",
         "action": "escalate_checkout_fix", "confidence": 0.92,
         "evidence": ["5 errors in 7 days", "50% error rate"]},
        # Hallucinated numbers
        {"summary": "User u_4821 has had 47 errors over the past month.",
         "action": "escalate_checkout_fix", "confidence": 0.88,
         "evidence": ["47 errors over past month"]},
        # Low confidence
        {"summary": "User u_4821 may have some issues.",
         "action": "monitor", "confidence": 0.42,
         "evidence": []},
        # Wrong user reference
        {"summary": "User u_9901 upgraded to pro plan and is healthy.",
         "action": "no_action", "confidence": 0.85,
         "evidence": ["upgraded to pro"]},
        # Invalid action
        {"summary": "User u_4821 has 5 errors.",
         "action": "delete_account", "confidence": 0.80,
         "evidence": ["5 errors"]},
        # Good output again
        {"summary": "User u_4821 has 5 errors (50% rate). Recommend escalation.",
         "action": "escalate_checkout_fix", "confidence": 0.91,
         "evidence": ["5 errors", "50% error rate"]},
    ]

    print(f"\n[VALIDATION RESULTS]")
    for i, output in enumerate(test_outputs):
        result = detect_hallucination(output, context, "u_4821")
        metrics.record(result)
        consistency.record("churn_query", output["action"])

        icon = "✅" if result.passed else "❌"
        print(f"\n  {icon} Response {i+1}: confidence={result.confidence:.0%}, "
              f"grounding={result.grounding_score:.2f}")
        if result.issues:
            for issue in result.issues:
                print(f"    ⚠️  {issue}")
        else:
            print(f"    All checks passed")

    print(f"\n[METRICS SUMMARY]")
    for k, v in metrics.summary().items():
        print(f"  {k}: {v}")

    print(f"\n[CONSISTENCY]")
    print(f"  churn_query action consistency: {consistency.get_consistency('churn_query'):.0%}")

    print(f"\n{'='*65}")
    print(f"  Hallucination detector runs on every LLM response.")
    print(f"  Failed responses are flagged for human review.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
