"""
LLM Reasoning — Day 19: Decision Layer Design
==============================================
Layer 3 of the decision system. Applies LLM reasoning to high-risk cases
that passed both the rules and ML layers.

The LLM receives:
  - Structured metrics (from Pinot via ML layer)
  - Semantic context (from Vector DB)
  - ML prediction scores
  - The specific question to answer

The LLM produces:
  - A plain-language explanation of why the user is at risk
  - A specific recommended action with evidence
  - A confidence score (validated before acting)

Properties:
  - Generative: produces natural language output
  - Slow: 200ms–2s per call
  - Expensive: per-token cost
  - Powerful: can reason over complex, multi-signal context
  - Non-deterministic: same input may produce different outputs
"""

import time
from dataclasses import dataclass, field


# ── LLM RESULT ────────────────────────────────────────────────────────────────

@dataclass
class LLMResult:
    summary:    str
    action:     str
    confidence: float
    evidence:   list[str]
    reasoning:  str       # the chain of thought
    latency_ms: float
    valid:      bool      # passed output validation


# ── CONTEXT BUILDER ───────────────────────────────────────────────────────────

def build_context(user: dict, ml_result, semantic_chunks: list[str]) -> str:
    """
    Assembles the context passed to the LLM.
    Combines structured metrics + ML scores + semantic events.
    """
    lines = [
        f"User {user['user_id']} ({user.get('plan','?')} plan) — ML analysis:",
        f"  Churn probability: {ml_result.churn_probability:.0%}",
        f"  Upgrade intent:    {ml_result.intent_score:.2f}",
        f"  Anomaly score:     {ml_result.anomaly_score:.2f}",
        f"  Error rate:        {user.get('error_rate',0):.0%}",
        f"  Pricing visits:    {user.get('pricing_visits',0)}",
        "",
        "Recent behavioral context:",
    ]
    for chunk in semantic_chunks[:3]:
        lines.append(f"  - {chunk}")
    return "\n".join(lines)


# ── MOCK LLM ──────────────────────────────────────────────────────────────────

def mock_llm_call(context: str, user: dict, ml_result) -> dict:
    """
    Mocks an LLM API call.

    In production:
        from openai import OpenAI
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": context + "\\n\\nQuestion: " + question}
            ]
        )
        return json.loads(response.choices[0].message.content)
    """
    time.sleep(0.200)  # simulate ~200ms LLM latency

    churn  = ml_result.churn_probability
    intent = ml_result.intent_score
    errors = user.get("error_rate", 0)
    visits = user.get("pricing_visits", 0)
    uid    = user["user_id"]
    plan   = user.get("plan", "?")

    # Simulate different response patterns based on signals
    if errors >= 0.5 and intent >= 0.7:
        return {
            "summary":   f"User {uid} ({plan} plan) is at HIGH churn risk ({churn:.0%}) due to "
                         f"checkout failures blocking a clear upgrade intent ({intent:.2f}). "
                         f"They want to convert but cannot.",
            "action":    "escalate_checkout_fix_and_send_upgrade_offer",
            "confidence":0.94,
            "evidence":  [
                f"{errors:.0%} error rate — checkout failures",
                f"Intent score {intent:.2f} — strong upgrade desire",
                f"{visits} pricing page visits — evaluating upgrade",
                "Support ticket submitted about checkout failures",
            ],
            "reasoning": (
                f"High error rate ({errors:.0%}) combined with high intent ({intent:.2f}) "
                f"indicates a user who wants to upgrade but is blocked by technical issues. "
                f"This is a conversion opportunity, not just a churn risk. "
                f"Fix the checkout issue AND send an upgrade offer simultaneously."
            ),
        }
    elif churn >= 0.6 and intent < 0.4:
        return {
            "summary":   f"User {uid} ({plan} plan) is disengaging ({churn:.0%} churn risk). "
                         f"Low intent ({intent:.2f}) suggests they may not see value.",
            "action":    "send_value_demonstration_email",
            "confidence":0.82,
            "evidence":  [
                f"Churn probability: {churn:.0%}",
                f"Low upgrade intent: {intent:.2f}",
                f"Error rate: {errors:.0%}",
            ],
            "reasoning": (
                f"User shows high churn risk but low upgrade intent. "
                f"This suggests disengagement rather than technical frustration. "
                f"A value demonstration (feature highlights, success stories) "
                f"is more appropriate than a discount offer."
            ),
        }
    else:
        return {
            "summary":   f"User {uid} shows moderate risk ({churn:.0%}). Monitor closely.",
            "action":    "add_to_monitoring_cohort",
            "confidence":0.71,
            "evidence":  [f"Churn probability: {churn:.0%}", f"Intent: {intent:.2f}"],
            "reasoning": "Mixed signals — not enough evidence for a specific intervention.",
        }


# ── OUTPUT VALIDATOR ──────────────────────────────────────────────────────────

def validate_output(output: dict) -> tuple[bool, str]:
    """Validates LLM output before acting on it."""
    required = {"summary", "action", "confidence", "evidence", "reasoning"}
    missing = required - set(output.keys())
    if missing:
        return False, f"missing_fields:{missing}"
    if not isinstance(output["confidence"], (int, float)):
        return False, "confidence_not_numeric"
    if not (0.0 <= output["confidence"] <= 1.0):
        return False, "confidence_out_of_range"
    if output["confidence"] < 0.6:
        return False, f"low_confidence:{output['confidence']:.2f}"
    return True, "ok"


# ── MAIN REASONER ─────────────────────────────────────────────────────────────

SEMANTIC_CHUNKS = {
    "u_4821": [
        "User u_4821 hit 500 error on /checkout. Churn risk: TRUE.",
        "User u_4821 clicked Upgrade to Pro on /pricing. Intent: 0.82.",
        "Support ticket: checkout keeps failing with server error.",
    ],
    "u_7734": [
        "User u_7734 hit 500 error on /checkout.",
        "User u_7734 visited /pricing twice. Moderate intent.",
    ],
}

def reason(user: dict, ml_result) -> LLMResult:
    """
    Runs LLM reasoning on a high-risk user.
    Returns explanation, action, and confidence.
    """
    t0 = time.perf_counter()

    # Get semantic context
    chunks  = SEMANTIC_CHUNKS.get(user["user_id"], ["No recent events found."])
    context = build_context(user, ml_result, chunks)

    # Call LLM
    output = mock_llm_call(context, user, ml_result)

    # Validate output
    valid, val_reason = validate_output(output)

    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    return LLMResult(
        summary=    output.get("summary", ""),
        action=     output.get("action", "no_action"),
        confidence= output.get("confidence", 0.0),
        evidence=   output.get("evidence", []),
        reasoning=  output.get("reasoning", ""),
        latency_ms= latency_ms,
        valid=      valid,
    )


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("LLM REASONING — Layer 3: Explanation and synthesis")
    print("=" * 65)

    from ml_predictor import predict, MLResult

    test_cases = [
        {"user_id":"u_4821","error_rate":0.50,"plan":"free","intent_score":0.82,
         "days_since_signup":45,"pricing_visits":3,"session_errors":5},
        {"user_id":"u_7734","error_rate":0.33,"plan":"free","intent_score":0.40,
         "days_since_signup":12,"pricing_visits":2,"session_errors":2},
    ]

    for user in test_cases:
        ml_result = predict(user)
        if ml_result.risk_tier != "high":
            print(f"\n  {user['user_id']}: risk_tier={ml_result.risk_tier} — skipping LLM")
            continue

        result = reason(user, ml_result)
        valid_icon = "✅" if result.valid else "❌"
        print(f"\n  {valid_icon} {user['user_id']}")
        print(f"     Summary:    {result.summary}")
        print(f"     Action:     {result.action}")
        print(f"     Confidence: {result.confidence:.0%}")
        print(f"     Reasoning:  {result.reasoning[:80]}...")
        print(f"     Evidence:")
        for e in result.evidence:
            print(f"       - {e}")
        print(f"     Latency:    {result.latency_ms}ms")
        print(f"     Valid:      {result.valid}")

    print(f"\n{'='*65}")
    print(f"  LLM only called for high-risk cases.")
    print(f"  Output validated before acting.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
