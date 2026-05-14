"""
Retry Handler — Day 21: Async vs Sync Architectures
=====================================================
Implements retry logic with exponential backoff, jitter,
dead letter queues, and idempotency for async task processing.

Covers:
  - Exponential backoff with jitter
  - Max retry limits
  - Dead letter queue (DLQ)
  - Idempotency verification
  - Retry budget (don't retry everything forever)
"""

import time
import random
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Any


# ── RETRY CONFIG ──────────────────────────────────────────────────────────────

@dataclass
class RetryConfig:
    max_retries:    int   = 5
    base_delay_s:   float = 1.0
    max_delay_s:    float = 60.0
    jitter:         bool  = True
    exponential:    bool  = True


# ── RETRY RESULT ──────────────────────────────────────────────────────────────

@dataclass
class RetryResult:
    success:     bool
    attempts:    int
    total_ms:    float
    output:      Any   = None
    error:       str | None = None
    dead_letter: bool  = False


# ── DEAD LETTER QUEUE ─────────────────────────────────────────────────────────

@dataclass
class DLQEntry:
    task_id:    str
    payload:    Any
    error:      str
    attempts:   int
    failed_at:  str


class DeadLetterQueue:
    """Stores permanently failed tasks for manual investigation."""
    def __init__(self):
        self._entries: list[DLQEntry] = []

    def push(self, task_id: str, payload: Any, error: str, attempts: int) -> None:
        self._entries.append(DLQEntry(
            task_id=task_id, payload=payload, error=error,
            attempts=attempts,
            failed_at=datetime.now(timezone.utc).isoformat(),
        ))
        print(f"  [DLQ] Task {task_id} moved to dead letter queue after {attempts} attempts: {error[:50]}")

    def replay(self, task_id: str) -> DLQEntry | None:
        """Remove from DLQ for replay after root cause is fixed."""
        for i, e in enumerate(self._entries):
            if e.task_id == task_id:
                return self._entries.pop(i)
        return None

    def count(self) -> int:
        return len(self._entries)

    def summary(self) -> None:
        print(f"\n  [DLQ] {len(self._entries)} entries:")
        for e in self._entries:
            print(f"    {e.task_id}: {e.error[:50]} (attempts={e.attempts})")


# ── RETRY EXECUTOR ────────────────────────────────────────────────────────────

def compute_delay(attempt: int, config: RetryConfig) -> float:
    """Computes retry delay with exponential backoff and optional jitter."""
    if config.exponential:
        delay = config.base_delay_s * (2 ** attempt)
    else:
        delay = config.base_delay_s

    delay = min(delay, config.max_delay_s)

    if config.jitter:
        # Full jitter: random between 0 and delay
        # Prevents thundering herd when many workers retry simultaneously
        delay = random.uniform(0, delay)

    return delay


def execute_with_retry(
    fn: Callable,
    task_id: str,
    args: tuple = (),
    kwargs: dict = None,
    config: RetryConfig = None,
    dlq: DeadLetterQueue = None,
) -> RetryResult:
    """
    Executes a function with retry, exponential backoff, and DLQ.
    """
    config = config or RetryConfig()
    kwargs = kwargs or {}
    t0     = time.perf_counter()

    for attempt in range(config.max_retries + 1):
        try:
            result = fn(*args, **kwargs)
            total_ms = round((time.perf_counter() - t0) * 1000, 1)
            if attempt > 0:
                print(f"  [RETRY] {task_id} succeeded on attempt {attempt + 1}")
            return RetryResult(success=True, attempts=attempt + 1,
                               total_ms=total_ms, output=result)

        except Exception as e:
            error_msg = str(e)
            if attempt < config.max_retries:
                delay = compute_delay(attempt, config)
                print(f"  [RETRY] {task_id} attempt {attempt + 1} failed: {error_msg[:40]}. "
                      f"Retry in {delay:.2f}s")
                time.sleep(delay * 0.05)  # scaled down for demo
            else:
                total_ms = round((time.perf_counter() - t0) * 1000, 1)
                if dlq:
                    dlq.push(task_id, args, error_msg, attempt + 1)
                return RetryResult(
                    success=False, attempts=attempt + 1,
                    total_ms=total_ms, error=error_msg, dead_letter=True,
                )

    return RetryResult(success=False, attempts=config.max_retries + 1,
                       total_ms=round((time.perf_counter() - t0) * 1000, 1),
                       error="max_retries_exceeded", dead_letter=True)


# ── IDEMPOTENCY STORE ─────────────────────────────────────────────────────────

class IdempotencyStore:
    """
    Tracks processed task IDs to prevent duplicate processing on retry.
    In production: Redis with TTL or Postgres with unique constraint.
    """
    def __init__(self):
        self._processed: set[str] = set()

    def is_processed(self, task_id: str) -> bool:
        return task_id in self._processed

    def mark_processed(self, task_id: str) -> None:
        self._processed.add(task_id)

    def count(self) -> int:
        return len(self._processed)


def idempotent_task(task_id: str, payload: dict, store: IdempotencyStore) -> str:
    """
    Idempotent task: safe to call multiple times with same task_id.
    Uses idempotency store to detect and skip duplicate executions.
    """
    if store.is_processed(task_id):
        return f"SKIPPED (already processed): {task_id}"

    # Simulate work
    time.sleep(0.020)
    store.mark_processed(task_id)
    return f"PROCESSED: {task_id}"


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("RETRY HANDLER — Backoff, DLQ, and idempotency")
    print("=" * 65)

    random.seed(42)
    dlq    = DeadLetterQueue()
    config = RetryConfig(max_retries=3, base_delay_s=0.5, jitter=True)

    # ── Demo 1: Successful retry ──────────────────────────────────────────
    print(f"\n[DEMO 1]  Transient failure → retry → success")
    call_count = [0]
    def flaky_api(fail_times: int = 2):
        call_count[0] += 1
        if call_count[0] <= fail_times:
            raise TimeoutError(f"API timeout on call {call_count[0]}")
        return "API call succeeded"

    result = execute_with_retry(flaky_api, "task_001", args=(2,), config=config, dlq=dlq)
    print(f"  Success: {result.success} | Attempts: {result.attempts} | Time: {result.total_ms:.0f}ms")

    # ── Demo 2: Permanent failure → DLQ ──────────────────────────────────
    print(f"\n[DEMO 2]  Permanent failure → dead letter queue")
    call_count2 = [0]
    def always_fails():
        call_count2[0] += 1
        raise ConnectionError(f"Service permanently unavailable (call {call_count2[0]})")

    result2 = execute_with_retry(always_fails, "task_002", config=config, dlq=dlq)
    print(f"  Success: {result2.success} | Attempts: {result2.attempts} | DLQ: {result2.dead_letter}")

    # ── Demo 3: Backoff timing ────────────────────────────────────────────
    print(f"\n[DEMO 3]  Exponential backoff delays (with jitter)")
    cfg = RetryConfig(max_retries=5, base_delay_s=1.0, max_delay_s=30.0, jitter=True)
    print(f"  {'Attempt':8s} {'Base delay':12s} {'With jitter':12s}")
    print(f"  {'-'*35}")
    for attempt in range(5):
        base  = min(1.0 * (2 ** attempt), 30.0)
        jittered = compute_delay(attempt, cfg)
        print(f"  {attempt+1:8d} {base:10.1f}s   {jittered:10.2f}s")

    # ── Demo 4: Idempotency ───────────────────────────────────────────────
    print(f"\n[DEMO 4]  Idempotency — safe to retry")
    store = IdempotencyStore()
    for run_num in range(1, 3):
        results = []
        for i in range(5):
            r = idempotent_task(f"task_{i:03d}", {"data": i}, store)
            results.append(r)
        skipped = sum(1 for r in results if "SKIPPED" in r)
        processed = sum(1 for r in results if "PROCESSED" in r)
        print(f"  Run {run_num}: {processed} processed, {skipped} skipped (idempotent)")

    # ── DLQ summary ───────────────────────────────────────────────────────
    dlq.summary()

    # ── DLQ replay ───────────────────────────────────────────────────────
    print(f"\n[DEMO 5]  DLQ replay after root cause fixed")
    entry = dlq.replay("task_002")
    if entry:
        print(f"  Replaying {entry.task_id} from DLQ...")
        result3 = execute_with_retry(lambda: "Replayed successfully", "task_002_replay",
                                     config=config, dlq=dlq)
        print(f"  Replay result: {result3.success} | Output: {result3.output}")

    print(f"\n{'='*65}")
    print(f"  DLQ remaining: {dlq.count()} entries")
    print(f"  Idempotency store: {store.count()} processed task IDs")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
