"""
Tool Registry — Day 18: Tooling for Agents
===========================================
Defines all tools available to agents, their schemas, permissions,
and execution policies (timeout, retry, fallback).

The registry is the single source of truth for:
  - What tools exist
  - What inputs they accept
  - Who can call them
  - How to handle failures

In production: tool definitions are loaded from a config file or
service registry. The LLM receives tool descriptions to decide which to call.
"""

from dataclasses import dataclass, field
from typing import Any


# ── TOOL DEFINITION ───────────────────────────────────────────────────────────

@dataclass
class ToolDefinition:
    name:           str
    description:    str           # shown to LLM for tool selection
    input_schema:   dict          # required and optional fields
    output_schema:  dict          # what the tool returns
    timeout_ms:     int           # hard timeout per call
    max_retries:    int           # retry attempts on failure
    tool_type:      str           # "read" or "write"
    allowed_roles:  list[str]     # which roles can call this tool
    tags:           list[str] = field(default_factory=list)


# ── TOOL REGISTRY ─────────────────────────────────────────────────────────────

TOOLS: dict[str, ToolDefinition] = {

    "query_pinot": ToolDefinition(
        name="query_pinot",
        description=(
            "Run SQL against Apache Pinot for real-time analytics. "
            "Use for exact counts, rates, aggregations, and time-window queries. "
            "Returns structured rows. Latency: ~68ms P99."
        ),
        input_schema={
            "required": ["sql"],
            "optional": ["timeout_ms"],
            "types":    {"sql": "string", "timeout_ms": "int"},
        },
        output_schema={"rows": "list[dict]", "latency_ms": "int", "row_count": "int"},
        timeout_ms=2000,
        max_retries=2,
        tool_type="read",
        allowed_roles=["support_agent", "on_call_engineer", "analyst", "admin"],
        tags=["analytics", "structured", "real-time"],
    ),

    "search_vectors": ToolDefinition(
        name="search_vectors",
        description=(
            "Semantic search over event history and support tickets. "
            "Use for behavioral context, similar past incidents, and unstructured text. "
            "Returns top-k most similar documents. Latency: ~50ms P99."
        ),
        input_schema={
            "required": ["query"],
            "optional": ["user_id", "top_k", "min_score"],
            "types":    {"query": "string", "user_id": "string", "top_k": "int", "min_score": "float"},
        },
        output_schema={"results": "list[{text, score, metadata}]"},
        timeout_ms=1000,
        max_retries=2,
        tool_type="read",
        allowed_roles=["support_agent", "on_call_engineer", "analyst", "admin"],
        tags=["semantic", "retrieval", "context"],
    ),

    "get_user_profile": ToolDefinition(
        name="get_user_profile",
        description=(
            "Fetch user profile from feature store. "
            "Returns plan, segment, LTV, signup date, and current risk flags."
        ),
        input_schema={
            "required": ["user_id"],
            "optional": [],
            "types":    {"user_id": "string"},
        },
        output_schema={"plan": "string", "segment": "string", "ltv": "float", "churn_risk": "bool"},
        timeout_ms=500,
        max_retries=3,
        tool_type="read",
        allowed_roles=["support_agent", "on_call_engineer", "analyst", "admin"],
        tags=["profile", "user", "features"],
    ),

    "query_logs": ToolDefinition(
        name="query_logs",
        description=(
            "Search application logs for error patterns and root cause signals. "
            "Use when errors might be systemic or when you need stack traces."
        ),
        input_schema={
            "required": ["query"],
            "optional": ["time_range_h", "level", "limit"],
            "types":    {"query": "string", "time_range_h": "int", "level": "string", "limit": "int"},
        },
        output_schema={"log_lines": "list[string]", "count": "int", "first_occurrence": "string"},
        timeout_ms=3000,
        max_retries=1,
        tool_type="read",
        allowed_roles=["on_call_engineer", "admin"],
        tags=["logs", "debugging", "observability"],
    ),

    "query_monitoring": ToolDefinition(
        name="query_monitoring",
        description=(
            "Query system metrics from monitoring (Prometheus/Grafana). "
            "Use to check error rates, latency percentiles, and throughput."
        ),
        input_schema={
            "required": ["metric"],
            "optional": ["time_range_h", "step_s"],
            "types":    {"metric": "string", "time_range_h": "int", "step_s": "int"},
        },
        output_schema={"values": "list[{ts, value}]", "current": "float", "baseline": "float"},
        timeout_ms=2000,
        max_retries=2,
        tool_type="read",
        allowed_roles=["on_call_engineer", "analyst", "admin"],
        tags=["metrics", "monitoring", "observability"],
    ),

    "send_alert": ToolDefinition(
        name="send_alert",
        description=(
            "Send alert to support team via PagerDuty or Slack. "
            "Use only when immediate human action is required. "
            "Requires explicit confirmation for high-priority alerts."
        ),
        input_schema={
            "required": ["message", "priority"],
            "optional": ["user_ids", "channel"],
            "types":    {"message": "string", "priority": "string", "user_ids": "list", "channel": "string"},
        },
        output_schema={"alert_id": "string", "sent": "bool", "recipients": "int"},
        timeout_ms=5000,
        max_retries=3,
        tool_type="write",
        allowed_roles=["on_call_engineer", "admin"],
        tags=["alerting", "notification", "write"],
    ),

    "trigger_airflow_dag": ToolDefinition(
        name="trigger_airflow_dag",
        description=(
            "Trigger an Apache Airflow DAG for batch processing or failover. "
            "Use for payment gateway failover, data reprocessing, or scheduled tasks."
        ),
        input_schema={
            "required": ["dag_id"],
            "optional": ["conf", "dry_run"],
            "types":    {"dag_id": "string", "conf": "dict", "dry_run": "bool"},
        },
        output_schema={"run_id": "string", "status": "string", "dag_id": "string"},
        timeout_ms=5000,
        max_retries=1,
        tool_type="write",
        allowed_roles=["on_call_engineer", "admin"],
        tags=["workflow", "airflow", "write"],
    ),
}


# ── VALIDATION ────────────────────────────────────────────────────────────────

def validate_tool_call(tool_name: str, args: dict, role: str = "support_agent") -> tuple[bool, str]:
    """
    Validates a tool call before execution.
    Returns (is_valid, error_message).
    """
    # Check tool exists
    if tool_name not in TOOLS:
        return False, f"Unknown tool: '{tool_name}'. Available: {list(TOOLS.keys())}"

    tool = TOOLS[tool_name]

    # Check permissions
    if role not in tool.allowed_roles and "admin" not in [role]:
        return False, f"Role '{role}' does not have access to tool '{tool_name}'"

    # Check required fields
    schema = tool.input_schema
    for field in schema.get("required", []):
        if field not in args:
            return False, f"Missing required field '{field}' for tool '{tool_name}'"

    # Check types (basic)
    types = schema.get("types", {})
    for field, expected_type in types.items():
        if field in args and args[field] is not None:
            if expected_type == "string" and not isinstance(args[field], str):
                return False, f"Field '{field}' must be string, got {type(args[field]).__name__}"
            if expected_type == "int" and not isinstance(args[field], int):
                return False, f"Field '{field}' must be int, got {type(args[field]).__name__}"

    return True, ""


def get_tool_descriptions() -> list[dict]:
    """Returns tool descriptions for LLM tool selection."""
    return [
        {
            "name":        t.name,
            "description": t.description,
            "type":        t.tool_type,
            "tags":        t.tags,
        }
        for t in TOOLS.values()
    ]


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("TOOL REGISTRY — Available agent tools")
    print("=" * 65)

    print(f"\n[REGISTRY]  {len(TOOLS)} tools defined\n")
    for name, tool in TOOLS.items():
        print(f"  {name}")
        print(f"    Type:     {tool.tool_type}")
        print(f"    Timeout:  {tool.timeout_ms}ms | Retries: {tool.max_retries}")
        print(f"    Roles:    {', '.join(tool.allowed_roles)}")
        print(f"    Tags:     {', '.join(tool.tags)}")
        print()

    print(f"[VALIDATION TESTS]")
    test_cases = [
        ("query_pinot",    {"sql": "SELECT * FROM events"},          "support_agent",    True),
        ("query_pinot",    {},                                        "support_agent",    False),  # missing sql
        ("query_logs",     {"query": "error"},                       "support_agent",    False),  # no permission
        ("query_logs",     {"query": "error"},                       "on_call_engineer", True),
        ("send_alert",     {"message": "test", "priority": "high"},  "support_agent",    False),  # no permission
        ("unknown_tool",   {},                                        "admin",            False),  # doesn't exist
    ]

    for tool_name, args, role, expected in test_cases:
        valid, msg = validate_tool_call(tool_name, args, role)
        status = "✅" if valid == expected else "❌ UNEXPECTED"
        result = "VALID" if valid else f"INVALID: {msg}"
        print(f"  {status} {tool_name}({list(args.keys())}) as {role}: {result}")


if __name__ == "__main__":
    run()
