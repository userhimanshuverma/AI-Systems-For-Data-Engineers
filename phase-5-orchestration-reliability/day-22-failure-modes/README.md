# Day 22 — Failure Modes in AI Systems

> **Phase 5 — Orchestration & Reliability**
> Traditional systems fail loudly. AI systems fail quietly — and confidently.

---

## Introduction

A traditional system failure is obvious: the server returns a 500, the database throws an exception, the pipeline stops. You know something is wrong.

An AI system failure is different. The LLM returns a well-formatted, confident-sounding response. The support agent reads it and acts on it. The business makes a decision. Only later — sometimes much later — does someone notice the answer was wrong.

This is the defining characteristic of AI system failures: **they are believable**. The system doesn't crash. It produces output that looks correct but isn't. Detecting and preventing these failures requires a different approach than traditional reliability engineering.

---

## Types of Failure Modes

### 1. Hallucinations
The LLM generates plausible-sounding content that is factually incorrect or unsupported by the retrieved context.

**Example:**
```
Context: "User u_4821 had 3 errors in the last 2 hours."
LLM output: "User u_4821 has had 12 errors over the past week, 
             suggesting a persistent infrastructure issue."
```
The LLM invented "12 errors" and "past week" — neither is in the context. The output sounds authoritative.

**Root cause:** LLMs are trained to produce fluent, coherent text. When context is insufficient, they fill gaps with plausible-sounding content from their training data.

**Detection:** Output validation — check that all cited numbers and facts appear in the retrieved context.

### 2. Stale Retrieval
The vector store returns embeddings that no longer reflect the current state of the world.

**Example:**
```
Reality: User u_4821 churned 30 minutes ago (5 checkout errors)
Vector store: Last updated 4 hours ago — shows "0 errors, healthy"
LLM output: "User u_4821 appears healthy. No action needed."
```
The LLM is not hallucinating — it's reasoning correctly over stale data. The failure is in the retrieval layer.

**Root cause:** Embedding refresh pipeline failed or ran too infrequently.

**Detection:** Freshness monitoring — track embedding age and alert when > SLA.

### 3. Timeout Cascades
A slow downstream component causes upstream components to wait, eventually timing out and triggering retries, which further overload the slow component.

**Example:**
```
LLM API slow (2s instead of 500ms)
→ Retrieval layer waits
→ API gateway times out (30s)
→ Client retries
→ More requests hit the already-slow LLM
→ LLM gets slower
→ More timeouts
→ Cascade
```

**Root cause:** No circuit breaker. No timeout per component. Retries without backoff.

**Detection:** Latency percentile monitoring (P99 > threshold → alert).

### 4. Retry Storms
Multiple components retry simultaneously after a failure, overwhelming the recovering service.

**Example:**
```
Vector store restarts (30 seconds downtime)
→ 1,000 workers all fail simultaneously
→ All 1,000 workers retry at t=30s
→ Vector store receives 1,000 simultaneous requests on startup
→ Vector store crashes again
→ Cycle repeats
```

**Root cause:** No exponential backoff. No jitter. All workers retry at the same time.

**Detection:** Request rate spike after a service recovery event.

### 5. Noisy Context
The retrieval layer returns irrelevant or contradictory documents that confuse the LLM.

**Example:**
```
Query: "Why is user u_4821 at risk?"
Retrieved: [
  "User u_4821 hit error on /checkout",     ← relevant
  "User u_9901 upgraded to pro plan",        ← WRONG USER
  "Checkout page redesign completed",        ← irrelevant
  "User u_4821 viewed /home",               ← low signal
]
LLM output: "User u_4821 recently upgraded to pro plan and 
             is not at risk." (confused by u_9901's data)
```

**Root cause:** Missing metadata filter. Vector search returned documents from other users.

**Detection:** Retrieval quality monitoring — check that returned documents match the query's user_id filter.

### 6. Bad Embeddings
Embeddings generated from thin or incorrect text produce poor retrieval results.

**Example:**
```
Event text: "User u_4821 did something at 14:32"  ← thin context
Embedding: generic vector, matches everything weakly
Retrieval: returns random events, not the relevant ones
LLM: reasons over irrelevant context → wrong answer
```

**Root cause:** Context engineering failure (Day 10). Event text doesn't contain enough semantic signal.

**Detection:** Retrieval precision monitoring — run test queries and check that expected documents are returned.

### 7. Tool Failures
An agent calls a tool that fails, returns incorrect data, or times out. The agent may proceed with incomplete information.

**Example:**
```
Agent calls query_pinot("SELECT error_rate WHERE user_id='u_4821'")
Pinot broker is restarting → returns empty result
Agent: "No errors found for u_4821" (incorrect — Pinot was unavailable)
LLM: "User appears healthy" (wrong conclusion from empty data)
```

**Root cause:** No fallback when tool returns empty or error result. Agent doesn't distinguish "no data" from "data not available."

**Detection:** Tool call success rate monitoring. Validate tool outputs before passing to LLM.

### 8. Silent Degradation
The system continues to function but quality gradually degrades over time. No alerts fire. No errors are logged.

**Example:**
```
Week 1: Embedding model upgraded. Old embeddings not re-indexed.
Week 2: 20% of vectors are from old model. Retrieval quality drops slightly.
Week 3: 40% old vectors. Retrieval quality drops noticeably.
Week 4: 60% old vectors. LLM answers are frequently wrong.
Month 2: Support team reports "AI assistant is getting worse."
```

**Root cause:** No embedding version tracking. No retrieval quality monitoring. No freshness SLA.

**Detection:** Periodic retrieval quality benchmarks. Embedding version audits.

---

## Why AI Failures Are Dangerous

### Believable but Incorrect Outputs
An LLM that says "I don't know" is safe. An LLM that says "User u_4821 is healthy, no action needed" with 94% confidence — when the user is actually churning — is dangerous. The confidence score makes the wrong answer more convincing.

### Silent Quality Degradation
Traditional systems have binary states: working or broken. AI systems have a quality spectrum. A system can be "working" (returning responses) while producing increasingly wrong answers. Without active quality monitoring, this degradation is invisible.

### Hard-to-Detect Reasoning Failures
When an LLM reasons incorrectly over correct data, the failure is in the reasoning chain — not in any single component. No error is thrown. No metric spikes. The output just happens to be wrong.

---

## Failure Propagation Across Architecture

```
KAFKA (ingestion layer)
  Failure: consumer lag builds up
  Impact: events not processed → Flink enrichment delayed
  Propagation: → Pinot data becomes stale → embeddings become stale
               → LLM retrieves outdated context → wrong answers

FLINK (processing layer)
  Failure: enrichment job crashes
  Impact: raw events reach Pinot without enrichment
  Propagation: → Pinot missing plan/segment columns → queries fail
               → LLM receives incomplete structured context

PINOT (analytics layer)
  Failure: broker restart, segment corruption
  Impact: SQL queries return empty or error
  Propagation: → Agent tool call returns empty → LLM assumes "no data"
               → LLM concludes "no issues" → wrong recommendation

VECTOR STORE (retrieval layer)
  Failure: index stale, collection unavailable
  Impact: semantic search returns empty or wrong results
  Propagation: → LLM has no behavioral context → hallucinates details
               → or reasons over wrong user's events

LLM API (reasoning layer)
  Failure: timeout, rate limit, model degradation
  Impact: no response or low-quality response
  Propagation: → Agent retries → retry storm → cascade
               → or fallback to cached/stale response

AGENT LAYER (orchestration)
  Failure: tool selection error, infinite loop, context overflow
  Impact: wrong tools called, wrong conclusions
  Propagation: → Wrong actions triggered → incorrect business decisions
```

---

## Hallucination vs Retrieval Failure

These are often confused but have different root causes and different fixes:

| Type | Root Cause | Fix |
|------|-----------|-----|
| **Model hallucination** | LLM fills gaps with training data | Better system prompt, output validation, grounding checks |
| **Retrieval-induced hallucination** | LLM reasons over wrong/irrelevant context | Better retrieval (metadata filters, re-ranking) |
| **Stale-context reasoning** | LLM reasons over outdated context | Freshness monitoring, embedding refresh SLA |

The most common failure in production RAG systems is **retrieval-induced hallucination** — the LLM is not "making things up" in the traditional sense; it's reasoning correctly over incorrect input.

---

## Reliability Engineering Patterns

### 1. Retries with Exponential Backoff
```python
for attempt in range(max_retries):
    try:
        return call_tool(args)
    except TransientError:
        time.sleep(base_delay * (2 ** attempt) + random.uniform(0, 1))
raise PermanentFailure("max retries exceeded")
```

### 2. Circuit Breakers
Stop calling a failing service before it cascades:
```python
if circuit_breaker.is_open("pinot"):
    return fallback_response()  # don't even try
result = call_pinot(query)
circuit_breaker.record_success("pinot")
```

A circuit breaker has three states:
- **Closed** (normal): requests pass through
- **Open** (failing): requests are blocked, fallback is used
- **Half-open** (recovering): one test request is allowed through

### 3. Fallback Logic
When a component fails, return a degraded but safe response:
```python
try:
    metrics = query_pinot(user_id)
except PinotUnavailable:
    metrics = get_cached_metrics(user_id)  # stale but better than nothing
    metrics["_stale"] = True
    metrics["_stale_age_s"] = cache_age_seconds()
```

### 4. Confidence Thresholds
Don't act on low-confidence LLM outputs:
```python
response = llm.generate(context, query)
if response.confidence < 0.6:
    return {"status": "uncertain", "message": "Insufficient data for confident answer",
            "raw_response": response}
# Only act on high-confidence responses
```

### 5. Validation Layers
Validate LLM output before acting on it:
```python
def validate_llm_output(output: dict, context: dict) -> tuple[bool, str]:
    # Check all cited numbers appear in context
    for number in extract_numbers(output["summary"]):
        if not number_in_context(number, context):
            return False, f"Hallucinated number: {number}"
    # Check confidence is above threshold
    if output["confidence"] < 0.6:
        return False, f"Low confidence: {output['confidence']}"
    return True, "ok"
```

### 6. Graceful Degradation
When the full system is unavailable, return a reduced but honest response:
```python
def get_user_analysis(user_id: str) -> dict:
    available = check_component_health()

    if available["pinot"] and available["vector_store"]:
        return full_analysis(user_id)          # full response
    elif available["pinot"]:
        return metrics_only_analysis(user_id)  # partial response
    elif available["vector_store"]:
        return context_only_analysis(user_id)  # partial response
    else:
        return {"status": "degraded", "message": "Analysis unavailable. Try again in 5 minutes."}
```

---

## Real-World Example — Conversion Drop Investigation

**Scenario:** Product team asks: "Why did our free-to-pro conversion rate drop 15% this week?"

### What Went Wrong (Failure Chain)

```
Monday 00:00: Embedding refresh job fails silently (Airflow alert missed)
Monday 00:30: Vector store now 4 hours stale
Monday 09:00: Product analyst asks AI assistant about conversion drop

AI assistant retrieves:
  Pinot: current week metrics (accurate)
  Vector store: events from 4 hours ago (stale — misses Monday's errors)

LLM receives:
  Structured: "conversion_rate=0.12 (down from 0.14)"
  Semantic: "Users visiting /pricing, clicking upgrade" (stale — no error events)

LLM concludes:
  "Conversion drop appears to be due to reduced pricing page engagement.
   Recommend: A/B test new pricing page copy."

Reality:
  Monday 00:00-09:00: Payment gateway had 847 errors
  Real cause: checkout failures, not pricing page engagement
  Real fix: escalate to engineering, not A/B test
```

### The Damage
The product team runs an A/B test on pricing copy for 2 weeks. Conversion doesn't improve. Engineering eventually discovers the payment gateway issue. 2 weeks of incorrect diagnosis, wasted A/B test, and continued checkout failures.

### The Fix
- Embedding freshness monitoring: alert when vector store > 1 hour stale
- Retrieval quality validation: check that retrieved events match the query time range
- Output grounding check: verify LLM conclusions are supported by retrieved data
- Confidence threshold: flag low-confidence responses for human review

---

## Common Mistakes

### 1. Monitoring Only Uptime
```
❌ Alert only when the API returns 500
✅ Monitor retrieval quality, embedding freshness, LLM confidence scores
   A system can be "up" while producing wrong answers
```

### 2. Ignoring Retrieval Quality
```
❌ Assume vector search always returns relevant results
✅ Run periodic retrieval quality benchmarks
   Track precision@k over time. Alert when it drops.
```

### 3. Infinite Retries
```
❌ Retry forever until success
✅ Max retries + exponential backoff + circuit breaker
   Infinite retries cause retry storms and mask permanent failures
```

### 4. No Validation Layer
```
❌ Trust LLM output directly and act on it
✅ Validate: structure, confidence, grounding, consistency
   Low-confidence or ungrounded responses → flag for human review
```

### 5. No Graceful Degradation
```
❌ Return error when any component is unavailable
✅ Return partial response with clear "degraded" flag
   "Metrics available, behavioral context unavailable" is better than 503
```

---

## Key Takeaways

1. **AI systems fail quietly.** The most dangerous failures produce confident-sounding wrong answers, not errors. Monitor quality, not just uptime.

2. **Retrieval-induced hallucination is the most common failure.** The LLM isn't making things up — it's reasoning correctly over wrong input. Fix the retrieval layer.

3. **Stale context is a silent killer.** An embedding refresh failure that goes undetected for hours produces increasingly wrong answers with no error signals.

4. **Circuit breakers prevent cascade failures.** When a component is failing, stop calling it. Use fallback logic. Let it recover.

5. **Validate LLM output before acting.** Check confidence scores, verify cited facts appear in context, flag low-confidence responses for human review.

6. **Graceful degradation beats hard failures.** A partial response with a clear "degraded" flag is more useful than a 503 error.

---

## What's Next

**Day 23** — Observability: instrumenting AI systems with logs, metrics, traces, and LLM-specific quality monitoring.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
