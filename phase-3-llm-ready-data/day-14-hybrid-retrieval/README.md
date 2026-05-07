# Day 14 — Hybrid Retrieval (Structured + Unstructured)

> **Phase 3 — Making Data LLM-Ready**
> Vector search finds what's semantically similar. Structured queries find what's exactly true. Neither alone is enough. Together, they give the LLM the complete picture.

---

## Introduction

On Day 11 we built embedding pipelines. On Day 12 we designed vector storage. On Day 13 we kept embeddings fresh. Now we answer the final retrieval question: **how do you combine structured metrics with semantic context to give the LLM the best possible input?**

Pure vector search is powerful but incomplete. It finds semantically similar events — but it can't tell you "how many errors did this user have in the last hour?" or "which users have churn_risk=TRUE right now?" Those questions require structured queries against Apache Pinot.

Pure structured queries are precise but narrow. They can count errors and compute rates — but they can't find "events that describe checkout frustration" or "support tickets similar to this one." Those questions require semantic search.

**Hybrid retrieval** combines both. The LLM receives structured facts (from Pinot) and semantic context (from the vector store) in a single assembled context. This is what makes AI responses both accurate and insightful.

---

## Structured Retrieval vs Semantic Retrieval

### Structured Retrieval (Apache Pinot)

Structured retrieval answers questions with **exact, computable answers**.

**What it does:**
- Filtering: `WHERE churn_risk = true AND plan = 'free'`
- Aggregations: `COUNT(*), AVG(error_rate), MAX(intent_score)`
- Time-window analysis: `WHERE ts > ago('1h')`
- Exact matching: `WHERE user_id = 'u_4821'`
- Ranking: `ORDER BY error_rate DESC LIMIT 10`

**What it cannot do:**
- Find documents by meaning ("checkout frustration")
- Retrieve behavioral narratives
- Match unstructured text (support tickets, transcripts)

**Example:**
```sql
SELECT user_id, error_rate, intent_score, churn_risk
FROM user_events_realtime
WHERE user_id = 'u_4821'
  AND ts > ago('7d')
ORDER BY ts DESC
LIMIT 1
```
Returns: `{error_rate: 0.50, intent_score: 0.82, churn_risk: true}`

This is a fact. It's precise. But it doesn't explain *why* the user is at risk or *what* they've been experiencing.

### Semantic Retrieval (Vector DB)

Semantic retrieval answers questions by **finding meaning-similar content**.

**What it does:**
- Similarity search: find events semantically related to a query
- Context matching: retrieve behavioral narratives
- Pattern discovery: find similar past incidents
- Unstructured text: match support tickets, transcripts, notes

**What it cannot do:**
- Compute exact aggregations
- Filter by precise numeric thresholds
- Answer "how many" or "what percentage" questions reliably

**Example:**
```python
results = vector_store.search(
    query="checkout errors and payment failures",
    filter={"user_id": "u_4821"},
    top_k=4
)
```
Returns: 4 event descriptions that semantically match "checkout errors" — including events described as "payment failed", "500 on billing page", "transaction declined".

This is context. It's rich. But it doesn't give you the exact error count or rate.

---

## Why Hybrid Retrieval Matters

The LLM needs both to give a complete, accurate, actionable response:

| Question | Needs | Source |
|----------|-------|--------|
| "How many errors?" | Exact count | Pinot |
| "What is the error rate?" | Computed metric | Pinot |
| "Is this user at risk?" | Boolean flag | Pinot |
| "What has the user been experiencing?" | Narrative context | Vector DB |
| "Are there similar past incidents?" | Semantic similarity | Vector DB |
| "What did the user say in their ticket?" | Unstructured text | Vector DB |

Without Pinot: the LLM gets narrative context but no hard numbers. It may hallucinate counts.
Without the vector store: the LLM gets numbers but no behavioral story. It can't explain *why*.
With both: the LLM gets facts + context = complete picture.

---

## Role of Apache Pinot

Pinot is the **structured retrieval layer**. It answers the "what" and "how much" questions.

### Real-Time Analytics
Pinot ingests from Kafka in real-time. Data is queryable within ~1 second of arrival. This means the structured metrics the LLM receives reflect the current state of the world.

### Filtering
```sql
-- Find all free-plan users with high churn risk in the last hour
SELECT user_id, error_rate, intent_score
FROM user_events_realtime
WHERE plan = 'free'
  AND churn_risk = true
  AND ts > ago('1h')
ORDER BY error_rate DESC
LIMIT 20
```

### Aggregations
```sql
-- Session summary for a specific user
SELECT
  user_id,
  COUNT(*)                                    AS total_events,
  SUM(CASE WHEN event_type LIKE '%error%' THEN 1 ELSE 0 END) AS error_count,
  MAX(error_rate)                             AS peak_error_rate,
  MAX(intent_score)                           AS peak_intent,
  BOOL_OR(churn_risk)                         AS ever_churn_risk
FROM user_events_realtime
WHERE user_id = 'u_4821'
  AND ts > ago('7d')
GROUP BY user_id
```

### Time-Window Analysis
```sql
-- Error trend: last 1h vs last 24h
SELECT
  COUNT(CASE WHEN ts > ago('1h')  THEN 1 END) AS errors_1h,
  COUNT(CASE WHEN ts > ago('24h') THEN 1 END) AS errors_24h
FROM user_events_realtime
WHERE user_id = 'u_4821'
  AND event_type = 'system.server_error'
```

---

## Role of Vector DB

The vector DB is the **semantic retrieval layer**. It answers the "what happened" and "what does this mean" questions.

### Embedding Retrieval
Given a query, find the top-k most semantically similar stored documents. The query and documents are compared in vector space — no keyword overlap required.

### Semantic Matching
```python
# Finds events related to "checkout frustration" even if they say
# "payment failed", "billing error", "transaction declined"
results = vector_store.search(
    query="checkout frustration and payment issues",
    filter={"user_id": "u_4821"},
    top_k=4
)
```

### Context Discovery
The vector store surfaces the behavioral narrative: what the user was doing, what they experienced, what they said. This is the story that explains the numbers from Pinot.

---

## End-to-End Hybrid Retrieval Flow

```
User Query: "Why is user u_4821 at risk of churning?"
                │
                ▼
        [Query Parser]
        intent = churn_investigation
        user_id = u_4821
                │
        ┌───────┴───────┐
        │               │
        ▼               ▼
[Pinot SQL Query]   [Vector Search]
SELECT metrics      embed(query)
WHERE user_id=      → top-4 similar
'u_4821'            events for u_4821
        │               │
        └───────┬───────┘
                ▼
        [Context Merger]
        Combine structured metrics
        + semantic event descriptions
        Token-budget the result
                │
                ▼
             [LLM]
        Receives: facts + context
        Returns: explanation + action
```

### What the LLM Receives

```
[STRUCTURED — from Pinot]
User u_4821 metrics (last 7 days):
  - Total events: 24
  - Errors: 5 (error_rate: 50%)
  - Pricing page visits: 3
  - Upgrade intent score: 0.82
  - Churn risk: TRUE
  - Plan: free

[SEMANTIC — from Vector DB]
Relevant events (top-4 by similarity):
  1. "User u_4821 hit 500 error on /checkout at 14:32. Churn risk: TRUE."
  2. "User u_4821 clicked 'Upgrade to Pro' on /pricing. Intent: 0.82."
  3. "Support ticket: checkout keeps failing with server error."
  4. "User u_4821 hit 500 error on /checkout at 14:38."

[QUERY]
Why is this user at risk of churning?
```

### LLM Response

```json
{
  "summary": "User u_4821 (free plan) is at HIGH churn risk. They have a 50% error
              rate (5 errors in 7 days), all on /checkout. Despite 3 visits to /pricing
              and clicking 'Upgrade to Pro', checkout failures are blocking conversion.
              They submitted a support ticket about the issue.",
  "action": "escalate_checkout_fix",
  "confidence": 0.96,
  "evidence": [
    "5 checkout errors, 50% error rate (Pinot)",
    "Upgrade intent score 0.82 — user wants to convert (Pinot)",
    "Clicked 'Upgrade to Pro' after each error (Vector DB)",
    "Support ticket: 'checkout keeps failing' (Vector DB)"
  ]
}
```

The structured data provides the numbers. The semantic data provides the story. Together they produce a response that is both accurate and actionable.

---

## Real-World Example — Premium User Drop-Off Analysis

**Business question:** "Which free-plan users are most likely to churn this week, and why?"

### Step 1: Structured Query (Pinot)
```sql
SELECT user_id, error_rate, intent_score, pricing_visits
FROM user_events_realtime
WHERE plan = 'free'
  AND churn_risk = true
  AND ts > ago('7d')
ORDER BY error_rate DESC
LIMIT 10
```
Returns: 10 users with highest error rates + intent scores.

### Step 2: Semantic Query (Vector DB)
For each of the 10 users, retrieve top-3 semantic events:
```python
for user_id in at_risk_users:
    events = vector_store.search(
        query="checkout errors and upgrade intent",
        filter={"user_id": user_id},
        top_k=3
    )
```

### Step 3: Context Merge
Combine Pinot metrics + semantic events for each user into a structured context block.

### Step 4: LLM Analysis
Pass the merged context to the LLM:
*"Analyze these 10 at-risk users. For each, explain the likely churn reason and recommend an action."*

### Result
The LLM produces a prioritized list with specific evidence for each user — something no SQL query or keyword search could produce alone.

---

## Common Mistakes

### 1. Using Only Vector Search
```
❌ Retrieve only semantic events, no structured metrics
✅ Always combine: Pinot for facts, vector DB for context
   Without Pinot: LLM may hallucinate error counts
   Without vector DB: LLM has numbers but no behavioral story
```

### 2. Ignoring Structured Filtering
```
❌ Search all vectors without metadata filters
✅ Always filter by user_id, date range, event_type
   Without filters: results include irrelevant users and old events
```

### 3. Sending Raw Results Directly to LLM
```
❌ Dump Pinot rows + vector results as JSON to LLM
✅ Merge and format into natural language context (Day 10)
   Raw data produces vague LLM responses
```

### 4. Treating Pinot and Vector DB as Alternatives
```
❌ "We have Pinot, we don't need a vector DB"
✅ They serve different purposes. Pinot answers "how many".
   Vector DB answers "what happened". Both are required.
```

### 5. Not Deduplicating Merged Results
```
❌ Pass overlapping Pinot rows and vector chunks to LLM
✅ Deduplicate by event_id before assembling context
   Duplicate context wastes tokens and confuses the LLM
```

---

## Key Takeaways

1. **Hybrid retrieval = structured facts + semantic context.** Neither alone is sufficient for a complete LLM response.

2. **Pinot answers "what" and "how much."** Error counts, rates, flags, aggregations — precise, computable answers.

3. **Vector DB answers "what happened" and "why."** Behavioral narratives, semantic patterns, unstructured text.

4. **The LLM needs both to be accurate and insightful.** Facts without context produce shallow responses. Context without facts produces hallucinated numbers.

5. **Always filter semantic search by metadata.** User ID, date range, event type. Without filters, you retrieve irrelevant documents.

6. **Merge and format before passing to LLM.** Raw Pinot rows + raw vector results produce poor LLM output. Context engineering (Day 10) applies here too.

---

## What's Next

**Phase 4 (Days 15–19)** — The Intelligence Layer: RAG in production, query understanding, agents vs pipelines, agent tooling, and decision systems.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
