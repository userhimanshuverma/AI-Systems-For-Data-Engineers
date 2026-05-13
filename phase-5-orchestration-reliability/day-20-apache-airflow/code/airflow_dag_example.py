"""
Airflow DAG Example — Day 20: Airflow for AI Systems
======================================================
Production-style DAG for an AI retrieval pipeline.

This DAG orchestrates the embedding refresh workflow:
  1. Detect changed documents (query Pinot)
  2. Generate embeddings (call embedding API)
  3. Upsert to vector store (write to Qdrant)
  4. Validate retrieval quality (run test queries)

Features demonstrated:
  - Scheduled execution (every 30 minutes)
  - Task dependencies (linear chain)
  - Retries with exponential backoff
  - SLA monitoring
  - Failure callbacks
  - XCom for passing data between tasks

To use with real Airflow:
  1. Copy this file to $AIRFLOW_HOME/dags/
  2. Airflow will auto-detect it within 30 seconds
  3. Enable the DAG in the UI
  4. Trigger a manual run to test

Note: This file uses standard Airflow imports. It will only run
inside an Airflow environment. For standalone simulation, see
workflow_simulation.py in this directory.
"""

from datetime import datetime, timedelta
import logging

log = logging.getLogger(__name__)

# ── TASK FUNCTIONS ────────────────────────────────────────────────────────────

def detect_changed_documents(**context) -> dict:
    """
    Task 1: Query Pinot for documents changed since last run.
    Returns list of doc_ids that need re-embedding.

    In production: query Pinot for events where
    content_hash != stored_hash OR embedded_at < last_run_ts
    """
    log.info("Querying Pinot for changed documents...")

    # Simulate finding changed documents
    changed_docs = [f"evt_{i:05d}" for i in range(847)]
    log.info(f"Found {len(changed_docs)} changed documents")

    # Push to XCom for downstream tasks
    context["ti"].xcom_push(key="changed_doc_ids", value=changed_docs)
    context["ti"].xcom_push(key="doc_count", value=len(changed_docs))

    return {"changed_count": len(changed_docs)}


def generate_embeddings(**context) -> dict:
    """
    Task 2: Generate embeddings for changed documents.
    Calls embedding API (OpenAI / local model).

    In production:
        from openai import OpenAI
        client = OpenAI()
        texts = [event_to_text(doc) for doc in changed_docs]
        response = client.embeddings.create(input=texts, model="text-embedding-3-small")
        vectors = [r.embedding for r in response.data]
    """
    changed_docs = context["ti"].xcom_pull(key="changed_doc_ids", task_ids="detect_changed_documents")
    log.info(f"Generating embeddings for {len(changed_docs)} documents...")

    # Simulate embedding generation
    embedded_count = len(changed_docs)
    log.info(f"Generated {embedded_count} embeddings")

    context["ti"].xcom_push(key="embedded_count", value=embedded_count)
    return {"embedded_count": embedded_count}


def upsert_to_vector_store(**context) -> dict:
    """
    Task 3: Upsert embeddings to vector store.
    Idempotent: safe to re-run on retry.

    In production:
        from qdrant_client import QdrantClient
        client = QdrantClient("localhost", port=6333)
        client.upsert(collection_name="user_events", points=points)
    """
    embedded_count = context["ti"].xcom_pull(key="embedded_count", task_ids="generate_embeddings")
    log.info(f"Upserting {embedded_count} vectors to Qdrant...")

    # Simulate upsert
    log.info(f"Upserted {embedded_count} vectors successfully")
    context["ti"].xcom_push(key="upserted_count", value=embedded_count)
    return {"upserted_count": embedded_count}


def validate_retrieval_quality(**context) -> dict:
    """
    Task 4: Validate that retrieval quality hasn't degraded.
    Runs a set of test queries and checks expected results are returned.

    In production: compare top-k results against a golden set.
    Alert if precision@4 drops below threshold.
    """
    log.info("Running retrieval quality validation...")

    # Simulate quality check
    test_queries = [
        ("checkout errors", ["evt_00001", "evt_00002", "evt_00003"]),
        ("upgrade intent",  ["evt_00010", "evt_00011"]),
        ("churn risk",      ["evt_00020", "evt_00021", "evt_00022"]),
    ]

    precision_scores = [0.92, 0.88, 0.95]
    avg_precision = sum(precision_scores) / len(precision_scores)

    log.info(f"Average precision@4: {avg_precision:.2f}")

    if avg_precision < 0.80:
        raise ValueError(f"Retrieval quality degraded: precision@4={avg_precision:.2f} < 0.80")

    return {"avg_precision": avg_precision, "queries_tested": len(test_queries)}


def alert_on_failure(context) -> None:
    """Called by Airflow when a task fails after all retries."""
    dag_id  = context["dag"].dag_id
    task_id = context["task_instance"].task_id
    run_id  = context["run_id"]
    error   = str(context.get("exception", "unknown"))

    log.error(f"ALERT: {dag_id}.{task_id} failed in run {run_id}: {error}")
    # In production: POST to PagerDuty or Slack webhook
    # requests.post(PAGERDUTY_URL, json={"summary": f"{dag_id}.{task_id} failed"})


def alert_on_sla_miss(dag, task_list, blocking_task_list, slas, blocking_tis) -> None:
    """Called by Airflow when a task misses its SLA."""
    log.warning(f"SLA MISS: {dag.dag_id} — tasks: {[t.task_id for t in task_list]}")
    # In production: send Slack notification


# ── DAG DEFINITION ────────────────────────────────────────────────────────────

try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator

    default_args = {
        "owner":                  "data-engineering",
        "depends_on_past":        False,
        "retries":                3,
        "retry_delay":            timedelta(minutes=2),
        "retry_exponential_backoff": True,
        "max_retry_delay":        timedelta(minutes=30),
        "on_failure_callback":    alert_on_failure,
        "execution_timeout":      timedelta(minutes=10),
    }

    with DAG(
        dag_id="embedding_refresh_pipeline",
        description="Refresh embeddings for changed documents every 30 minutes",
        schedule_interval="*/30 * * * *",
        start_date=datetime(2026, 1, 1),
        catchup=False,
        default_args=default_args,
        tags=["ai-systems", "embeddings", "retrieval"],
        sla_miss_callback=alert_on_sla_miss,
    ) as dag:

        t1_detect = PythonOperator(
            task_id="detect_changed_documents",
            python_callable=detect_changed_documents,
            sla=timedelta(minutes=5),
        )

        t2_embed = PythonOperator(
            task_id="generate_embeddings",
            python_callable=generate_embeddings,
            sla=timedelta(minutes=15),
        )

        t3_upsert = PythonOperator(
            task_id="upsert_to_vector_store",
            python_callable=upsert_to_vector_store,
            sla=timedelta(minutes=5),
        )

        t4_validate = PythonOperator(
            task_id="validate_retrieval_quality",
            python_callable=validate_retrieval_quality,
            sla=timedelta(minutes=5),
        )

        # Define task dependencies
        t1_detect >> t2_embed >> t3_upsert >> t4_validate

except ImportError:
    # Airflow not installed — this is expected when running standalone
    print("[INFO] Airflow not installed. This DAG file is for reference.")
    print("[INFO] To run standalone simulation, use workflow_monitor.py")


# ── STANDALONE DEMO (no Airflow required) ─────────────────────────────────────

if __name__ == "__main__":
    print("=" * 65)
    print("AIRFLOW DAG EXAMPLE — Standalone task execution demo")
    print("=" * 65)
    print("\nThis file defines the embedding_refresh_pipeline DAG.")
    print("To run with real Airflow: copy to $AIRFLOW_HOME/dags/")
    print("\nRunning task functions standalone:\n")

    class MockTaskInstance:
        def __init__(self):
            self._xcoms = {}
        def xcom_push(self, key, value):
            self._xcoms[key] = value
        def xcom_pull(self, key, task_ids=None):
            return self._xcoms.get(key)

    ctx = {"ti": MockTaskInstance()}

    print("[Task 1] detect_changed_documents")
    result = detect_changed_documents(**ctx)
    print(f"  Result: {result}\n")

    print("[Task 2] generate_embeddings")
    result = generate_embeddings(**ctx)
    print(f"  Result: {result}\n")

    print("[Task 3] upsert_to_vector_store")
    result = upsert_to_vector_store(**ctx)
    print(f"  Result: {result}\n")

    print("[Task 4] validate_retrieval_quality")
    result = validate_retrieval_quality(**ctx)
    print(f"  Result: {result}\n")

    print("All tasks completed successfully.")
    print("In production: Airflow manages scheduling, retries, and alerting.")
