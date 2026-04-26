# Day 03 — The New Stack

> **Phase 1 — Reset the Mental Model**
> Kafka. Flink. Pinot. Vector DB. LLM. Orchestrator. Each layer exists because the one below it can't do the job alone.

---

## Introduction

A traditional data stack has three layers: ingest, store, query. That's enough for dashboards and reports.

An AI data system has five layers — and each one solves a problem the previous layer creates.

This isn't about adding tools for the sake of it. Every component in the new stack exists because a specific failure mode appears without it:

- Without Kafka → you can't decouple producers from consumers at scale
- Without stream processing → raw events are noise, not signal
- Without Pinot → you can't query fresh data at sub-second latency
- Without a vector store → you can't retrieve context by meaning
- Without an LLM layer → you can't reason over unstructured context
- Without an orchestrator → you can't coordinate multi-step workflows reliably

Understanding *why* each layer exists is more important than knowing *how* to configure it.

---

## The New Stack — Overview

```
┌─────────────────────────────────────────────────────────┐
│  Layer 5 — Orchestration    Airflow / Prefect / Dagster  │
├─────────────────────────────────────────────────────────┤
│  Layer 4 — Reasoning        LLM + RAG + Agents           │
├─────────────────────────────────────────────────────────┤
│  Layer 3 — Retrieval        Vector DB + Hybrid Search    │
├─────────────────────────────────────────────────────────┤
│  Layer 2 — Real-Time OLAP   Apache Pinot                 │
├─────────────────────────────────────────────────────────┤
│  Layer 1 — Streaming        Kafka + Flink                │
└─────────────────────────────────────────────────────────┘
```

Data flows **up**. Events enter at Layer 1 and become decisions at Layer 4. Layer 5 coordinates everything.

---

## Each Layer Explained

---

### Layer 1 — Streaming (Kafka + Flink)

**Purpose:** Capture every event as it happens and process it in motion.

**What problem it solves:**
Traditional ingestion is pull-based — a job runs on a schedule and pulls data from a source. This creates an inherent latency floor. If your job runs every hour, your data is always at least an hour stale.

Kafka inverts this. Producers **push** events the moment they occur. Consumers read them independently, at their own pace, from any point in the stream's history (within the retention window).

Flink (or Kafka Streams) sits on top of Kafka and processes events **in motion** — enriching, filtering, joining, and aggregating before data ever reaches storage.

**Why it exists:**
- Decouples producers from consumers — a slow consumer doesn't block a fast producer
- Enables replay — consumers can re-read past events to recover from failures
- Enables fan-out — one event can be consumed by multiple independent systems simultaneously
- Enables stateful processing — Flink maintains per-key state (e.g., session windows) across events

**Where it fails if missing:**
Without a streaming layer, every downstream system must poll sources independently. You get duplicated ingestion logic, inconsistent data across systems, and no single source of truth for event history.

**Key Kafka concepts:**
| Concept | What it means |
|---------|--------------|
| Topic | Named stream of events (e.g., `user.events`) |
| Partition | How a topic is split for parallelism; ordering guaranteed within a partition |
| Offset | Position of a consumer in a partition; enables replay |
| Consumer group | Multiple consumers sharing the work of reading a topic |
| Retention | How long Kafka keeps events (hours to forever) |

---

### Layer 2 — Real-Time OLAP (Apache Pinot)

**Purpose:** Make streaming data queryable at sub-second latency, seconds after it arrives.

**What problem it solves:**
Kafka is a log, not a query engine. You can't run `SELECT COUNT(*) WHERE user_id = 'u_001'` against a Kafka topic. You need a store that:
1. Ingests from Kafka continuously
2. Indexes data for fast analytical queries
3. Returns results in milliseconds, not minutes

Apache Pinot is purpose-built for this. It ingests from Kafka in real-time, builds columnar indexes, and serves SQL queries with P99 latency under 100ms — even on tables with billions of rows.

**Why it exists:**
- Bridges the gap between streaming (Kafka) and querying (SQL)
- Enables "what is happening right now" queries that a data warehouse can't answer
- Supports upserts, time-series queries, and multi-value columns natively

**Where it fails if missing:**
Without Pinot (or equivalent), you're forced to choose between:
- Querying Kafka directly (no SQL, no aggregations, high complexity)
- Waiting for a batch job to land data in a warehouse (high latency)

Neither works for real-time AI systems that need fresh data in milliseconds.

**Pinot architecture (simplified):**
```
Kafka Topic → Pinot Realtime Table (in-memory segments)
                    ↓ (periodically committed)
             Pinot Offline Table (deep storage segments)
                    ↓
             Pinot Broker → SQL Query → Result
```

---

### Layer 3 — Retrieval (Vector DB + Hybrid Search)

**Purpose:** Find semantically relevant context given a natural language query.

**What problem it solves:**
SQL finds exact matches. `WHERE page = '/pricing'` returns rows where the page column equals that exact string. It cannot find "pages related to cost concerns" — that requires understanding meaning.

A vector database stores data as dense numerical vectors (embeddings). When a query arrives, it's also converted to a vector, and the store returns the documents whose vectors are most similar — regardless of exact wording.

This is what makes RAG (Retrieval-Augmented Generation) possible: instead of asking an LLM to memorize all your data, you retrieve the relevant pieces at query time and pass them as context.

**Why it exists:**
- LLMs have a fixed context window — you can't pass an entire database to them
- Semantic search finds relevant content that keyword search misses
- Enables the LLM to answer questions about data it was never trained on

**Hybrid search** combines vector similarity with keyword (BM25) search and metadata filters. In practice, pure vector search misses exact-match cases (e.g., specific IDs, product names). Hybrid search handles both.

**Common vector stores:**
| Store | Best for |
|-------|---------|
| Pinecone | Managed, production-scale, simple API |
| Qdrant | Self-hosted, rich filtering, high performance |
| Weaviate | Multi-modal, built-in hybrid search |
| pgvector | Postgres extension — good for smaller scale |
| Chroma | Local development and prototyping |

**Where it fails if missing:**
Without a retrieval layer, you're forced to either:
- Pass all data to the LLM (hits context window limits immediately)
- Ask the LLM to answer from memory (hallucinations, stale knowledge)

---

### Layer 4 — Reasoning (LLM + RAG + Agents)

**Purpose:** Generate responses, decisions, and actions from retrieved context.

**What problem it solves:**
Retrieval gives you relevant data. But data alone doesn't answer questions — it needs to be synthesized, interpreted, and expressed in a useful form. That's what the LLM does.

The LLM receives a prompt containing:
1. A system instruction (role, constraints, output format)
2. Retrieved context (from Layer 3)
3. The user's question

It generates a response by predicting the most likely continuation of that prompt. It does **not** query any database. It does **not** compute. It reasons over what's in the context window.

**RAG pattern:**
```
Query → Embed query → Retrieve top-k chunks → Assemble prompt → LLM → Response
```

**Agent pattern** (extends RAG):
```
Query → LLM decides which tool to call → Tool executes → Result returned to LLM → LLM responds
```

Agents can call SQL queries, vector searches, APIs, or code execution — but the LLM orchestrates the decision of *which* tool to use and *when*.

**Why it exists:**
- Unstructured data (text, documents, transcripts) can't be queried with SQL
- Open-ended questions can't be answered with fixed query templates
- Synthesis across multiple data sources requires reasoning, not just retrieval

**Where it fails if missing:**
Without an LLM layer, you can retrieve data but can't synthesize it. A support agent would get a list of raw events — not an explanation of what they mean.

**Critical constraint:** LLMs are probabilistic. The same input can produce different outputs. Design for this:
- Use structured output (JSON mode) when you need parseable responses
- Validate LLM output before acting on it
- Never use LLMs for arithmetic or exact computation — compute first, reason second

---

### Layer 5 — Orchestration (Airflow / Prefect / Dagster)

**Purpose:** Coordinate multi-step workflows, manage dependencies, handle failures, and schedule jobs.

**What problem it solves:**
A production AI data system has dozens of interdependent jobs:
- Batch feature computation (runs nightly)
- Embedding pipeline (runs when new documents arrive)
- Model evaluation (runs after each deployment)
- Data quality checks (runs before downstream jobs)
- Retraining triggers (runs when drift is detected)

Without an orchestrator, these jobs are managed by cron scripts, shell commands, and tribal knowledge. Failures are silent. Dependencies are implicit. Retries are manual.

An orchestrator makes all of this explicit, observable, and recoverable.

**Why it exists:**
- Defines dependencies between tasks as a DAG (Directed Acyclic Graph)
- Retries failed tasks automatically with configurable backoff
- Provides a UI for monitoring job status, logs, and history
- Enables parameterized runs (backfills, date ranges, environment configs)
- Sends alerts when SLAs are missed

**Where it fails if missing:**
Without orchestration, a failed embedding pipeline silently serves stale vectors. A failed batch job poisons downstream features. There's no audit trail, no alerting, no recovery path.

---

## Data Flow — End-to-End

### Path 1: Event → Storage (write path)

```
[User Action]
     │
     ▼
[Kafka Topic: user.events]          ← event published within milliseconds
     │
     ▼
[Flink Stream Processor]            ← enrich with user metadata, filter noise
     │
     ├──────────────────────────────────────────────┐
     ▼                                              ▼
[Apache Pinot]                              [Embedding Pipeline]
(structured, queryable within ~1s)          (text → vector)
                                                    │
                                                    ▼
                                            [Vector Store]
                                            (indexed for similarity search)
```

### Path 2: Query → Response (read path)

```
[User Query: "Why is user u_001 churning?"]
     │
     ▼
[Query Parser]                      ← extract intent + entities
     │
     ▼
[Retrieval Layer]
     ├── Vector Store query         ← semantic search: top-k relevant events
     └── Pinot SQL query            ← structured metrics: counts, rates, flags
     │
     ▼
[Context Assembly]                  ← combine vector + structured results
     │
     ▼
[LLM]                               ← reason over context, generate response
     │
     ▼
[Response / Action]                 ← text answer, JSON output, or tool call
```

---

## Real-World Example — User Activity Intelligence System

**Scenario:** A SaaS platform wants to give support engineers an AI assistant that can answer questions about any user's recent behavior.

| Layer | Component | Role in this system |
|-------|-----------|-------------------|
| Streaming | Kafka + Flink | Captures every click, error, purchase in real-time. Flink enriches with user plan and country. |
| Real-Time OLAP | Apache Pinot | Stores enriched events. Answers "how many errors did u_001 have this week?" in <100ms. |
| Retrieval | Qdrant | Stores embedded event descriptions. Finds semantically similar past incidents. |
| Reasoning | GPT-4o | Receives Pinot metrics + Qdrant chunks. Generates a coherent explanation. |
| Orchestration | Airflow | Schedules nightly batch feature jobs, triggers re-embedding when new doc types arrive, alerts on pipeline failures. |

**Query flow:**
1. Support engineer asks: *"Has user u_001 been having checkout issues?"*
2. Query parser extracts: `user_id=u_001`, `intent=error_investigation`
3. Pinot query: `SELECT COUNT(*) FROM events WHERE user_id='u_001' AND event='error' AND page='/checkout' AND ts > NOW() - 7d`
4. Vector query: top-4 semantically similar events for u_001
5. LLM receives both results as context → generates explanation with specific timestamps and counts
6. Response returned to support engineer in ~600ms

---

## Common Mistakes

### 1. Overusing LLMs
```
❌ Route every question through the LLM, including "how many users signed up today?"
✅ Use Pinot/SQL for counts and aggregations. Use LLM only for reasoning and synthesis.
```
LLMs are slow (~500ms–2s) and expensive (per token). A SQL query answers "how many" in 10ms for free.

### 2. Skipping the Retrieval Layer
```
❌ Pass all user data directly to the LLM in a giant prompt
✅ Retrieve only the top-k relevant chunks and pass those
```
Context windows are finite (even 200K tokens has limits). More importantly, irrelevant context degrades LLM output quality. Precision in retrieval = precision in reasoning.

### 3. Ignoring Orchestration
```
❌ Run embedding pipelines manually or via cron with no monitoring
✅ Define pipelines as DAGs with dependencies, retries, and alerting
```
A silent failure in the embedding pipeline means the vector store serves stale data. The LLM will confidently answer with outdated context. You won't know until a user reports a wrong answer.

### 4. Treating Pinot as a Replacement for a Data Warehouse
```
❌ Use Pinot for historical analysis, complex joins, and ad-hoc exploration
✅ Use Pinot for low-latency queries on recent data. Use Snowflake/BigQuery for history.
```
Pinot is optimized for speed on fresh data. It doesn't support complex multi-table joins or the full SQL surface area that a warehouse does.

---

## Key Takeaways

1. **Every layer solves a specific failure mode.** Remove any one layer and a specific class of problems becomes unsolvable.

2. **Kafka is the backbone.** Everything else reads from or writes to the event stream. It's the single source of truth for what happened and when.

3. **Pinot bridges streaming and querying.** It's the answer to "I need SQL on data that's 2 seconds old."

4. **Vector stores enable semantic retrieval.** Without them, LLMs can only reason over what you explicitly put in the prompt — which doesn't scale.

5. **LLMs reason, they don't compute.** Always compute metrics in Pinot/SQL. Pass the results to the LLM as context.

6. **Orchestration is not optional in production.** Silent pipeline failures produce confidently wrong AI responses. You need visibility, retries, and alerting.

---

## What's Next

**Day 04** — System Blueprint: assembling all five layers into a complete reference architecture with component-level design decisions.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
