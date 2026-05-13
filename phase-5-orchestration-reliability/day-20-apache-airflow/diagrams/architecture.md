# Architecture Diagrams — Day 20: Airflow for AI Systems

---

## ASCII Diagram — Airflow Coordinating AI Workflows

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  APACHE AIRFLOW — Orchestration Control Plane                                ║
║                                                                              ║
║  Scheduler: reads DAG definitions, triggers tasks on schedule               ║
║  Executor:  runs tasks (LocalExecutor / CeleryExecutor / KubernetesExecutor)║
║  Webserver: UI for monitoring, triggering, and debugging                    ║
║  Metadata DB: stores DAG run history, task states, logs                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
         │                    │                    │                    │
         ▼                    ▼                    ▼                    ▼
╔══════════════╗  ╔══════════════════╗  ╔═══════════════╗  ╔══════════════════╗
║ DAG:         ║  ║ DAG:             ║  ║ DAG:          ║  ║ DAG:             ║
║ nightly_     ║  ║ embedding_       ║  ║ retrieval_    ║  ║ pinot_           ║
║ feature_     ║  ║ refresh          ║  ║ quality_      ║  ║ maintenance      ║
║ compute      ║  ║ (every 30min)    ║  ║ monitor       ║  ║ (weekly)         ║
║ (daily)      ║  ║                  ║  ║ (hourly)      ║  ║                  ║
║              ║  ║ ┌─────────────┐  ║  ║               ║  ║                  ║
║ ┌──────────┐ ║  ║ │detect_      │  ║  ║ ┌───────────┐ ║  ║ ┌──────────────┐║
║ │compute_  │ ║  ║ │changed_docs │  ║  ║ │run_test_  │ ║  ║ │compact_      ║║
║ │cohorts   │ ║  ║ └──────┬──────┘  ║  ║ │queries    │ ║  ║ │segments      ║║
║ └────┬─────┘ ║  ║        │         ║  ║ └─────┬─────┘ ║  ║ └──────┬───────┘║
║      │       ║  ║        ▼         ║  ║       │       ║  ║        │        ║
║ ┌────▼─────┐ ║  ║ ┌─────────────┐  ║  ║ ┌─────▼─────┐ ║  ║ ┌──────▼───────┐║
║ │update_   │ ║  ║ │generate_    │  ║  ║ │compute_   │ ║  ║ │rebuild_      ║║
║ │pinot_    │ ║  ║ │embeddings   │  ║  ║ │metrics    │ ║  ║ │indexes       ║║
║ │segments  │ ║  ║ │(retries=3)  │  ║  ║ └─────┬─────┘ ║  ║ └──────┬───────┘║
║ └────┬─────┘ ║  ║ └──────┬──────┘  ║  ║       │       ║  ║        │        ║
║      │       ║  ║        │         ║  ║ ┌─────▼─────┐ ║  ║ ┌──────▼───────┐║
║ ┌────▼─────┐ ║  ║        ▼         ║  ║ │alert_if_  │ ║  ║ │validate_     ║║
║ │validate_ │ ║  ║ ┌─────────────┐  ║  ║ │degraded   │ ║  ║ │performance   ║║
║ │freshness │ ║  ║ │upsert_to_   │  ║  ║ └───────────┘ ║  ║ └──────────────┘║
║ └──────────┘ ║  ║ │vector_store │  ║  ╚═══════════════╝  ╚══════════════════╝
╚══════════════╝  ║ └──────┬──────┘  ║
                  ║        │         ║
                  ║        ▼         ║
                  ║ ┌─────────────┐  ║
                  ║ │validate_    │  ║
                  ║ │retrieval_   │  ║
                  ║ │quality      │  ║
                  ║ └─────────────┘  ║
                  ╚══════════════════╝
         │                    │
         ▼                    ▼
╔══════════════╗  ╔══════════════════╗
║ Apache Pinot ║  ║ Vector Store     ║
║ (data store) ║  ║ (Qdrant/Pinecone)║
╚══════════════╝  ╚══════════════════╝
```

---

## ASCII Diagram — Task Retry Flow

```
TASK: generate_embeddings
─────────────────────────────────────────────────────────────────────────────

Attempt 1 (14:30:00):
  → Call OpenAI embedding API
  ← TimeoutError after 30s
  Status: FAILED
  Next retry in: 2 minutes (exponential backoff)

Attempt 2 (14:32:00):
  → Call OpenAI embedding API
  ← TimeoutError after 30s
  Status: FAILED
  Next retry in: 4 minutes

Attempt 3 (14:36:00):
  → Call OpenAI embedding API
  ← Success (847 embeddings generated)
  Status: SUCCESS
  Duration: 12.3s

Downstream task upsert_to_vector_store: STARTS (was waiting)

Total delay: 6 minutes
SLA: 30 minutes
Alert: NONE (completed within SLA)

─────────────────────────────────────────────────────────────────────────────

If all 3 retries fail:
  Status: FAILED (no more retries)
  on_failure_callback: fires → PagerDuty alert
  Downstream tasks: BLOCKED (will not run on stale data)
  Dead letter: failed doc IDs written to dead_letter table
```

---

## Mermaid Diagram — Embedding Refresh DAG

```mermaid
flowchart TD
    subgraph DAG["DAG: embedding_refresh — every 30 minutes"]
        T1[detect_changed_documents\nQuery Pinot for new/updated events]
        T2[generate_embeddings\nCall embedding API\nretries=3, backoff=exponential]
        T3[upsert_to_vector_store\nWrite to Qdrant\nidempotent upsert]
        T4[validate_retrieval_quality\nRun test queries\ncheck precision@4]
        T5[alert_on_degradation\nPagerDuty if quality drops]
    end

    subgraph Sensors["Sensors"]
        S1[ExternalTaskSensor\nwait for nightly_feature_compute]
    end

    subgraph Infra["Infrastructure"]
        P[Apache Pinot]
        V[Vector Store\nQdrant]
        E[Embedding API\nOpenAI / local]
    end

    S1 --> T1
    T1 --> T2
    T2 --> T3
    T3 --> T4
    T4 --> T5

    T1 -.reads.-> P
    T2 -.calls.-> E
    T3 -.writes.-> V
    T4 -.queries.-> V

    style DAG fill:#0d1e30,color:#7eb8f7
    style Sensors fill:#1a1a0d,color:#f7f77e
    style Infra fill:#0d2a1a,color:#7ef7a0
```

---

## Mermaid Diagram — Failure and Recovery Flow

```mermaid
sequenceDiagram
    participant AF as Airflow Scheduler
    participant T as Task: generate_embeddings
    participant API as Embedding API
    participant VS as Vector Store
    participant PD as PagerDuty

    AF->>T: trigger (14:30)
    T->>API: embed 847 documents
    API-->>T: TimeoutError (30s)
    T-->>AF: FAILED (attempt 1/3)

    Note over AF: wait 2 minutes (backoff)
    AF->>T: retry (14:32)
    T->>API: embed 847 documents
    API-->>T: TimeoutError (30s)
    T-->>AF: FAILED (attempt 2/3)

    Note over AF: wait 4 minutes (backoff)
    AF->>T: retry (14:36)
    T->>API: embed 847 documents
    API-->>T: 847 vectors returned
    T-->>AF: SUCCESS

    AF->>VS: trigger upsert_to_vector_store
    VS-->>AF: SUCCESS

    Note over AF: SLA = 30min, elapsed = 6min → no alert
```
