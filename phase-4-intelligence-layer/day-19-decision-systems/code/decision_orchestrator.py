"""
Decision Orchestrator — Day 19: Decision Layer Design
======================================================
Combines all three layers into a single decision pipeline:
  Layer 1: Rules Engine (deterministic, instant)
  Layer 2: ML Predictor (probabilistic, ~5ms)
  Layer 3: LLM Reasoning (generative, ~200ms, high-risk only)

Demonstrates:
  - Layer routing (not every case reaches every layer)
  - Confidence layering (final confidence = product of all layers)
  - Cost comparison (LLM-only vs layered)
  - Fallback when LLM fails
"""

import time
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from rules_engine  import apply_rules, RuleResult
from ml_predictor  import predict, MLResult
from llm_reasoning import reason, LLMResult


# ── DECISION RESULT ───────────────────────────────────────────────────────────

from dataclasses import dataclass, field

@dataclass
class DecisionResult:
    user_id:      str
    final_action: str
    final_reason: str
    confidence:   float
    layer_path:   list[str]   # which layers were invoked
    evidence:     list[str]
    total_ms:     float
    llm_called:   bool


# ── ORCHESTRATOR ──────────────────────────────────────────────────────────────

def make_decision(user: dict) -> DecisionResult:
    """
    Runs the full layered decision pipeline for a single user.
    Returns a DecisionResult with action, confidence, and audit trail.
    """
    t0         = time.perf_counter()
    layer_path = []
    evidence   = []

    # ── LAYER 1: Rules ────────────────────────────────────────────────────────
    layer_path.append("rules")
    rules_result = apply_rules(user)
    evidence.append(f"rules:{rules_result.reason}")

    if rules_result.outcome == "block":
        return DecisionResult(
            user_id=user["user_id"],
            final_action=rules_result.action,
            final_reason=rules_result.reason,
            confidence=1.0,
            layer_path=layer_path,
            evidence=evidence,
            total_ms=round((time.perf_counter() - t0) * 1000, 1),
            llm_called=False,
        )

    if rules_result.outcome == "fast_track":
        return DecisionResult(
            user_id=user["user_id"],
            final_action=rules_result.action,
            final_reason=rules_result.reason,
            confidence=1.0,
            layer_path=layer_path,
            evidence=evidence,
            total_ms=round((time.perf_counter() - t0) * 1000, 1),
            llm_called=False,
        )

    # ── LAYER 2: ML ───────────────────────────────────────────────────────────
    layer_path.append("ml")
    ml_result = predict(user)
    evidence.append(f"ml:churn={ml_result.churn_probability:.2f},tier={ml_result.risk_tier}")

    if ml_result.risk_tier == "low":
        return DecisionResult(
            user_id=user["user_id"],
            final_action="no_action",
            final_reason=f"ml_low_risk:{ml_result.churn_probability:.2f}",
            confidence=rules_result.confidence * ml_result.confidence,
            layer_path=layer_path,
            evidence=evidence,
            total_ms=round((time.perf_counter() - t0) * 1000, 1),
            llm_called=False,
        )

    if ml_result.risk_tier == "medium":
        return DecisionResult(
            user_id=user["user_id"],
            final_action="send_retention_email",
            final_reason=f"ml_medium_risk:{ml_result.churn_probability:.2f}",
            confidence=rules_result.confidence * ml_result.confidence,
            layer_path=layer_path,
            evidence=evidence,
            total_ms=round((time.perf_counter() - t0) * 1000, 1),
            llm_called=False,
        )

    # ── LAYER 3: LLM (high-risk only) ─────────────────────────────────────────
    layer_path.append("llm")
    try:
        llm_result = reason(user, ml_result)
        if not llm_result.valid:
            # Fallback: use ML result if LLM output is invalid
            return DecisionResult(
                user_id=user["user_id"],
                final_action="send_retention_email",
                final_reason=f"llm_invalid_fallback_to_ml",
                confidence=rules_result.confidence * ml_result.confidence * 0.5,
                layer_path=layer_path + ["fallback"],
                evidence=evidence + ["llm:invalid_output"],
                total_ms=round((time.perf_counter() - t0) * 1000, 1),
                llm_called=True,
            )

        # Combine confidence from all layers
        final_confidence = round(
            rules_result.confidence * ml_result.confidence * llm_result.confidence, 3
        )
        evidence.extend(llm_result.evidence[:2])

        return DecisionResult(
            user_id=user["user_id"],
            final_action=llm_result.action,
            final_reason=llm_result.summary[:80],
            confidence=final_confidence,
            layer_path=layer_path,
            evidence=evidence,
            total_ms=round((time.perf_counter() - t0) * 1000, 1),
            llm_called=True,
        )

    except Exception as e:
        # Fallback: LLM failed entirely
        return DecisionResult(
            user_id=user["user_id"],
            final_action="send_retention_email",
            final_reason=f"llm_error_fallback:{str(e)[:40]}",
            confidence=rules_result.confidence * ml_result.confidence * 0.4,
            layer_path=layer_path + ["error_fallback"],
            evidence=evidence,
            total_ms=round((time.perf_counter() - t0) * 1000, 1),
            llm_called=True,
        )


# ── BATCH PROCESSING ──────────────────────────────────────────────────────────

def process_batch(users: list[dict]) -> dict:
    """Processes a batch of users through the decision pipeline."""
    results    = []
    layer_dist = {"rules_only": 0, "rules_ml": 0, "rules_ml_llm": 0}
    actions    = {}

    for user in users:
        result = make_decision(user)
        results.append(result)

        if len(result.layer_path) == 1:
            layer_dist["rules_only"] += 1
        elif len(result.layer_path) == 2:
            layer_dist["rules_ml"] += 1
        else:
            layer_dist["rules_ml_llm"] += 1

        actions[result.final_action] = actions.get(result.final_action, 0) + 1

    llm_calls = sum(1 for r in results if r.llm_called)
    total_ms  = sum(r.total_ms for r in results)

    return {
        "total_users":  len(users),
        "layer_dist":   layer_dist,
        "actions":      actions,
        "llm_calls":    llm_calls,
        "llm_pct":      f"{llm_calls/len(users):.0%}",
        "total_ms":     round(total_ms, 1),
        "avg_ms":       round(total_ms / len(users), 1),
    }


# ── DEMO ──────────────────────────────────────────────────────────────────────

TEST_USERS = [
    # High risk: errors + intent → rules pass → ML high → LLM
    {"user_id":"u_4821","error_rate":0.50,"plan":"free","intent_score":0.82,
     "days_since_signup":45,"pricing_visits":3,"session_errors":5,"days_since_last_event":2},
    # Critical: rules fast-track
    {"user_id":"u_crit","error_rate":0.90,"plan":"free","intent_score":0.50,
     "days_since_signup":30,"pricing_visits":1,"session_errors":9,"days_since_last_event":1},
    # Inactive: rules block
    {"user_id":"u_gone","error_rate":0.10,"plan":"free","intent_score":0.10,
     "days_since_signup":90,"pricing_visits":0,"session_errors":1,"days_since_last_event":45},
    # Low risk: rules pass → ML low → no action
    {"user_id":"u_0012","error_rate":0.00,"plan":"pro","intent_score":0.30,
     "days_since_signup":180,"pricing_visits":1,"session_errors":0,"days_since_last_event":1},
    # Medium risk: rules pass → ML medium → email
    {"user_id":"u_7734","error_rate":0.33,"plan":"free","intent_score":0.40,
     "days_since_signup":12,"pricing_visits":2,"session_errors":2,"days_since_last_event":5},
    # Enterprise: rules block (different flow)
    {"user_id":"u_9901","error_rate":0.05,"plan":"enterprise","intent_score":0.10,
     "days_since_signup":180,"pricing_visits":0,"session_errors":0,"days_since_last_event":2},
]

def run() -> None:
    print("=" * 65)
    print("DECISION ORCHESTRATOR — Layered decision pipeline")
    print("=" * 65)

    print(f"\n[INDIVIDUAL DECISIONS]\n")
    for user in TEST_USERS:
        result = make_decision(user)
        layers = " → ".join(result.layer_path)
        llm_icon = "🤖" if result.llm_called else "  "
        print(f"  {llm_icon} {result.user_id:8s}  [{layers:20s}]  "
              f"action={result.final_action:35s}  conf={result.confidence:.2f}  "
              f"{result.total_ms:.0f}ms")

    print(f"\n[BATCH SUMMARY]")
    summary = process_batch(TEST_USERS)
    for k, v in summary.items():
        print(f"  {k}: {v}")

    # Cost comparison
    n = len(TEST_USERS)
    llm_only_cost  = n * 0.0005
    layered_cost   = summary["llm_calls"] * 0.0005
    print(f"\n[COST COMPARISON]  (at $0.0005/LLM call)")
    print(f"  LLM-only:  {n} calls = ${llm_only_cost:.4f}")
    print(f"  Layered:   {summary['llm_calls']} calls = ${layered_cost:.4f}")
    print(f"  Savings:   {(1-layered_cost/llm_only_cost):.0%} cost reduction")

    print(f"\n{'='*65}")
    print(f"  The layered system routes {summary['llm_pct']} of cases to LLM.")
    print(f"  Rules and ML handle the rest — faster, cheaper, deterministic.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
