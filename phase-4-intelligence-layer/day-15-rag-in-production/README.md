# Day 15 — RAG in Real Systems (Not Toy Examples)

> **Phase 4 — Intelligence Layer**
> The gap between a demo and a production RAG system is not the LLM — it's everything around it.

---

## Introduction

Every RAG tutorial shows the same three steps: embed the query, search the vector store, send the top-k chunks to the LLM. It works in a notebook. It fails in production.

The failure isn't dramatic. The system responds. It generates fluent, confident text. But the answers are wrong — because the retrieval was wrong, the context was stale, the query was misunderstood, or the LLM hallucinated a number that no one validated.

Production RAG is not about a better LLM. It's about building the five layers that make retrieval trustworthy: query understanding, structured retrieval, semantic retrieval, context filtering, and output validation. This day covers all five.

---

## Why Toy RAG Fails

The naive pattern looks like this:

```
User Query → embed(query) → vector_search(top_k=5) → LLM(chunks) → Answer
```

It's clean. It's teachable. It breaks in at least five ways the moment real users touch it.

### No Query Understanding

"Show me errors" and "why is this user churning?" are treated identically. Both get embedded, both get vector-searched, both get the same top-k treatment. But they are fundamentally different queries:

- "Show me errors" → needs structured retrieval: `SELECT * FROM errors WHERE ts > now()-1h`
- "Why is this user churning?" → needs behavioral context: semantic search over activity events

A single retrieval strategy cannot serve both. Without query understanding, you're guessing.

### No Structured Retrieval

Vector search cannot answer: "How many checkout errors did user u_4821 have in the last hour?" It can find semantically similar documents. It cannot count, aggregate, filter by time range, or join across dimensions.

For any question involving numbers, counts, rankings, or time windows, you need SQL — specifically, a system like Apache Pinot that can answer these queries in milliseconds over real-time data.

### No Context Filtering

The naive pattern sends all retrieved chunks to the LLM. If top-k=5 and each chunk is 200 tokens, that's 1,000 tokens of context — some of it relevant, some of it noise. LLMs degrade with noisy context. Irrelevant chunks dilute the signal and increase the chance of hallucination.

Production systems score, rank, and filter retrieved context before it reaches the LLM. Only the most relevant, most recent, non-duplicate chunks make the cut.

### No Freshness Awareness

Vector stores don't update themselves. If your embedding pipeline runs hourly, every query in the last 59 minutes is answered with hour-old context. For a user who just hit 8 checkout errors, that's the difference between "no issues detected" and "critical churn risk."

Stale embeddings don't throw errors. They produce confident wrong answers. That's the dangerous part.

### No Output Validation

The LLM response is trusted blindly. If the LLM hallucinates a user ID, invents a metric, or returns malformed JSON, the system passes it downstream. Production systems validate LLM output: required fields present, confidence above threshold, no contradictions with the structured data that was retrieved.

---

## What Real RAG Systems Actually Need

Five layers, each solving a specific failure mode:

### Layer 1 — Query Understanding

Before any retrieval happens, classify the query:

- **Intent classification** — what kind of answer does this query need? (churn analysis, error investigation, upgrade analysis, retention analysis, general)
- **Entity extraction** — which user, which time range, which plan segment?
- **Retrieval routing** — based on intent and entities, decide: use Pinot? use vector search? both? what filters?

```
Query: "Which free-plan users are most at risk this week?"
→ intent: churn_analysis
→ entities: {plan_filter: "free", time_range_hours: 168}
→ routing: use_pinot=True, use_vector=True, pinot_filters={plan: "free", churn_risk: True}
```

### Layer 2 — Structured Retrieval

Apache Pinot (or any OLAP store) handles the factual, countable, filterable questions:

- Top users by error rate in the last N hours
- Count of events by type per user
- Aggregated metrics: session duration, page views, conversion funnel

Pinot answers these in milliseconds. Vector search cannot.

### Layer 3 — Semantic Retrieval

The vector store handles behavioral context — the *why* behind the numbers:

- What was the user doing before they churned?
- What error messages appeared in their session?
- What features did they engage with?

Vector search finds semantically similar events. It surfaces context that SQL can't express.

### Layer 4 — Context Filtering

Both retrieval layers return candidates. Not all of them go to the LLM:

- **Relevance scoring** — combine vector similarity score + recency + metadata match
- **Token budgeting** — keep total context under 400 tokens (quality degrades above this)
- **Deduplication** — remove chunks with overlapping event IDs
- **Ordering** — most relevant first; most recent first for ties

### Layer 5 — Reasoning Layer

The LLM receives a structured prompt with filtered context. Its output is validated:

- Required fields present (users, risk_level, evidence, confidence)
- Confidence above threshold (reject low-confidence responses)
- No contradiction with structured data (if Pinot says 0 errors, LLM can't say "many errors")

---

## Retrieval Challenges in Production

### Noisy Retrieval

Top-k vector search returns the k most similar documents — but "most similar" doesn't mean "most relevant." A query about checkout errors might retrieve documents about the checkout page design, the payment team's roadmap, and a user who mentioned "errors" in a different context.

Noisy retrieval is worse than no retrieval. It gives the LLM false signal to reason over.

**Fix:** Score chunks by relevance (not just similarity), filter below a threshold, cap at a token budget.

### Stale Context

Embeddings are computed at a point in time. If the embedding pipeline runs hourly, the vector store is always up to 59 minutes behind. For real-time support tooling, that's unacceptable.

**Fix:** Event-driven embedding updates. Re-embed on content hash change. Monitor embedding lag.

### Token Limits

GPT-4 has a 128K context window, but quality degrades well before that. Studies show LLM reasoning quality drops significantly above 4K tokens of context, and the "lost in the middle" problem means chunks in the middle of a long context are often ignored.

**Fix:** Hard token budget (400 tokens for context). Rank and select, don't dump everything.

### Latency

Pinot query + vector search + LLM call in sequence = 2-4 seconds. Users expect < 1 second.

**Fix:** Run Pinot and vector search in parallel. Cache frequent queries. Set timeouts — if retrieval takes > 500ms, proceed with partial results rather than blocking.

### Conflicting Signals

Pinot says "user has 0 errors in the last hour." Vector store returns an event: "user hit checkout error, payment failed." These are not contradictory — the Pinot query might be scoped to a different time window. But the LLM will see both and may produce a confused response.

**Fix:** Include metadata (timestamps, sources) with every chunk. Let the LLM reason about the provenance of each piece of evidence.

---

## Hybrid Retrieval in Production

Pinot and the vector store are not alternatives — they're complements. Every production RAG system needs both.

```
                    ┌─────────────────────────────────┐
                    │         Query Understanding      │
                    │  intent + entities + routing     │
                    └──────────┬──────────────────────┘
                               │
               ┌───────────────┴───────────────┐
               │                               │
               ▼                               ▼
    ┌──────────────────┐           ┌──────────────────────┐
    │   Pinot (SQL)    │           │   Vector Store       │
    │                  │           │                      │
    │ • counts         │           │ • behavioral context │
    │ • aggregations   │           │ • semantic similarity│
    │ • time filters   │           │ • event narratives   │
    │ • rankings       │           │ • "why" questions    │
    └────────┬─────────┘           └──────────┬───────────┘
             │                                │
             └──────────────┬─────────────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │   Context Filter     │
                 │ score + rank + trim  │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │        LLM           │
                 │  + output validation │
                 └──────────────────────┘
```

The parallel retrieval pattern is critical for latency. Both queries fire simultaneously. The context filter merges and ranks the results. The LLM sees a clean, token-budgeted context.

---

## Context Selection Layer

Not all retrieved data should reach the LLM. The context selection layer is what separates production RAG from toy RAG.

### Relevance Scoring

Each retrieved chunk gets a score combining three signals:

```
relevance_score = (
    0.5 * vector_similarity_score   +   # how semantically close
    0.3 * recency_score             +   # how recent (exponential decay)
    0.2 * metadata_match_score          # does metadata match query entities?
)
```

Chunks below a relevance threshold (e.g., 0.3) are dropped regardless of how many were retrieved.

### Token Budgeting

The LLM context window is a shared resource. Structured metrics (from Pinot) get priority — they're factual and compact. Semantic chunks fill the remaining budget.

```
Total budget:        400 tokens
Structured metrics:  ~80 tokens  (always included)
Semantic chunks:     up to 320 tokens (fill with highest-scored chunks)
```

If the top chunk is 200 tokens and the second is 180 tokens, only the top chunk fits. The second is dropped.

### Deduplication

Vector search can return multiple chunks describing the same event (if the event was embedded multiple times, or if similar events exist). Deduplicate by `event_id` before scoring.

### Ordering

The LLM attends more strongly to the beginning and end of the context (primacy and recency effects). Put the most relevant chunk first. For ties in relevance, put the most recent chunk first.

---

## Real-World Example

**Query:** "Which free-plan users are most at risk this week and why?"

### Step 1 — Query Understanding

```python
intent = "churn_analysis"
entities = {
    "plan_filter": "free",
    "time_range_hours": 168,   # 7 days
    "segment_filter": None
}
retrieval_plan = {
    "use_pinot": True,
    "use_vector": True,
    "pinot_filters": {"plan": "free", "churn_risk": True},
    "vector_query": "free plan user churn risk behavior errors",
    "top_k": 5,
    "freshness_required": True
}
```

### Step 2 — Structured Retrieval (Pinot)

```sql
SELECT user_id, error_rate, session_count, last_active_hours_ago, churn_risk_score
FROM user_metrics
WHERE plan = 'free'
  AND churn_risk = true
  AND last_active_hours_ago < 168
ORDER BY churn_risk_score DESC
LIMIT 10
```

Returns: top 10 free-plan users by churn risk score with their error rates and activity metrics.

### Step 3 — Semantic Retrieval (Vector Store)

For each of the top 10 users from Pinot, run a vector search filtered by `user_id`:

```python
for user in pinot_results[:10]:
    chunks = vector_store.search(
        query="churn risk behavior errors",
        filter={"user_id": user["user_id"]},
        top_k=3
    )
```

Returns: up to 3 behavioral event descriptions per user.

### Step 4 — Context Filter

Score all chunks. Apply token budget. Select top-5 users with the richest context (highest combined relevance score across their chunks).

```
Before filter: 10 users × 3 chunks = 30 chunks, ~1,200 tokens
After filter:  5 users × 2 chunks = 10 chunks, ~380 tokens
```

### Step 5 — LLM Reasoning

The LLM receives a structured prompt:

```
You are a retention analyst. Based on the following data, identify the top free-plan
users at churn risk this week and explain why each is at risk.

STRUCTURED METRICS:
user_id=u_4821: error_rate=0.34, sessions=2, last_active=18h ago, churn_risk=0.91
user_id=u_3302: error_rate=0.21, sessions=4, last_active=6h ago, churn_risk=0.78
...

BEHAVIORAL CONTEXT:
[u_4821] Hit checkout error 3 times, payment failed, viewed /pricing page
[u_3302] Reached feature limit, viewed upgrade page, did not convert
...

Return JSON: {users: [{user_id, risk_level, primary_reason, evidence}], confidence}
```

Output: ranked list with specific evidence per user, validated against structured data.

---

## Common Mistakes

### 1. Over-Relying on Vector Search

Vector search is powerful for semantic similarity. It cannot count, aggregate, or filter by time. If your RAG system only uses vector search, it will fail on any question involving numbers or time ranges.

```
❌ "How many errors did u_4821 have today?" → vector search → wrong
✅ "How many errors did u_4821 have today?" → Pinot SQL → correct
```

### 2. Sending Too Much Context

More context is not better. LLMs have a "lost in the middle" problem — they attend strongly to the beginning and end of the context, and weakly to the middle. Sending 20 chunks when 4 would suffice actively degrades answer quality.

```
❌ top_k=20, send all chunks to LLM
✅ top_k=20, score and filter to top-4, token budget = 400
```

### 3. Ignoring Retrieval Quality

If retrieval is wrong, the LLM answer is wrong. No amount of prompt engineering fixes bad retrieval. Monitor retrieval precision: for a sample of queries, manually check whether the retrieved chunks are actually relevant.

```
❌ Assume vector search returns relevant results
✅ Score relevance, filter below threshold, monitor retrieval precision
```

### 4. No Output Validation

LLMs hallucinate. They invent user IDs, fabricate metrics, and return malformed JSON. If you pass LLM output directly to downstream systems without validation, you will eventually corrupt data or make wrong decisions.

```
❌ Trust LLM output blindly
✅ Validate: required fields present, confidence above threshold, no contradictions
```

### 5. Single Retrieval Strategy for All Query Types

A query about a specific user needs different retrieval than a query about a user segment. A question about errors needs different retrieval than a question about upgrade intent. One retrieval strategy cannot serve all query types well.

```
❌ Same top_k=5 vector search for every query
✅ Classify intent → route to appropriate retrieval strategy
```

---

## Key Takeaways

1. **The toy RAG pattern fails in production** because it has no query understanding, no structured retrieval, no context filtering, and no output validation. The LLM is the least of your problems.

2. **Hybrid retrieval is not optional.** Pinot handles facts, counts, and aggregations. Vector search handles behavioral context and semantic similarity. You need both.

3. **Context filtering is what separates production RAG from toy RAG.** Score, rank, deduplicate, and token-budget your context before it reaches the LLM.

4. **Query understanding determines retrieval quality.** Classify intent before retrieval. Route different query types to different retrieval strategies.

5. **Validate LLM output.** Required fields, confidence thresholds, contradiction checks. Never pass raw LLM output to downstream systems without validation.

6. **Latency requires parallelism.** Run Pinot and vector search simultaneously. Cache frequent queries. Set timeouts and proceed with partial results rather than blocking.

---

## What's Next

**Day 16** — Query Understanding Layer: building a robust intent classifier and entity extractor that routes queries to the right retrieval strategy.

---

*Part of the [AI Systems for Data Engineers](../../../README.md) — 28-Day Roadmap*
