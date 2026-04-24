# Architecture Diagrams — Day 01

## Traditional Pipeline vs AI-Enabled System

---

## ASCII Comparison

```
TRADITIONAL DATA PIPELINE
─────────────────────────────────────────────────────────────────

  [Data Source]
       │
       ▼
  [Ingest Layer]        ← Kafka / Fivetran / Airbyte
       │
       ▼
  [Transform Layer]     ← Spark / dbt / SQL
       │
       ▼
  [Storage Layer]       ← Snowflake / BigQuery / S3
       │
       ▼
  [Query Layer]         ← SQL / Presto / Athena
       │
       ▼
  [BI / Dashboard]      ← Tableau / Looker
       │
       ▼
  [Human reads chart]

  Trigger: SCHEDULED (cron)
  Latency: Minutes → Hours
  Consumer: Human


AI-ENABLED INTELLIGENT SYSTEM
─────────────────────────────────────────────────────────────────

  [Data Source]
       │
       ▼
  [Ingest Layer]        ← Kafka (real-time events)
       │
       ▼
  [Enrich + Process]    ← Flink / Kafka Streams
       │
       ├──────────────────────────┐
       ▼                          ▼
  [Structured Store]        [Embedding Pipeline]
  (Postgres / Pinot)         (text → vectors)
                                  │
                                  ▼
                            [Vector Store]
                            (Pinecone / Qdrant / pgvector)
                                  │
       ┌───────────────────────────┘
       ▼
  [Retrieval Layer]     ← semantic search + filters
       │
       ▼
  [LLM Reasoning]       ← OpenAI / Anthropic / local model
       │
       ▼
  [Agent / Action]      ← responds, routes, triggers workflow
       │
       ▼
  [Feedback Loop]       ← logs outcome → improves retrieval

  Trigger: EVENT-DRIVEN
  Latency: Milliseconds → Seconds
  Consumer: LLM / Agent
```

---

## Mermaid Diagram

### Traditional Pipeline

```mermaid
flowchart LR
    A[Data Source] --> B[Ingest]
    B --> C[Transform]
    C --> D[Storage\nSnowflake / S3]
    D --> E[Query\nSQL]
    E --> F[Dashboard\nTableau / Looker]
    F --> G[Human]

    style A fill:#2d2d2d,color:#fff
    style B fill:#1a3a5c,color:#fff
    style C fill:#1a3a5c,color:#fff
    style D fill:#1a3a5c,color:#fff
    style E fill:#1a3a5c,color:#fff
    style F fill:#1a5c3a,color:#fff
    style G fill:#5c1a1a,color:#fff
```

### AI-Enabled System

```mermaid
flowchart TD
    A[Data Source] --> B[Ingest\nKafka]
    B --> C[Enrich + Process\nFlink / Kafka Streams]
    C --> D[Structured Store\nPostgres / Pinot]
    C --> E[Embedding Pipeline\ntext → vectors]
    E --> F[Vector Store\nPinecone / Qdrant]
    D --> G[Retrieval Layer]
    F --> G
    G --> H[LLM Reasoning\nOpenAI / Anthropic]
    H --> I[Agent / Action]
    I --> J[Feedback Loop]
    J --> F

    style A fill:#2d2d2d,color:#fff
    style B fill:#1a3a5c,color:#fff
    style C fill:#1a3a5c,color:#fff
    style D fill:#1a5c3a,color:#fff
    style E fill:#3a1a5c,color:#fff
    style F fill:#3a1a5c,color:#fff
    style G fill:#5c3a1a,color:#fff
    style H fill:#5c1a3a,color:#fff
    style I fill:#1a5c5c,color:#fff
    style J fill:#2d2d2d,color:#fff
```

---

## Key Structural Differences

| Aspect | Traditional | AI-Enabled |
|--------|-------------|------------|
| Flow direction | Linear | Graph (with feedback) |
| Trigger | Time-based | Event-based |
| Storage type | Relational / columnar | Relational + vector |
| End consumer | Human | LLM / Agent |
| State | Stateless | Stateful (context) |
| Latency | Minutes–hours | Milliseconds–seconds |
