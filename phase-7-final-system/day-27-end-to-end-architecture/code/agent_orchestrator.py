"""
Day 27 — Agent Orchestrator (Tool Coordination Simulation)
===========================================================
Simulates the agent orchestration layer that coordinates multiple tools,
manages execution flow, and implements reliability patterns.

Architecture Role:
    The agent layer sits between the retrieval engine and the LLM.
    It decides WHAT information to retrieve, WHICH tools to invoke,
    and HOW to assemble context for reasoning — all while managing
    retries, timeouts, and fallbacks.

Key Design Principles:
    1. Agents are COORDINATORS, not AI — they route and orchestrate
    2. Tool calls are typed, validated, and observable
    3. Every execution path has a fallback
    4. Parallel execution when tools are independent
    5. Observability is first-class — every step is traced

Production Considerations:
    - Circuit breakers per tool to prevent cascade failures
    - Timeout budgets: total query budget split across tool calls
    - Retry with exponential backoff + jitter
    - Tool results cached where appropriate
    - Structured execution traces for debugging
"""

import time
import uuid
import random
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class ToolStatus(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    FALLBACK = "fallback"
    CIRCUIT_OPEN = "circuit_open"


class CircuitState(Enum):
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class ToolCall:
    """Record of a single tool invocation."""
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
    """Full trace of an orchestration execution."""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    query: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    total_latency_ms: float = 0.0
    status: str = "pending"
    context_assembled: Dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """
    Circuit breaker pattern to prevent cascade failures.
    Opens after consecutive failures, allowing recovery time.
    """

    def __init__(self, failure_threshold: int = 3, recovery_time: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.success_count = 0

    def can_execute(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_time:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        # HALF_OPEN — allow one test call
        return True

    def record_success(self):
        self.failure_count = 0
        self.success_count += 1
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """
    Registry of available tools with metadata, circuit breakers,
    and execution wrappers.
    """

    def __init__(self):
        self.tools: Dict[str, Dict] = {}
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}

    def register(self, name: str, handler: Callable,
                 timeout_ms: float = 5000, retries: int = 2,
                 fallback: Optional[Callable] = None):
        self.tools[name] = {
            "handler": handler,
            "timeout_ms": timeout_ms,
            "retries": retries,
            "fallback": fallback,
        }
        self.circuit_breakers[name] = CircuitBreaker()

    def execute(self, name: str, **kwargs) -> ToolCall:
        """Execute a tool with retry, timeout, circuit breaker, and fallback."""
        if name not in self.tools:
            return ToolCall(
                tool_name=name,
                status=ToolStatus.FAILURE,
                error=f"Unknown tool: {name}",
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )

        tool = self.tools[name]
        cb = self.circuit_breakers[name]
        call = ToolCall(tool_name=name, timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"))

        # Circuit breaker check
        if not cb.can_execute():
            call.status = ToolStatus.CIRCUIT_OPEN
            call.error = f"Circuit breaker OPEN for {name}"
            # Try fallback
            if tool["fallback"]:
                return self._execute_fallback(tool, call, kwargs)
            return call

        # Retry loop
        last_error = None
        for attempt in range(tool["retries"] + 1):
            start = time.time()
            try:
                result = tool["handler"](**kwargs)
                call.latency_ms = (time.time() - start) * 1000

                # Timeout check
                if call.latency_ms > tool["timeout_ms"]:
                    raise TimeoutError(f"Tool {name} exceeded {tool['timeout_ms']}ms")

                call.result = result
                call.status = ToolStatus.SUCCESS
                call.retries = attempt
                cb.record_success()
                return call

            except Exception as e:
                last_error = str(e)
                call.retries = attempt + 1
                time.sleep(min(0.01 * (2 ** attempt), 0.1))  # Exponential backoff

        # All retries exhausted
        cb.record_failure()
        call.status = ToolStatus.FAILURE
        call.error = last_error
        call.latency_ms = (time.time() - start) * 1000

        # Try fallback
        if tool["fallback"]:
            return self._execute_fallback(tool, call, kwargs)

        return call

    def _execute_fallback(self, tool: Dict, call: ToolCall, kwargs: Dict) -> ToolCall:
        try:
            call.result = tool["fallback"](**kwargs)
            call.status = ToolStatus.FALLBACK
            call.error = f"Primary failed, used fallback"
        except Exception as e:
            call.status = ToolStatus.FAILURE
            call.error = f"Both primary and fallback failed: {e}"
        return call


# ---------------------------------------------------------------------------
# Agent Orchestrator
# ---------------------------------------------------------------------------

class AgentOrchestrator:
    """
    Orchestrates the full query-to-response pipeline by:
    1. Planning which tools to call based on query intent
    2. Executing tools with reliability patterns
    3. Assembling context from tool results
    4. Managing execution budgets and traces
    """

    def __init__(self):
        self.registry = ToolRegistry()
        self.traces: List[ExecutionTrace] = []
        self._register_default_tools()

    def _register_default_tools(self):
        """Register all available tools."""

        # Structured retrieval tool
        self.registry.register(
            name="structured_retrieval",
            handler=self._tool_structured_retrieval,
            timeout_ms=500,
            retries=2,
            fallback=self._fallback_cached_analytics,
        )

        # Semantic retrieval tool
        self.registry.register(
            name="semantic_retrieval",
            handler=self._tool_semantic_retrieval,
            timeout_ms=1000,
            retries=1,
            fallback=self._fallback_keyword_search,
        )

        # Feature lookup tool
        self.registry.register(
            name="feature_lookup",
            handler=self._tool_feature_lookup,
            timeout_ms=200,
            retries=2,
        )

        # Context assembly tool
        self.registry.register(
            name="context_assembly",
            handler=self._tool_context_assembly,
            timeout_ms=100,
            retries=0,
        )

    # ── Tool Implementations ──────────────────────────────────────────────

    def _tool_structured_retrieval(self, query: str, intent: str, **kwargs) -> Dict:
        """Simulate structured data retrieval from Pinot."""
        time.sleep(random.uniform(0.005, 0.050))
        # Simulate occasional failures (5% rate)
        if random.random() < 0.05:
            raise ConnectionError("Pinot broker connection timeout")
        return {
            "source": "pinot",
            "metrics": {
                "users_at_risk": random.randint(5, 50),
                "avg_churn_score": round(random.uniform(0.3, 0.8), 3),
                "revenue_impact": round(random.uniform(5000, 100000), 2),
                "active_users_trend": random.choice(["increasing", "stable", "declining"]),
            },
            "top_users": [f"user_{random.randint(1,200):04d}" for _ in range(5)],
        }

    def _tool_semantic_retrieval(self, query: str, **kwargs) -> Dict:
        """Simulate semantic vector search."""
        time.sleep(random.uniform(0.010, 0.080))
        if random.random() < 0.03:
            raise TimeoutError("Vector DB search timeout")
        patterns = ["declining_engagement", "expansion_signal", "churn_risk", "power_user"]
        return {
            "source": "vector_db",
            "similar_patterns": random.sample(patterns, min(3, len(patterns))),
            "confidence_scores": [round(random.uniform(0.6, 0.95), 3) for _ in range(3)],
            "behavioral_clusters": random.randint(2, 8),
        }

    def _tool_feature_lookup(self, user_ids: List[str] = None, **kwargs) -> Dict:
        """Simulate feature store lookup."""
        time.sleep(random.uniform(0.002, 0.010))
        user_ids = user_ids or []
        features = {}
        for uid in user_ids[:10]:
            features[uid] = {
                "events_24h": random.randint(0, 100),
                "health_score": round(random.uniform(0, 100), 1),
                "days_since_last_login": random.randint(0, 60),
            }
        return {"source": "feature_store", "features": features}

    def _tool_context_assembly(self, tool_results: Dict, **kwargs) -> Dict:
        """Assemble retrieved data into LLM-ready context."""
        context_parts = []
        for tool_name, result in tool_results.items():
            if result and isinstance(result, dict):
                context_parts.append(f"[{tool_name}]: {result}")
        return {
            "assembled_context": context_parts,
            "context_token_estimate": sum(len(str(p)) for p in context_parts) // 4,
            "sources_used": list(tool_results.keys()),
        }

    # ── Fallbacks ─────────────────────────────────────────────────────────

    def _fallback_cached_analytics(self, **kwargs) -> Dict:
        """Return cached/stale analytics when Pinot is unavailable."""
        return {
            "source": "cache_fallback",
            "note": "Using cached analytics — data may be 5-15 minutes stale",
            "metrics": {
                "users_at_risk": 25,
                "avg_churn_score": 0.55,
            },
        }

    def _fallback_keyword_search(self, **kwargs) -> Dict:
        """Fall back to keyword search when vector search fails."""
        return {
            "source": "keyword_fallback",
            "note": "Vector search unavailable — using keyword matching",
            "results": ["pattern_match_1", "pattern_match_2"],
        }

    # ── Orchestration ─────────────────────────────────────────────────────

    def orchestrate(self, query: str, intent: str = "general") -> ExecutionTrace:
        """
        Full orchestration pipeline:
        1. Plan tool calls based on intent
        2. Execute tools (parallel when independent)
        3. Assemble context
        4. Return execution trace
        """
        trace = ExecutionTrace(query=query)
        start = time.time()

        # Step 1: Plan tool calls
        tool_plan = self._plan_tools(intent)

        # Step 2: Execute tools
        tool_results = {}
        for tool_name, tool_kwargs in tool_plan:
            tool_kwargs["query"] = query
            tool_kwargs["intent"] = intent
            call = self.registry.execute(tool_name, **tool_kwargs)
            trace.tool_calls.append(call)
            if call.status in (ToolStatus.SUCCESS, ToolStatus.FALLBACK):
                tool_results[tool_name] = call.result

        # Step 3: Assemble context
        assembly_call = self.registry.execute(
            "context_assembly",
            tool_results=tool_results,
        )
        trace.tool_calls.append(assembly_call)

        if assembly_call.status == ToolStatus.SUCCESS:
            trace.context_assembled = assembly_call.result
            trace.status = "completed"
        else:
            trace.status = "partial"

        trace.total_latency_ms = (time.time() - start) * 1000
        self.traces.append(trace)
        return trace

    def _plan_tools(self, intent: str) -> List[tuple]:
        """
        Determine which tools to call and in what order.
        This is the agent's PLANNING step — not AI, just routing logic.
        """
        base_plan = [
            ("structured_retrieval", {}),
        ]

        # Add semantic retrieval for specific intents
        if intent in ("churn_analysis", "similar_users", "support_analysis", "general"):
            base_plan.append(("semantic_retrieval", {}))

        # Add feature lookup for user-specific queries
        if intent in ("health_check", "usage_analysis", "churn_analysis"):
            base_plan.append(("feature_lookup", {
                "user_ids": [f"user_{random.randint(1,200):04d}" for _ in range(5)]
            }))

        return base_plan

    # ── Observability ─────────────────────────────────────────────────────

    def get_metrics(self) -> Dict:
        if not self.traces:
            return {"total_orchestrations": 0}

        total = len(self.traces)
        successful = sum(1 for t in self.traces if t.status == "completed")
        total_tool_calls = sum(len(t.tool_calls) for t in self.traces)
        retries = sum(
            tc.retries for t in self.traces for tc in t.tool_calls
        )
        fallbacks = sum(
            1 for t in self.traces for tc in t.tool_calls
            if tc.status == ToolStatus.FALLBACK
        )
        avg_latency = sum(t.total_latency_ms for t in self.traces) / total

        # Per-tool stats
        tool_stats = {}
        for t in self.traces:
            for tc in t.tool_calls:
                if tc.tool_name not in tool_stats:
                    tool_stats[tc.tool_name] = {
                        "calls": 0, "successes": 0, "failures": 0,
                        "total_latency_ms": 0.0,
                    }
                stats = tool_stats[tc.tool_name]
                stats["calls"] += 1
                if tc.status in (ToolStatus.SUCCESS, ToolStatus.FALLBACK):
                    stats["successes"] += 1
                else:
                    stats["failures"] += 1
                stats["total_latency_ms"] += tc.latency_ms

        for name, stats in tool_stats.items():
            stats["avg_latency_ms"] = round(stats["total_latency_ms"] / max(stats["calls"], 1), 2)
            stats["success_rate"] = round(stats["successes"] / max(stats["calls"], 1), 3)

        return {
            "total_orchestrations": total,
            "success_rate": round(successful / total, 3),
            "total_tool_calls": total_tool_calls,
            "total_retries": retries,
            "total_fallbacks": fallbacks,
            "avg_latency_ms": round(avg_latency, 2),
            "tool_stats": tool_stats,
            "circuit_breaker_states": {
                name: cb.state.value
                for name, cb in self.registry.circuit_breakers.items()
            },
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("  AGENT ORCHESTRATOR — Tool Coordination & Reliability")
    print("=" * 70)

    orchestrator = AgentOrchestrator()

    queries = [
        ("Which enterprise users are at risk of churning?", "churn_analysis"),
        ("Show usage trends for the professional tier", "usage_analysis"),
        ("Find users with declining engagement patterns", "similar_users"),
        ("What's the revenue impact of recent cancellations?", "revenue_analysis"),
        ("Give me a health overview for user_0042", "health_check"),
    ]

    for query, intent in queries:
        print(f"\n{'─' * 60}")
        print(f"  Query  : {query}")
        print(f"  Intent : {intent}")
        print(f"{'─' * 60}")

        trace = orchestrator.orchestrate(query, intent)

        print(f"  Trace ID : {trace.trace_id}")
        print(f"  Status   : {trace.status}")
        print(f"  Latency  : {trace.total_latency_ms:.1f} ms")
        print(f"  Tools    :")
        for tc in trace.tool_calls:
            status_icon = "✓" if tc.status == ToolStatus.SUCCESS else "⚠" if tc.status == ToolStatus.FALLBACK else "✗"
            print(f"    {status_icon} {tc.tool_name:25s} → {tc.status.value:12s}  "
                  f"latency={tc.latency_ms:.1f}ms  retries={tc.retries}")

        if trace.context_assembled:
            ctx = trace.context_assembled
            print(f"  Context  : ~{ctx.get('context_token_estimate', 0)} tokens from "
                  f"{ctx.get('sources_used', [])}")

    # Metrics
    metrics = orchestrator.get_metrics()
    print(f"\n{'═' * 70}")
    print("  ORCHESTRATOR METRICS")
    print(f"{'═' * 70}")
    print(f"  Total Orchestrations : {metrics['total_orchestrations']}")
    print(f"  Success Rate         : {metrics['success_rate']:.1%}")
    print(f"  Total Tool Calls     : {metrics['total_tool_calls']}")
    print(f"  Total Retries        : {metrics['total_retries']}")
    print(f"  Total Fallbacks      : {metrics['total_fallbacks']}")
    print(f"  Avg Latency          : {metrics['avg_latency_ms']:.1f} ms")

    print(f"\n  Tool-Level Stats:")
    for name, stats in metrics.get("tool_stats", {}).items():
        print(f"    {name:25s} → calls={stats['calls']}  "
              f"success={stats['success_rate']:.0%}  "
              f"avg_lat={stats['avg_latency_ms']:.1f}ms")

    print(f"\n  Circuit Breakers:")
    for name, state in metrics.get("circuit_breaker_states", {}).items():
        icon = "🟢" if state == "closed" else "🔴" if state == "open" else "🟡"
        print(f"    {icon} {name:25s} → {state}")

    print("\n✓ Agent orchestration complete.")
