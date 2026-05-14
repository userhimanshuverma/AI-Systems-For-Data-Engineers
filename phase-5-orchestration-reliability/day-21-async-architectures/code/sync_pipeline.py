"""
Sync Pipeline — Day 21: Async vs Sync Architectures
=====================================================
Simulates a synchronous request-response pipeline for AI queries.

The caller blocks until all operations complete:
  1. Query Pinot (structured metrics)
  2. Search vectors (semantic context)
  3. Call LLM (reasoning)

Demonstrates:
  - How sync works under normal load
  - How sync breaks under high concurrency
  - Latency accumulation across sequential operations
  - Thread blocking behavior
"""

import time
import random
import threading
from dataclasses import dataclass
from datetime import datetime


# ── SIMULATED SERVICES ────────────────────────────────────────────────────────

def query_pinot(user_id: str) -> dict:
    """Simulates Pinot SQL query (~70ms)."""
    time.sleep(random.uniform(0.060, 0.080))
    return {"user_id": user_id, "error_rate": 0.50, "churn_risk": True}

def search_vectors(query: str, user_id: str) -> list[str]:
    """Simulates vector similarity search (~50ms)."""
    time.sleep(random.uniform(0.040, 0.060))
    return [f"User {user_id} hit error on /checkout", f"User {user_id} clicked Upgrade"]

def call_llm(context: str) -> str:
    """Simulates LLM inference (~600ms, variable)."""
    time.sleep(random.uniform(0.400, 0.800))
    return f"User is at HIGH churn risk. Recommend: escalate checkout fix."


# ── SYNC PIPELINE ─────────────────────────────────────────────────────────────

@dataclass
class SyncResult:
    user_id:    str
    response:   str
    latency_ms: float
    breakdown:  dict


def process_sync(user_id: str) -> SyncResult:
    """
    Processes a single request synchronously.
    The caller blocks until all three operations complete.
    """
    t0 = time.perf_counter()
    timings = {}

    # Step 1: Query Pinot (blocks)
    t1 = time.perf_counter()
    metrics = query_pinot(user_id)
    timings["pinot_ms"] = round((time.perf_counter() - t1) * 1000, 1)

    # Step 2: Search vectors (blocks)
    t2 = time.perf_counter()
    chunks = search_vectors("churn risk", user_id)
    timings["vector_ms"] = round((time.perf_counter() - t2) * 1000, 1)

    # Step 3: Call LLM (blocks — this is the bottleneck)
    t3 = time.perf_counter()
    context = f"Metrics: {metrics}\nContext: {chunks}"
    response = call_llm(context)
    timings["llm_ms"] = round((time.perf_counter() - t3) * 1000, 1)

    total_ms = round((time.perf_counter() - t0) * 1000, 1)
    return SyncResult(user_id=user_id, response=response,
                      latency_ms=total_ms, breakdown=timings)


# ── CONCURRENCY TEST ──────────────────────────────────────────────────────────

def run_concurrent_sync(n_requests: int, n_threads: int) -> dict:
    """
    Simulates concurrent sync requests.
    Shows how sync degrades under load.
    """
    results = []
    lock    = threading.Lock()

    def worker(user_id: str):
        result = process_sync(user_id)
        with lock:
            results.append(result)

    t0      = time.perf_counter()
    threads = []
    for i in range(n_requests):
        t = threading.Thread(target=worker, args=(f"u_{i:04d}",))
        threads.append(t)

    # Start threads in batches (simulating concurrent requests)
    batch_size = n_threads
    for i in range(0, len(threads), batch_size):
        batch = threads[i:i + batch_size]
        for t in batch:
            t.start()
        for t in batch:
            t.join()

    total_wall_ms = round((time.perf_counter() - t0) * 1000, 1)
    latencies     = [r.latency_ms for r in results]

    return {
        "requests":       n_requests,
        "threads":        n_threads,
        "wall_time_ms":   total_wall_ms,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1),
        "p99_latency_ms": round(sorted(latencies)[int(len(latencies) * 0.99)], 1),
        "throughput_rps": round(n_requests / (total_wall_ms / 1000), 1),
    }


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("SYNC PIPELINE — Blocking request-response flow")
    print("=" * 65)

    # Single request
    print(f"\n[SINGLE REQUEST]")
    result = process_sync("u_4821")
    print(f"  User:     {result.user_id}")
    print(f"  Latency:  {result.latency_ms}ms total")
    print(f"  Breakdown: Pinot={result.breakdown['pinot_ms']}ms, "
          f"Vector={result.breakdown['vector_ms']}ms, "
          f"LLM={result.breakdown['llm_ms']}ms")
    print(f"  Response: {result.response[:60]}...")

    # Concurrency test
    print(f"\n[CONCURRENCY TEST]  How sync scales under load")
    for n_req, n_threads in [(5, 5), (10, 10), (20, 10)]:
        stats = run_concurrent_sync(n_req, n_threads)
        print(f"\n  {n_req} requests, {n_threads} concurrent threads:")
        print(f"    Wall time:    {stats['wall_time_ms']}ms")
        print(f"    Avg latency:  {stats['avg_latency_ms']}ms")
        print(f"    Throughput:   {stats['throughput_rps']} req/sec")

    print(f"\n{'='*65}")
    print(f"  OBSERVATION: Sync throughput is limited by LLM latency.")
    print(f"  At 600ms/request, max throughput ≈ 1/0.6 = 1.67 req/sec/thread.")
    print(f"  To handle 1000 req/sec: need 600 concurrent threads.")
    print(f"  Solution: async queue + worker pool (see async_queue.py)")
    print(f"{'='*65}")


if __name__ == "__main__":
    random.seed(42)
    run()
