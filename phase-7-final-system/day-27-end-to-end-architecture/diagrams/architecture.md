# Day 27 — Architecture Diagrams

## 1. ASCII Diagram — Complete End-to-End AI System

```
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                        END-TO-END AI SYSTEM ARCHITECTURE                            ║
╠══════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                      ║
║   ┌─────────────────────────── DATA PATH (Background) ──────────────────────────┐    ║
║   │                                                                              │    ║
║   │  ┌──────────────┐    ┌──────────────────┐    ┌────────────────────────────┐  │    ║
║   │  │   Event       │    │  Stream           │    │  Downstream Sinks          │  │    ║
║   │  │   Sources     │    │  Processor        │    │                            │  │    ║
║   │  │              │    │                    │    │  ┌──────────────────────┐  │  │    ║
║   │  │  Web App ──┐ │    │  ┌──────────────┐ │    │  │   Apache Pinot       │  │  │    ║
║   │  │  Mobile ──┤ │──▶│  │ Validate     │ │──▶│  │   (Real-time OLAP)   │  │  │    ║
║   │  │  API    ──┤ │    │  │ Enrich       │ │    │  └──────────────────────┘  │  │    ║
║   │  │  IoT    ──┘ │    │  │ Transform    │ │    │  ┌──────────────────────┐  │  │    ║
║   │  │              │    │  │ Window       │ │──▶│  │   Vector DB          │  │  │    ║
║   │  │  ┌────────┐ │    │  │ Route        │ │    │  │   (Embeddings)       │  │  │    ║
║   │  │  │ Kafka  │ │    │  └──────────────┘ │    │  └──────────────────────┘  │  │    ║
║   │  │  │ Topics │ │    │                    │    │  ┌──────────────────────┐  │  │    ║
║   │  │  │ (12    │ │    │  State: RocksDB   │──▶│  │   Feature Store      │  │  │    ║
║   │  │  │  part) │ │    │  Watermarks       │    │  │   (Redis)            │  │  │    ║
║   │  │  └────────┘ │    │  Exactly-once     │    │  └──────────────────────┘  │  │    ║
║   │  └──────────────┘    └──────────────────┘    └────────────────────────────┘  │    ║
║   └──────────────────────────────────────────────────────────────────────────────┘    ║
║                                                                                      ║
║   ┌─────────────────────────── QUERY PATH (Real-time) ──────────────────────────┐    ║
║   │                                                                              │    ║
║   │  ┌──────────┐   ┌───────────────┐   ┌──────────────┐   ┌────────────────┐   │    ║
║   │  │  User    │   │  Query         │   │  Retrieval   │   │  Agent          │   │    ║
║   │  │  Query   │──▶│  Understanding │──▶│  Engine      │──▶│  Orchestrator   │   │    ║
║   │  │          │   │               │   │              │   │                │   │    ║
║   │  │  NL text │   │  Intent ──────│   │  Structured ─│   │  Plan tools ──│   │    ║
║   │  │          │   │  Entities ────│   │  Semantic ───│   │  Execute ─────│   │    ║
║   │  │          │   │  Routing ─────│   │  RRF Fusion ─│   │  Retry ───────│   │    ║
║   │  │          │   │  Confidence ──│   │  Caching ────│   │  Fallback ────│   │    ║
║   │  └──────────┘   └───────────────┘   └──────────────┘   └───────┬────────┘   │    ║
║   │                                                                 │            │    ║
║   │                                                                 ▼            │    ║
║   │                                     ┌──────────────┐   ┌────────────────┐   │    ║
║   │                                     │  User        │   │  LLM           │   │    ║
║   │                                     │  Response    │◀──│  Reasoning     │   │    ║
║   │                                     │              │   │                │   │    ║
║   │                                     │  Formatted   │   │  Model Route ─│   │    ║
║   │                                     │  Actionable  │   │  Prompt Build ─│   │    ║
║   │                                     │  Grounded    │   │  Generate ────│   │    ║
║   │                                     │              │   │  Validate ────│   │    ║
║   │                                     └──────────────┘   └────────────────┘   │    ║
║   └──────────────────────────────────────────────────────────────────────────────┘    ║
║                                                                                      ║
║   ┌─────────────────────────── OBSERVABILITY PLANE ─────────────────────────────┐    ║
║   │                                                                              │    ║
║   │  ┌────────────┐  ┌────────────┐  ┌──────────────┐  ┌────────────────────┐   │    ║
║   │  │ Distributed│  │ Metrics    │  │ Circuit      │  │ Cost              │   │    ║
║   │  │ Tracing    │  │ Dashboard  │  │ Breakers     │  │ Tracking          │   │    ║
║   │  │            │  │            │  │              │  │                    │   │    ║
║   │  │ Trace ID   │  │ P50/P95/P99│  │ Per-tool     │  │ Token counts     │   │    ║
║   │  │ Spans      │  │ Throughput │  │ Failure rate │  │ Model costs      │   │    ║
║   │  │ Latency    │  │ Error rate │  │ Recovery     │  │ Budget alerts    │   │    ║
║   │  └────────────┘  └────────────┘  └──────────────┘  └────────────────────┘   │    ║
║   └──────────────────────────────────────────────────────────────────────────────┘    ║
║                                                                                      ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
```

---

## 2. Mermaid Diagram — Distributed AI Architecture Flow

```mermaid
flowchart TB
    subgraph DataPath["📥 DATA PATH — Background Ingestion"]
        direction LR
        
        Sources["🌐 Event Sources<br/>Web · Mobile · API · IoT"]
        Kafka["📨 Apache Kafka<br/>12 Partitions<br/>At-least-once delivery"]
        Flink["⚡ Stream Processor<br/>Flink / Kafka Streams<br/>Validate · Enrich · Window"]
        
        Sources --> Kafka --> Flink
        
        Flink --> Pinot["📊 Apache Pinot<br/>Real-time OLAP<br/>Star-tree Index"]
        Flink --> VectorDB["🧠 Vector DB<br/>Behavioral Embeddings<br/>HNSW Index"]
        Flink --> FeatureStore["⚡ Feature Store<br/>Real-time Features<br/>Redis"]
        Flink --> DLQ["☠️ Dead Letter Queue<br/>Failed Events"]
    end

    subgraph QueryPath["🔍 QUERY PATH — Real-time Intelligence"]
        direction TB
        
        UserQuery["👤 User Query<br/>'Which users are at risk?'"]
        QU["🎯 Query Understanding<br/>Intent Detection<br/>Entity Extraction<br/>Route Planning"]
        
        subgraph Retrieval["🔎 Retrieval Engine"]
            direction LR
            StructuredR["📊 Structured Retrieval<br/>Pinot SQL Queries<br/>Metrics & Aggregations"]
            SemanticR["🧠 Semantic Retrieval<br/>Vector Similarity<br/>Behavioral Patterns"]
            RRF["🔀 Reciprocal Rank Fusion<br/>Score Merging"]
            StructuredR --> RRF
            SemanticR --> RRF
        end
        
        subgraph Agent["🤖 Agent Orchestrator"]
            direction TB
            Planner["📋 Tool Planner<br/>Decide what to call"]
            Executor["⚙️ Tool Executor<br/>Circuit Breakers<br/>Retry + Backoff"]
            Assembler["📦 Context Assembler<br/>Merge all results"]
            Planner --> Executor --> Assembler
        end
        
        LLM["🧠 LLM Reasoning<br/>Model Routing<br/>Prompt Construction<br/>Response Generation"]
        Response["📤 User Response<br/>Formatted · Actionable · Grounded"]
        
        UserQuery --> QU --> Retrieval --> Agent --> LLM --> Response
    end

    Pinot -.->|"SQL Queries"| StructuredR
    VectorDB -.->|"ANN Search"| SemanticR
    FeatureStore -.->|"Feature Lookup"| Executor

    subgraph Observability["📡 OBSERVABILITY PLANE"]
        direction LR
        Traces["🔍 Distributed Traces"]
        Metrics["📈 Metrics & SLOs"]
        Alerts["🚨 Alerts & Incidents"]
        Costs["💰 Cost Tracking"]
    end

    QueryPath -.-> Observability
    DataPath -.-> Observability

    style DataPath fill:#1a1a2e,stroke:#e94560,color:#eee
    style QueryPath fill:#16213e,stroke:#0f3460,color:#eee
    style Observability fill:#0f3460,stroke:#533483,color:#eee
    style Retrieval fill:#1a1a3e,stroke:#e94560,color:#eee
    style Agent fill:#1a1a3e,stroke:#0f3460,color:#eee
```

---

## 3. Layered Architecture Diagram

```mermaid
block-beta
    columns 1
    
    block:Presentation["🖥️ PRESENTATION LAYER"]
        columns 3
        WebUI["Web Dashboard"]
        API_GW["API Gateway"]
        Slack["Slack / Teams Bot"]
    end
    
    block:Intelligence["🧠 INTELLIGENCE LAYER"]
        columns 3
        LLM_Layer["LLM Reasoning<br/>GPT-4o / Claude<br/>Model Routing<br/>Prompt Templates"]
        Agent_Layer["Agent Orchestration<br/>Tool Coordination<br/>Circuit Breakers<br/>Retry Logic"]
        Query_Layer["Query Understanding<br/>Intent Detection<br/>Entity Extraction<br/>Query Routing"]
    end
    
    block:Retrieval_Layer["🔎 RETRIEVAL LAYER"]
        columns 3
        Structured["Structured Retrieval<br/>Apache Pinot SQL<br/>Pre-aggregated<br/>Sub-100ms P99"]
        Semantic["Semantic Retrieval<br/>Vector Similarity<br/>HNSW ANN<br/>Cosine Distance"]
        Fusion["Rank Fusion<br/>RRF Algorithm<br/>Score Merging<br/>Result Ranking"]
    end
    
    block:Processing["⚡ PROCESSING LAYER"]
        columns 3
        StreamProc["Stream Processing<br/>Apache Flink<br/>Enrichment<br/>Windowing"]
        Features["Feature Engineering<br/>Real-time Features<br/>Aggregations<br/>Feature Store"]
        Embedding["Embedding Pipeline<br/>Behavior Encoding<br/>Model Inference<br/>Index Updates"]
    end
    
    block:Storage["💾 STORAGE LAYER"]
        columns 4
        Pinot_Store["Apache Pinot<br/>Real-time OLAP"]
        Vector_Store["Vector DB<br/>Qdrant / Pinecone"]
        Feature_Store["Feature Store<br/>Redis / Feast"]
        ObjectStore["Object Store<br/>S3 / GCS"]
    end
    
    block:Ingestion["📥 INGESTION LAYER"]
        columns 3
        Kafka_Ingest["Apache Kafka<br/>Event Streaming<br/>12+ Partitions<br/>Schema Registry"]
        CDC["Change Data Capture<br/>Debezium<br/>Database Events"]
        Batch["Batch Ingestion<br/>Airflow / Spark<br/>Historical Data"]
    end

    Presentation --> Intelligence
    Intelligence --> Retrieval_Layer
    Retrieval_Layer --> Storage
    Processing --> Storage
    Ingestion --> Processing

    style Presentation fill:#6c5ce7,stroke:#a29bfe,color:#fff
    style Intelligence fill:#e17055,stroke:#fab1a0,color:#fff
    style Retrieval_Layer fill:#00b894,stroke:#55efc4,color:#fff
    style Processing fill:#0984e3,stroke:#74b9ff,color:#fff
    style Storage fill:#636e72,stroke:#b2bec3,color:#fff
    style Ingestion fill:#fdcb6e,stroke:#ffeaa7,color:#333
```

---

## 4. Data Flow Sequence

```mermaid
sequenceDiagram
    participant U as 👤 User
    participant QU as 🎯 Query Understanding
    participant RE as 🔎 Retrieval Engine
    participant P as 📊 Apache Pinot
    participant V as 🧠 Vector DB
    participant AO as 🤖 Agent Orchestrator
    participant FS as ⚡ Feature Store
    participant LLM as 🧠 LLM
    participant OBS as 📡 Observability

    U->>QU: "Which users are at risk of churning?"
    activate QU
    QU->>QU: Detect Intent: churn_analysis
    QU->>QU: Extract Entities
    QU->>RE: Route to retrieval (intent + entities)
    deactivate QU

    activate RE
    par Structured Retrieval
        RE->>P: SQL: SELECT users WHERE churn_risk > 0.7
        P-->>RE: Top 10 at-risk users + metrics
    and Semantic Retrieval
        RE->>V: ANN search: churn behavior embedding
        V-->>RE: Similar behavioral patterns (top 5)
    end
    RE->>RE: Reciprocal Rank Fusion
    RE->>AO: Fused retrieval results
    deactivate RE

    activate AO
    AO->>AO: Plan: retrieval ✓, feature lookup needed
    AO->>FS: Lookup features for top users
    FS-->>AO: Real-time features (health scores, activity)
    AO->>AO: Assemble context (~2K tokens)
    AO->>LLM: Context + Query + Prompt Template
    deactivate AO

    activate LLM
    LLM->>LLM: Route to Premium model (complex analysis)
    LLM->>LLM: Generate reasoned response
    LLM-->>U: Formatted churn analysis + recommendations
    deactivate LLM

    Note over OBS: Trace captured: 4 spans, 380ms total
    OBS->>OBS: Log: latency, tokens, cost, model
```
