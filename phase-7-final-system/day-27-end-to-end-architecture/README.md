# Day 27: End-to-End AI System Architecture

> **AI Systems for Data Engineers — Phase 7: Final System**
>
> Building production AI systems is not about calling an LLM API. It's about engineering a distributed intelligent system where every layer — from event ingestion to response generation — is purpose-built, independently scalable, and observable.

---

## Table of Contents

- [Introduction](#introduction)
- [Complete End-to-End Architecture](#complete-end-to-end-architecture)
- [Layer-by-Layer Breakdown](#layer-by-layer-breakdown)
  - [Kafka — Event Ingestion](#1-kafka--event-ingestion)
  - [Stream Processing — Enrichment](#2-stream-processing--enrichment)
  - [Apache Pinot — Real-Time Analytics](#3-apache-pinot--real-time-analytics)
  - [Vector DB — Semantic Retrieval](#4-vector-db--semantic-retrieval)
  - [Query Understanding — Intent Detection](#5-query-understanding--intent-detection)
  - [Retrieval Layer — Hybrid Fusion](#6-retrieval-layer--hybrid-fusion)
  - [Agent Layer — Orchestration](#7-agent-layer--orchestration)
  - [LLM Layer — Reasoning](#8-llm-layer--reasoning)
- [Reliability & Orchestration](#reliability--orchestration)
- [Scaling & Cost Engineering](#scaling--cost-engineering)
- [Failure Modes](#failure-modes)
- [Real-World Example](#real-world-example)
- [Common Mistakes](#common-mistakes)
- [Key Takeaways](#key-takeaways)
- [Interactive Simulation](#interactive-simulation)
- [Code Implementation](#code-implementation)
- [Optional Tool Setup](#optional-tool-setup)
- [Folder Structure](#folder-structure)

---

## Introduction

Most teams treat AI as a feature: call an API, get a response, ship it. This works for demos. It fails catastrophically in production.

A production AI system is a **distributed intelligent system** — a multi-layered architecture where:

- **Data infrastructure** feeds context to the AI, not the other way around
- **Retrieval quality** determines response quality more than model choice
- **Orchestration reliability** determines whether users get answers or error pages
- **Observability** determines whether you can debug failures at 3 AM
- **Cost engineering** determines whether the system survives past the first invoice

The difference between a demo and a production system is not the LLM. It's everything else.

This module covers the complete architecture of an AI system that a data engineering team would actually build, operate, and be on-call for.

---

## Complete End-to-End Architecture

The full system has two distinct paths:

### Data Path (Background)

Continuous ingestion and processing of events that keep the system's knowledge current:

```
Event Sources → Kafka → Stream Processor → Apache Pinot (analytics)
                                         → Vector DB (embeddings)
                                         → Feature Store (real-time features)
```

### Query Path (Real-time)

User-facing request flow that turns questions into grounded, actionable responses:

```
User Query → Query Understanding → Retrieval Engine → Agent Orchestrator → LLM → Response
                                        ↑                    ↑
                                   Apache Pinot          Feature Store
                                   Vector DB
```

### Why Two Paths?

Combining ingestion and query processing into one pipeline creates coupling that kills both reliability and latency. The data path optimizes for **throughput** (events/second). The query path optimizes for **latency** (milliseconds to response). They share storage (Pinot, Vector DB, Feature Store) but never share execution context.

### Responsibility Matrix

| Layer | Owns | Does NOT Own |
|-------|------|-------------|
| **Kafka** | Event ordering, delivery guarantees, backpressure | Event validation, schema enforcement |
| **Stream Processor** | Enrichment, validation, routing, feature computation | Storage, querying, response generation |
| **Apache Pinot** | Real-time OLAP, pre-aggregated analytics | Semantic search, unstructured data |
| **Vector DB** | Embedding storage, ANN search | Exact match queries, aggregations |
| **Query Understanding** | Intent detection, entity extraction, routing | Data retrieval, response generation |
| **Retrieval Engine** | Hybrid search, rank fusion, caching | Tool coordination, LLM interaction |
| **Agent Orchestrator** | Tool coordination, retries, fallbacks, tracing | Data storage, model inference |
| **LLM** | Reasoning, explanation, recommendation generation | Data retrieval, tool selection |

---

## Layer-by-Layer Breakdown

### 1. Kafka — Event Ingestion

Kafka is the **entry point** of the system. Every downstream component depends on high-quality, ordered events flowing through it.

#### What It Does

- Receives events from all application surfaces (web, mobile, API, IoT)
- Guarantees ordering within a partition (critical for per-user processing)
- Provides at-least-once delivery with idempotent producers
- Acts as a buffer between producers and consumers (backpressure handling)

#### Production Configuration

```
Partitions         : 12+ (scaled to consumer parallelism)
Replication Factor : 3 (durability)
Acks               : all (no data loss)
Compression        : Snappy (throughput)
Retention          : 7 days (replay capability)
Schema Registry    : Avro/Protobuf (contract enforcement)
```

#### Key Design Decisions

- **Partition key = user_id**: Ensures all events for a user land on the same partition, enabling ordered per-user processing without cross-partition coordination
- **Schema Registry**: Every event conforms to a versioned schema. Producers that violate the schema are rejected, not silently corrupted
- **Idempotent producer**: `enable.idempotence=true` prevents duplicate events during retries, which would poison downstream aggregations

#### What Goes Wrong

- **Partition skew**: If 10% of users generate 90% of events, those partitions become hot. Monitor partition lag and rebalance
- **Schema evolution**: A field rename without backward compatibility breaks every consumer simultaneously
- **Consumer lag**: If stream processing can't keep up, the lag queue grows and freshness degrades

---

### 2. Stream Processing — Enrichment

Raw events are **never consumed directly** by the intelligence layer. The stream processor transforms raw data into query-ready, enriched records.

#### What It Does

1. **Schema Validation**: Reject malformed events to a dead-letter queue — never silently drop
2. **Profile Enrichment**: Join events with user profile data (tier, industry, revenue) via lookup against Redis/DynamoDB
3. **Session Windowing**: Group events into logical user sessions using 30-minute gap windows
4. **Feature Computation**: Calculate real-time features (event count, error rate, engagement velocity) and write to the feature store
5. **Multi-Sink Routing**: Route enriched events to the correct downstream stores:
   - All events → Apache Pinot
   - Semantic events → Vector DB (for embedding)
   - All events → Feature Store (real-time features)
   - Failed events → Dead-letter queue

#### Production Stack

- **Apache Flink**: Stateful processing with RocksDB state backend, exactly-once via Kafka transactions
- **Kafka Streams**: Lighter alternative when the topology fits single-JVM deployment
- **Watermarks**: Handle late-arriving events with configurable allowed lateness

#### What Goes Wrong

- **State explosion**: Session windows that never close (zombie sessions) consume unbounded memory. Always set maximum window duration
- **Enrichment failures**: If the profile store is down, do you drop events or process without enrichment? Decision must be explicit
- **Backpressure propagation**: If Pinot ingestion slows down, the processor must handle backpressure without losing events

---

### 3. Apache Pinot — Real-Time Analytics

Pinot provides **sub-100ms analytical queries** over streaming data. It's the structured retrieval backend for the intelligence layer.

#### What It Does

- Ingests enriched events from the stream processor in real-time
- Provides SQL-compatible query interface for aggregations, filters, and time-series analysis
- Pre-aggregates data using star-tree indexes for common query patterns
- Serves both real-time (streaming) and historical (batch) data through hybrid tables

#### Why Not Just Use PostgreSQL?

| Dimension | PostgreSQL | Apache Pinot |
|-----------|-----------|--------------|
| Query Latency | 100ms–10s for analytics | 5ms–100ms |
| Ingestion | Batch inserts | Real-time streaming |
| Concurrency | 100s of queries/sec | 10,000s of queries/sec |
| Column Store | No (row-oriented) | Yes (columnar + inverted index) |
| Aggregations | Full scan | Pre-aggregated star-tree |

#### Key Query Patterns

```sql
-- User-level churn risk metrics
SELECT user_id, churn_risk_score, feature_adoption_rate, last_login_hours_ago
FROM user_analytics
WHERE tier = 'enterprise' AND churn_risk_score > 0.7
ORDER BY churn_risk_score DESC
LIMIT 10

-- Tier-level aggregation
SELECT tier,
       AVG(churn_risk_score) as avg_churn_risk,
       COUNT(*) as user_count,
       SUM(mrr) as total_mrr
FROM user_analytics
GROUP BY tier
```

---

### 4. Vector DB — Semantic Retrieval

The vector database stores **behavioral embeddings** that capture patterns Pinot's SQL can't express.

#### What It Does

- Stores high-dimensional vectors representing user behavior patterns
- Enables approximate nearest neighbor (ANN) search via HNSW indexes
- Returns semantically similar users/patterns based on cosine similarity
- Maintains metadata alongside vectors for filtered search

#### What Gets Embedded

- **User behavior sequences**: Last 30 days of interaction patterns encoded into a 128-dimensional vector
- **Support ticket content**: Ticket text + sentiment encoded for semantic matching
- **Feature usage patterns**: Which features are used, in what order, with what frequency

#### Why Not Just SQL?

SQL can find "users with churn_score > 0.7". Vectors find "users whose behavior pattern looks like users who churned last quarter" — a fundamentally different (and often more valuable) signal.

#### Production Choices

| Database | Strength | Trade-off |
|----------|----------|-----------|
| Qdrant | Performance, filtering | Smaller ecosystem |
| Pinecone | Managed, simple | Vendor lock-in, cost |
| Weaviate | Hybrid search built-in | Complexity |
| pgvector | PostgreSQL integration | Scale limits |

---

### 5. Query Understanding — Intent Detection

Before any retrieval happens, the system must understand **what the user is actually asking**.

#### What It Does

1. **Intent Classification**: Map natural language to a known intent category (churn_analysis, usage_analysis, revenue_analysis, similar_users, etc.)
2. **Entity Extraction**: Pull structured entities from the query (user IDs, time ranges, tier names)
3. **Retrieval Planning**: Decide which retrieval strategies to activate (structured only, semantic only, or hybrid)
4. **Confidence Scoring**: If intent confidence is low, either ask for clarification or use a broader retrieval strategy

#### Intent → Retrieval Routing

| Intent | Structured (Pinot) | Semantic (Vector) | Feature Store |
|--------|-------------------|-------------------|---------------|
| churn_analysis | ✅ | ✅ | ✅ |
| usage_analysis | ✅ | ❌ | ✅ |
| revenue_analysis | ✅ | ❌ | ❌ |
| similar_users | ❌ | ✅ | ✅ |
| support_analysis | ✅ | ✅ | ❌ |
| health_check | ✅ | ❌ | ✅ |

#### Production Implementation

- **Simple path**: Keyword matching with scoring (works for well-defined domains)
- **Production path**: Fine-tuned classifier (DistilBERT) or small LLM (GPT-4o-mini) with structured output
- **Always**: Log intents and confidence scores for monitoring and retraining

---

### 6. Retrieval Layer — Hybrid Fusion

The retrieval layer is the **bridge between data infrastructure and AI**. It answers: "Given a query, what context does the LLM need?"

#### Retrieval Strategy

1. **Structured Retrieval**: SQL queries against Apache Pinot for metrics, counts, aggregations, and ranked lists
2. **Semantic Retrieval**: Vector similarity search for behavioral patterns, similar users, and contextual matches
3. **Reciprocal Rank Fusion (RRF)**: Merge results from both sources into a unified ranking

#### RRF Algorithm

```
RRF_score(item) = Σ 1 / (k + rank_i)
```

Where `rank_i` is the item's rank in each source and `k` (typically 60) prevents top-ranked items from dominating. RRF is preferred over score normalization because it doesn't require calibrating scores across different retrieval systems.

#### Caching Strategy

- **Query-level cache**: Hash the query + intent as cache key, TTL = 60 seconds
- **Result-level cache**: Cache Pinot query results with TTL based on data freshness
- **Cache invalidation**: Event-driven invalidation when underlying data changes significantly

---

### 7. Agent Layer — Orchestration

The agent orchestrator **coordinates tools** and manages the execution flow between retrieval and reasoning.

#### What It Does

1. **Tool Planning**: Based on query intent, determine which tools to invoke and in what order
2. **Tool Execution**: Call tools with circuit breakers, retries, and timeout budgets
3. **Context Assembly**: Merge results from multiple tools into a coherent context for the LLM
4. **Observability**: Generate execution traces with per-tool latency, status, and retry counts

#### Reliability Patterns

| Pattern | Purpose | Implementation |
|---------|---------|----------------|
| **Circuit Breaker** | Prevent cascade failures | Open after 3 consecutive failures, test recovery after 30s |
| **Retry with Backoff** | Handle transient failures | Exponential backoff with jitter, max 2 retries |
| **Timeout Budget** | Prevent unbounded latency | Total query budget split across tool calls |
| **Fallback** | Graceful degradation | Each tool has a fallback (e.g., cached analytics, keyword search) |

#### Critical Design Rule

Agents are **coordinators, not AI**. They don't "think" — they route, retry, and assemble. The moment you put reasoning logic in the agent layer, you've created an undebuggable system. Keep agents deterministic and observable.

---

### 8. LLM Layer — Reasoning

The LLM is the **last mile** — it receives pre-assembled context and generates human-readable analysis.

#### What It Does

1. **Model Routing**: Select the appropriate model based on query complexity and cost
2. **Prompt Construction**: Build structured prompts from versioned templates
3. **Response Generation**: Generate grounded, actionable responses
4. **Quality Validation**: Verify response quality before delivery

#### Model Routing Strategy

| Query Complexity | Model | Cost (per 1K tokens) | Latency | Use Case |
|-----------------|-------|---------------------|---------|----------|
| Simple (status checks) | GPT-4o-mini | $0.00015 / $0.0006 | ~300ms | Health checks, simple summaries |
| Standard (analysis) | GPT-4o | $0.0025 / $0.01 | ~800ms | Usage analysis, trends |
| Complex (reasoning) | GPT-4-Turbo | $0.01 / $0.03 | ~2000ms | Churn analysis, recommendations |

#### Prompt Engineering

```
SYSTEM: You are an expert customer intelligence analyst...
        Always ground analysis in provided data — never fabricate numbers.

USER:   ## Query
        {query}

        ## Retrieved Context
        {structured_results}
        {semantic_patterns}
        {user_features}

        ## Instructions
        1. Identify risk factors
        2. Quantify impact
        3. Recommend actions
        4. Prioritize by feasibility
```

#### Key Principle

The LLM should **never** retrieve data or decide what to fetch. It receives a pre-built context package and reasons over it. If the LLM needs more data, the agent should fetch it — not the LLM itself.

---

## Reliability & Orchestration

### Retries

Not all failures are equal. Retry strategy must match the failure mode:

| Failure Type | Retry? | Strategy |
|-------------|--------|----------|
| Network timeout | Yes | Exponential backoff + jitter |
| 429 Rate Limited | Yes | Respect Retry-After header |
| 500 Server Error | Yes | Max 2 attempts, then fallback |
| 400 Bad Request | No | Log and fail immediately |
| Schema Mismatch | No | Route to dead-letter queue |

### Observability

Every stage of the pipeline emits structured traces:

```json
{
  "trace_id": "query-48291",
  "spans": [
    {"stage": "retrieval", "latency_ms": 45, "status": "success"},
    {"stage": "orchestration", "latency_ms": 120, "status": "success", "tool_calls": 3},
    {"stage": "llm_reasoning", "latency_ms": 850, "status": "success", "model": "gpt-4o", "tokens": 1240}
  ],
  "total_latency_ms": 1015,
  "cost_usd": 0.0034
}
```

Key metrics to monitor:
- **P50 / P95 / P99 latency** per stage
- **Error rate** per tool and per model
- **Cache hit rate** for retrieval and LLM responses
- **Token consumption** and cost per query
- **Circuit breaker state** per tool

### Async Workflows

For queries that take >5 seconds:
1. Accept the query and return a tracking ID
2. Process asynchronously
3. Deliver results via webhook, WebSocket, or polling endpoint
4. Never block the user for >3 seconds on the critical path

### Fallback Logic

Every tool has a defined fallback chain:

```
Primary: Apache Pinot SQL query
  ↓ (failure)
Fallback 1: Cached analytics (5-15 min stale)
  ↓ (failure)
Fallback 2: Pre-computed daily aggregation
  ↓ (failure)
Fallback 3: Return "data temporarily unavailable" with partial context
```

---

## Scaling & Cost Engineering

### Caching Strategy

| Layer | Cache | TTL | Hit Rate Target |
|-------|-------|-----|-----------------|
| Query Understanding | Intent cache | 5 min | 40% |
| Structured Retrieval | Query result cache | 60s | 30% |
| Semantic Retrieval | Embedding cache | 5 min | 25% |
| LLM Response | Response cache (query hash) | 5 min | 15% |

### Model Routing for Cost

Route 60% of queries to the cheapest model. Reserve expensive models for complex reasoning:

```
Total queries: 10,000/day

Fast model  (60%): 6,000 × $0.001 = $6.00
Standard    (30%): 3,000 × $0.015 = $45.00
Premium     (10%): 1,000 × $0.050 = $50.00

Total: $101/day vs $500/day (all premium)
Savings: 80%
```

### Retrieval Optimization

- **Pre-computed aggregations**: Star-tree indexes in Pinot eliminate scan-time computation
- **Embedding refresh**: Re-embed only users with significant behavior changes (delta encoding)
- **Result pruning**: Limit retrieved context to top-k most relevant items to reduce LLM token costs

### Parallel Execution

Independent tools execute simultaneously:

```
Sequential: Pinot (50ms) + VectorDB (30ms) + FeatureStore (10ms) = 90ms
Parallel:   max(50ms, 30ms, 10ms) = 50ms
Savings:    44%
```

---

## Failure Modes

### 1. Stale Embeddings

**Problem**: Behavioral embeddings are generated daily, but user behavior changes hourly. The vector search returns "similar" users based on yesterday's patterns.

**Impact**: Semantic retrieval quality degrades silently — no errors, just wrong answers.

**Mitigation**:
- Trigger re-embedding on significant behavior changes (>2σ from baseline)
- Add embedding staleness metadata to retrieval results
- Weight semantic results lower when embeddings are >24h old

### 2. Retry Storms

**Problem**: When a downstream service (Pinot, Vector DB) goes down, all clients retry simultaneously, creating a thundering herd that prevents recovery.

**Impact**: Total system failure that persists long after the root cause resolves.

**Mitigation**:
- Exponential backoff with **jitter** (randomized delay)
- Circuit breakers that open after 3 consecutive failures
- Retry budgets: max 2 retries per tool, max 5 retries per query

### 3. Latency Spikes

**Problem**: LLM API latency spikes from 800ms to 15s due to provider-side issues. The system appears "hanging" to users.

**Impact**: User experience degrades, timeout cascades, queue buildup.

**Mitigation**:
- Strict timeout budgets per stage (retrieval: 500ms, orchestration: 1s, LLM: 5s)
- Streaming responses (SSE) so users see partial progress
- Model fallback: if premium model is slow, fall back to standard model

### 4. Retrieval Degradation

**Problem**: Retrieval quality degrades over time as data distribution shifts, but there's no monitoring to detect it.

**Impact**: LLM generates plausible-sounding but inaccurate responses (grounded in stale/irrelevant context).

**Mitigation**:
- Track retrieval relevance scores over time
- A/B test retrieval strategies with held-out evaluation sets
- Alert on retrieval score distribution shifts (KL divergence monitoring)

---

## Real-World Example

### Premium User Retention Intelligence Platform

A SaaS company builds an AI-powered platform to predict and prevent customer churn for their enterprise accounts.

#### 1. Ingestion Layer

```
Web app → Kafka topic: user-events (page views, feature usage, API calls)
CRM      → Kafka topic: account-events (subscriptions, support tickets)
Billing  → Kafka topic: revenue-events (payments, upgrades, cancellations)

Volume: 50,000 events/minute across 200K users
```

#### 2. Stream Processing

```
Flink job: user-behavior-enrichment
  - Joins events with user profiles (tier, industry, ARR)
  - Computes session windows (30-min gap)
  - Calculates real-time features:
    • event_count_1h, error_rate_1h
    • feature_adoption_velocity
    • support_sentiment_trend
  - Routes to: Pinot (all events), Vector DB (semantic events), Feature Store
  - Alerts on: enterprise cancellation, critical support ticket from high-value user
```

#### 3. Analytics Layer (Apache Pinot)

```
Table: user_analytics
  - Hybrid table (real-time + offline)
  - Star-tree index on: tier × churn_risk × region
  - Query patterns: cohort analysis, churn risk ranking, revenue impact

P99 query latency: 45ms
```

#### 4. Semantic Retrieval (Vector DB)

```
Collection: user_behavior_embeddings
  - 128-dimensional vectors from behavior encoder model
  - Updated daily + delta updates on significant behavior changes
  - HNSW index with ef_search=100

Use case: "Find users behaving like users who churned last quarter"
```

#### 5. Intelligence Pipeline (Query → Response)

```
User: "Which enterprise accounts are at highest churn risk this quarter?"

1. Query Understanding → intent: churn_analysis, entity: tier=enterprise
2. Structured Retrieval → Pinot: top 10 by churn_risk_score WHERE tier=enterprise
3. Semantic Retrieval → Vector: similar-to-churned-user behavioral patterns
4. Feature Lookup → Feature Store: real-time health scores for top users
5. Rank Fusion → RRF merge of structured + semantic results
6. Context Assembly → ~2K tokens of structured context
7. LLM (GPT-4o) → Formatted churn analysis with recommendations

Total latency: 1.2s | Cost: $0.004 per query
```

#### 6. Observability

```
Dashboards:
  - Query latency P50/P95/P99 per stage
  - Token consumption and cost per query
  - Retrieval cache hit rates
  - Circuit breaker states
  - Model routing distribution
  - Alert: latency P95 > 3s, cost/day > $150, error rate > 1%
```

---

## Common Mistakes

### 1. Overusing Agents

**Mistake**: Building a multi-agent system with 5 agents that "discuss" and "debate" before responding.

**Reality**: For most production systems, a single orchestrator with typed tool calls is sufficient. Multi-agent adds latency, cost, and debugging complexity without proportional value. Use agents when you need genuinely independent reasoning paths — not for simple routing.

### 2. Ignoring Orchestration

**Mistake**: Calling the LLM directly with raw user queries and hoping retrieval-augmented generation (RAG) handles everything.

**Reality**: Without explicit orchestration (tool planning, retries, fallbacks, timeout budgets), the system is fragile. Every tool call should have a defined failure mode and recovery path.

### 3. Weak Observability

**Mistake**: Logging only the final response and LLM latency.

**Reality**: You need distributed traces across every stage. When a user reports "the AI gave a wrong answer," you need to trace back through retrieval results, tool calls, prompt content, and model selection to find the root cause.

### 4. Poor Retrieval Quality

**Mistake**: Assuming more context = better responses. Stuffing 10K tokens of marginally relevant data into the prompt.

**Reality**: Retrieval precision matters more than recall. 500 tokens of highly relevant context produces better responses than 5K tokens of loosely related data. And it costs 10x less.

### 5. Oversized Prompts

**Mistake**: Including entire database schemas, lengthy instructions, and every possible edge case in the system prompt.

**Reality**: Prompt size directly impacts cost and latency. A well-structured 500-token system prompt with clear instructions outperforms a 3000-token prompt with kitchen-sink coverage. Version your prompts and A/B test them.

---

## Key Takeaways

1. **Production AI is a distributed system, not an API call**. The LLM is <10% of the architecture. Data infrastructure, retrieval, orchestration, and observability are the other 90%.

2. **Two paths, one system**. The data path (ingestion → processing → storage) and query path (query → retrieval → reasoning → response) must be independently optimizable but share storage.

3. **Retrieval quality > model quality**. A cheaper model with excellent retrieval context outperforms an expensive model with poor context. Invest in retrieval first.

4. **Every tool call needs a fallback**. Circuit breakers, retries with backoff, cached fallbacks, and timeout budgets are non-negotiable in production.

5. **Agents coordinate, they don't think**. Keep agent logic deterministic and observable. Put reasoning in the LLM, coordination in the agent, and data in the retrieval layer.

6. **Cost engineering is architecture**. Model routing, caching, and retrieval optimization can reduce costs by 5-10x without degrading quality.

7. **Observability is the foundation**. If you can't trace a user's query through every layer of the system, you can't debug, optimize, or trust it.

---

## Interactive Simulation

Open **[simulation.html](simulation.html)** in your browser to visualize the complete architecture flow:

- Trigger user queries and observe the full pipeline execution
- Watch events flow through Kafka → Stream Processing → Downstream stores
- See retrieval, orchestration, and LLM reasoning in real-time
- Monitor latency, retries, caching, and observability metrics
- Dark futuristic UI with animated architecture flow

---

## Code Implementation

All simulations are in the `code/` directory:

| File | Layer | Description |
|------|-------|-------------|
| [event_producer.py](code/event_producer.py) | Kafka | Simulates event generation with partitioning and delivery semantics |
| [stream_processor.py](code/stream_processor.py) | Stream Processing | Enrichment, session windowing, feature computation, multi-sink routing |
| [retrieval_engine.py](code/retrieval_engine.py) | Retrieval | Hybrid structured + semantic retrieval with RRF fusion and caching |
| [agent_orchestrator.py](code/agent_orchestrator.py) | Orchestration | Tool coordination with circuit breakers, retries, fallbacks, and tracing |
| [llm_reasoning.py](code/llm_reasoning.py) | LLM | Model routing, prompt construction, response generation, cost tracking |
| [system_pipeline.py](code/system_pipeline.py) | End-to-End | Full pipeline wiring all layers with distributed tracing |

### Running the Pipeline

```bash
cd code/
python system_pipeline.py
```

This executes the full end-to-end flow: event ingestion → stream processing → query processing → response generation, with complete observability output.

### Running Individual Layers

```bash
python event_producer.py       # Test Kafka event generation
python stream_processor.py     # Test enrichment and routing
python retrieval_engine.py     # Test hybrid retrieval
python agent_orchestrator.py   # Test tool coordination
python llm_reasoning.py        # Test LLM reasoning
```

---

## Optional Tool Setup

### Apache Kafka (Local)

```bash
# Using Docker Compose
# docker-compose.yml
version: '3'
services:
  zookeeper:
    image: confluentinc/cp-zookeeper:7.5.0
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181

  kafka:
    image: confluentinc/cp-kafka:7.5.0
    depends_on: [zookeeper]
    ports: ["9092:9092"]
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1

  schema-registry:
    image: confluentinc/cp-schema-registry:7.5.0
    depends_on: [kafka]
    ports: ["8081:8081"]
    environment:
      SCHEMA_REGISTRY_HOST_NAME: schema-registry
      SCHEMA_REGISTRY_KAFKASTORE_BOOTSTRAP_SERVERS: kafka:9092
```

```bash
docker-compose up -d
# Verify: kafka-topics --bootstrap-server localhost:9092 --list
```

### Apache Pinot (Local)

```bash
# Quick start with Docker
docker run -p 9000:9000 apachepinot/pinot:latest QuickStart \
  -type batch

# Pinot Controller UI: http://localhost:9000
# Query Console: http://localhost:9000/#/query
```

### Vector DB — Qdrant (Local)

```bash
# Docker
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest

# Verify
curl http://localhost:6333/collections

# Python client
pip install qdrant-client
```

### Lightweight Orchestration Testing

```bash
# Python dependencies (all standard library except optional)
pip install redis          # For feature store simulation
pip install qdrant-client  # For vector DB integration

# Run the full pipeline locally
cd code/
python system_pipeline.py
```

> **Note**: The code simulations in this module run entirely with Python standard library — no external services required. The setup above is for teams that want to connect the simulations to real infrastructure.

---

## Folder Structure

```
day-27-end-to-end-architecture/
│── README.md                          # This document
│── simulation.html                    # Interactive architecture visualization
│── code/
│   ├── event_producer.py              # Kafka event generation simulation
│   ├── stream_processor.py            # Stream enrichment and routing
│   ├── retrieval_engine.py            # Hybrid retrieval with RRF fusion
│   ├── agent_orchestrator.py          # Tool coordination and reliability
│   ├── llm_reasoning.py              # LLM reasoning and cost tracking
│   └── system_pipeline.py            # End-to-end pipeline orchestration
│── diagrams/
│   └── architecture.md               # ASCII, Mermaid, and layered diagrams
```

---

<div align="center">

**Day 27 of 30 — AI Systems for Data Engineers**

*Production AI is not about the model. It's about everything around it.*

[← Day 26: Scaling & Cost](../day-26-scaling-cost/) · [Day 28: Case Study →](../day-28-case-study/)

</div>
