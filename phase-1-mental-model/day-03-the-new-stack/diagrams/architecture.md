# Architecture Diagrams — Day 03: The New Stack

---

## ASCII Diagram — Full Stack (Write + Read Paths)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                          DATA SOURCES                                        ║
║         [Web App]    [Mobile App]    [Backend Services]    [Docs/Files]      ║
╚═══════════╤══════════════╤═══════════════════╤══════════════════╤════════════╝
            │              │                   │                  │
            └──────────────┴───────────────────┘                  │
                           │                                       │
                           ▼                                       ▼
╔══════════════════════════════════════╗      ╔════════════════════════════════╗
║  LAYER 1 — STREAMING                 ║      ║  EMBEDDING PIPELINE            ║
║──────────────────────────────────────║      ║────────────────────────────────║
║                                      ║      ║  Triggered by: new docs/events ║
║  ┌─────────────────────────────────┐ ║      ║                                ║
║  │  Apache Kafka                   │ ║      ║  [Text Chunker]                ║
║  │  Topics: user.events            │ ║      ║       │                        ║
║  │          order.events           │ ║      ║       ▼                        ║
║  │          system.errors          │ ║      ║  [Embedding Model]             ║
║  └──────────────┬──────────────────┘ ║      ║  (text-embedding-3-small)      ║
║                 │                    ║      ║       │                        ║
║                 ▼                    ║      ║       ▼                        ║
║  ┌─────────────────────────────────┐ ║      ║  [Vector Store]                ║
║  │  Apache Flink                   │ ║      ║  Pinecone / Qdrant / pgvector  ║
║  │  - Enrich with user metadata    │ ║      ╚════════════════════════════════╝
║  │  - Filter noise                 │ ║
║  │  - Compute session windows      │ ║
║  │  - Detect anomalies             │ ║
║  └──────────────┬──────────────────┘ ║
╚═════════════════╪════════════════════╝
                  │
                  ▼
╔═════════════════════════════════════════════════════════════════════════════╗
║  LAYER 2 — REAL-TIME OLAP (Apache Pinot)                                    ║
║─────────────────────────────────────────────────────────────────────────────║
║                                                                             ║
║  Ingests from Kafka → builds columnar indexes → serves SQL in <100ms        ║
║                                                                             ║
║  Tables:  user_events_realtime   (last 7 days, hot)                         ║
║           user_events_offline    (historical, cold)                         ║
║           session_metrics        (aggregated per session)                   ║
║                                                                             ║
║  Query example:                                                             ║
║  SELECT user_id, COUNT(*) as errors                                         ║
║  FROM user_events_realtime                                                  ║
║  WHERE event='error' AND ts > ago('7d')                                     ║
║  GROUP BY user_id ORDER BY errors DESC LIMIT 10                             ║
╚═════════════════════════════════════════════════════════════════════════════╝
                  │
                  │  ◄─────────────────────────────────────────────────────┐
                  ▼                                                         │
╔═════════════════════════════════════════════════════════════════════════════╗
║  LAYER 3 — RETRIEVAL                                                        ║
║─────────────────────────────────────────────────────────────────────────────║
║                                                                             ║
║  [User Query] → [Query Parser] → [Query Embedder]                           ║
║                                        │                                   ║
║                    ┌───────────────────┤                                   ║
║                    ▼                   ▼                                   ║
║             [Vector Search]     [Pinot SQL Query]                          ║
║             (semantic top-k)    (structured metrics)                       ║
║                    │                   │                                   ║
║                    └─────────┬─────────┘                                   ║
║                              ▼                                             ║
║                    [Context Assembly]                                      ║
║                    (ranked, deduplicated, token-budgeted)                  ║
╚══════════════════════════════╪══════════════════════════════════════════════╝
                               │
                               ▼
╔═════════════════════════════════════════════════════════════════════════════╗
║  LAYER 4 — REASONING (LLM + Agents)                                         ║
║─────────────────────────────────────────────────────────────────────────────║
║                                                                             ║
║  [System Prompt] + [Retrieved Context] + [User Query]                       ║
║                              │                                             ║
║                              ▼                                             ║
║                    [LLM: GPT-4o / Claude / local]                          ║
║                              │                                             ║
║              ┌───────────────┼───────────────┐                             ║
║              ▼               ▼               ▼                             ║
║       [Text Response]  [JSON Output]  [Tool Call]                          ║
║                                           │                                ║
║                                           ▼                                ║
║                                    [Agent executes tool]                   ║
║                                    → SQL query                             ║
║                                    → API call                              ║
║                                    → Vector search                         ║
╚═════════════════════════════════════════════════════════════════════════════╝

╔═════════════════════════════════════════════════════════════════════════════╗
║  LAYER 5 — ORCHESTRATION (Airflow / Prefect / Dagster)                      ║
║─────────────────────────────────────────────────────────────────────────────║
║                                                                             ║
║  Manages:  nightly_batch_features     → runs 00:00 UTC daily               ║
║            embedding_pipeline         → triggered on new document arrival  ║
║            data_quality_checks        → runs before downstream jobs        ║
║            model_eval_pipeline        → runs after each LLM config change  ║
║            pinot_segment_compaction   → runs weekly                        ║
║                                                                             ║
║  Provides: dependency graph · retry logic · SLA alerting · audit logs      ║
╚═════════════════════════════════════════════════════════════════════════════╝
```

---

## Mermaid Diagram — Full Stack Architecture

```mermaid
flowchart TD
    subgraph Sources["Data Sources"]
        S1[Web / Mobile App]
        S2[Backend Services]
        S3[Documents / Files]
    end

    subgraph L1["Layer 1 — Streaming"]
        K[Apache Kafka\nTopics: user.events, order.events]
        F[Apache Flink\nenrich · filter · window]
    end

    subgraph L2["Layer 2 — Real-Time OLAP"]
        P[Apache Pinot\nSub-second SQL on fresh data]
    end

    subgraph L3["Layer 3 — Retrieval"]
        EP[Embedding Pipeline\ntext → vectors]
        VS[Vector Store\nPinecone / Qdrant]
        RL[Retrieval Layer\nvector + SQL hybrid]
    end

    subgraph L4["Layer 4 — Reasoning"]
        QP[Query Parser\nintent + entities]
        CA[Context Assembly]
        LLM[LLM\nGPT-4o / Claude]
        OUT[Response / Action]
    end

    subgraph L5["Layer 5 — Orchestration"]
        ORC[Airflow / Prefect\nDAGs · retries · alerting]
    end

    S1 --> K
    S2 --> K
    S3 --> EP
    K --> F --> P
    F --> EP --> VS
    P --> RL
    VS --> RL
    RL --> CA
    QP --> RL
    CA --> LLM --> OUT
    ORC -.manages.-> F
    ORC -.manages.-> EP
    ORC -.manages.-> P

    style L1 fill:#0d1e30,color:#7eb8f7
    style L2 fill:#0d2a1a,color:#7ef7a0
    style L3 fill:#1a0d30,color:#b07ef7
    style L4 fill:#2a0d1a,color:#f77eb0
    style L5 fill:#1a1a0d,color:#f7f77e
    style Sources fill:#1a1a1a,color:#ccc
```

---

## Mermaid Diagram — Query Path (Read Flow)

```mermaid
sequenceDiagram
    participant U as User
    participant QP as Query Parser
    participant VS as Vector Store
    participant PT as Apache Pinot
    participant CA as Context Assembly
    participant LM as LLM

    U->>QP: "Why is user u_001 churning?"
    QP->>QP: extract intent=churn, user_id=u_001

    par Parallel retrieval
        QP->>VS: semantic search (top-4 chunks, filter: u_001)
        QP->>PT: SELECT metrics WHERE user_id='u_001' AND ts > ago('7d')
    end

    VS-->>CA: 4 relevant event descriptions
    PT-->>CA: {page_views: 14, errors: 3, churn_risk: "high"}

    CA->>LM: system_prompt + context + query
    LM-->>U: "User u_001 visited /pricing 6 times, encountered 3 checkout errors..."

    Note over U,LM: Total latency: ~600ms
```

---

## Layer Responsibility Matrix

| Layer | Reads from | Writes to | Latency | Failure impact |
|-------|-----------|-----------|---------|----------------|
| Kafka | App events | Topic partitions | <10ms publish | Events lost or delayed |
| Flink | Kafka topics | Pinot, Vector pipeline | <100ms processing | Stale enrichment |
| Pinot | Kafka (via connector) | Columnar segments | <100ms query | No fresh structured data |
| Vector Store | Embedding pipeline | Index | <50ms query | No semantic retrieval |
| LLM | Context window | Response tokens | 200ms–2s | No reasoning output |
| Orchestrator | DAG definitions | Job state, logs | N/A (control plane) | Silent pipeline failures |
