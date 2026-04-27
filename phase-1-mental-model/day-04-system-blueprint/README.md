# Day 04 — System Blueprint

> **Phase 1 — Reset the Mental Model**
> Before writing a single line of production code, you need to see the whole system. This is the blueprint we will build across 28 days.

---

## Introduction

Days 1–3 established the *why*: data engineering is changing, three paradigms exist, and a five-layer stack is required. Day 4 is the *what*: a concrete, end-to-end system design that every subsequent day will implement piece by piece.

This document is a reference architecture. Every component decision here has a reason. Every tradeoff is explicit. By the end of Day 28, this blueprint will be a running system.

---

## What We Are Building

A **User Activity Intelligence System** — a production-grade platform that:

1. Captures every user action in real-time via an event stream
2. Processes and enriches events as they arrive
3. Makes fresh data queryable at sub-second latency
4. Enables natural language queries over user behavior
5. Generates AI-powered explanations, risk scores, and recommended actions
6. Orchestrates all pipelines with dependency management and alerting

**This is not a toy.** The architecture mirrors what companies like Stripe, Notion, and Intercom run to power their user intelligence and support tooling.

---

## Problem Statement

### The Business Problem
A SaaS company has 50,000 active users. Their support team gets 200 tickets/day. 40% of those tickets are about users who churned or are about to churn. The support team needs to:

- Understand *why* a specific user is struggling — in seconds, not hours
- Identify users at risk *before* they submit a ticket
- Get a plain-language explanation of what a user has been doing

### Why the Traditional Stack Fails
- **Batch pipelines** update data hourly — a user who churned 20 minutes ago looks fine
- **SQL dashboards** answer "how many" but not "why" or "what should we do"
- **Manual investigation** takes 30+ minutes per user and doesn't scale

### What the New System Delivers
- Support agent asks: *"Why is user u_4821 having trouble?"*
- System retrieves real-time events + historical metrics + similar past cases
- LLM generates a coherent explanation with specific evidence in ~600ms
- Agent gets actionable context without writing a single query

---

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        USER / API LAYER                              │
│              REST API · WebSocket · Support UI                       │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ query
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     LLM REASONING LAYER                              │
│         Query Parser → Retrieval → Context Assembly → LLM           │
└──────────┬────────────────────────────────────────┬──────────────────┘
           │ vector search                          │ SQL query
           ▼                                        ▼
┌─────────────────────────┐            ┌────────────────────────────────┐
│    VECTOR STORE          │            │      APACHE PINOT              │
│  Qdrant / Pinecone       │            │  Real-time OLAP                │
│  Semantic retrieval      │            │  Sub-second SQL on fresh data  │
└─────────────────────────┘            └──────────────┬─────────────────┘
           ▲                                           ▲
           │ embed + upsert                            │ ingest
           │                                           │
┌──────────────────────────────────────────────────────────────────────┐
│                    STREAM PROCESSING LAYER                           │
│              Apache Flink — enrich · window · detect                 │
└──────────────────────────────┬───────────────────────────────────────┘
                               ▲
                               │ consume
┌──────────────────────────────────────────────────────────────────────┐
│                      STREAMING BACKBONE                              │
│                Apache Kafka — topics · partitions                    │
└──────────────────────────────┬───────────────────────────────────────┘
                               ▲
                               │ publish
┌──────────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                                  │
│         Web App · Mobile · Backend Services · Documents              │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATION LAYER (cross-cutting)               │
│         Apache Airflow — DAGs · retries · SLA alerting               │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Component Breakdown

### 1. Data Sources
**Role:** Origin of all events and documents.

**What it includes:**
- Web/mobile app events (clicks, page views, errors, purchases)
- Backend service events (payment processed, subscription changed)
- Support documents (tickets, transcripts, knowledge base articles)

**Why it exists:** Every user action is a signal. The system is only as good as the events it captures.

**If missing:** No data → no intelligence. The system has nothing to reason over.

---

### 2. Apache Kafka — Streaming Backbone
**Role:** Durable, replayable event bus. The single source of truth for what happened and when.

**What it does:**
- Receives events from all producers (apps, services)
- Stores events in partitioned, ordered topics
- Allows multiple consumers to read independently at their own pace
- Retains events for configurable periods (hours to forever)

**Key topics in this system:**
| Topic | Contents | Partitions |
|-------|----------|-----------|
| `user.events` | All user actions | 12 (keyed by user_id) |
| `system.errors` | Application errors | 6 |
| `support.tickets` | New support tickets | 3 |

**Why it exists:** Without Kafka, every producer must know every consumer. Adding a new consumer requires changing producers. Kafka decouples them completely.

**If missing:** Tight coupling between systems. No replay capability. No fan-out. Downstream failures cause data loss.

---

### 3. Apache Flink — Stream Processing
**Role:** Processes events in motion before they reach any store.

**What it does:**
- Enriches events with user profile data (plan, country, segment)
- Computes session windows (groups events within a 30-min inactivity gap)
- Detects anomalies (error spike, unusual purchase pattern)
- Routes enriched events to two sinks: Pinot and the embedding pipeline

**Why it exists:** Raw events are incomplete. A `page_view` event has a `user_id` but no plan or segment. Flink joins the stream with a lookup store to add that context before storage.

**If missing:** Downstream systems receive incomplete events. Pinot tables lack enrichment columns. The LLM gets less context.

---

### 4. Apache Pinot — Real-Time OLAP
**Role:** Makes streaming data queryable via SQL within ~1 second of arrival.

**What it does:**
- Ingests enriched events from Kafka via a real-time connector
- Builds columnar indexes for fast analytical queries
- Serves sub-second SQL queries even on tables with billions of rows
- Supports time-series queries, multi-value columns, and upserts

**Key tables:**
| Table | Type | Retention | Purpose |
|-------|------|-----------|---------|
| `user_events_realtime` | Realtime | 7 days | Recent activity queries |
| `user_metrics_daily` | Offline | 2 years | Historical aggregations |
| `session_summary` | Hybrid | 30 days | Session-level metrics |

**Why it exists:** Kafka is a log, not a query engine. A data warehouse is too slow (minutes). Pinot fills the gap: SQL on data that's seconds old.

**If missing:** No way to answer "how many errors did this user have in the last hour?" in real-time. The LLM receives no structured metrics.

---

### 5. Embedding Pipeline
**Role:** Converts event descriptions and documents into vector embeddings for semantic search.

**What it does:**
- Receives enriched events from Flink (via Kafka topic)
- Converts each event to a natural language description
- Calls an embedding model (e.g., `text-embedding-3-small`)
- Upserts the resulting vector + metadata into the vector store

**Trigger:** Event-driven (new event arrives) + scheduled (re-embed updated documents)

**Why it exists:** Pinot answers exact-match SQL queries. It cannot answer "find events semantically related to checkout frustration." That requires vector similarity.

**If missing:** The retrieval layer can only do keyword/SQL search. The LLM receives no semantic context. RAG quality degrades significantly.

---

### 6. Vector Store — Retrieval Layer
**Role:** Stores embeddings and serves semantic similarity queries.

**What it does:**
- Stores dense vectors with metadata (user_id, event_type, timestamp)
- Given a query vector, returns the top-k most similar documents
- Supports metadata filtering (e.g., filter to a specific user_id)
- Enables hybrid search (vector + keyword) for better precision

**Why it exists:** LLMs have a fixed context window. You can't pass all user events to the LLM. The vector store selects the *most relevant* events for a given query.

**If missing:** The LLM either gets too much irrelevant context (degrades quality) or too little context (hallucinations). Semantic retrieval is not possible.

---

### 7. LLM Reasoning Layer
**Role:** Receives assembled context and generates responses, risk scores, and recommended actions.

**What it does:**
- Receives: system prompt + retrieved vector chunks + Pinot metrics
- Generates: natural language explanation, structured JSON output, or tool call
- Optionally: calls tools (SQL runner, API caller) as an agent

**What it does NOT do:**
- Query databases directly
- Compute aggregations or arithmetic
- Access data outside the context window

**Why it exists:** Retrieval gives you relevant data. The LLM synthesizes it into something a human (or downstream system) can act on.

**If missing:** You have data but no synthesis. Support agents still have to read raw event logs and draw their own conclusions.

---

### 8. API / User Layer
**Role:** Exposes the system to end users and downstream services.

**What it does:**
- Accepts natural language queries via REST or WebSocket
- Routes to the query pipeline (parse → retrieve → reason)
- Returns structured responses with evidence and confidence scores
- Handles authentication, rate limiting, and response caching

**Why it exists:** The intelligence layer needs a clean interface. The API abstracts all complexity from the consumer.

**If missing:** The system exists but is unusable. No interface = no value delivered.

---

### 9. Apache Airflow — Orchestration
**Role:** Coordinates all multi-step pipelines, manages dependencies, handles failures.

**DAGs in this system:**
| DAG | Schedule | Purpose |
|-----|----------|---------|
| `nightly_feature_compute` | 00:00 UTC | Batch aggregations → Pinot offline tables |
| `embedding_refresh` | Event-triggered | Re-embed updated documents |
| `data_quality_checks` | Hourly | Validate Pinot table freshness |
| `model_eval` | Weekly | Evaluate LLM response quality |
| `pinot_compaction` | Weekly | Compact Pinot segments |

**Why it exists:** Without orchestration, pipeline failures are silent. A failed embedding job serves stale vectors. A failed batch job poisons downstream features. There's no audit trail.

**If missing:** Silent failures. Stale data. No recovery path. The system degrades without anyone knowing.

---

## End-to-End Data Flow

### Write Path — Event Ingestion

```
1. User clicks "Upgrade Plan" in the web app
2. App publishes event to Kafka topic: user.events
   {user_id: "u_4821", event: "click", element: "cta_upgrade", ts: "..."}
3. Flink consumes the event within ~10ms
4. Flink enriches: adds plan="free", country="US", segment="at_risk"
5. Flink emits enriched event to two sinks:
   a. Pinot connector topic → Pinot ingests → queryable within ~1s
   b. Embedding pipeline topic → text generated → vector upserted to Qdrant
6. Airflow monitors pipeline health; alerts if lag exceeds SLA
```

### Read Path — Query Flow

```
1. Support agent asks: "Why is user u_4821 struggling with checkout?"
2. API receives query → Query Parser extracts:
   intent=error_investigation, user_id=u_4821
3. Parallel retrieval:
   a. Vector store: semantic search → top-4 relevant event descriptions
   b. Pinot SQL: SELECT metrics WHERE user_id='u_4821' AND ts > ago('7d')
      → {errors_7d: 5, page_views_7d: 18, churn_risk: "high"}
4. Context Assembly: combine vector chunks + structured metrics
   → token-budgeted, ranked by relevance
5. LLM call: system_prompt + context + query
   → "User u_4821 has experienced 5 checkout errors in 7 days.
      They visited /pricing 4 times and submitted a support message
      citing payment failures. Churn risk: HIGH.
      Recommended action: escalate to engineering + offer plan credit."
6. API returns structured response with evidence + confidence score
   Total latency: ~600ms
```

---

## Tradeoffs

### Latency vs Accuracy
| Choice | Latency | Accuracy |
|--------|---------|----------|
| Retrieve top-2 chunks | ~200ms | Lower — less context |
| Retrieve top-8 chunks | ~400ms | Higher — more context |
| Re-rank results | +100ms | Higher — better ordering |
| Larger LLM (GPT-4o) | +300ms | Higher reasoning quality |
| Smaller LLM (GPT-4o-mini) | -200ms | Lower reasoning quality |

**Decision:** Top-4 chunks + GPT-4o-mini for latency-sensitive paths. Top-8 + GPT-4o for deep investigation queries.

### Cost vs Performance
| Component | Cost driver | Optimization |
|-----------|------------|-------------|
| LLM API | Tokens per call | Cache frequent queries; use smaller model for simple intents |
| Vector store | Index size + query volume | Namespace by recency; archive old vectors |
| Pinot | Always-on cluster | Right-size server tiers; use offline tables for cold data |
| Flink | Parallelism + state size | Tune checkpoint intervals; use RocksDB state backend |

### Real-Time vs Batch
| Data type | Layer | Rationale |
|-----------|-------|-----------|
| Last 7 days of events | Pinot realtime table | Needs to be fresh for support queries |
| 90-day cohort metrics | Snowflake / BigQuery | Historical; batch is sufficient and cheaper |
| Embeddings | Vector store | Updated on event arrival; stale embeddings = wrong answers |
| User segments | Feature store | Updated daily by batch job; hourly freshness is enough |

---

## Common Mistakes

### 1. Overusing LLMs
```
❌ Route every query through the LLM, including "how many errors today?"
✅ Use Pinot for counts/aggregations. Use LLM only for synthesis and explanation.
```
A Pinot query answers "how many" in 10ms for free. An LLM call costs tokens and takes 500ms.

### 2. Ignoring the Real-Time Layer
```
❌ Use only a batch pipeline; update data hourly
✅ Stream events through Kafka → Flink → Pinot for sub-second freshness
```
A user who churned 30 minutes ago looks healthy in a batch system. The support agent gets the wrong answer.

### 3. Skipping Orchestration
```
❌ Run embedding pipelines via cron scripts with no monitoring
✅ Define all pipelines as Airflow DAGs with dependencies, retries, and SLA alerts
```
A silent embedding failure means the vector store serves 3-day-old data. The LLM confidently answers with stale context.

### 4. Passing Raw Data to the LLM
```
❌ Dump all user events into the prompt
✅ Retrieve top-k relevant chunks; assemble a token-budgeted context
```
More context is not always better. Irrelevant context degrades LLM output quality and increases cost.

### 5. No Output Validation
```
❌ Trust LLM output directly and act on it
✅ Validate structure, confidence score, and grounding before acting
```
LLMs are probabilistic. A low-confidence response should be flagged for human review, not acted on automatically.

---

## Key Takeaways

1. **The blueprint is a layered system, not a pipeline.** Each layer has a distinct job. Removing any one layer creates a specific class of failures.

2. **Data flows in two directions.** Write path: events → Kafka → Flink → Pinot + Vector Store. Read path: query → retrieval → LLM → response.

3. **The LLM is at the top, not the center.** It reasons over pre-retrieved context. It never touches raw data.

4. **Freshness is a design constraint, not an afterthought.** Stale vectors and stale Pinot data produce confidently wrong AI responses.

5. **Orchestration is the reliability layer.** Without it, the system works in demos and fails silently in production.

6. **Every tradeoff is explicit.** Latency vs accuracy, cost vs performance, real-time vs batch — these are engineering decisions, not accidents.

---

## What's Next

**Phase 2 (Days 5–9)** — Building the real-time data backbone: Kafka, event schema design, stream processing, Apache Pinot, and latency vs freshness tradeoffs.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
