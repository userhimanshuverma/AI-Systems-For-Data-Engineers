# Architecture Diagrams — Day 02

## Batch vs Real-Time vs AI Systems

---

## ASCII Diagram — Three-Layer Architecture

```
╔══════════════════════════════════════════════════════════════════════╗
║                    DATA SOURCES                                      ║
║   [App Events]  [Databases]  [Files / Logs]  [APIs]  [Documents]    ║
╚══════════╤═══════════════════════════════════════════════════════════╝
           │
           ├─────────────────────────────────────────────────────────┐
           │                                                         │
           ▼                                                         ▼
╔══════════════════════════╗                    ╔════════════════════════════╗
║   LAYER 1 — BATCH        ║                    ║  LAYER 2 — REAL-TIME       ║
║──────────────────────────║                    ║────────────────────────────║
║  Trigger: Cron / Schedule║                    ║  Trigger: Event-driven     ║
║  Latency: Hours          ║                    ║  Latency: Milliseconds     ║
║                          ║                    ║                            ║
║  [Spark / dbt]           ║                    ║  [Kafka]                   ║
║       │                  ║                    ║     │                      ║
║       ▼                  ║                    ║     ▼                      ║
║  [Snowflake / BigQuery]  ║                    ║  [Flink / Kafka Streams]   ║
║       │                  ║                    ║     │                      ║
║       ▼                  ║                    ║     ▼                      ║
║  [Historical Tables]     ║                    ║  [Apache Pinot]            ║
║  (30/60/90-day metrics)  ║                    ║  (real-time OLAP)          ║
╚══════════╤═══════════════╝                    ╚══════════╤═════════════════╝
           │                                               │
           └───────────────────┬───────────────────────────┘
                               │
                               ▼
╔══════════════════════════════════════════════════════════════════════╗
║                    LAYER 3 — AI / REASONING                          ║
║──────────────────────────────────────────────────────────────────────║
║  Trigger: On-demand (user query or event)                            ║
║  Latency: 100ms – 2s                                                 ║
║                                                                      ║
║  [Embedding Pipeline]  →  [Vector Store (Pinecone / Qdrant)]        ║
║                                    │                                 ║
║  [Structured Query (Pinot/SQL)] ───┤                                 ║
║                                    ▼                                 ║
║                          [Retrieval Layer]                           ║
║                                    │                                 ║
║                                    ▼                                 ║
║                          [LLM (GPT-4o / Claude)]                    ║
║                                    │                                 ║
║                                    ▼                                 ║
║                     [Response / Decision / Action]                   ║
╚══════════════════════════════════════════════════════════════════════╝


FLOW SUMMARY
────────────────────────────────────────────────────────────────────────
Batch Layer    → Historical aggregations, feature tables, cohort data
Real-Time Layer → Fresh events, enriched streams, low-latency queries
AI Layer       → Retrieval + reasoning over both layers
────────────────────────────────────────────────────────────────────────
```

---

## ASCII Diagram — Side-by-Side System Comparison

```
BATCH SYSTEM              REAL-TIME SYSTEM          AI SYSTEM
─────────────────         ─────────────────         ─────────────────
[Source Data]             [Event Source]            [User Query]
      │                         │                         │
      ▼                         ▼                         ▼
[Scheduled Job]           [Kafka Topic]             [Query Parser]
(runs every hour)         (continuous)              (intent + entities)
      │                         │                         │
      ▼                         ▼                         ▼
[Spark Transform]         [Stream Processor]        [Retrieval Layer]
(aggregate, clean)        (enrich, filter)          (vector + SQL)
      │                         │                         │
      ▼                         ▼                         ▼
[Write to Warehouse]      [Write to Pinot]          [Context Assembly]
(Snowflake / BQ)          (real-time OLAP)          (top-k chunks)
      │                         │                         │
      ▼                         ▼                         ▼
[SQL Query]               [Low-latency Query]       [LLM Reasoning]
      │                         │                         │
      ▼                         ▼                         ▼
[Dashboard / Report]      [Alert / Live UI]         [Generated Response]

Trigger:  CRON             EVENT                     ON-DEMAND
Latency:  HOURS            MILLISECONDS              100ms–2s
Output:   TABLE/CHART      ALERT/UPDATE              TEXT/DECISION
Consumer: HUMAN (BI)       SYSTEM/HUMAN              HUMAN/AGENT
```

---

## Mermaid Diagram — Full Layered Architecture

```mermaid
flowchart TD
    subgraph Sources["Data Sources"]
        S1[App Events]
        S2[Databases]
        S3[Documents / Logs]
    end

    subgraph Batch["Layer 1 — Batch"]
        B1[Spark / dbt]
        B2[Snowflake / BigQuery]
        B3[Historical Tables]
    end

    subgraph RealTime["Layer 2 — Real-Time"]
        R1[Kafka]
        R2[Flink / Kafka Streams]
        R3[Apache Pinot]
    end

    subgraph AI["Layer 3 — AI / Reasoning"]
        A1[Embedding Pipeline]
        A2[Vector Store]
        A3[Retrieval Layer]
        A4[LLM]
        A5[Response / Action]
    end

    S1 --> R1
    S2 --> B1
    S3 --> A1

    B1 --> B2 --> B3
    R1 --> R2 --> R3

    B3 --> A3
    R3 --> A3
    A1 --> A2 --> A3
    A3 --> A4 --> A5

    style Batch fill:#0d1e30,color:#7eb8f7
    style RealTime fill:#0d2a1a,color:#7ef7a0
    style AI fill:#1a0d30,color:#b07ef7
    style Sources fill:#1a1a1a,color:#ccc
```

---

## Mermaid Diagram — Event Flow (Real-Time Path)

```mermaid
sequenceDiagram
    participant App as Application
    participant Kafka as Kafka Topic
    participant Flink as Flink Processor
    participant Pinot as Apache Pinot
    participant LLM as LLM Layer

    App->>Kafka: publish event (user.clicked /pricing)
    Kafka->>Flink: deliver event (< 10ms)
    Flink->>Flink: enrich with user metadata
    Flink->>Pinot: write enriched event
    Note over Pinot: queryable within ~1s

    Note over LLM: Later — support agent asks a question
    LLM->>Pinot: query recent events for user
    Pinot-->>LLM: return last 20 events
    LLM->>LLM: reason over context
    LLM-->>App: return explanation
```

---

## Key Architectural Decisions

| Decision | Reason |
|----------|--------|
| Kafka as event bus | Durable, replayable, horizontally scalable. The source of truth for real-time events. |
| Flink for stream processing | Stateful operations (joins, aggregations) with exactly-once semantics. |
| Pinot for real-time OLAP | Sub-second queries on data that's seconds old. Bridges real-time and query layers. |
| Vector store for AI layer | Enables semantic retrieval — finding relevant context by meaning, not exact match. |
| LLM at the top | Reasons over pre-retrieved context. Never touches raw data directly. |
| Batch layer retained | Historical data doesn't need real-time processing. Batch is cheaper and simpler for it. |
