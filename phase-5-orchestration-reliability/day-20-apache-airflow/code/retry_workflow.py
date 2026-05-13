"""
Retry Workflow — Day 20: Airflow for AI Systems
=================================================
Demonstrates retry patterns for AI workflow tasks.

Covers:
  - Exponential backoff retry
  - Max retry limits
  - Dead letter handling for permanently failed tasks
  - Idempotency verification
  - Partial failure recovery (resume from last successful task)

These patterns are what Airflow implements automatically.
This file shows the underlying logic explicitly.
"""

import time
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Any


# ── RETRY RESULT ──────────────────────────────────────────────────────────────

@dataclass
class RetryResult:
    success:    bool
    attempts:   int
    total_ms:   float
    output:     Any = None
    error:      str | None = None
    dead_letter:bool = False


# ── RETRY EXECUTOR ────────────────────────────────────────────────────────────

def execute_with_retry(
    fn: Callable,
    args: tuple = (),
    kwargs: dict = None,
    max_retries: int = 3,
    base_delay_s: float = 2.0,
    exponential: bool = True,
    timeout_s: float = 30.0,
    task_name: str = "task",
) -> RetryResult:
    """
    Executes a function with retry and exponential backoff.
    This is what Airflow does internally for each task.
    """
    kwargs    = kwargs or {}
    t0        = time.perf_counter()
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            result = fn(*args, **kwargs)
            total_ms = round((time.perf_counter() - t0) * 1000, 1)
            if attempt > 0:
                print(f"  [{task_name}] Succeeded on attempt {attempt + 1}")
            return RetryResult(success=True, attempts=attempt + 1,
                               total_ms=total_ms, output=result)

        except Exception as e:
            last_error = str(e)
            total_ms   = round((time.perf_counter() - t0) * 1000, 1)

            if attempt == max_retries:
                print(f"  [{task_name}] FAILED after {max_retries + 1} attempts: {last_error}")
                return RetryResult(success=False, attempts=attempt + 1,
                                   total_ms=total_ms, error=last_error, dead_letter=True)

            delay = base_delay_s * (2 ** attempt) if exponential else base_delay_s
            print(f"  [{task_name}] Attempt {attempt + 1} failed: {last_error}. "
                  f"Retrying in {delay:.1f}s...")
            time.sleep(delay * 0.1)  # scaled down for demo (real: full delay)

    return RetryResult(success=False, attempts=max_retries + 1,
                       total_ms=round((time.perf_counter() - t0) * 1000, 1),
                       error="max_retries_exceeded", dead_letter=True)


# ── DEAD LETTER STORE ─────────────────────────────────────────────────────────

class DeadLetterStore:
    """
    Stores permanently failed task inputs for manual review.
    In production: write to a database table or S3 bucket.
    """
    def __init__(self):
        self._items: list[dict] = []

    def write(self, task_name: str, input_data: Any, error: str) -> None:
        self._items.append({
            "task":       task_name,
            "input":      str(input_data)[:50],
            "error":      error,
            "failed_at":  datetime.now(timezone.utc).isoformat(),
        })

    def count(self) -> int:
        return len(self._items)

    def print_summary(self) -> None:
        if not self._items:
            print("  Dead letter store: empty")
            return
        print(f"  Dead letter store: {len(self._items)} items")
        for item in self._items:
            print(f"    [{item['task']}] {item['error'][:50]} at {item['failed_at'][:19]}")


# ── SIMULATED TASKS ───────────────────────────────────────────────────────────

def flaky_embedding_api(doc_ids: list[str], failure_rate: float = 0.5) -> dict:
    """Simulates an embedding API that fails intermittently."""
    time.sleep(0.050)
    if random.random() < failure_rate:
        raise TimeoutError(f"Embedding API timeout (rate_limit or network)")
    return {"embedded": len(doc_ids), "model": "text-embedding-3-small"}


def flaky_vector_upsert(vectors: list, failure_rate: float = 0.2) -> dict:
    """Simulates a vector store upsert that occasionally fails."""
    time.sleep(0.020)
    if random.random() < failure_rate:
        raise ConnectionError("Vector store connection refused")
    return {"upserted": len(vectors)}


def idempotent_task(doc_id: str, state: dict) -> str:
    """
    Demonstrates idempotency: running twice produces the same result.
    Uses a state dict to track what's been processed.
    """
    if doc_id in state:
        return f"already_processed:{doc_id}"  # safe to re-run
    state[doc_id] = True
    return f"processed:{doc_id}"


# ── PARTIAL FAILURE RECOVERY ──────────────────────────────────────────────────

def run_with_checkpoint(
    items: list[str],
    process_fn: Callable,
    checkpoint: set,
    dead_letter: DeadLetterStore,
    task_name: str,
) -> dict:
    """
    Processes items with checkpointing.
    On retry, skips already-processed items.
    Failed items go to dead letter store.
    """
    processed = 0
    skipped   = 0
    failed    = 0

    for item in items:
        if item in checkpoint:
            skipped += 1
            continue

        result = execute_with_retry(
            process_fn, args=(item,),
            max_retries=2, base_delay_s=0.5,
            task_name=task_name,
        )

        if result.success:
            checkpoint.add(item)
            processed += 1
        else:
            dead_letter.write(task_name, item, result.error or "unknown")
            failed += 1

    return {"processed": processed, "skipped": skipped, "failed": failed}


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("RETRY WORKFLOW — Airflow retry patterns")
    print("=" * 65)

    random.seed(42)
    dead_letter = DeadLetterStore()

    # Demo 1: Exponential backoff retry
    print(f"\n[DEMO 1]  Exponential backoff retry (flaky embedding API)")
    doc_ids = [f"evt_{i:05d}" for i in range(10)]
    result = execute_with_retry(
        flaky_embedding_api,
        args=(doc_ids,),
        kwargs={"failure_rate": 0.6},
        max_retries=3,
        base_delay_s=0.5,
        task_name="generate_embeddings",
    )
    print(f"  Success: {result.success} | Attempts: {result.attempts} | "
          f"Time: {result.total_ms:.0f}ms")
    if result.dead_letter:
        dead_letter.write("generate_embeddings", doc_ids, result.error or "")

    # Demo 2: Idempotency
    print(f"\n[DEMO 2]  Idempotency (safe to re-run)")
    state = {}
    for run_num in range(1, 3):
        results = [idempotent_task(f"doc_{i}", state) for i in range(5)]
        already = sum(1 for r in results if "already_processed" in r)
        new_proc = sum(1 for r in results if "processed:" in r and "already" not in r)
        print(f"  Run {run_num}: {new_proc} processed, {already} already done (idempotent)")

    # Demo 3: Partial failure with checkpoint
    print(f"\n[DEMO 3]  Partial failure recovery with checkpoint")
    items      = [f"doc_{i:03d}" for i in range(20)]
    checkpoint = set()

    def process_item(item: str) -> str:
        if random.random() < 0.3:
            raise ValueError(f"Processing failed for {item}")
        return f"ok:{item}"

    result = run_with_checkpoint(items, process_item, checkpoint, dead_letter, "process_docs")
    print(f"  Run 1: {result}")

    # Simulate retry — checkpoint prevents re-processing successful items
    result2 = run_with_checkpoint(items, process_item, checkpoint, dead_letter, "process_docs")
    print(f"  Run 2 (retry): {result2}  ← skipped already-processed items")

    # Demo 4: Dead letter summary
    print(f"\n[DEMO 4]  Dead letter store")
    dead_letter.print_summary()

    print(f"\n{'='*65}")
    print(f"  Airflow implements these patterns automatically.")
    print(f"  retries=3, retry_exponential_backoff=True in default_args")
    print(f"  Dead letter handling requires custom on_failure_callback.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
