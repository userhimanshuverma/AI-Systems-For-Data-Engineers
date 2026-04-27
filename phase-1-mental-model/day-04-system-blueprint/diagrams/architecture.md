# Architecture Diagrams — Day 04: System Blueprint

---

## ASCII Diagram — Full System (Write + Read Paths)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                          DATA SOURCES                                        ║
║    [Web App]   [Mobile App]   [Backend Services]   [Support Docs]            ║
╚═══════╤════════════╤══════════════════╤═══════════════════╤══════════════════╝
        │            │                  │                   │
        └────────────┴──────────────────┘                   │
                     │  publish events                       │ ingest docs
                     ▼                                       ▼
╔════════════════════════════════════╗     ╔══════════════════════════════════╗
║  STREAMING BACKBONE                ║     ║  DOCUMENT PIPELINE               ║
║  Apache Kafka                      ║     ║  Chunker → Embedder              ║
║                                    ║     ║  (triggered by new doc arrival)  ║
║  Topics:                           ║     ╚══════════════════╤═══════════════╝
║  ├── user.events    (12 partitions)║                        │
║  ├── system.errors  (6 partitions) ║                        │ upsert vectors
║  └── support.tickets(3 partitions) ║                        ▼
╚════════════════╤═══════════════════╝     ╔══════════════════════════════════╗
                 │ consume                 ║  VECTOR STORE                    ║
                 ▼                         ║  Qdrant / Pinecone               ║
╔════════════════════════════════════╗     ║  ├── user_events namespace        ║
║  STREAM PROCESSING                 ║     ║  └── support_docs namespace       ║
║  Apache Flink                      ║     ╚══════════════════╤═══════════════╝
║                                    ║                        ▲
║  ├── Enrich (user profile lookup)  ║                        │ upsert
║  ├── Session windowing (30min gap) ║─────────────────────────┘
║  ├── Anomaly detection             ║  emit to embedding pipeline
║  └── Route to sinks                ║
╚════════════════╤═══════════════════╝
                 │ write enriched events
                 ▼
╔════════════════════════════════════════════════════════════════════════════╗
║  REAL-TIME OLAP                                                            ║
║  Apache Pinot                                                              ║
║                                                                            ║
║  Tables:                                                                   ║
║  ├── user_events_realtime   (7-day retention, hot segments)                ║
║  ├── user_metrics_daily     (2-year retention, offline segments)           ║
║  └── session_summary        (30-day retention, hybrid)                     ║
║                                                                            ║
║  Query: SELECT user_id, COUNT(*) as errors                                 ║
║         FROM user_events_realtime                                          ║
║         WHERE event='error' AND ts > ago('7d')                             ║
║         GROUP BY user_id  →  P99 latency: <100ms                          ║
╚════════════════════════════════════════════════════════════════════════════╝
         ▲                                    ▲
         │ SQL query                          │ vector search
         │                                   │
╔════════════════════════════════════════════════════════════════════════════╗
║  LLM REASONING LAYER                                                       ║
║                                                                            ║
║  [Query Parser]  →  [Retrieval Layer]  →  [Context Assembly]  →  [LLM]   ║
║                       ├── Pinot SQL                                        ║
║                       └── Vector search                                    ║
║                                                                            ║
║  Output: text response · JSON · tool call · confidence score               ║
╚════════════════════════════════════════════════════════════════════════════╝
         ▲
         │ query
╔════════════════════════════════════════════════════════════════════════════╗
║  API / USER LAYER                                                          ║
║  REST API · WebSocket · Support UI                                         ║
║  Auth · Rate limiting · Response caching                                   ║
╚════════════════════════════════════════════════════════════════════════════╝

╔════════════════════════════════════════════════════════════════════════════╗
║  ORCHESTRATION (cross-cutting)                                             ║
║  Apache Airflow                                                            ║
║  DAGs: nightly_feature_compute · embedding_refresh · data_quality_checks  ║
║        model_eval · pinot_compaction                                       ║
╚════════════════════════════════════════════════════════════════════════════╝


WRITE PATH (event ingestion):
  App → Kafka → Flink → Pinot (structured, queryable in ~1s)
                      → Embedding Pipeline → Vector Store (semantic, queryable in ~50ms)

READ PATH (query flow):
  User → API → Query Parser → [Pinot SQL + Vector Search] → Context Assembly
       → LLM → Response (total: ~600ms)
```

---

## Mermaid Diagram — Full System Architecture

```mermaid
flowchart TD
    subgraph SRC["Data Sources"]
        A1[Web / Mobile App]
        A2[Backend Services]
        A3[Support Documents]
    end

    subgraph STREAM["Streaming Backbone"]
        K[Apache Kafka\nuser.events · system.errors · support.tickets]
    end

    subgraph PROC["Stream Processing"]
        FL[Apache Flink\nenrich · window · detect · route]
    end

    subgraph STORE["Storage Layer"]
        PT[Apache Pinot\nReal-Time OLAP\nSub-second SQL]
        EP[Embedding Pipeline\ntext → vectors]
        VS[Vector Store\nQdrant / Pinecone]
    end

    subgraph REASON["Reasoning Layer"]
        QP[Query Parser\nintent + entities]
        RL[Retrieval Layer\nvector + SQL hybrid]
        CA[Context Assembly\ntoken-budgeted]
        LM[LLM\nGPT-4o / Claude]
    end

    subgraph API["API / User Layer"]
        AP[REST API\nAuth · Cache · Rate limit]
        UI[Support UI]
    end

    subgraph ORC["Orchestration"]
        AF[Apache Airflow\nDAGs · retries · SLA alerts]
    end

    A1 --> K
    A2 --> K
    A3 --> EP
    K --> FL
    FL --> PT
    FL --> EP
    EP --> VS
    VS --> RL
    PT --> RL
    UI --> AP --> QP --> RL --> CA --> LM
    LM --> AP
    AF -.monitors.-> FL
    AF -.monitors.-> EP
    AF -.monitors.-> PT

    style SRC   fill:#0d0d0d,color:#888
    style STREAM fill:#0d1e30,color:#7eb8f7
    style PROC  fill:#0d2a1a,color:#7ef7a0
    style STORE fill:#1a0d30,color:#b07ef7
    style REASON fill:#2a0d1a,color:#f77eb0
    style API   fill:#1a1a0d,color:#f7f77e
    style ORC   fill:#1a1a1a,color:#aaa
```

---

## Mermaid Diagram — Write Path Sequence

```mermaid
sequenceDiagram
    participant App as Web App
    participant K as Kafka
    participant FL as Flink
    participant PT as Pinot
    participant EP as Embedding Pipeline
    participant VS as Vector Store

    App->>K: publish event {user_id, event_type, ts}
    Note over K: stored in partition, offset assigned

    K->>FL: deliver event (<10ms)
    FL->>FL: enrich with user profile
    FL->>FL: update session window state

    par parallel sinks
        FL->>PT: write enriched event
        Note over PT: queryable within ~1s
    and
        FL->>EP: emit event text
        EP->>EP: generate embedding vector
        EP->>VS: upsert vector + metadata
        Note over VS: queryable within ~50ms
    end
```

---

## Mermaid Diagram — Read Path Sequence

```mermaid
sequenceDiagram
    participant U as Support Agent
    participant API as REST API
    participant QP as Query Parser
    participant VS as Vector Store
    participant PT as Apache Pinot
    participant CA as Context Assembly
    participant LM as LLM

    U->>API: "Why is user u_4821 struggling?"
    API->>QP: parse query
    QP->>QP: intent=error_investigation, user_id=u_4821

    par parallel retrieval
        QP->>VS: semantic search (top-4, filter: u_4821)
        VS-->>CA: 4 relevant event descriptions
    and
        QP->>PT: SELECT metrics WHERE user_id='u_4821'
        PT-->>CA: {errors_7d:5, churn_risk:"high", ...}
    end

    CA->>CA: assemble + token-budget context
    CA->>LM: system_prompt + context + query
    LM-->>API: structured response + evidence + confidence
    API-->>U: explanation + recommended action

    Note over U,LM: Total latency: ~600ms
```

---

## Component Latency Budget

```
Query received by API                    t=0ms
├── Query parsing                        t=5ms
├── Parallel retrieval starts            t=10ms
│   ├── Vector search (Qdrant)           t=60ms   (+50ms)
│   └── Pinot SQL query                  t=80ms   (+70ms)
├── Context assembly                     t=90ms   (+10ms)
├── LLM call (GPT-4o-mini)              t=550ms  (+460ms)
└── Response serialization + return      t=600ms  (+50ms)

Total: ~600ms P50 | ~900ms P99
```
