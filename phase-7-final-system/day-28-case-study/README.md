# AI Systems for Data Engineers — Day 28: Deep Dive Production Case Study
## User Activity Intelligence Platform: Premium Churn Detection at Scale

Welcome to the Day 28 Production Case Study module. This repository contains the architecture design, simulation codebase, and interactive visualization dashboard for a real-world, premium-grade **User Activity Intelligence Platform**. 

Production AI systems are not standalone chatbots. When deployed in enterprise environments, they are complex, distributed data engineering pipelines. This case study demonstrates how stateful stream processing, low-latency analytical data stores, vector search, and LLM reasoning agents converge to detect and mitigate premium customer churn patterns under tight service level agreements (SLAs), network outages, and pricing constraints.

---

## 1. Systems Engineering Realities of Production AI

Modern AI software engineering often hides the underlying system architectures behind thin client libraries. However, building and operating a reliable intelligence platform at scale highlights several core systems engineering challenges:

### Nondeterministic Latency Profile
Unlike traditional microservices which feature predictable p95 latency bounds, LLM inference API calls suffer from high variance. A standard reasoning cycle can take anywhere from $300\text{ms}$ (utility tier) to $15,000\text{ms}$ (deep reasoning/premium tiers) depending on network queue depth, gateway congestion, and prompt size. This platform models this real-world variance and implements mitigation patterns like query budgeting and fallback models to prevent cascading timeouts.

### Stateful Stream Processing vs. Database Overloads
Feeding raw activity logs directly to LLMs is cost-prohibitive and computationally inefficient. A production architecture must separate the high-throughput write path (events ingestion) from the read path (user-facing query engine). We use stateful stream processing (Flink) to aggregate rolling event patterns over a $30$-minute window. This enriches the incoming records and writes compact status vectors into the analytical (Pinot) and vector databases, preventing database query execution exhaustion.

### Retrieval Drift & Data Freshness
Analytical queries (OLAP) and semantic lookups (Vector search) must reflect the user's latest behavioral patterns. If a premium customer triggers a string of support tickets and billing failures, the vector embeddings cache becomes stale until the database updates. This system demonstrates the tradeoff between embedding update freshness (costly real-time computation) and query latency, using an automated output fact-checking verification layer to identify when the model refers to outdated state.

---

## 2. Complete System Architecture

The User Activity Intelligence Platform separates the **Asynchronous Ingestion Path** (write path) from the **Synchronous Agentic Query Path** (read path) to optimize performance, isolation, and scalability.

```
       [ Client Activity Events ]
                   │
                   ▼ (Hash Partition by User ID)
         ┌───────────────────┐
         │    Kafka Topic    │
         └─────────┬─────────┘
                   │
                   ▼ (30-Minute Session Aggregations)
         ┌───────────────────┐
         │ Flink Stream Proc.├─────────┐
         └────┬──────────┬───┘         │ (Schema Breach)
              │          │             ▼
              │          │      ┌─────────────┐
              │          │      │  Kafka DLQ  │
              ▼          ▼      └─────────────┘
          ┌───────┐  ┌───────┐
          │ Pinot │  │Vector │
          │ OLAP  │  │DB HNSW│
          └─▲─────┘  └─▲─────┘
            │          │
    ┌───────┴──────────┴───────┐
    │    Agent Orchestrator    │◄────── [ Client Query ]
    └──────────┬───────────────┘
               │ (Dynamic Route)
               ▼
     ┌───────────────────┐      ┌────────────────┐
     │    LLM Gateway    ├─────►│ Semantic Cache │
     └───────────────────┘      └────────────────┘
```

### Asynchronous Data Ingestion Path
1. **Event Stream (Kafka)**: Telemetry sources (web clients, billing systems, workspace backends) emit user action events. The event producer hashes `user_id` to partition messages, guaranteeing that events for any single user are processed sequentially in order.
2. **Stateful Stream Processor (Flink)**: Windowed operators group events by user over sliding $30$-minute sessions. It maintains state to count billing failures, error rate spikes, and support sentiment scores.
3. **Downstream Database Sinks**: Aggregated summaries are sunk to two data stores:
   - **Apache Pinot**: An OLAP database optimized for real-time aggregation queries on structured fields (e.g., filtering users with ARR $> \$50,000$ and billing errors $> 3$).
   - **Vector Database (HNSW)**: Stores behavioral trajectory embeddings representing historical patterns of known churners.
4. **Dead Letter Queue (DLQ)**: Events violating schemas or failing ingestion checks are routed to a Kafka DLQ topic for alerting and manual replay.

### Synchronous Agentic Query Path
1. **Agent Orchestrator**: Coordinates database retrieval, execution budgets, and fallback systems.
2. **Hybrid Retrieval**:
   - **SQL Pinot Tool**: Fetches structured cohorts matching specified filters.
   - **Semantic Vector Search Tool**: Identifies behavioral similarity vectors using Cosine similarity.
   - **Reciprocal Rank Fusion (RRF)**: Combines structured metrics and semantic embeddings into a single ranked list. The fusion formula computes a fused score for each user:
     $$RRF\_Score(d \in D) = \sum_{m \in M} \frac{1}{60 + r_m(d)}$$
     where $M$ represents the search tools and $r_m(d)$ is the rank of document $d$ in tool $m$.
3. **LLM Gateway & Router**: Selects the appropriate model based on prompt complexity and context size:
   - **Utility Tier (e.g., GPT-4o-mini)**: For simple summaries or small contexts.
   - **Standard Tier (e.g., GPT-4o)**: Default analytical reasoning model.
   - **Premium Tier (e.g., GPT-4-turbo)**: Triggered automatically for large context payloads.
4. **Semantic Cache**: Intercepts queries at the gateway. Matches queries with identical parameters and valid TTL values to bypass LLM inference entirely.

---

## 3. Real Production Workflows & Tradeoffs

Architecting distributed AI platforms involves balancing competing constraints:

| Tradeoff Axis | Choice A | Choice B | Selected Balance in Our Platform |
| :--- | :--- | :--- | :--- |
| **Latency vs. Quality** | Deep, multi-step agent reasoning loops (High SLA cost) | Fast, single-pass retrieval augmented queries (Low latency) | **Dynamic Reasoning Budgets**: The orchestrator enforces strict timeouts (e.g., $1500\text{ms}$). If databases respond slowly, the agent limits reasoning cycles and downgrades to cached data. |
| **Freshness vs. Caching** | Direct, real-time table joins on database queries | Cached vector snapshots & precompiled profiles | **Lambda-Hybrid Querying**: Pinot provides real-time event updates, while Vector DB queries historical patterns. The RRF layer merges both to maintain freshness while reducing indexing overhead. |
| **Token Size vs. Cost** | Packing raw session traces in LLM prompts (Verbose context) | Context compression & aggregated feature stores | **Feature Adoptions & Embedding Sinks**: Flink aggregates the behavior stream beforehand. Instead of raw logs, the prompt receives structured summaries, saving over $90\%$ in token costs. |

---

## 4. System Failure Modes & Reliability Engineering

Day 2 operations require handling inevitable network and API errors. This system implements four production-grade resilience patterns:

### Circuit Breakers
To prevent slow downstream systems from exhausting connection pools and thread workers, circuit breakers monitor connection states. If Pinot queries timeout or Vector DB drops connections consecutively (threshold $= 3$):
- The circuit trips to **OPEN**.
- Future calls bypass the dependency instantly, preventing thread starvation.
- The system returns cached or fallback data.
- After a cool-down window ($8\text{ seconds}$), the circuit goes to **HALF-OPEN**, sending a canary probe to test for recovery.

### Retries with Jittered Exponential Backoff
When the LLM Gateway encounters transient errors (like HTTP 429 Rate Limits), it retries using exponential backoff:
$$Delay = Base \times 2^{attempt} + Jitter$$
Jitter introduces random noise to prevent retrying clients from hammering the service simultaneously (the "thundering herd" problem).

### Dead Letter Queues (DLQ)
Malformed event schemas can crash stateful operators. Rather than halting the stream, Flink routes bad payloads to a Kafka DLQ partition, increments alerting metrics, and resumes processing the event stream.

### Graceful Degradation
If the LLM reasoning tier is completely unavailable, the platform degrades to structured Pinot SQL output, presenting raw analytical tables directly to the user rather than rendering a blank page or returning a 500 error.

---

## 5. Cost & Observability Engineering

Production platforms require deep telemetry to manage budgets and monitor model hallucinations.

### OpenTelemetry Distributed Tracing Schema
Every user request initializes a transaction trace consisting of parent and child spans. This allows developers to localize performance bottlenecks:

```json
{
  "trace_id": "c9ef92c8-ecce-4934-86a1-858d56cee196",
  "name": "IntelligenceQueryFlow",
  "total_latency_ms": 1011.8,
  "status": "SUCCESS",
  "spans": [
    {
      "name": "QueryUnderstandingIntent",
      "span_id": "4dc11fa2",
      "parent_span_id": null,
      "latency_ms": 0.0,
      "status": "SUCCESS"
    },
    {
      "name": "AgentOrchestrationAndRetrieval",
      "span_id": "54da7a78",
      "parent_span_id": "4dc11fa2",
      "latency_ms": 53.8,
      "status": "SUCCESS",
      "metadata": {
        "orchestrator_status": "completed",
        "tools_triggered": [
          { "tool": "structured_pinot_lookup", "status": "success", "latency_ms": 19.16 },
          { "tool": "semantic_vector_search", "status": "success", "latency_ms": 34.64 }
        ]
      }
    },
    {
      "name": "LLMReasoningAndVerification",
      "span_id": "ed7bd1e8",
      "parent_span_id": "4dc11fa2",
      "latency_ms": 957.5,
      "status": "SUCCESS",
      "metadata": {
        "model": "gpt-4o",
        "tier": "standard",
        "cost_usd": 0.00285,
        "tokens_input": 230,
        "tokens_output": 350
      }
    }
  ]
}
```

### Prometheus Metrics Instrumentation
The platform exposes several Prometheus counters, gauges, and histograms to track system performance:
- `llm_cost_usd_total`: Gauge tracking cumulative API spend.
- `llm_rate_limits_total`: Counter tracking HTTP 429 throttles.
- `llm_hallucinations_detected_total`: Counter tracking fact-check mismatches.
- `pinot_query_latency_seconds`: Histogram tracking analytical latency percentiles ($p50$, $p95$, $p99$).

---

## 6. Lessons Learned & V2 Architecture Roadmap

Running this simulation demonstrates critical production takeaways:
1. **Dynamic Model Routing is a Cost-Saver**: Directing $100\%$ of queries to premium models like GPT-4-turbo drains budgets. Routing queries under $1000$ characters to GPT-4o-mini reduces costs by up to $85\%$ without degrading summary quality.
2. **Hallucination Checking Must Be Grounded**: LLMs frequently output fictional user IDs (e.g., referencing users not present in the retrieval context). Implementing a post-generation fact-check parser (matching output tags against retrieved database records) is necessary to catch and suppress hallucinated statements.

### V2 Roadmap
- **Semantic Cache Invalidation Hooks**: Triggering Cache invalidate signals from the Flink stream when a customer's churn risk score rises above $0.80$, ensuring queries immediately pull fresh data.
- **Asynchronous Agent Queues**: Moving deep reasoning tasks off the synchronous query path onto Celery/Redis workers to prevent blocking client connection pools.
- **Multi-LLM Provider Fallbacks**: Implementing automated routing from OpenAI to Anthropic/Google endpoints when the primary gateway experiences persistent HTTP 429 rate limits or timeouts.

---

## 7. Runnable Code Structure & Setup

This case study is implemented using the Python standard library, requiring no external dependencies to run.

### File Directory Layout
* [`code/event_stream.py`](file:///d:/AI_Systems_for_Data_Engineers/AI-Systems-For-Data-Engineers/phase-7-final-system/day-28-case-study/code/event_stream.py): Kafka broker partition-by-user simulation.
* [`code/stream_processor.py`](file:///d:/AI_Systems_for_Data_Engineers/AI-Systems-For-Data-Engineers/phase-7-final-system/day-28-case-study/code/stream_processor.py): Stateful Flink enricher, session windowing, and DLQ router.
* [`code/retrieval_engine.py`](file:///d:/AI_Systems_for_Data_Engineers/AI-Systems-For-Data-Engineers/phase-7-final-system/day-28-case-study/code/retrieval_engine.py): Pinot OLAP query matching, Vector HNSW cosine search, RRF fusion, and semantic cache.
* [`code/agent_orchestrator.py`](file:///d:/AI_Systems_for_Data_Engineers/AI-Systems-For-Data-Engineers/phase-7-final-system/day-28-case-study/code/agent_orchestrator.py): Resilient tool coordinator, timeouts, and circuit breaker.
* [`code/llm_reasoning.py`](file:///d:/AI_Systems_for_Data_Engineers/AI-Systems-For-Data-Engineers/phase-7-final-system/day-28-case-study/code/llm_reasoning.py): Router, token bookkeeping, 429 backoff simulator, and fact validation.
* [`code/observability.py`](file:///d:/AI_Systems_for_Data_Engineers/AI-Systems-For-Data-Engineers/phase-7-final-system/day-28-case-study/code/observability.py): Telemetry collector, structured JSON logger, tracing, and metric histograms.
* [`code/failure_simulator.py`](file:///d:/AI_Systems_for_Data_Engineers/AI-Systems-For-Data-Engineers/phase-7-final-system/day-28-case-study/code/failure_simulator.py): Global runtime chaos state controller.
* [`code/system_pipeline.py`](file:///d:/AI_Systems_for_Data_Engineers/AI-Systems-For-Data-Engineers/phase-7-final-system/day-28-case-study/code/system_pipeline.py): E2E execution pipeline containing normal and failure loops.
* [`simulation.html`](file:///d:/AI_Systems_for_Data_Engineers/AI-Systems-For-Data-Engineers/phase-7-final-system/day-28-case-study/simulation.html): Interactive cyberpunk control dashboard.
* [`diagrams/architecture.md`](file:///d:/AI_Systems_for_Data_Engineers/AI-Systems-For-Data-Engineers/phase-7-final-system/day-28-case-study/diagrams/architecture.md): System sequence, failure propagation, and tracing diagrams.

### Running the Backend Simulation
To run the complete backend chaos test pipeline:
```powershell
python phase-7-final-system/day-28-case-study/code/system_pipeline.py
```

### Running the Interactive Dashboard
To launch the interactive control dashboard, open [`simulation.html`](file:///d:/AI_Systems_for_Data_Engineers/AI-Systems-For-Data-Engineers/phase-7-final-system/day-28-case-study/simulation.html) in any modern browser. You can tune sliders, inject chaos events, view real-time traces, and trigger thundering herd storms.
