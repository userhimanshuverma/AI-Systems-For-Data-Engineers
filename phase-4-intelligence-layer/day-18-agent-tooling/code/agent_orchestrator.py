"""
Agent Orchestrator — Day 18: Tooling for Agents
=================================================
Orchestrates tool calls for the agent, combining:
  - Tool registry (validation + permissions)
  - Pinot tool (real-time analytics)
  - API tools (alerts, DAGs, logs, monitoring)
  - Observability (logging every tool call)

This is the production-grade tool execution layer.
"""

import time
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from tool_registry import validate_tool_call, TOOLS
from pinot_tool    import execute_pinot_query
from api_tool      import send_alert, trigger_airflow_dag, query_logs, query_monitoring

import math
import random


# ── MOCK VECTOR SEARCH ────────────────────────────────────────────────────────

def mock_embed(text: str, dim: int = 8) -> list[float]:
    random.seed(abs(hash(text)) % (2**32))
    v = [random.gauss(0, 1) for _ in range(dim)]
    n = math.sqrt(sum(x**2 for x in v))
    return [x/n for x in v]

VECTOR_DOCS = [
    {"text": "Payment gateway outage 2025-11. Resolved by switching to backup endpoint. Recovery: 2 min.", "score": 0.91},
    {"text": "User u_4821 hit 500 error on /checkout. Payment gateway timeout.", "score": 0.87},
    {"text": "Checkout timeout spike 2025-08. Root cause: upstream rate limiting.", "score": 0.82},
    {"text": "User u_4821 clicked Upgrade to Pro. Intent: 0.82.", "score": 0.71},
]

def search_vectors(query: str, user_id: str = None, top_k: int = 3) -> list[dict]:
    time.sleep(0.050)
    docs = VECTOR_DOCS if not user_id else [d for d in VECTOR_DOCS if user_id in d["text"] or "gateway" in d["text"]]
    return docs[:top_k]


# ── TOOL CALL LOG ─────────────────────────────────────────────────────────────

class ToolCallLog:
    """Records all tool calls for observability."""
    def __init__(self):
        self._calls: list[dict] = []

    def record(self, tool_name: str, args: dict, result: dict,
               latency_ms: float, success: bool, error: str = None) -> None:
        self._calls.append({
            "tool":       tool_name,
            "args":       {k: str(v)[:30] for k, v in args.items()},
            "success":    success,
            "latency_ms": latency_ms,
            "error":      error,
        })

    def summary(self) -> dict:
        total    = len(self._calls)
        success  = sum(1 for c in self._calls if c["success"])
        avg_lat  = sum(c["latency_ms"] for c in self._calls) / max(total, 1)
        return {
            "total_calls":    total,
            "success_rate":   f"{success/max(total,1):.0%}",
            "avg_latency_ms": round(avg_lat, 1),
            "tools_used":     list(set(c["tool"] for c in self._calls)),
        }

    def print_log(self) -> None:
        print(f"\n  [TOOL CALL LOG]  {len(self._calls)} calls recorded:")
        for c in self._calls:
            status = "✅" if c["success"] else "❌"
            print(f"    {status} {c['tool']:25s} {c['latency_ms']:6.1f}ms"
                  + (f"  ERROR: {c['error']}" if c["error"] else ""))


# ── ORCHESTRATOR ──────────────────────────────────────────────────────────────

class AgentOrchestrator:
    """
    Executes tool calls on behalf of the agent.
    Handles validation, execution, retry, and observability.
    """
    def __init__(self, role: str = "on_call_engineer"):
        self.role = role
        self.log  = ToolCallLog()

    def execute(self, tool_name: str, args: dict) -> dict:
        """
        Validates and executes a tool call.
        Returns a standardized result dict.
        """
        t0 = time.perf_counter()

        # Step 1: Validate
        valid, error_msg = validate_tool_call(tool_name, args, self.role)
        if not valid:
            self.log.record(tool_name, args, {}, 0, False, error_msg)
            return {"success": False, "error": error_msg, "tool": tool_name}

        # Step 2: Execute
        try:
            result = self._dispatch(tool_name, args)
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            self.log.record(tool_name, args, result, latency_ms, True)
            return {"success": True, "output": result, "tool": tool_name, "latency_ms": latency_ms}

        except Exception as e:
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            self.log.record(tool_name, args, {}, latency_ms, False, str(e))
            return {"success": False, "error": str(e), "tool": tool_name, "latency_ms": latency_ms}

    def _dispatch(self, tool_name: str, args: dict) -> dict:
        """Routes tool call to the correct implementation."""
        if tool_name == "query_pinot":
            r = execute_pinot_query(args["sql"], args.get("timeout_ms", 2000))
            return {"rows": r.rows, "row_count": r.row_count, "latency_ms": r.latency_ms}

        elif tool_name == "search_vectors":
            results = search_vectors(args["query"], args.get("user_id"), args.get("top_k", 3))
            return {"results": results}

        elif tool_name == "get_user_profile":
            profiles = {
                "u_4821": {"plan":"free","segment":"at_risk","ltv":0,"churn_risk":True},
                "u_0012": {"plan":"pro", "segment":"active", "ltv":588,"churn_risk":False},
            }
            return profiles.get(args["user_id"], {"error": "not found"})

        elif tool_name == "query_logs":
            r = query_logs(args["query"], args.get("time_range_h", 1),
                           args.get("level", "ERROR"), args.get("limit", 10))
            return r.output

        elif tool_name == "query_monitoring":
            r = query_monitoring(args["metric"], args.get("time_range_h", 1))
            return r.output

        elif tool_name == "send_alert":
            r = send_alert(args["message"], args.get("priority","medium"),
                           args.get("user_ids"), args.get("channel","support-alerts"),
                           dry_run=args.get("dry_run", True))  # default dry_run=True for safety
            return r.output

        elif tool_name == "trigger_airflow_dag":
            r = trigger_airflow_dag(args["dag_id"], args.get("conf"),
                                    dry_run=args.get("dry_run", True))
            return r.output

        else:
            raise ValueError(f"No implementation for tool: {tool_name}")


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("AGENT ORCHESTRATOR — Tool execution with validation + observability")
    print("=" * 65)

    orch = AgentOrchestrator(role="on_call_engineer")

    tool_calls = [
        ("query_pinot",      {"sql": "SELECT user_id, error_rate FROM user_events_realtime WHERE churn_risk=true LIMIT 5"}),
        ("search_vectors",   {"query": "payment gateway timeout", "top_k": 3}),
        ("query_logs",       {"query": "payment gateway timeout", "time_range_h": 1}),
        ("query_monitoring", {"metric": "payment_gateway_error_rate"}),
        ("send_alert",       {"message": "Gateway outage: 847 errors", "priority": "high", "dry_run": True}),
        ("trigger_airflow_dag", {"dag_id": "payment_gateway_failover", "dry_run": True}),
        # Invalid calls (to show validation)
        ("query_pinot",      {}),                          # missing sql
        ("unknown_tool",     {"arg": "value"}),            # doesn't exist
    ]

    print(f"\n  Executing {len(tool_calls)} tool calls as role='{orch.role}'\n")

    for tool_name, args in tool_calls:
        result = orch.execute(tool_name, args)
        status = "✅" if result["success"] else "❌"
        print(f"  {status} {tool_name}")
        if result["success"]:
            output = result["output"]
            if isinstance(output, dict):
                preview = str(output)[:70]
            else:
                preview = str(output)[:70]
            print(f"     {preview}{'...' if len(str(output))>70 else ''}")
        else:
            print(f"     Error: {result['error']}")

    orch.log.print_log()
    print(f"\n  Summary: {orch.log.summary()}")


if __name__ == "__main__":
    run()
