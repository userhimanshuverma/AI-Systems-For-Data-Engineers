# Day 13 — Data Freshness in RAG Systems

> **Phase 3 — Making Data LLM-Ready**
> A RAG system that answers with yesterday's data is worse than no system at all — because it's confidently wrong.

---

## Introduction

RAG (Retrieval-Augmented Generation) is only as good as what it retrieves. And what it retrieves is only as good as what's in the vector store. And what's in the vector store is only as fresh as the last time you ran your embedding pipeline.

This is the freshness problem: **the world changes, but your embeddings don't — unless you make them**.

A user who was healthy yesterday can be at high churn risk today. A support ticket filed this morning contains critical context. A product that was in stock an hour ago is now sold out. If your vector store doesn't reflect these changes, your LLM will answer confidently based on outdated facts.

Stale embeddings don't produce errors. They produce wrong answers that look correct. That's the dangerous part.

---

## What is Data Freshness?

**Data freshness** in a RAG system is the measure of how closely the content in your vector store reflects the current state of the world.

```
Freshness = 1 - (average age of embeddings / acceptable staleness threshold)

Example:
  Embeddings last updated: 4 hours ago
  Acceptable staleness:    1 hour
  Freshness score:         1 - (4/1) = -3  → STALE (below 0 = unacceptable)
```

### Freshness vs Latency

These are related but different:
- **Latency** = how fast the system responds to a query
- **Freshness** = how current the data is that the system responds with

You can have a fast system (low latency) that serves stale data (low freshness). This is the worst combination for AI systems — fast, confident, wrong.

### Retrieval Correctness

A fresh system retrieves documents that reflect the current state. A stale system retrieves documents that reflect a past state. The LLM cannot distinguish between them — it reasons over whatever it receives.

```
Fresh retrieval:  "User u_4821 has 5 checkout errors today. Churn risk: HIGH."
Stale retrieval:  "User u_4821 has 0 errors. No churn risk detected."

Same user. Same query. Opposite answers. The LLM confidently delivers both.
```

---

## How RAG Systems Become Stale

### 1. Static Embeddings (Most Common)
The embedding pipeline runs once at setup. New events arrive in Kafka, get processed by Flink, land in Pinot — but the embedding pipeline is never triggered again.

```
t=0:   Embedding pipeline runs. Vector store has 10K documents.
t=1h:  1,000 new events arrive. Vector store still has 10K documents.
t=2h:  User u_4821 hits 5 checkout errors. Not in vector store.
t=2h:  Support agent asks: "Is u_4821 having issues?"
       LLM retrieves old embeddings: "No issues detected."
       WRONG.
```

### 2. Delayed Updates
The embedding pipeline runs on a schedule (e.g., hourly batch job). Events that arrived in the last 59 minutes are not yet embedded.

```
Batch job runs at 00:00, 01:00, 02:00...
User churns at 01:45.
Next embedding run: 02:00.
For 15 minutes, the vector store has no record of the churn.
```

### 3. Outdated Context
Even if events are embedded promptly, the *context* of older embeddings becomes outdated. An embedding created when a user was on the free plan is now misleading if they've upgraded to pro.

```
Old embedding: "User u_4821 (free plan, at_risk) viewed /pricing"
Current state: User u_4821 is now on pro plan, no longer at_risk

The old embedding still exists in the vector store.
A query about u_4821's current plan will retrieve this stale context.
```

### 4. Model Version Drift
The embedding model is upgraded. New embeddings use the new model. Old embeddings use the old model. They're not comparable — similarity scores between old and new embeddings are meaningless.

---

## Real-World Failure Example

**Scenario:** SaaS support system. User u_4821 was healthy 3 hours ago. In the last 2 hours, they hit 8 checkout errors and submitted 2 support tickets.

**Embedding pipeline:** Runs every 4 hours (batch job).

**What happens:**
```
3 hours ago:  Last embedding run. u_4821 has 0 errors. Embedded as "healthy user."
2 hours ago:  u_4821 starts hitting checkout errors. Not yet embedded.
Now:          Support agent asks: "What's going on with u_4821?"

Vector store retrieves: "User u_4821 (free plan) viewed /home. No issues."
LLM responds: "User u_4821 appears to be browsing normally. No issues detected."

Reality: User has 8 errors, 2 support tickets, and is about to churn.
```

The system didn't fail. It responded confidently. It was just completely wrong.

---

## Why This Problem is Dangerous

### Silent Failure
Stale embeddings don't throw errors. The vector store returns results. The LLM generates a response. Everything looks fine. The failure is invisible until a user reports a wrong answer — or churns because no one intervened.

### Confident but Incorrect Responses
LLMs don't know their context is stale. They reason over whatever they receive and produce confident, well-structured responses. A stale context produces a confident wrong answer, which is more dangerous than no answer.

### Compounding Effect
The longer the embedding pipeline is delayed, the more stale the vector store becomes. A 4-hour delay means 4 hours of events are missing. At 1,000 events/hour, that's 4,000 missing data points — and the LLM is reasoning over a 4-hour-old picture of the world.

---

## Freshness Strategies

### 1. Incremental Re-embedding (Recommended for most systems)
Embed new and changed documents as they arrive. Only re-embed what has changed.

```
Trigger: New event arrives in Kafka
Action:  Compute content_hash of event text
         If hash differs from stored hash → re-embed and upsert
         If hash matches → skip (no change)

Latency: ~1-2 seconds from event to embedded
Cost:    Only changed documents are re-embedded
```

**Best for:** User activity events, support tickets, any high-velocity data.

### 2. Full Re-indexing (For model upgrades or logic changes)
Re-embed the entire collection when the embedding model or context engineering logic changes.

```
Trigger: Model upgrade OR context engineering logic change
Action:  Batch job reads all source documents
         Re-embeds all documents with new model/logic
         Replaces entire vector collection

Duration: Hours to days depending on collection size
Cost:     High (embed everything)
```

**Best for:** Model upgrades, major schema changes, periodic quality audits.

### 3. Event-Driven Updates (Real-time freshness)
Trigger embedding updates from Kafka events. Every new event immediately triggers an embedding upsert.

```
Kafka consumer (embedding-pipeline group):
  for event in kafka.consume("user.events.enriched"):
      text  = event_to_text(event)
      hash  = sha256(text)
      if hash != stored_hash(event.id):
          vector = embed(text)
          vector_store.upsert(event.id, vector, metadata)
          store_hash(event.id, hash)
```

**Best for:** Support tooling, fraud detection, any system where freshness < 5 seconds is required.

### 4. Time-Based Refresh (TTL)
Assign a TTL (time-to-live) to each embedding. Re-embed when TTL expires.

```
User activity events:    TTL = 1 hour
Support tickets:         TTL = 24 hours
Product catalog:         TTL = 7 days
Historical documents:    TTL = never (static)
```

**Best for:** Mixed-freshness systems where different document types have different update rates.

---

## Monitoring Freshness

### Freshness Metrics to Track

| Metric | Definition | Alert threshold |
|--------|-----------|----------------|
| `embedding_lag_p50` | Median time from event to embedded | > 60 seconds |
| `embedding_lag_p99` | 99th percentile embedding lag | > 300 seconds |
| `stale_doc_ratio` | % of docs older than TTL | > 5% |
| `index_age_max` | Age of oldest document in index | > 24 hours |
| `hash_mismatch_rate` | % of docs where hash has changed | Spike = data drift |

### Retrieval Drift Detection
Compare retrieval results over time for the same query. If the top-k results change significantly without a corresponding change in the query, the index may be drifting.

```python
# Run this daily:
baseline_results = vector_store.search("checkout errors", top_k=5)
current_results  = vector_store.search("checkout errors", top_k=5)

overlap = len(set(r.id for r in baseline_results) &
              set(r.id for r in current_results))
drift_score = 1 - (overlap / 5)
# drift_score > 0.4 → significant retrieval drift → investigate
```

### Embedding Versioning
Tag every embedding with the model name and version used to create it.

```json
{
  "doc_id":        "evt_a003",
  "vector":        [...],
  "model_name":    "text-embedding-3-small",
  "model_version": "2024-02",
  "embedded_at":   "2026-04-27T14:32:01Z",
  "content_hash":  "fd15ce1f2796441d"
}
```

When you upgrade the model, you can identify all documents that need re-embedding by filtering on `model_version`.

---

## Where This Fits in Architecture

```
Kafka (user.events.enriched)
    │
    ├── Pinot connector → Pinot table (structured, queryable)
    │
    └── Embedding consumer (event-driven)
            │
            ▼
        Content hash check
            │
            ├── Hash unchanged → SKIP
            │
            └── Hash changed → embed → upsert → Vector Store
                                                      │
                                              Freshness monitor
                                              (tracks lag, TTL, drift)
                                                      │
                                                      ▼
                                              Retrieval Layer
                                              (fresh context for LLM)
```

---

## Common Mistakes

### 1. One-Time Embeddings
```
❌ Run embedding pipeline once at launch, never again
✅ Treat embeddings as derived data that must be kept in sync with source
```

### 2. Ignoring Updates
```
❌ Assume events don't change after they're logged
✅ Enrichment data changes (churn_risk, intent_score update over time)
   Re-embed when the text description of an event changes
```

### 3. No Freshness Monitoring
```
❌ Assume the embedding pipeline is running correctly
✅ Monitor embedding_lag, stale_doc_ratio, and retrieval drift
   Silent failures are the most dangerous kind
```

### 4. Batch-Only Embedding for Real-Time Use Cases
```
❌ Run hourly batch embedding job for a support tool that needs < 5s freshness
✅ Match embedding strategy to freshness SLA:
   Support tooling: event-driven (< 5s)
   Weekly reports:  daily batch is fine
```

### 5. Not Versioning Embeddings
```
❌ Upgrade embedding model without re-indexing
✅ Tag embeddings with model version. Re-index on model upgrade.
   Mixed-model collections produce meaningless similarity scores.
```

---

## Key Takeaways

1. **Stale embeddings produce confident wrong answers.** The LLM doesn't know the context is outdated. It reasons over whatever it receives.

2. **Freshness is a pipeline concern, not a model concern.** The LLM can't fix stale data. Only your embedding pipeline can.

3. **Match freshness strategy to use case.** Support tooling needs event-driven updates. Historical analysis can tolerate daily batch.

4. **Content hashing prevents unnecessary re-embedding.** Only re-embed when the text description actually changes. This keeps costs manageable.

5. **Monitor embedding lag and retrieval drift.** Silent failures are the most dangerous. Alert before users notice wrong answers.

6. **Version your embeddings.** When you upgrade the model, you need to know which documents to re-embed. Without versioning, you can't.

---

## What's Next

**Day 14** — Hybrid Retrieval: combining vector similarity search with keyword search for better precision.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
