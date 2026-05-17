"""
Evaluation Pipeline — Day 23: Observability for AI Systems
============================================================
Runs automated quality evaluations for the AI system.

Evaluations run:
  - Daily: full golden test set evaluation
  - After every deployment: regression check
  - Hourly: lightweight spot check

Metrics tracked:
  - Retrieval precision@k
  - LLM response quality score
  - Grounding score
  - Consistency score
  - Cost per query

In production: results stored in evaluation DB, visualized in Grafana,
alerts fire when quality drops below baseline.
"""

import time
import random
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta


# ── EVALUATION RESULT ─────────────────────────────────────────────────────────

@dataclass
class EvalResult:
    eval_id:          str
    eval_type:        str   # "daily" | "deployment" | "spot"
    ts:               str
    retrieval_precision: float
    grounding_score:  float
    consistency_score:float
    avg_confidence:   float
    avg_latency_ms:   float
    cost_per_query:   float
    passed:           bool
    issues:           list[str] = field(default_factory=list)


# ── GOLDEN TEST SET ───────────────────────────────────────────────────────────

GOLDEN_QUERIES = [
    {
        "query":          "Why is user u_4821 at risk of churning?",
        "expected_action":"escalate_checkout_fix",
        "expected_facts": [5, 50],  # errors, error_rate%
        "query_type":     "churn_investigation",
    },
    {
        "query":          "Which free-plan users are most at risk this week?",
        "expected_action":"trigger_retention_workflow",
        "expected_facts": [],
        "query_type":     "churn_analysis",
    },
    {
        "query":          "Is user u_0012 likely to upgrade?",
        "expected_action":"send_upgrade_offer",
        "expected_facts": [],
        "query_type":     "upgrade_investigation",
    },
]


# ── MOCK SYSTEM ───────────────────────────────────────────────────────────────

def mock_system_response(query: dict, quality: str = "good") -> dict:
    """Simulates the AI system responding to a query."""
    time.sleep(random.uniform(0.050, 0.100))

    if quality == "good":
        return {
            "action":     query["expected_action"],
            "confidence": random.uniform(0.85, 0.95),
            "grounding":  random.uniform(0.90, 1.00),
            "latency_ms": random.uniform(500, 700),
            "tokens":     random.randint(250, 350),
        }
    elif quality == "degraded":
        return {
            "action":     random.choice(["no_action", "monitor", query["expected_action"]]),
            "confidence": random.uniform(0.45, 0.70),
            "grounding":  random.uniform(0.50, 0.75),
            "latency_ms": random.uniform(800, 1500),
            "tokens":     random.randint(350, 600),
        }
    else:  # regression
        return {
            "action":     query["expected_action"],
            "confidence": random.uniform(0.75, 0.88),
            "grounding":  random.uniform(0.80, 0.92),
            "latency_ms": random.uniform(600, 900),
            "tokens":     random.randint(280, 420),
        }


# ── EVALUATION RUNNER ─────────────────────────────────────────────────────────

class EvaluationPipeline:
    """Runs quality evaluations and tracks results over time."""

    THRESHOLDS = {
        "retrieval_precision": 0.75,
        "grounding_score":     0.80,
        "consistency_score":   0.80,
        "avg_confidence":      0.70,
        "avg_latency_ms":      1000,
        "cost_per_query":      0.002,
    }

    def __init__(self):
        self._results: list[EvalResult] = []

    def run_evaluation(self, eval_type: str = "daily",
                        quality: str = "good") -> EvalResult:
        """Runs a full evaluation against the golden test set."""
        responses = []
        action_matches = 0

        for query in GOLDEN_QUERIES:
            resp = mock_system_response(query, quality)
            responses.append(resp)
            if resp["action"] == query["expected_action"]:
                action_matches += 1

        # Compute aggregate metrics
        precision    = action_matches / len(GOLDEN_QUERIES)
        grounding    = sum(r["grounding"] for r in responses) / len(responses)
        confidence   = sum(r["confidence"] for r in responses) / len(responses)
        latency      = sum(r["latency_ms"] for r in responses) / len(responses)
        tokens       = sum(r["tokens"] for r in responses) / len(responses)
        cost         = tokens * 0.0000015  # ~$0.0015 per 1K tokens

        # Consistency: run same query twice, check action matches
        q0 = GOLDEN_QUERIES[0]
        r1 = mock_system_response(q0, quality)
        r2 = mock_system_response(q0, quality)
        consistency = 1.0 if r1["action"] == r2["action"] else 0.5

        # Check thresholds
        issues = []
        if precision    < self.THRESHOLDS["retrieval_precision"]:
            issues.append(f"LOW_PRECISION:{precision:.2f}")
        if grounding    < self.THRESHOLDS["grounding_score"]:
            issues.append(f"LOW_GROUNDING:{grounding:.2f}")
        if consistency  < self.THRESHOLDS["consistency_score"]:
            issues.append(f"LOW_CONSISTENCY:{consistency:.2f}")
        if confidence   < self.THRESHOLDS["avg_confidence"]:
            issues.append(f"LOW_CONFIDENCE:{confidence:.2f}")
        if latency      > self.THRESHOLDS["avg_latency_ms"]:
            issues.append(f"HIGH_LATENCY:{latency:.0f}ms")
        if cost         > self.THRESHOLDS["cost_per_query"]:
            issues.append(f"HIGH_COST:${cost:.4f}")

        result = EvalResult(
            eval_id=f"eval_{int(time.time())}",
            eval_type=eval_type,
            ts=datetime.now(timezone.utc).isoformat(),
            retrieval_precision=round(precision, 3),
            grounding_score=round(grounding, 3),
            consistency_score=round(consistency, 3),
            avg_confidence=round(confidence, 3),
            avg_latency_ms=round(latency, 1),
            cost_per_query=round(cost, 6),
            passed=len(issues) == 0,
            issues=issues,
        )
        self._results.append(result)
        return result

    def compare_to_baseline(self, baseline: EvalResult,
                             current: EvalResult) -> dict:
        """Compares current evaluation to baseline."""
        return {
            "precision_delta":  round(current.retrieval_precision - baseline.retrieval_precision, 3),
            "grounding_delta":  round(current.grounding_score - baseline.grounding_score, 3),
            "confidence_delta": round(current.avg_confidence - baseline.avg_confidence, 3),
            "latency_delta_ms": round(current.avg_latency_ms - baseline.avg_latency_ms, 1),
            "regression":       current.retrieval_precision < baseline.retrieval_precision - 0.05,
        }

    def print_result(self, result: EvalResult) -> None:
        icon = "✅" if result.passed else "❌"
        print(f"  {icon} [{result.eval_type}] {result.ts[:19]}")
        print(f"     precision={result.retrieval_precision:.3f}  "
              f"grounding={result.grounding_score:.3f}  "
              f"confidence={result.avg_confidence:.3f}")
        print(f"     latency={result.avg_latency_ms:.0f}ms  "
              f"cost=${result.cost_per_query:.5f}/query")
        if result.issues:
            for issue in result.issues:
                print(f"     ⚠️  {issue}")


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("EVALUATION PIPELINE — Automated quality assessment")
    print("=" * 65)

    random.seed(42)
    pipeline = EvaluationPipeline()

    # Baseline evaluation
    print(f"\n[BASELINE]  Daily evaluation (healthy system)")
    baseline = pipeline.run_evaluation("daily", quality="good")
    pipeline.print_result(baseline)

    # Deployment check
    print(f"\n[DEPLOYMENT CHECK]  After new embedding model")
    deploy = pipeline.run_evaluation("deployment", quality="regression")
    pipeline.print_result(deploy)
    comparison = pipeline.compare_to_baseline(baseline, deploy)
    print(f"     Δ precision={comparison['precision_delta']:+.3f}  "
          f"Δ grounding={comparison['grounding_delta']:+.3f}  "
          f"Δ latency={comparison['latency_delta_ms']:+.0f}ms")
    if comparison["regression"]:
        print(f"     ❌ REGRESSION DETECTED — block deployment")
    else:
        print(f"     ✅ No regression — deployment approved")

    # Degraded system
    print(f"\n[DEGRADED]  After embedding refresh failure")
    degraded = pipeline.run_evaluation("daily", quality="degraded")
    pipeline.print_result(degraded)
    comparison2 = pipeline.compare_to_baseline(baseline, degraded)
    print(f"     Δ precision={comparison2['precision_delta']:+.3f}  "
          f"Δ grounding={comparison2['grounding_delta']:+.3f}")
    if comparison2["regression"]:
        print(f"     ❌ REGRESSION DETECTED — trigger embedding refresh")

    # Trend
    print(f"\n[TREND]  Evaluation history")
    print(f"  {'Type':12s} {'Precision':10s} {'Grounding':10s} {'Passed':8s}")
    print(f"  {'-'*45}")
    for r in pipeline._results:
        icon = "✅" if r.passed else "❌"
        print(f"  {r.eval_type:12s} {r.retrieval_precision:10.3f} "
              f"{r.grounding_score:10.3f} {icon}")

    print(f"\n{'='*65}")
    print(f"  Evaluations run daily + after every deployment.")
    print(f"  Regressions block deployments automatically.")
    print(f"  Quality trends visible in Grafana dashboard.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
