# Day 02 — Batch vs Real-Time vs AI Systems

> **Phase 1 — Reset the Mental Model**
> Three paradigms. Different contracts. Different failure modes. Knowing which to use — and when to combine them — is the core skill.

---

## Introduction

Most data systems are built on one of three paradigms: **batch**, **real-time**, or **AI-driven**. In practice, production systems use all three — layered on top of each other.

The mistake most engineers make is treating these as alternatives. They're not. They're **complementary layers** with different jobs:

- Batch handles **volume** cheaply
- Real-time handles **latency** at scale
- AI handles **reasoning** over context

Understanding where each layer starts and ends — and what breaks when you misuse one — is what separates a pipeline builder from a systems architect.

---

## Batch Systems

### Definition
A batch system processes data in **scheduled, bounded chunks**. It reads a fixed dataset, transforms it, and writes the result. Then it stops. The next run starts on a schedule.

### How They Work
```
Schedule triggers → Read data window → Transform → Write output → Done
```

The key property: **the input is finite and known at the start of the job**. This makes batch systems simple to reason about, easy to retry, and cheap to run.

### Real-World Examples
- Nightly ETL job aggregating the previous day's transactions into a summary table
- Weekly ML feature computation over 90 days of user behavior
- Monthly billing rollup across all customer accounts
- Daily data quality checks on warehouse tables

### Strengths
- **High throughput** — processes massive datasets efficiently (Spark reads TBs in minutes)
- **Simple failure model** — jobs are idempotent; re-run the same window to fix errors
- **Cost-efficient** — runs on spot/preemptible compute; no always-on infrastructure
- **Easy to test** — deterministic: same input always produces same output
- **Mature tooling** — Spark, dbt, Airflow, BigQuery are battle-tested at scale

### Limitations
- **High latency** — data is stale by definition; hourly batch = up to 60 min lag
- **No event awareness** — can't react to something that just happened
- **Waterfall failures** — a bad upstream run poisons all downstream jobs
- **Not suitable for user-facing features** that require fresh data

---

## Real-Time Systems

### Definition
A real-time system processes data **continuously as events arrive**. There is no fixed start/end — the system runs indefinitely, processing each event within milliseconds to seconds of it occurring.

### Event-Driven Architecture Basics
```
Event occurs → Published to topic → Consumer reads → Processes → Emits result
```

The fundamental unit is the **event** — an immutable record of something that happened, with a timestamp. Events flow through a message bus (Kafka being the standard), and consumers process them independently.

Key concepts:
- **Topic** — a named stream of events (e.g., `user.clicks`, `order.placed`)
- **Partition** — how a topic is split for parallelism and ordering guarantees
- **Consumer group** — multiple consumers sharing the work of reading a topic
- **Offset** — the position of a consumer in a partition; enables replay

### Latency vs Throughput
These are in tension. You can't always have both:

| Goal | Approach | Tradeoff |
|------|----------|----------|
| Lowest latency | Process each event immediately | Lower throughput, higher cost |
| Highest throughput | Micro-batch (buffer 100ms of events) | Slightly higher latency |
| Balance | Tune batch size + parallelism | Requires careful benchmarking |

Kafka + Flink gives you sub-second latency at millions of events/second — but only if your processing logic is stateless or uses efficient state backends (RocksDB).

### Real-World Examples
- Fraud detection: flag a transaction within 200ms of it occurring
- Live leaderboard: update game scores as events arrive
- Real-time personalization: update a user's recommendation feed as they browse
- Alerting: trigger a PagerDuty alert when error rate crosses a threshold

### Strengths
- **Low latency** — react to events within milliseconds
- **Always fresh** — data reflects the current state of the world
- **Decoupled architecture** — producers and consumers are independent
- **Scalable** — Kafka partitions scale horizontally

### Limitations
- **Harder to operate** — stateful stream processing (joins, aggregations) is complex
- **Exactly-once semantics** are non-trivial to implement correctly
- **Higher baseline cost** — always-on infrastructure vs scheduled compute
- **Debugging is harder** — you can't easily "re-run" a stream like a batch job

---

## AI Systems (LLMs)

### What Makes Them Different
LLMs are not query engines. They don't look up answers — they **generate** them by predicting the most likely next token given a context window.

This means:
- They have **no persistent memory** between calls (unless you build it)
- They operate on **text and tokens**, not rows and columns
- Their output is **probabilistic** — the same input can produce different outputs
- They are **context-bound** — they can only reason over what's in the prompt

### Why They Are Not Deterministic
A SQL query on the same data always returns the same result. An LLM call does not.

Even with `temperature=0`, minor differences in tokenization, model version, or system prompt can shift outputs. This matters for:
- **Auditing** — you can't reproduce the exact reasoning path
- **Testing** — you can't assert exact string equality
- **Debugging** — "why did it say that?" is genuinely hard to answer

This doesn't make LLMs unreliable — it means they require **different reliability patterns**: output validation, structured outputs (JSON mode), confidence scoring, and human-in-the-loop for high-stakes decisions.

### Where They Fit
LLMs are the right tool when:
- The question is **open-ended** and can't be answered by a fixed query
- The data is **unstructured** (text, documents, transcripts)
- You need **synthesis** across multiple data sources
- The output is **language** (explanation, summary, recommendation)

LLMs are the wrong tool when:
- You need **exact computation** (use SQL or code)
- You need **guaranteed determinism** (use a rules engine)
- You need **sub-10ms latency** (LLM inference is 100ms–2s)
- The answer is a **simple lookup** (use a database)

---

## Comparison Table

| Dimension | Batch | Real-Time | AI (LLM) |
|-----------|-------|-----------|----------|
| **Latency** | Minutes–hours | Milliseconds–seconds | 100ms–2s per call |
| **Determinism** | Fully deterministic | Deterministic | Probabilistic |
| **Trigger** | Schedule (cron) | Event-driven | On-demand / event |
| **Data format** | Structured tables | Events / streams | Text / embeddings |
| **Query type** | Known SQL | Fixed processing logic | Dynamic / natural language |
| **Throughput** | Very high (TBs/hour) | High (millions events/sec) | Low (tokens/sec) |
| **Cost model** | Compute per job | Always-on infrastructure | Per-token API cost |
| **Failure model** | Retry the job | Replay from offset | Retry + validate output |
| **Complexity** | Low–medium | Medium–high | High (non-determinism) |
| **Best for** | Analytics, reporting | Alerting, personalization | Reasoning, explanation |

---

## Common Mistakes

### 1. Using LLMs for Computation
```
❌ "What is the total revenue for Q3?" → LLM
✅ "What is the total revenue for Q3?" → SQL query → return number
   "Explain why Q3 revenue dropped" → SQL result → LLM → explanation
```
LLMs hallucinate numbers. Never trust an LLM to do arithmetic or aggregation over data it hasn't seen. Always compute first, then reason.

### 2. Replacing Databases with LLMs
```
❌ Store all user data in a prompt and ask the LLM to find patterns
✅ Store data in a database, retrieve relevant rows, pass to LLM as context
```
LLMs have a fixed context window (8K–200K tokens). A database has no such limit. Use each for what it's designed for.

### 3. Ignoring Data Freshness
```
❌ Embed documents once, never update, serve stale context to LLM
✅ Track document versions, re-embed on change, invalidate stale vectors
```
A RAG system that answers with 6-month-old data is worse than no system — it's confidently wrong.

### 4. Skipping the Batch Layer
```
❌ Stream everything, compute everything in real-time
✅ Use batch for historical aggregations, stream for recent events, LLM for reasoning
```
Real-time processing is expensive. Historical data doesn't need to be reprocessed every second. Batch + stream (Lambda or Kappa architecture) is almost always the right answer.

---

## Correct Architecture Pattern — Layered System

The right mental model is **three layers, each with a distinct job**:

```
┌─────────────────────────────────────────────────────┐
│  LAYER 3 — AI / REASONING LAYER                     │
│  LLM + RAG + Agents                                 │
│  Job: reason over context, generate responses       │
├─────────────────────────────────────────────────────┤
│  LAYER 2 — REAL-TIME LAYER                          │
│  Kafka + Flink + Pinot                              │
│  Job: ingest events, enrich, serve fresh data       │
├─────────────────────────────────────────────────────┤
│  LAYER 1 — BATCH LAYER                              │
│  Spark + dbt + Snowflake / BigQuery                 │
│  Job: historical aggregation, feature computation   │
└─────────────────────────────────────────────────────┘
```

Data flows **up** through the layers. The AI layer never touches raw data directly — it always queries through the retrieval layer, which pulls from both real-time and batch stores.

---

## Real-World Example — User Activity Analytics + NL Query System

**Scenario:** A SaaS product wants to let support agents ask natural language questions about user behavior.

### Layer 1 — Batch
- Spark job runs nightly
- Computes 30/60/90-day user engagement metrics
- Writes to `analytics.user_cohorts` in Snowflake
- Used for: trend reports, cohort analysis, billing

### Layer 2 — Real-Time
- User events (clicks, page views, errors) stream into Kafka
- Flink enriches events with user metadata
- Apache Pinot ingests from Kafka → serves sub-second queries on recent activity
- Used for: live dashboards, real-time alerting, session tracking

### Layer 3 — AI
- Support agent asks: *"Has user #4821 been having issues this week?"*
- Retrieval layer queries Pinot for recent events (last 7 days)
- Retrieval layer queries vector store for similar past support tickets
- Both results passed as context to LLM
- LLM generates a coherent summary with specific timestamps and event types
- Used for: support tooling, churn investigation, anomaly explanation

**What each layer contributes:**
- Batch → historical context (what's normal for this user)
- Real-time → current state (what's happening right now)
- AI → synthesis (what does it mean, in plain language)

---

## Key Takeaways

1. **Batch, real-time, and AI are not alternatives** — they're layers. Each has a distinct job.

2. **Batch is for volume and history.** Cheap, reliable, deterministic. Not for anything user-facing that needs fresh data.

3. **Real-time is for latency and freshness.** Complex to operate, but necessary for reactive systems.

4. **LLMs are for reasoning, not computation.** Never ask an LLM to aggregate data. Always compute first, then reason.

5. **Data freshness is a first-class concern.** Stale context in an AI system produces confidently wrong answers.

6. **The layered architecture is the production pattern.** Batch feeds history. Real-time feeds current state. AI reasons over both.

---

## What's Next

**Day 03** — The New Stack: mapping every layer to specific tools and understanding why each was chosen.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
