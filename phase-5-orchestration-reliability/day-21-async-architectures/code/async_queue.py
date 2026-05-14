"""
Async Queue — Day 21: Async vs Sync Architectures
===================================================
Simulates a queue-based async worker system.

Pattern:
  Producer → Queue → Worker Pool → Result Store

The producer enqueues tasks and returns immediately (non-blocking).
Workers consume tasks from the queue at their own pace.
The queue absorbs traffic spikes — workers drain it over time.

Demonstrates:
  - Decoupled producer/consumer
  - Worker pool processing
  - Queue depth tracking
  - Throughput comparison vs sync
"""

import time
import random
import threading
from queue import Queue, Empty
from dataclasses import dataclass, field
from datetime import datetime


# ── TASK DEFINITION ───────────────────────────────────────────────────────────

@dataclass
class Task:
    task_id:    str
    user_id:    str
    task_type:  str
    payload:    dict
    enqueued_at:float = field(default_factory=time.perf_counter)
    attempts:   int   = 0


@dataclass
class TaskResult:
    task_id:    str
    user_id:    str
    success:    bool
    output:     str
    latency_ms: float
    queue_wait_ms: float


# ── SIMULATED SERVICES ────────────────────────────────────────────────────────

def process_embedding_task(task: Task) -> str:
    """Simulates embedding generation + vector upsert (~150ms)."""
    time.sleep(random.uniform(0.100, 0.200))
    return f"Embedded {task.user_id}: 1536-dim vector upserted"

def process_analysis_task(task: Task) -> str:
    """Simulates LLM analysis (~600ms)."""
    time.sleep(random.uniform(0.400, 0.800))
    return f"Analysis for {task.user_id}: HIGH churn risk, escalate checkout"

TASK_PROCESSORS = {
    "embedding": process_embedding_task,
    "analysis":  process_analysis_task,
}


# ── RESULT STORE ──────────────────────────────────────────────────────────────

class ResultStore:
    """Stores completed task results. In production: Redis or Postgres."""
    def __init__(self):
        self._results: dict[str, TaskResult] = {}
        self._lock = threading.Lock()

    def store(self, result: TaskResult) -> None:
        with self._lock:
            self._results[result.task_id] = result

    def get(self, task_id: str) -> TaskResult | None:
        return self._results.get(task_id)

    def count(self) -> int:
        return len(self._results)


# ── WORKER ────────────────────────────────────────────────────────────────────

class Worker(threading.Thread):
    """
    Consumes tasks from the queue and processes them.
    In production: a separate process or container.
    """
    def __init__(self, worker_id: int, queue: Queue, result_store: ResultStore,
                 stats: dict, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.worker_id    = worker_id
        self.queue        = queue
        self.result_store = result_store
        self.stats        = stats
        self.stop_event   = stop_event
        self._lock        = threading.Lock()

    def run(self):
        while not self.stop_event.is_set():
            try:
                task: Task = self.queue.get(timeout=0.1)
            except Empty:
                continue

            t0 = time.perf_counter()
            queue_wait_ms = round((t0 - task.enqueued_at) * 1000, 1)

            try:
                processor = TASK_PROCESSORS.get(task.task_type, process_embedding_task)
                output    = processor(task)
                latency_ms = round((time.perf_counter() - t0) * 1000, 1)

                result = TaskResult(
                    task_id=task.task_id, user_id=task.user_id,
                    success=True, output=output,
                    latency_ms=latency_ms, queue_wait_ms=queue_wait_ms,
                )
                self.result_store.store(result)

                with self._lock:
                    self.stats["processed"] = self.stats.get("processed", 0) + 1
                    self.stats["total_latency_ms"] = (
                        self.stats.get("total_latency_ms", 0) + latency_ms
                    )

            except Exception as e:
                with self._lock:
                    self.stats["failed"] = self.stats.get("failed", 0) + 1

            finally:
                self.queue.task_done()


# ── ASYNC QUEUE SYSTEM ────────────────────────────────────────────────────────

class AsyncQueueSystem:
    """
    Queue-based async processing system.
    Producer enqueues tasks; workers process them independently.
    """
    def __init__(self, n_workers: int = 4, max_queue_size: int = 10000):
        self.queue        = Queue(maxsize=max_queue_size)
        self.result_store = ResultStore()
        self.stats        = {"processed": 0, "failed": 0, "total_latency_ms": 0}
        self.stop_event   = threading.Event()
        self.workers      = [
            Worker(i, self.queue, self.result_store, self.stats, self.stop_event)
            for i in range(n_workers)
        ]
        for w in self.workers:
            w.start()

    def enqueue(self, task: Task) -> str:
        """
        Enqueues a task and returns immediately.
        The caller does NOT wait for processing.
        Returns the task_id for polling.
        """
        self.queue.put(task)
        return task.task_id

    def get_result(self, task_id: str) -> TaskResult | None:
        """Poll for result. Returns None if not yet complete."""
        return self.result_store.get(task_id)

    def queue_depth(self) -> int:
        return self.queue.qsize()

    def wait_all(self, timeout: float = 30.0) -> None:
        """Wait for all queued tasks to complete."""
        self.queue.join()

    def shutdown(self) -> None:
        self.stop_event.set()

    def summary(self) -> dict:
        processed = self.stats.get("processed", 0)
        avg_lat   = (self.stats.get("total_latency_ms", 0) / max(processed, 1))
        return {
            "processed":      processed,
            "failed":         self.stats.get("failed", 0),
            "avg_latency_ms": round(avg_lat, 1),
            "results_stored": self.result_store.count(),
        }


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("ASYNC QUEUE — Decoupled producer/consumer pattern")
    print("=" * 65)

    random.seed(42)

    # ── Test 1: Basic async flow ──────────────────────────────────────────
    print(f"\n[TEST 1]  Basic async flow — 10 embedding tasks, 4 workers")
    system = AsyncQueueSystem(n_workers=4)
    t0     = time.perf_counter()

    task_ids = []
    for i in range(10):
        task = Task(
            task_id=f"task_{i:03d}",
            user_id=f"u_{i:04d}",
            task_type="embedding",
            payload={"doc_count": 100},
        )
        tid = system.enqueue(task)
        task_ids.append(tid)

    enqueue_ms = round((time.perf_counter() - t0) * 1000, 1)
    print(f"  Enqueued 10 tasks in {enqueue_ms}ms (non-blocking)")
    print(f"  Queue depth: {system.queue_depth()}")

    # Wait for completion
    system.wait_all(timeout=10.0)
    total_ms = round((time.perf_counter() - t0) * 1000, 1)

    summary = system.summary()
    print(f"  All tasks completed in {total_ms}ms wall time")
    print(f"  Processed: {summary['processed']} | Avg latency: {summary['avg_latency_ms']}ms")
    print(f"  Throughput: {round(10 / (total_ms/1000), 1)} tasks/sec (4 parallel workers)")
    system.shutdown()

    # ── Test 2: Traffic spike absorption ─────────────────────────────────
    print(f"\n[TEST 2]  Traffic spike — 50 tasks burst, 4 workers")
    system2 = AsyncQueueSystem(n_workers=4)
    t0      = time.perf_counter()

    for i in range(50):
        task = Task(
            task_id=f"burst_{i:03d}",
            user_id=f"u_{i:04d}",
            task_type="embedding",
            payload={},
        )
        system2.enqueue(task)

    enqueue_ms = round((time.perf_counter() - t0) * 1000, 1)
    print(f"  Enqueued 50 tasks in {enqueue_ms}ms")
    print(f"  Queue depth after burst: {system2.queue_depth()} (workers draining...)")

    system2.wait_all(timeout=30.0)
    total_ms = round((time.perf_counter() - t0) * 1000, 1)
    summary2 = system2.summary()
    print(f"  All 50 tasks completed in {total_ms}ms wall time")
    print(f"  Throughput: {round(50 / (total_ms/1000), 1)} tasks/sec")
    system2.shutdown()

    # ── Comparison ────────────────────────────────────────────────────────
    print(f"\n[COMPARISON]  Sync vs Async for 10 embedding tasks")
    sync_estimate = 10 * 150  # 10 tasks × 150ms each, sequential
    async_actual  = round(10 * 150 / 4)  # 4 parallel workers
    print(f"  Sync (sequential):  ~{sync_estimate}ms")
    print(f"  Async (4 workers):  ~{async_actual}ms  ({sync_estimate//async_actual}x faster)")
    print(f"  Async enqueue time: {enqueue_ms}ms (caller returns immediately)")

    print(f"\n{'='*65}")
    print(f"  KEY: Async caller returns in {enqueue_ms}ms.")
    print(f"  Workers process in background. Queue absorbs spikes.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
