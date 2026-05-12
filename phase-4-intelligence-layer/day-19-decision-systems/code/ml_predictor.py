"""
ML Predictor — Day 19: Decision Layer Design
=============================================
Layer 2 of the decision system. Applies a trained ML model to score
users who passed the rules layer.

In production: load a trained model (scikit-learn, XGBoost, etc.)
and run inference on extracted features.

Here we simulate a gradient boosting model with feature-weighted scoring.
The weights represent what a real model might learn from historical churn data.

Properties:
  - Probabilistic: returns a score 0.0–1.0, not a binary decision
  - Fast: 1–10ms per inference
  - Trained on your data: reflects actual patterns
  - Requires maintenance: models drift and need retraining
"""

import time
import math
from dataclasses import dataclass


# ── ML RESULT ─────────────────────────────────────────────────────────────────

@dataclass
class MLResult:
    churn_probability: float    # 0.0 = no risk, 1.0 = certain churn
    intent_score:      float    # upgrade intent 0.0–1.0
    anomaly_score:     float    # how unusual this user's behavior is
    risk_tier:         str      # "low", "medium", "high"
    action:            str      # recommended action from ML layer
    confidence:        float    # model confidence
    features_used:     list[str]
    latency_ms:        float


# ── FEATURE EXTRACTION ────────────────────────────────────────────────────────

def extract_features(user: dict) -> dict:
    """
    Extracts ML features from raw user data.
    In production: this runs in a feature store or Flink enrichment pipeline.
    """
    return {
        "error_rate":          user.get("error_rate", 0.0),
        "intent_score":        user.get("intent_score", 0.0),
        "is_free_plan":        1.0 if user.get("plan") == "free" else 0.0,
        "days_since_signup_norm": min(user.get("days_since_signup", 30) / 90.0, 1.0),
        "pricing_visits_norm": min(user.get("pricing_visits", 0) / 5.0, 1.0),
        "session_errors":      min(user.get("session_errors", 0) / 10.0, 1.0),
    }


# ── SIMULATED GRADIENT BOOSTING MODEL ────────────────────────────────────────

# Feature weights (what a trained model might learn)
CHURN_WEIGHTS = {
    "error_rate":             0.40,
    "intent_score":          -0.15,  # high intent = lower churn (they want to stay)
    "is_free_plan":           0.20,
    "days_since_signup_norm": 0.10,
    "pricing_visits_norm":   -0.05,  # pricing visits = engagement = lower churn
    "session_errors":         0.15,
}

INTENT_WEIGHTS = {
    "pricing_visits_norm":    0.50,
    "intent_score":           0.30,
    "is_free_plan":           0.10,
    "error_rate":            -0.10,  # errors reduce conversion
}

def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))

def predict_churn(features: dict) -> float:
    """Simulates gradient boosting churn prediction."""
    raw = sum(features.get(k, 0) * w for k, w in CHURN_WEIGHTS.items())
    # Shift to center around 0.5 for typical users
    return round(_sigmoid(raw * 3 - 1.5), 3)

def predict_intent(features: dict) -> float:
    """Simulates upgrade intent scoring."""
    raw = sum(features.get(k, 0) * w for k, w in INTENT_WEIGHTS.items())
    return round(max(0.0, min(1.0, raw)), 3)

def detect_anomaly(features: dict) -> float:
    """
    Simulates anomaly detection (isolation forest / z-score).
    High score = unusual behavior pattern.
    """
    # Anomaly: very high error rate + high intent = unusual (blocked conversion)
    if features["error_rate"] > 0.5 and features["intent_score"] > 0.6:
        return 0.85
    # Anomaly: zero activity but not inactive
    if features["error_rate"] == 0 and features["intent_score"] == 0:
        return 0.60
    return round(features["error_rate"] * 0.4 + features["session_errors"] * 0.3, 3)


# ── RISK TIER ASSIGNMENT ──────────────────────────────────────────────────────

def assign_risk_tier(churn_prob: float) -> tuple[str, str]:
    """Returns (risk_tier, recommended_action)."""
    if churn_prob >= 0.6:
        return "high",   "escalate_to_llm"
    elif churn_prob >= 0.4:
        return "medium", "send_retention_email"
    else:
        return "low",    "no_action"


# ── MAIN PREDICTOR ────────────────────────────────────────────────────────────

def predict(user: dict) -> MLResult:
    """
    Runs ML prediction on a user who passed the rules layer.
    Returns churn probability, intent score, anomaly score, and recommended action.
    """
    t0 = time.perf_counter()

    # Extract features
    features = extract_features(user)

    # Run predictions
    churn_prob    = predict_churn(features)
    intent        = predict_intent(features)
    anomaly       = detect_anomaly(features)
    tier, action  = assign_risk_tier(churn_prob)

    # Simulate model inference latency (~5ms)
    time.sleep(0.005)

    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    return MLResult(
        churn_probability=churn_prob,
        intent_score=intent,
        anomaly_score=anomaly,
        risk_tier=tier,
        action=action,
        confidence=0.85,  # model accuracy on validation set
        features_used=list(features.keys()),
        latency_ms=latency_ms,
    )


# ── DEMO ──────────────────────────────────────────────────────────────────────

TEST_USERS = [
    {"user_id":"u_4821","error_rate":0.50,"plan":"free",  "intent_score":0.82,"days_since_signup":45,"pricing_visits":3,"session_errors":5},
    {"user_id":"u_0012","error_rate":0.00,"plan":"pro",   "intent_score":0.30,"days_since_signup":180,"pricing_visits":1,"session_errors":0},
    {"user_id":"u_7734","error_rate":0.33,"plan":"free",  "intent_score":0.40,"days_since_signup":12,"pricing_visits":2,"session_errors":2},
    {"user_id":"u_5566","error_rate":0.10,"plan":"free",  "intent_score":0.20,"days_since_signup":60,"pricing_visits":0,"session_errors":1},
]

def run() -> None:
    print("=" * 65)
    print("ML PREDICTOR — Layer 2: Probabilistic scoring")
    print("=" * 65)

    tiers = {"low": 0, "medium": 0, "high": 0}

    for user in TEST_USERS:
        result = predict(user)
        tiers[result.risk_tier] += 1
        icon = {"low":"🟢","medium":"🟡","high":"🔴"}[result.risk_tier]
        print(f"\n  {icon} {user['user_id']:8s}")
        print(f"     churn_prob:  {result.churn_probability:.3f}")
        print(f"     intent:      {result.intent_score:.3f}")
        print(f"     anomaly:     {result.anomaly_score:.3f}")
        print(f"     risk_tier:   {result.risk_tier}")
        print(f"     action:      {result.action}")
        print(f"     confidence:  {result.confidence:.0%}")
        print(f"     latency:     {result.latency_ms}ms")

    print(f"\n{'='*65}")
    print(f"  Risk distribution: {tiers}")
    print(f"  Only 'high' tier cases escalate to LLM.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
