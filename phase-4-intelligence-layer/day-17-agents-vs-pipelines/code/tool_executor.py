"""
Tool Executor — Day 17: Agents vs Pipelines
=============================================
Defines and executes the tools available to the agent.

Each tool has:
  - A name and description (for LLM tool selection)
  - An input schema (validated before execution)
  - An output format (consistent for LLM consumption)
  - A timeout and retry policy

In production: tools are real API calls, SQL queries, vector searches.
Here they are simulated with realistic latencies and outputs.
"""

import time
import random
from dataclasses import dataclass
from typing import Any


# ── TOOL RESULT ───────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    tool_name:  str
    success:    bool
    output:     Any
    latency_ms: float
    error:      str | None = None


# ── SIMULATED DATA ────────────────────────────────────────────────────────────

PINOT_DATA = {
    "u_4821": {"errors": 5, "error_rate": 0.80, "intent": 0.82, "churn": True,  "plan": "free", "page": "/checkout"},
    "u_0012": {"errors": 0, "error_rate": 0.00, "intent": 0.30, "churn": False, "plan": "pro",  "page": "/docs"},
    "u_7734": {"errors": 2, "error_rate": 0.33, "intent": 0.40, "churn": True,  "plan": "free", "page": "/checkout"},
}

GATEWAY_STATUS = {
    "last_2h_errors": 847,
    "affected_users": 23,
    "status":         "degraded",
    "root_cause":     "payment gateway timeout — upstream provider issue",
}

VECTOR_DOCS = {
    "u_4821": [
        "User u_4821 hit 500 error on /checkout at 14:32. Payment gateway timeout.",
        "User u_4821 clicked Upgrade to Pro on /pricing. Intent: 0.82.",
        "Support ticket: checkout keeps failing with server error.",
    ],
    "u_7734": [
        "User u_7734 hit 500 error on /checkout.",
        "User u_7734 visited /pricing twice. Moderate intent.",
    ],
}

USER_PROFILES = {
    "u_4821": {"plan": "free", "segment": "at_risk", "ltv": 0,   "signup_days": 45},
    "u_0012": {"plan": "pro",  "segment": "active",  "ltv": 588, "signup_days": 180},
    "u_7734": {"plan": "free", "segment": "new",     "ltv": 0,   "signup_days": 12},
}

SIMILAR_CASES = [
    {"case_id": "case_001", "description": "Payment gateway outage 2025-11. 18 users affected. Proactive outreach recovered 15/18 (83%)."},
    {"case_id": "case_002", "description": "Checkout timeout 2025-08. 31 users affected. Discount offer recovered 24/31 (77%)."},
]


# ── TOOL DEFINITIONS ──────────────────────────────────────────────────────────

TOOL_REGISTRY = {
    "query_pinot": {
        "description": "Run SQL-style query against real-time analytics (Apache Pinot). Use for exact metrics, counts, rates, and aggregations.",
        "input_schema": {"user_id": "str (optional)", "query_type": "str", "time_h": "int"},
    },
    "search_vectors": {
        "description": "Semantic search over event history and support tickets. Use for behavioral context and similar past incidents.",
        "input_schema": {"query": "str", "user_id": "str (optional)", "top_k": "int"},
    },
    "get_user_profile": {
        "description": "Fetch user profile from feature store. Use to get plan, segment, LTV, and signup date.",
        "input_schema": {"user_id": "str"},
    },
    "check_system_status": {
        "description": "Check current system health metrics. Use when errors might be systemic rather than user-specific.",
        "input_schema": {"component": "str", "time_h": "int"},
    },
    "get_similar_cases": {
        "description": "Find similar historical incidents. Use to understand patterns and recovery strategies.",
        "input_schema": {"description": "str", "top_k": "int"},
    },
    "send_alert": {
        "description": "Send alert or notification to support team. Use only when immediate action is required.",
        "input_schema": {"user_ids": "list[str]", "message": "str", "priority": "str"},
    },
}


# ── TOOL IMPLEMENTATIONS ──────────────────────────────────────────────────────

def execute_tool(tool_name: str, args: dict) -> ToolResult:
    """
    Executes a tool by name with given arguments.
    Returns a ToolResult with output and metadata.
    """
    t0 = time.perf_counter()

    try:
        if tool_name == "query_pinot":
            output = _query_pinot(**args)
        elif tool_name == "search_vectors":
            output = _search_vectors(**args)
        elif tool_name == "get_user_profile":
            output = _get_user_profile(**args)
        elif tool_name == "check_system_status":
            output = _check_system_status(**args)
        elif tool_name == "get_similar_cases":
            output = _get_similar_cases(**args)
        elif tool_name == "send_alert":
            output = _send_alert(**args)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return ToolResult(tool_name=tool_name, success=True, output=output, latency_ms=latency_ms)

    except Exception as e:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return ToolResult(tool_name=tool_name, success=False, output=None,
                          latency_ms=latency_ms, error=str(e))


def _query_pinot(user_id: str = None, query_type: str = "user_metrics", time_h: int = 24) -> dict:
    time.sleep(0.068)
    if user_id:
        return PINOT_DATA.get(user_id, {"error": "user not found"})
    if query_type == "gateway_errors":
        return GATEWAY_STATUS
    # Return all users with errors
    return {uid: d for uid, d in PINOT_DATA.items() if d["errors"] > 0}


def _search_vectors(query: str, user_id: str = None, top_k: int = 3) -> list[dict]:
    time.sleep(0.050)
    if user_id:
        docs = VECTOR_DOCS.get(user_id, [])
    else:
        docs = [d for docs in VECTOR_DOCS.values() for d in docs]
    return [{"text": d, "score": round(0.9 - i * 0.05, 2)} for i, d in enumerate(docs[:top_k])]


def _get_user_profile(user_id: str) -> dict:
    time.sleep(0.010)
    return USER_PROFILES.get(user_id, {"error": "user not found"})


def _check_system_status(component: str = "payment_gateway", time_h: int = 2) -> dict:
    time.sleep(0.030)
    if "gateway" in component.lower() or "payment" in component.lower():
        return GATEWAY_STATUS
    return {"status": "healthy", "errors": 0}


def _get_similar_cases(description: str, top_k: int = 3) -> list[dict]:
    time.sleep(0.040)
    return SIMILAR_CASES[:top_k]


def _send_alert(user_ids: list, message: str, priority: str = "medium") -> dict:
    time.sleep(0.100)
    return {"alert_id": f"alert_{int(time.time())}", "sent": True,
            "recipients": len(user_ids), "priority": priority}


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("TOOL EXECUTOR — Available agent tools")
    print("=" * 65)

    print(f"\n[TOOL REGISTRY]  {len(TOOL_REGISTRY)} tools available:")
    for name, meta in TOOL_REGISTRY.items():
        print(f"  {name:25s} — {meta['description'][:50]}...")

    print(f"\n[TOOL EXECUTION DEMO]")
    test_calls = [
        ("query_pinot",       {"user_id": "u_4821", "query_type": "user_metrics", "time_h": 2}),
        ("search_vectors",    {"query": "checkout errors", "user_id": "u_4821", "top_k": 2}),
        ("get_user_profile",  {"user_id": "u_4821"}),
        ("check_system_status",{"component": "payment_gateway", "time_h": 2}),
        ("get_similar_cases", {"description": "payment gateway outage", "top_k": 2}),
    ]

    for tool_name, args in test_calls:
        result = execute_tool(tool_name, args)
        status = "✅" if result.success else "❌"
        print(f"\n  {status} {tool_name}({args})")
        print(f"     Latency: {result.latency_ms}ms")
        if result.success:
            output_str = str(result.output)
            print(f"     Output:  {output_str[:80]}{'...' if len(output_str)>80 else ''}")
        else:
            print(f"     Error:   {result.error}")


if __name__ == "__main__":
    run()
