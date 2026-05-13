# Day 20 — Airflow for AI Systems

> **Phase 5 — Orchestration & Reliability**
> An AI system without orchestration is a collection of scripts. Orchestration is what turns scripts into a production system.

---

## Introduction

You've built the pipeline. Kafka ingests events. Flink enriches them. Pinot stores them. Embeddings are generated. The vector store is populated. The LLM retrieves context and reasons over it.

Now ask: what happens when the embedding pipeline fails at 2am? What happens when the vector store goes stale because a refresh job silently stopped? What happens when a Pinot segment compaction job conflicts with a query-heavy period?

Without orchestration, the answer is: you find out when users report wrong answers.

Apache Airflow is the orchestration layer that coordinates all of this — scheduling jobs, managing dependencies, retrying failures, and alerting when things go wrong.

---

## What Orchestration Actually Means

Orchestration is not just scheduling. It's the full lifecycle management of multi-step workflows.

### Scheduling
Run jobs at the right time, in the right order, with the right frequency.
```
nightly_feature_compute:    runs at 00:00 UTC daily
embedding_refresh:          runs every 30 minutes
pinot_segment_compaction:   runs every Sunday at 02:00 UTC
retrieval_quality_check:    runs every hour
```

### Retries
When a task fails, retry it automatically with configurable backoff.
```python
task = PythonOperator(
    task_id="embed_new_documents",
    retries=3,
    retry_delay=timedelta(minutes=5),
    retry_exponential_backoff=True,
)
```

### Dependency Management
Tasks run in the correct order. Downstream tasks wait for upstream tasks to succeed.
```
validate_data → compute_features → generate_embeddings → upsert_to_vector_db → validate_index
```
If `compute_features` fails, `generate_embeddings` never starts. The failure is contained.

### Workflow Coordination
Multiple pipelines that share data must be coordinated. Airflow sensors wait for external conditions before proceeding.
```python
# Wait for Pinot to have fresh data before running embedding refresh
wait_for_pinot = ExternalTaskSensor(
    task_id="wait_for_pinot_ingestion",
    external_dag_id="pinot_ingestion_pipeline",
    external_task_id="verify_segment_freshness",
    timeout=3600,
)
```

### Observability
Every task execution is logged. Success, failure, duration, and retry count are visible in the Airflow UI. SLA misses trigger alerts.
```python
task = PythonOperator(
    task_id="embedding_refresh",
    sla=timedelta(minutes=15),  # alert if task takes > 15 minutes
    on_failure_callback=send_pagerduty_alert,
)
```

---

## Why AI Systems Need Orchestration

AI systems have more failure points than traditional data pipelines. Each additional component — embedding model, vector store, LLM API — is a potential failure point that needs to be managed.

### Embedding Refresh Workflows
Embeddings must be kept fresh. New events arrive continuously. Changed events need re-embedding. Model upgrades require full re-indexing.

Without orchestration: embedding refresh runs as a cron script. It fails silently. The vector store serves stale data. The LLM answers with outdated context. No one knows.

With orchestration: Airflow runs the refresh job, retries on failure, alerts if it hasn't completed within the SLA, and blocks downstream jobs from running on stale data.

### Retraining Pipelines
ML models drift. Churn prediction models trained 6 months ago may no longer reflect current user behavior. Retraining pipelines must run on schedule, validate the new model before deploying it, and roll back if quality degrades.

### Vector Sync Jobs
The vector store must stay in sync with the source data. When documents are updated or deleted, the corresponding vectors must be updated or removed. This is a multi-step workflow: detect changes → re-embed → upsert → validate.

### Retrieval Validation
After every embedding refresh, validate that retrieval quality hasn't degraded. Run a set of test queries and check that the expected documents are returned. If quality drops, alert and block the deployment.

### Recovery Workflows
When a component fails (Pinot broker restart, vector store index corruption), recovery workflows must run in the correct order: restore data → rebuild index → validate → resume serving.

---

## Role of Apache Airflow

Airflow is a platform for programmatically authoring, scheduling, and monitoring workflows.

### DAG Orchestration
A DAG (Directed Acyclic Graph) defines a workflow as a set of tasks with dependencies.

```python
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

with DAG(
    dag_id="embedding_refresh_pipeline",
    schedule_interval="*/30 * * * *",  # every 30 minutes
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={
        "retries": 3,
        "retry_delay": timedelta(minutes=5),
        "on_failure_callback": alert_on_failure,
    },
) as dag:

    detect_changes = PythonOperator(
        task_id="detect_changed_documents",
        python_callable=detect_changed_documents,
    )

    generate_embeddings = PythonOperator(
        task_id="generate_embeddings",
        python_callable=generate_embeddings_for_changed,
    )

    upsert_vectors = PythonOperator(
        task_id="upsert_to_vector_store",
        python_callable=upsert_vectors_to_qdrant,
    )

    validate_index = PythonOperator(
        task_id="validate_retrieval_quality",
        python_callable=run_retrieval_quality_checks,
    )

    # Define dependencies
    detect_changes >> generate_embeddings >> upsert_vectors >> validate_index
```

### Retries
Airflow retries failed tasks automatically. Each retry is logged with the error message and duration.

```python
# Task-level retry configuration
task = PythonOperator(
    task_id="call_embedding_api",
    retries=3,
    retry_delay=timedelta(minutes=2),
    retry_exponential_backoff=True,  # 2min, 4min, 8min
    max_retry_delay=timedelta(minutes=30),
)
```

### Task Dependencies
Airflow enforces task ordering. A task only runs when all its upstream dependencies have succeeded.

```
validate_data
    │
    ▼
compute_features ──────────────────────────────────┐
    │                                               │
    ▼                                               ▼
generate_embeddings                        update_pinot_features
    │                                               │
    ▼                                               │
upsert_to_vector_db ◄──────────────────────────────┘
    │
    ▼
validate_index
```

### Monitoring
The Airflow UI shows:
- DAG run history (success, failure, running)
- Task duration trends
- Retry counts
- SLA misses
- Log output for every task execution

---

## Real-World Example — AI Retrieval Pipeline

**System:** SaaS platform with Kafka → Flink → Pinot → Embedding Pipeline → Vector DB → LLM

### Orchestration Points

```
DAILY BATCH (00:00 UTC)
  DAG: nightly_feature_compute
  ├── Task 1: compute_user_cohorts (Spark job)
  ├── Task 2: update_pinot_offline_segments
  ├── Task 3: compute_churn_features
  └── Task 4: validate_feature_freshness

EVERY 30 MINUTES
  DAG: embedding_refresh
  ├── Task 1: detect_changed_documents (query Pinot for new/updated events)
  ├── Task 2: generate_embeddings (call embedding API for changed docs)
  ├── Task 3: upsert_to_vector_store (write to Qdrant)
  └── Task 4: validate_retrieval_quality (run test queries)

EVERY HOUR
  DAG: retrieval_quality_monitor
  ├── Task 1: run_test_queries (known queries with expected results)
  ├── Task 2: compute_retrieval_metrics (precision@k, recall@k)
  └── Task 3: alert_if_degraded (PagerDuty if metrics drop > 10%)

WEEKLY (Sunday 02:00 UTC)
  DAG: pinot_maintenance
  ├── Task 1: compact_offline_segments
  ├── Task 2: rebuild_inverted_indexes
  └── Task 3: validate_query_performance
```

### Failure Scenario: Embedding Refresh Fails

```
embedding_refresh DAG run at 14:30:
  ✅ detect_changed_documents (847 new events found)
  ❌ generate_embeddings (OpenAI API timeout after 30s)
      → Retry 1 (14:35): ❌ still timing out
      → Retry 2 (14:45): ✅ succeeded
  ✅ upsert_to_vector_store
  ✅ validate_retrieval_quality

Total delay: 15 minutes (within SLA of 30 minutes)
Alert: none (completed within SLA)
```

Without Airflow: the cron job fails silently. No retry. No alert. Vector store is 15+ minutes stale.

---

## Failure Scenarios

### Embedding Refresh Failure
**Cause:** Embedding API timeout, rate limit, or model unavailable.
**Impact:** Vector store serves stale embeddings. LLM retrieves outdated context.
**Airflow response:** Retry 3 times with exponential backoff. Alert if all retries fail. Block downstream validation task.

### API Timeouts
**Cause:** External API (OpenAI, Pinot broker) slow or unavailable.
**Impact:** Task hangs or fails. Downstream tasks blocked.
**Airflow response:** Task-level timeout (`execution_timeout`). Retry with backoff. Alert on repeated failures.

### Stale Retrieval Index
**Cause:** Embedding refresh job hasn't run in > 1 hour (SLA miss).
**Impact:** LLM retrieves outdated context. Wrong answers.
**Airflow response:** SLA miss alert fires. On-call engineer investigates. Recovery DAG triggered.

### Workflow Dependency Failure
**Cause:** Upstream DAG (nightly_feature_compute) failed. Downstream DAG (embedding_refresh) starts on stale features.
**Impact:** Embeddings generated from stale features. Retrieval quality degrades.
**Airflow response:** ExternalTaskSensor blocks downstream DAG until upstream succeeds. Alert if upstream hasn't succeeded within timeout.

---

## Reliability Patterns

### Retries with Exponential Backoff
```python
default_args = {
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=30),
}
```

### Idempotency
Every task must be safe to re-run. If a task is retried, it should not create duplicate data.
```python
def upsert_vectors(doc_ids: list[str]) -> None:
    # Upsert = insert if new, update if exists
    # Running this twice with the same doc_ids produces the same result
    vector_store.upsert(doc_ids)  # idempotent by design
```

### Monitoring and Alerting
```python
def alert_on_failure(context):
    """Called by Airflow when a task fails after all retries."""
    dag_id  = context["dag"].dag_id
    task_id = context["task_instance"].task_id
    error   = context["exception"]
    # In production: POST to PagerDuty or Slack
    print(f"ALERT: {dag_id}.{task_id} failed: {error}")

default_args = {
    "on_failure_callback": alert_on_failure,
    "sla": timedelta(minutes=30),
    "on_sla_miss_callback": alert_on_sla_miss,
}
```

### Dead Letter Handling
Failed tasks that cannot be retried should write to a dead-letter queue for manual investigation.
```python
def handle_failed_embeddings(failed_doc_ids: list[str]) -> None:
    """Write failed doc IDs to dead-letter table for manual review."""
    for doc_id in failed_doc_ids:
        dead_letter_store.write(doc_id, reason="embedding_failed", ts=datetime.now())
```

---

## Common Mistakes

### 1. Manual Orchestration
```
❌ Run embedding refresh as a cron script with no monitoring
✅ Define as an Airflow DAG with retries, SLA, and alerting
```

### 2. No Retry Logic
```
❌ Task fails → workflow stops → stale data serves until someone notices
✅ Task fails → retry 3x with backoff → alert if all retries fail
```

### 3. Hidden Workflow Dependencies
```
❌ embedding_refresh runs without checking if nightly_feature_compute succeeded
✅ Use ExternalTaskSensor to wait for upstream DAGs before proceeding
```

### 4. Non-Idempotent Tasks
```
❌ Task inserts new rows on every run → duplicates on retry
✅ Use upsert semantics → safe to re-run any number of times
```

### 5. No SLA Monitoring
```
❌ Embedding refresh takes 2 hours but no one knows
✅ Set SLA on every task. Alert when SLA is missed.
   Stale embeddings = wrong LLM answers. You need to know immediately.
```

---

## Key Takeaways

1. **Orchestration is not optional in production AI systems.** Silent failures in embedding pipelines produce wrong LLM answers. You need retries, alerting, and dependency management.

2. **Airflow DAGs make dependencies explicit.** Every task knows what it depends on. Failures are contained. Downstream tasks don't run on bad data.

3. **Retries with exponential backoff handle transient failures.** API timeouts, rate limits, and brief outages are handled automatically without human intervention.

4. **Idempotency is required for reliable retries.** Every task must be safe to re-run. Use upsert semantics, not insert.

5. **SLA monitoring catches silent degradation.** An embedding refresh that takes 3 hours instead of 30 minutes is a problem — even if it eventually succeeds.

6. **The embedding refresh pipeline is the most critical orchestration target.** Stale embeddings are the most common cause of wrong LLM answers in production RAG systems.

---

## What's Next

**Day 21** — Async Architectures: designing systems where components communicate asynchronously via queues and events.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
