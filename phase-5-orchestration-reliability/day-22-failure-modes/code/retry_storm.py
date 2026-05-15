"""
Retry Storm — Day 22: Failure Modes in AI Systems
===================================================
Demonstrates how retry storms form and how to prevent them.

A retry storm occurs when:
  1. A service goes down
  2. Many clients fail simultaneously
  3. All clients retry at the same time
  4. The recovering service is overwhelmed
  5. It crashes again → cycle repeats

Prevention:
  - Exponential backoff with jitter
  - Circuit breakers
  - Retry budgets (max concurrent retries)
"""

import time
import random
import threading
from dataclasses import dataclass, field
from collections import defaultdict


# ── SERVICE SIMULATOR ─────────────────────────────────────────────────────────

class MockService:
    """Simulates a service that goes down and recovers."""
    def __init__(self, name: str, recovery_time_s: float = 2.0,
                 overload_threshold: int = 20):
        self.name               = name
        self.recovery_time_s    = recovery_time_s
        self.overload_threshold = overload_threshold
        self._down_at:  float | None = None
        self._concurrent_requests = 0
        self._lock = threading.Lock()
        self.request_log: list[dict] = []

    def go_down(self) -> None:
        self._down_at = time.perf_counter()
        print(f"  [{self.name}] ⬇️  Service went DOWN at t={self._down_at:.1f}")

    def call(self) -> str:
        with self._lock:
            self._concurrent_requests += 1
            concurrent = self._concurrent_requests

        try:
            # Check if down
            if self._down_at is not None:
                elapsed = time.perf_counter() - self._down_at
                if elapsed < self.recovery_time_s:
                    raise ConnectionError(f"{self.name} is down ({elapsed:.1f}s into outage)")

                # Recovered — but check for overload
                if concurrent > self.overload_threshold:
                    raise ConnectionError(f"{self.name} overloaded ({concurrent} concurrent requests)")

                # Successfully recovered
                self._down_at = None

            time.sleep(0.010)  # simulate 10ms response
            return f"OK from {self.name}"

        finally:
            with self._lock:
                self._concurrent_requests -= 1


# ── RETRY STRATEGIES ──────────────────────────────────────────────────────────

def retry_no_backoff(service: MockService, client_id: str,
                     max_retries: int = 5) -> dict:
    """
    BAD: Retries immediately with no delay.
    Creates thundering herd when service recovers.
    """
    for attempt in range(max_retries + 1):
        try:
            result = service.call()
            return {"client": client_id, "success": True, "attempts": attempt + 1}
        except Exception:
            if attempt == max_retries:
                return {"client": client_id, "success": False, "attempts": attempt + 1}
            # No delay — retry immediately!
            pass
    return {"client": client_id, "success": False, "attempts": max_retries + 1}


def retry_with_backoff_and_jitter(service: MockService, client_id: str,
                                   max_retries: int = 5,
                                   base_delay: float = 0.1) -> dict:
    """
    GOOD: Exponential backoff with full jitter.
    Spreads retries over time — prevents thundering herd.
    """
    for attempt in range(max_retries + 1):
        try:
            result = service.call()
            return {"client": client_id, "success": True, "attempts": attempt + 1}
        except Exception:
            if attempt == max_retries:
                return {"client": client_id, "success": False, "attempts": attempt + 1}
            # Full jitter: random between 0 and cap
            cap   = min(base_delay * (2 ** attempt), 2.0)
            delay = random.uniform(0, cap)
            time.sleep(delay)
    return {"client": client_id, "success": False, "attempts": max_retries + 1}


# ── CIRCUIT BREAKER ───────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Prevents retry storms by stopping calls to a failing service.
    States: CLOSED (normal) → OPEN (failing) → HALF_OPEN (testing)
    """
    def __init__(self, name: str, failure_threshold: int = 5,
                 recovery_timeout_s: float = 1.0):
        self.name              = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout  = recovery_timeout_s
        self._state            = "CLOSED"
        self._failure_count    = 0
        self._opened_at: float | None = None
        self._lock             = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == "OPEN":
                if time.perf_counter() - self._opened_at > self.recovery_timeout:
                    self._state = "HALF_OPEN"
            return self._state

    def call(self, fn, *args, **kwargs):
        state = self.state
        if state == "OPEN":
            raise RuntimeError(f"Circuit {self.name} is OPEN — using fallback")

        try:
            result = fn(*args, **kwargs)
            with self._lock:
                self._failure_count = 0
                if self._state == "HALF_OPEN":
                    self._state = "CLOSED"
                    print(f"  [CB:{self.name}] ✅ Circuit CLOSED (service recovered)")
            return result

        except Exception as e:
            with self._lock:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold and self._state != "OPEN":
                    self._state    = "OPEN"
                    self._opened_at = time.perf_counter()
                    print(f"  [CB:{self.name}] 🔴 Circuit OPENED after {self._failure_count} failures")
            raise


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("RETRY STORM — Formation and prevention")
    print("=" * 65)

    random.seed(42)

    # ── Demo 1: Retry storm (no backoff) ──────────────────────────────────
    print(f"\n[DEMO 1]  Retry storm — no backoff (BAD pattern)")
    service1 = MockService("vector-store", recovery_time_s=1.0, overload_threshold=10)
    service1.go_down()

    results = []
    threads = []
    t0 = time.perf_counter()

    for i in range(20):
        t = threading.Thread(
            target=lambda cid=f"client_{i:02d}": results.append(
                retry_no_backoff(service1, cid, max_retries=3)
            )
        )
        threads.append(t)

    for t in threads: t.start()
    for t in threads: t.join()

    elapsed = round((time.perf_counter() - t0) * 1000, 0)
    success = sum(1 for r in results if r["success"])
    total_attempts = sum(r["attempts"] for r in results)
    print(f"  20 clients, no backoff: {success}/20 succeeded")
    print(f"  Total retry attempts: {total_attempts} (avg {total_attempts/20:.1f}/client)")
    print(f"  Wall time: {elapsed:.0f}ms")
    print(f"  ❌ All clients retry simultaneously → service overloaded on recovery")

    # ── Demo 2: With backoff + jitter ─────────────────────────────────────
    print(f"\n[DEMO 2]  Exponential backoff + jitter (GOOD pattern)")
    service2 = MockService("vector-store-2", recovery_time_s=0.5, overload_threshold=10)
    service2.go_down()

    results2 = []
    threads2 = []
    t0 = time.perf_counter()

    for i in range(20):
        t = threading.Thread(
            target=lambda cid=f"client_{i:02d}": results2.append(
                retry_with_backoff_and_jitter(service2, cid, max_retries=5, base_delay=0.05)
            )
        )
        threads2.append(t)

    for t in threads2: t.start()
    for t in threads2: t.join()

    elapsed2 = round((time.perf_counter() - t0) * 1000, 0)
    success2 = sum(1 for r in results2 if r["success"])
    total2   = sum(r["attempts"] for r in results2)
    print(f"  20 clients, backoff+jitter: {success2}/20 succeeded")
    print(f"  Total retry attempts: {total2} (avg {total2/20:.1f}/client)")
    print(f"  Wall time: {elapsed2:.0f}ms")
    print(f"  ✅ Retries spread over time → service recovers without overload")

    # ── Demo 3: Circuit breaker ───────────────────────────────────────────
    print(f"\n[DEMO 3]  Circuit breaker prevents storm")
    service3 = MockService("pinot", recovery_time_s=0.5, overload_threshold=100)
    service3.go_down()
    cb = CircuitBreaker("pinot", failure_threshold=3, recovery_timeout_s=0.6)

    blocked = 0
    passed  = 0
    for i in range(15):
        try:
            cb.call(service3.call)
            passed += 1
        except RuntimeError:
            blocked += 1  # circuit open — blocked
        except ConnectionError:
            pass  # service down — counted as failure
        time.sleep(0.05)

    print(f"  15 calls: {passed} passed, {blocked} blocked by circuit breaker")
    print(f"  ✅ Circuit breaker stopped {blocked} calls from hitting the failing service")
    print(f"  Final circuit state: {cb.state}")

    print(f"\n{'='*65}")
    print(f"  PREVENTION SUMMARY:")
    print(f"  1. Exponential backoff + jitter → spreads retries over time")
    print(f"  2. Circuit breaker → stops calls when service is failing")
    print(f"  3. Max retry limit → prevents infinite retry loops")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
