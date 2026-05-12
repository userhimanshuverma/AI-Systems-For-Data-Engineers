# Day 19 — Decision Layer Design

> **Phase 4 — Intelligence Layer**
> Production AI systems don't make decisions with LLMs alone. They layer rules, ML predictions, and LLM reasoning — each doing what it's best at.

---

## Introduction

Every mature AI system eventually converges on the same architecture: a layered decision system where deterministic rules, ML models, and LLMs each play a specific role.

This isn't a compromise. It's the correct design. Each layer has different strengths, different failure modes, and different costs. Using all three — in the right order — produces decisions that are faster, cheaper, more reliable, and more explainable than any single layer alone.

---

## Why LLM-Only Systems Fail

Building a decision system that routes everything through an LLM seems appealing. One model, one interface, one deployment. In practice, it fails in four ways:

### Inconsistency
The same input can produce different outputs on different calls. An LLM that decides "should we send a retention offer?" may say yes on Monday and no on Tuesday for identical user data. Rules and ML models are deterministic — same input, same output, every time.

### Latency
LLM inference takes 200ms–2s per call. A decision system that processes 10,000 events per second cannot route every event through an LLM. Rules execute in microseconds. ML inference takes 1–10ms. Reserve LLMs for the cases that genuinely need reasoning.

### Hallucinations
LLMs can generate plausible-sounding but incorrect decisions. An LLM asked "should we flag this transaction as fraud?" may confidently say yes or no based on pattern-matching in its training data — not on the actual transaction features. ML models trained on your data are far more reliable for classification tasks.

### Cost
At $0.15–$5.00 per million tokens, routing every decision through an LLM is expensive at scale. A rules engine costs nothing. An ML model costs milliseconds of compute. Use LLMs only where their reasoning capability adds value that cheaper systems cannot provide.

---

## Decision Layer Architecture

### Layer 1 — Rules Engine (Deterministic)

Applies hardcoded business logic that must always be enforced.

- Validates inputs and applies threshold-based decisions
- Enforces business constraints
- Detects obvious anomalies
- Blocks or fast-tracks cases that don't need ML or LLM
- Deterministic, instant, free, auditable

### Layer 2 — ML Predictor (Probabilistic)

Applies trained models to score, classify, and rank cases that passed the rules layer.

- Predicts churn probability (0.0–1.0)
- Scores upgrade intent and anomaly likelihood
- Ranks users by intervention priority
- Fast (1–10ms), trained on your data, requires maintenance

### Layer 3 — LLM Reasoning (Generative)

Applies language model reasoning to cases that need explanation, synthesis, or nuanced judgment.

- Explains why a user is at risk in plain language
- Synthesizes signals from multiple sources
- Recommends specific actions with evidence
- Slow (200ms–2s), expensive, powerful, non-deterministic

---

## How These Layers Work Together

### Orchestration Flow

```
Event arrives
    │
    ▼
[Rules Engine]
    ├── BLOCK → skip (inactive user, invalid data)
    ├── FAST TRACK → immediate action (critical error rate)
    └── PASS → continue to ML
    │
    ▼
[ML Predictor]
    ├── LOW SCORE (< 0.4) → no action needed
    ├── MEDIUM SCORE (0.4–0.6) → automated action
    └── HIGH SCORE (> 0.6) → escalate to LLM
    │
    ▼
[LLM Reasoning] (only for high-risk cases)
    ├── Generate explanation
    ├── Recommend specific action
    └── Produce confidence score
    │
    ▼
[Decision Output]
    action + reason + confidence + evidence
```

### Decision Routing

| Case | Rules | ML | LLM | Reason |
|------|-------|----|----|--------|
| Inactive user | ✅ BLOCK | ❌ | ❌ | Rules handle it instantly |
| Critical error rate | ✅ FAST TRACK | ❌ | ❌ | No analysis needed |
| Low-risk user | ✅ PASS | ✅ LOW | ❌ | ML says no action |
| Medium-risk user | ✅ PASS | ✅ MEDIUM | ❌ | Automated action |
| High-risk user | ✅ PASS | ✅ HIGH | ✅ | Needs explanation |

---

## Real-World Example — Premium User Retention Analysis

**Scenario:** 50,000 free-plan users. Identify who is at risk of churning.

| Step | Layer | Users processed | Result |
|------|-------|----------------|--------|
| 1 | Rules | 50,000 | 12,847 blocked/fast-tracked |
| 2 | ML | 37,153 | 35,500 low/medium risk handled |
| 3 | LLM | 1,653 | Full explanation + action |

**Cost comparison:**

| Approach | LLM calls | Cost | Time |
|----------|-----------|------|------|
| LLM-only | 50,000 | ~$25 | ~14h |
| Layered | 1,653 | ~$0.83 | ~30min |

The layered system is **30x faster and 30x cheaper** while producing better decisions.

---

## Reliability Benefits

- **Stable decisions** — rules and ML are deterministic
- **Lower hallucination risk** — LLMs only see pre-validated, high-confidence cases
- **Lower cost** — only 3.3% of cases reach the LLM
- **Better explainability** — every decision has a traceable path through all three layers

---

## Common Mistakes

1. **Replacing rules with prompts** — rules are free and instant; never use LLM for threshold checks
2. **Replacing ML with LLMs** — LLMs aren't trained on your data; use ML for prediction tasks
3. **No confidence boundaries** — low-confidence decisions must be flagged for human review
4. **Routing everything to LLM** — filter aggressively with rules and ML first
5. **No fallback when LLM fails** — degrade gracefully to ML score + rules-based action

---

## Key Takeaways

1. **Layer your decision system.** Rules → ML → LLM. Each does what it's best at.
2. **Rules are free and instant.** Never use an LLM for threshold checks or validation.
3. **ML is trained on your data.** For prediction tasks, a trained model beats an LLM every time.
4. **LLMs are for reasoning, not classification.** Use them to explain and synthesize, not to replace deterministic logic.
5. **Confidence layering enables human oversight.** Low-confidence decisions get flagged; high-confidence decisions get automated.
6. **The layered system is 30x cheaper and faster.** Filter with rules and ML first to minimize LLM calls.

---

## What's Next

**Phase 5 (Days 20–23)** — Orchestration and Reliability: Apache Airflow, async architectures, failure modes, and observability.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
