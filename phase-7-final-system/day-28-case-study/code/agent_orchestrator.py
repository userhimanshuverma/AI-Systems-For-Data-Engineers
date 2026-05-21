"""
Day 28 — Resilient Agent Orchestration Layer
============================================
Coordinates tools, implements circuit breakers, manages exponential backoff 
retries with random jitter, and enforces a strict latency/time budget.
Features:
1. Tool Registry: Register and invoke typed tools.
2. Circuit Breakers: Trip tool access after 3 errors (30s cooldown).
3. Exponential Backoff with Jitter: Prevent thundering herds during retries.
4. Total Latency Budget: Truncates calls if budget (e.g. 1500ms) runs thin.
5. Graceful Fallbacks: Returns stale/pre-computed cohorts on tool error.
"""

import time
import uuid
import random
import math
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

from observability import logger, metrics
from failure_simulator import chaos_injector
from retrieval_engine import HybridRetrievalEngine, CombinedContext


class ToolStatus(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    FALLBACK = "fallback"
    CIRCUIT_OPEN = "circuit_open"


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class ToolCall:
    """Telemetry structure for a single tool call."""
    tool_name: str
    call_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: ToolStatus = ToolStatus.SUCCESS
    result: Any = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    retries: int = 0
    timestamp: str = ""


@dataclass
class ExecutionTrace:
    """Complete trace of the orchestrator run."""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    query: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    total_latency_ms: float = 0.0
    status: str = "pending"
    context_assembled: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Circuit Breaker Logic
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Trips after a sequence of errors, protecting downstream systems."""

    def __init__(self, failure_threshold: int = 3, cooldown_sec: float = 10.0):
        self.failure_threshold = failure_threshold
        self.cooldown_sec = cooldown_sec
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.last_failure_time = 0.0

    def can_execute(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            # Check cooldown expiry
            if time.time() - self.last_failure_time > self.cooldown_sec:
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit Breaker entering HALF_OPEN: testing downstream service recovery.")
                return True
            return False
        # HALF_OPEN allows testing queries
        return True

    def record_success(self):
        self.consecutive_failures = 0
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            logger.info("Circuit Breaker reset to CLOSED: downstream service fully recovered.")

    def record_failure(self):
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        if self.consecutive_failures >= self.failure_threshold:
            if self.state != CircuitState.OPEN:
                self.state = CircuitState.OPEN
                metrics.increment("circuit_breaker_tripped_total")
                logger.error(f"CIRCUIT BREAKER CRITICAL TRIP: Entering OPEN state. Cooldown = {self.cooldown_sec}s")


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """Manages registered tools, circuits, and retries with backoff."""

    def __init__(self):
        self.tools: Dict[str, Dict] = {}
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}

    def register_tool(self, name: str, handler: Callable, timeout_ms: float = 1000.0, 
                      max_retries: int = 2, fallback: Optional[Callable] = None):
        self.tools[name] = {
            "handler": handler,
            "timeout_ms": timeout_ms,
            "max_retries": max_retries,
            "fallback": fallback
        }
        self.circuit_breakers[name] = CircuitBreaker()

    def execute_tool(self, name: str, trace_id: str, **kwargs) -> ToolCall:
        """Execute tool, applying circuit breaker, timeouts, backoff, and fallbacks."""
        if name not in self.tools:
            return ToolCall(
                tool_name=name,
                status=ToolStatus.FAILURE,
                error=f"Unregistered tool: {name}",
                timestamp=time.strftime("%H:%M:%S")
            )

        tool = self.tools[name]
        cb = self.circuit_breakers[name]
        call = ToolCall(tool_name=name, timestamp=time.strftime("%H:%M:%S"))

        metrics.increment("tool_invocations_total", 1, {"tool": name})

        # 1. Circuit Breaker Check
        if not cb.can_execute():
            call.status = ToolStatus.CIRCUIT_OPEN
            call.error = "Request blocked: Circuit Breaker is OPEN."
            if tool["fallback"]:
                return self._trigger_fallback(tool, call, **kwargs)
            return call

        # 2. Execution & Jittered Retry Loop
        last_error = None
        for attempt in range(tool["max_retries"] + 1):
            start = time.time()
            try:
                # Execute with artificial timeout check
                result = tool["handler"](**kwargs)
                latency = (time.time() - start) * 1000

                if latency > tool["timeout_ms"]:
                    metrics.increment("tool_timeouts_total", 1, {"tool": name})
                    raise TimeoutError(f"Operation timed out: exceeded SLA limit of {tool['timeout_ms']}ms. Took {latency:.1f}ms")

                call.result = result
                call.latency_ms = latency
                call.status = ToolStatus.SUCCESS
                call.retries = attempt
                cb.record_success()
                return call

            except Exception as e:
                last_error = str(e)
                call.retries = attempt
                metrics.increment("tool_failures_total", 1, {"tool": name})
                
                logger.warn(
                    f"Tool Execution Failed (Attempt {attempt + 1}/{tool['max_retries'] + 1}): {e}",
                    trace_id=trace_id, span_id=call.call_id
                )

                if attempt < tool["max_retries"]:
                    # Exponential Backoff with Jitter: delay = base * 2^attempt + random_jitter
                    backoff = (0.05 * (2 ** attempt)) + random.uniform(0.01, 0.05)
                    metrics.increment("tool_retries_total", 1, {"tool": name})
                    time.sleep(backoff)

        # All retries exhausted: trip circuit breaker
        cb.record_failure()
        call.status = ToolStatus.FAILURE
        call.error = f"Retries exhausted. Root Cause: {last_error}"
        
        # 3. Fallback Trigger
        if tool["fallback"]:
            return self._trigger_fallback(tool, call, **kwargs)

        return call

    def _trigger_fallback(self, tool: Dict, call: ToolCall, **kwargs) -> ToolCall:
        """Invoke fallback logic and return degraded results."""
        metrics.increment("tool_fallbacks_total", 1, {"tool": call.tool_name})
        try:
            fallback_res = tool["fallback"](**kwargs)
            call.result = fallback_res
            call.status = ToolStatus.FALLBACK
            call.error = f"Degraded State: Fallback served. Root Error: {call.error}"
        except Exception as e:
            call.status = ToolStatus.FAILURE
            call.error = f"Critical Failure: Fallback also failed: {e}"
        return call


# ---------------------------------------------------------------------------
# Agent Orchestrator Coordinating the System
# ---------------------------------------------------------------------------

class AgentOrchestrator:
    """Manages query execution trace pipelines, SLAs, and fallback routing."""

    def __init__(self, retrieval_engine: HybridRetrievalEngine):
        self.retrieval = retrieval_engine
        self.registry = ToolRegistry()
        self._register_intelligence_tools()

    def _register_intelligence_tools(self):
        """Register Pinot structured, Vector DB semantic, and Context Assembly tools."""
        
        self.registry.register_tool(
            name="structured_pinot_lookup",
            handler=self._tool_structured_pinot,
            timeout_ms=300.0, # Pinot SLA: 300ms
            max_retries=2,
            fallback=self._fallback_pinot
        )

        self.registry.register_tool(
            name="semantic_vector_search",
            handler=self._tool_semantic_vector,
            timeout_ms=500.0, # Vector DB SLA: 500ms
            max_retries=1,
            fallback=self._fallback_vector
        )

        self.registry.register_tool(
            name="context_packer",
            handler=self._tool_context_packer,
            timeout_ms=100.0,
            max_retries=0
        )

    # ── Tool Handlers ──────────────────────────────────────────────────────

    def _tool_structured_pinot(self, query: str, user_id: Optional[str] = None) -> List[Dict]:
        """Fetch real-time analytics data from Pinot."""
        params = {"user_id": user_id} if user_id else {}
        return self.retrieval.pinot.query(query, params)

    def _tool_semantic_vector(self, query: str) -> List[Dict]:
        """Fetch similar behavior profiles from Vector DB."""
        # This will raise a ConnectionError if chaos_injector.vector_db_outage is active
        seed = hash(query) % (2**31)
        rng = random.Random(seed)
        q_vector = [rng.gauss(0, 1) for _ in range(self.retrieval.vector_db.dimension)]
        norm = math.sqrt(sum(x*x for x in q_vector))
        q_vector = [x / norm for x in q_vector]
        return self.retrieval.vector_db.search(q_vector, top_k=3)

    def _tool_context_packer(self, pinot_data: Optional[List[Dict]] = None, 
                             vector_data: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """Compress and package the retrieved data for LLM ingestion."""
        formatted_pinot = []
        if pinot_data:
            for item in pinot_data[:8]:
                formatted_pinot.append(
                    f"User {item['user_id']}: Risk={item['churn_risk_score']} | "
                    f"ERR={item['error_rate']:.1%} | Billing Fails={item['billing_failures']} | "
                    f"Sentiment={item['avg_ticket_sentiment']} | ARR=${item['arr_usd']:.0f}"
                )

        formatted_vector = []
        if vector_data:
            for item in vector_data[:4]:
                formatted_vector.append(
                    f"Similar behavioral signature matching cluster '{item['behavior_cluster']}' "
                    f"(User {item['user_id']}, similarity={item['score']})"
                )

        context_payload = {
            "structured_telemetry": formatted_pinot,
            "semantic_similarities": formatted_vector,
            "total_records_fused": len(formatted_pinot) + len(formatted_vector),
            "extraction_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        return context_payload

    # ── Fallback Implementations ───────────────────────────────────────────

    def _fallback_pinot(self, **kwargs) -> List[Dict]:
        """Fallback when Pinot times out or fails: returns safe historical defaults."""
        logger.warn("Using PINOT FALLBACK: serving static pre-computed historical cohort metrics.")
        return [
            {
                "user_id": "usr_prem_HISTORICAL_AVG",
                "tier": "enterprise",
                "arr_usd": 75000.0,
                "total_events_7d": 1200,
                "error_rate": 0.045,
                "billing_failures": 1,
                "avg_ticket_sentiment": -0.15,
                "churn_risk_score": 0.380,
                "last_active_hours_ago": 12,
                "is_fallback_stub": True
            }
        ]

    def _fallback_vector(self, **kwargs) -> List[Dict]:
        """Fallback when Vector DB fails: returns empty vector search matches."""
        logger.warn("Using VECTOR DB FALLBACK: vector search bypassed. Serving empty similarity lists.")
        return []

    # ── Orchestration Workflow ─────────────────────────────────────────────

    def orchestrate_query(self, query: str, budget_ms: float = 1200.0) -> ExecutionTrace:
        """Plan and execute tool retrievals, adhering to a strict SLA latency budget."""
        trace = ExecutionTrace(query=query)
        start_time = time.time()

        req = self.retrieval.parser.parse_query(query)
        user_id = req.entities.get("user_id")

        pinot_data = None
        vector_data = None

        # Step 1: Structured Pinot Lookup
        elapsed_ms = (time.time() - start_time) * 1000
        if elapsed_ms < budget_ms:
            call = self.registry.execute_tool(
                name="structured_pinot_lookup",
                trace_id=trace.trace_id,
                query=query,
                user_id=user_id
            )
            trace.tool_calls.append(call)
            pinot_data = call.result
        else:
            logger.warn(f"Budget exceeded ({elapsed_ms:.1f}ms / {budget_ms}ms) before executing Pinot. Skipping structured query.")

        # Step 2: Semantic Vector DB Lookup (if planned)
        elapsed_ms = (time.time() - start_time) * 1000
        if req.needs_semantic:
            if elapsed_ms < budget_ms:
                call = self.registry.execute_tool(
                    name="semantic_vector_search",
                    trace_id=trace.trace_id,
                    query=query
                )
                trace.tool_calls.append(call)
                vector_data = call.result
            else:
                logger.warn(f"Budget exceeded ({elapsed_ms:.1f}ms / {budget_ms}ms) before executing Vector DB. Skipping semantic query.")
                # Force fallback result directly due to budget depletion
                vector_call = ToolCall(tool_name="semantic_vector_search", status=ToolStatus.TIMEOUT, error="Latency budget expired.")
                vector_data = self._fallback_vector()
                vector_call.result = vector_data
                trace.tool_calls.append(vector_call)

        # Step 3: Package Context
        elapsed_ms = (time.time() - start_time) * 1000
        if elapsed_ms < budget_ms:
            call = self.registry.execute_tool(
                name="context_packer",
                trace_id=trace.trace_id,
                pinot_data=pinot_data,
                vector_data=vector_data
            )
            trace.tool_calls.append(call)
            trace.context_assembled = call.result or {}
            trace.status = "completed" if all(tc.status == ToolStatus.SUCCESS for tc in trace.tool_calls) else "degraded"
        else:
            logger.error("Latency Budget depleted before context packaging could complete!")
            trace.status = "failed"
            trace.context_assembled = {"error": "Pipeline SLA violation: budget exceeded."}

        trace.total_latency_ms = (time.time() - start_time) * 1000
        
        # Logging trace outcome
        logger.info(f"Agent Orchestration finished. Status={trace.status} Latency={trace.total_latency_ms:.1f}ms")
        return trace


if __name__ == "__main__":
    print("Testing Agent Orchestrator...")
    retrieval = HybridRetrievalEngine()
    orchestrator = AgentOrchestrator(retrieval)
    
    trace = orchestrator.orchestrate_query("Show me premium user risks")
    print("Trace Status:", trace.status)
    print("Total Latency:", trace.total_latency_ms)
    print("Assembled Context Keys:", trace.context_assembled.keys())
