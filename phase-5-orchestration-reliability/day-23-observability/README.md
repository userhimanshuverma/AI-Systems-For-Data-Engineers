# Day 23 — Observability for AI Systems

> **Phase 5 — Orchestration & Reliability**
> Traditional monitoring tells you if the system is running. Observability tells you if the system is working correctly.

---

## Introduction

On Day 22 we cataloged how AI systems fail. Today we answer: how do you know when they're failing?

Traditional monitoring — CPU, memory, uptime, error rates — is necessary but not sufficient for AI systems. A system can be 100% available, returning 200 OK on every request, with zero infrastructure errors, while producing confidently wrong answers to every query.

Observability for AI systems means instrumenting the **quality of reasoning**, not just the health of infrastructure.

---

## Monitoring vs Observability

### Traditional Monitoring
Answers: "Is the system up?"
- CPU utilization
- Memory usage
- Request error rate (5xx)
- Response time (P99)
- Service uptime

These metrics tell you nothing about whether the LLM is hallucinating, whether the vector store is returning stale results, or whether retrieval quality has degraded.

### AI Observability
Answers: "Is the system working correctly?"
- Retrieval precision@k (are the right documents being returned?)
- LLM confidence score distribution (are responses confident?)
- Hallucination detection rate (are facts grounded in context?)
- Embedding freshness (how old is the vector store?)
- Context token usage (is context growing uncontrollably?)
- Reasoning consistency (do similar queries produce consistent answers?)
- Workflow trace completeness (did all pipeline steps execute?)

### The Gap
```
Traditional monitoring says: ✅ All services healthy, 0% error rate
AI observability says:       ❌ Retrieval precision dropped from 0.91 to 0.62
                             ❌ 23% of LLM responses have low confidence
                             ❌ Vector store embeddings are 4 hours stale
```

The system is "up" but producing wrong answers. Only AI observability catches this.

---

## What AI Systems Need Observability For

### Retrieval Quality
The most common silent failure. Vector search returns irrelevant documents. Precision@k drops. The LLM reasons over wrong context.

**What to track:**
- `retrieval_precision_at_k` — fraction of top-k results that are relevant
- `retrieval_recall_at_k` — fraction of relevant documents in top-k
- `avg_similarity_score` — mean cosine similarity of returned results
- `empty_result_rate` — fraction of queries returning 0 results

### Hallucinations
LLM outputs that are not grounded in the retrieved context.

**What to track:**
- `hallucination_rate` — fraction of responses with ungrounded facts
- `confidence_score_p10` — 10th percentile confidence (low = many uncertain responses)
- `grounding_check_pass_rate` — fraction of responses passing grounding validation

### Context Drift
The distribution of retrieved context shifts over time as the vector store is updated.

**What to track:**
- `context_similarity_drift` — how much retrieved context has changed for the same queries
- `embedding_model_version_mix` — fraction of embeddings from each model version

### Stale Embeddings
Embeddings not updated after source data changes.

**What to track:**
- `embedding_age_p99` — 99th percentile age of embeddings in the index
- `stale_embedding_ratio` — fraction of embeddings older than SLA
- `embedding_refresh_lag_s` — time from event to embedding

### Latency Across Layers
End-to-end latency broken down by component.

**What to track:**
- `retrieval_latency_ms_p99` — Pinot + vector search combined
- `llm_latency_ms_p99` — LLM inference time
- `e2e_latency_ms_p99` — total query-to-response time
- `context_assembly_latency_ms` — time to merge and format context

### Workflow Reliability
Airflow DAG health, retry counts, SLA compliance.

**What to track:**
- `dag_success_rate` — fraction of DAG runs that succeed
- `task_retry_count` — retries per task per run
- `sla_miss_rate` — fraction of tasks missing their SLA
- `embedding_refresh_success_rate` — most critical pipeline

### Token Growth and Cost
LLM token usage growing uncontrollably increases cost and degrades quality.

**What to track:**
- `avg_context_tokens` — average tokens in LLM context window
- `avg_response_tokens` — average tokens in LLM response
- `cost_per_query_usd` — estimated cost per query
- `token_budget_exceeded_rate` — fraction of queries hitting token limit

---

## AI Observability Layers

### Logs
Structured logs for every significant event in the AI pipeline.

```json
{
  "ts":           "2026-04-27T14:32:01.412Z",
  "trace_id":     "trace_a1b2c3",
  "span_id":      "span_001",
  "component":    "retrieval_layer",
  "event":        "vector_search_complete",
  "user_id":      "u_4821",
  "query":        "checkout errors",
  "top_k":        4,
  "results_count":4,
  "avg_score":    0.87,
  "latency_ms":   52,
  "embedding_age_s": 45
}
```

### Traces
Distributed traces that follow a single request through all pipeline components.

```
Trace: trace_a1b2c3 (total: 650ms)
  ├── span: query_parse          (5ms)
  ├── span: pinot_query          (68ms)
  ├── span: vector_search        (52ms)
  ├── span: context_assembly     (8ms)
  ├── span: llm_call             (510ms)
  └── span: output_validation    (7ms)
```

### Metrics
Time-series metrics for dashboards and alerting.

```
retrieval_precision_at_4{dag="embedding_refresh"} 0.91
llm_confidence_p10 0.72
hallucination_rate 0.03
embedding_age_p99_seconds 45
e2e_latency_p99_ms 650
cost_per_query_usd 0.00048
```

### Evaluations
Periodic quality assessments using a golden test set.

```python
# Run daily: compare top-k results against known-good answers
for query, expected_docs in golden_test_set:
    retrieved = vector_store.search(query, top_k=4)
    precision = len(set(retrieved) & set(expected_docs)) / 4
    evaluation_log.record(query, precision, datetime.now())
```

### Workflow Tracing
Track every step of every Airflow DAG run.

```
DAG: embedding_refresh_pipeline | Run: 2026-04-27T14:30
  Task: detect_changed_documents  ✅ 847 docs | 68ms
  Task: generate_embeddings       ✅ 847 vecs | 12.3s (2 retries)
  Task: upsert_to_vector_store    ✅ 847 upserted | 2.1s
  Task: validate_retrieval_quality ✅ precision=0.91 | 1.2s
  SLA: 30min | Actual: 16min | ✅ Within SLA
```

---

## Retrieval Observability

### Relevance Scoring
Track the distribution of similarity scores returned by vector search.

```
Normal:   avg_score=0.87, min_score=0.71 → good retrieval
Degraded: avg_score=0.52, min_score=0.31 → poor retrieval
          → Alert: avg_score < 0.65
```

### Retrieval Precision
Run a golden test set periodically and measure precision@k.

```python
# Golden test set: known queries with known relevant documents
test_cases = [
    ("checkout errors", ["evt_001", "evt_002", "evt_003"]),
    ("upgrade intent",  ["evt_010", "evt_011"]),
]

for query, expected in test_cases:
    retrieved = [r.id for r in vector_store.search(query, top_k=4)]
    precision = len(set(retrieved) & set(expected)) / 4
    # Alert if precision < 0.70
```

### Context Freshness
Track the age of embeddings returned by vector search.

```python
# For each retrieved document, check its embedding age
for doc in retrieved_docs:
    age_s = (now - doc.embedded_at).total_seconds()
    if age_s > 3600:  # > 1 hour
        stale_count += 1
# Alert if stale_count / total > 0.10
```

---

## LLM Observability

### Hallucination Detection
Validate that LLM outputs are grounded in retrieved context.

```python
def check_grounding(output: str, context: str) -> float:
    """Returns grounding score 0.0-1.0."""
    cited_numbers = extract_numbers(output)
    context_numbers = extract_numbers(context)
    if not cited_numbers:
        return 1.0  # no numbers to check
    grounded = sum(1 for n in cited_numbers if n in context_numbers)
    return grounded / len(cited_numbers)
```

### Reasoning Consistency
Run the same query multiple times and check that responses are consistent.

```python
# Alert if the same query produces contradictory answers
responses = [llm.generate(context, query) for _ in range(3)]
actions = [r["action"] for r in responses]
if len(set(actions)) > 1:
    log_inconsistency(query, actions)
```

### Token Usage
Track token consumption to detect runaway context growth.

```python
# Alert if avg_context_tokens > 600 (budget: 400)
# This indicates context assembly is not filtering properly
```

---

## Workflow Observability

### Retries
Track retry counts per task. High retries indicate flaky dependencies.

```
Alert: task retry_count > 2 in last 24h
       → Investigate: API rate limits? Network instability?
```

### Queue Growth
Track Kafka consumer lag and async queue depth.

```
Alert: kafka_consumer_lag > 10,000 messages
       → Investigate: Flink job slow? Worker count insufficient?
```

### Orchestration Failures
Track DAG failure rates and SLA misses.

```
Alert: dag_success_rate < 0.95 over last 24h
Alert: sla_miss_rate > 0.05 over last 24h
```

---

## Real-World Example — Retention Analysis System

**Scenario:** The AI retention analysis system starts producing wrong recommendations. No infrastructure alerts have fired.

### What Observability Reveals

```
Day 1 (baseline):
  retrieval_precision_at_4: 0.91  ✅
  hallucination_rate:        0.03  ✅
  embedding_age_p99_s:       45    ✅
  llm_confidence_p10:        0.72  ✅

Day 3 (degraded):
  retrieval_precision_at_4: 0.62  ❌ ALERT: dropped 32%
  hallucination_rate:        0.18  ❌ ALERT: 6x increase
  embedding_age_p99_s:       14400 ❌ ALERT: 4 hours stale
  llm_confidence_p10:        0.41  ❌ ALERT: low confidence

Root cause (from traces):
  embedding_refresh DAG: FAILED on Day 2 at 02:00
  Airflow alert: MISSED (alert email went to spam)
  Vector store: 4 hours stale
  LLM: reasoning over outdated context → wrong recommendations
```

### The Fix
1. Embedding freshness alert fires → on-call engineer notified
2. Embedding refresh DAG re-triggered manually
3. Vector store updated
4. Retrieval precision recovers to 0.91
5. Hallucination rate drops back to 0.03

**Without observability:** The system would have continued producing wrong recommendations for days until a user reported it.

---

## Common Mistakes

### 1. Monitoring Only Uptime
```
❌ Alert only on 5xx errors and service downtime
✅ Monitor retrieval precision, LLM confidence, embedding freshness
   A system can be "up" while producing wrong answers
```

### 2. Ignoring Retrieval Metrics
```
❌ Assume vector search always returns relevant results
✅ Run daily precision@k benchmarks against a golden test set
   Retrieval quality is the most common silent failure
```

### 3. No Evaluation Pipeline
```
❌ Deploy LLM changes without measuring response quality
✅ Run automated evaluations before and after every change
   Track: grounding score, confidence distribution, consistency
```

### 4. No Tracing Between Layers
```
❌ Log each component independently with no correlation
✅ Use trace IDs to follow a single request through all layers
   Without traces, you cannot diagnose multi-component failures
```

### 5. No Cost Monitoring
```
❌ Ignore token usage until the bill arrives
✅ Track cost_per_query and alert on spikes
   A context assembly bug can 10x your LLM costs overnight
```

---

## Key Takeaways

1. **Traditional monitoring is insufficient.** CPU and uptime tell you nothing about retrieval quality or hallucination rates. You need AI-specific metrics.

2. **Retrieval quality is the most important metric.** Most AI system failures start with degraded retrieval. Monitor precision@k daily.

3. **Traces connect the dots.** A single request touches 5+ components. Without distributed tracing, you cannot diagnose multi-component failures.

4. **Evaluations are not optional.** Run automated quality assessments on a golden test set. Alert when quality drops. This is the only way to catch silent degradation.

5. **Monitor cost alongside quality.** Token usage growth is a leading indicator of context assembly problems. Alert before the bill arrives.

6. **Embedding freshness is a leading indicator.** Stale embeddings precede retrieval degradation, which precedes hallucination increases. Monitor freshness first.

---

## What's Next

**Phase 6 (Days 24–26)** — Scaling and Cost: cost optimization, scaling systems, and performance optimization.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
