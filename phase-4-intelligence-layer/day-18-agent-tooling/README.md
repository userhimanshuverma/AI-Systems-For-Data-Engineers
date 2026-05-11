# Day 18 — Tooling for Agents

> **Phase 4 — Intelligence Layer**
> An agent without tools is just an LLM. Tools are what make agents useful in production data systems. Designing them well is the difference between a reliable system and an unpredictable one.

---

## Introduction

On Day 17 we established that agents are adaptive orchestrators — they decide which tools to call based on what they find. But we glossed over the tools themselves.

In production, tools are not simple function calls. They are interfaces to real infrastructure: Apache Pinot, vector databases, REST APIs, logging systems, monitoring platforms. Each has its own failure modes, latency characteristics, and security requirements.

Designing tools that agents can call **reliably, safely, and efficiently** is a distinct engineering discipline. This day covers it.

---

## What is Tooling for Agents?

Agent tooling is the set of **well-defined, validated interfaces** that an agent can call to interact with external systems.

A tool has four components:

### 1. Database Access
The agent queries structured data stores for facts, metrics, and aggregations.
```python
tool = {
    "name":        "query_pinot",
    "description": "Run SQL against Apache Pinot for real-time analytics",
    "input":       {"sql": "string", "timeout_ms": "int"},
    "output":      {"rows": "list[dict]", "latency_ms": "int"},
}
```

### 2. API Execution
The agent calls external services: alerting systems, CRM platforms, payment processors.
```python
tool = {
    "name":        "send_slack_alert",
    "description": "Send alert to Slack channel",
    "input":       {"channel": "string", "message": "string", "priority": "string"},
    "output":      {"sent": "bool", "message_id": "string"},
}
```

### 3. Retrieval Systems
The agent searches vector databases for semantic context.
```python
tool = {
    "name":        "search_vectors",
    "description": "Semantic search over event history",
    "input":       {"query": "string", "user_id": "string", "top_k": "int"},
    "output":      {"results": "list[{text, score}]"},
}
```

### 4. Workflow Triggering
The agent triggers downstream workflows: Airflow DAGs, notification pipelines, escalation flows.
```python
tool = {
    "name":        "trigger_airflow_dag",
    "description": "Trigger an Airflow DAG for batch processing",
    "input":       {"dag_id": "string", "conf": "dict"},
    "output":      {"run_id": "string", "status": "string"},
}
```

### 5. Observability Interaction
The agent reads logs, metrics, and traces to understand system state.
```python
tool = {
    "name":        "query_logs",
    "description": "Search application logs for error patterns",
    "input":       {"query": "string", "time_range_h": "int", "level": "string"},
    "output":      {"log_lines": "list[string]", "count": "int"},
}
```

---

## Types of Tools Agents Use

### Apache Pinot (Real-Time Analytics)
**Purpose:** Answer "how many", "what rate", "which users" questions with sub-second latency.

```sql
-- Agent calls this to get current error metrics
SELECT user_id, error_rate, churn_risk
FROM user_events_realtime
WHERE plan = 'free' AND churn_risk = true
AND ts > ago('1h')
ORDER BY error_rate DESC LIMIT 10
```

**Tool contract:**
- Input: SQL string + timeout
- Output: rows as list of dicts
- Latency: ~68ms P99
- Failure modes: query timeout, schema mismatch, broker unavailable

### Vector DBs (Semantic Retrieval)
**Purpose:** Find semantically similar events, support tickets, and behavioral patterns.

```python
# Agent calls this to get behavioral context
results = qdrant.search(
    collection="user_events",
    query_vector=embed("checkout errors payment failure"),
    query_filter={"user_id": "u_4821"},
    limit=4
)
```

**Tool contract:**
- Input: query text + metadata filter + top_k
- Output: list of {text, score, metadata}
- Latency: ~50ms P99
- Failure modes: embedding model unavailable, index stale, collection not found

### REST APIs (External Services)
**Purpose:** Trigger actions in external systems — alerts, CRM updates, payment retries.

```python
# Agent calls this to send a support alert
response = requests.post(
    "https://api.pagerduty.com/incidents",
    json={"title": "Checkout errors for 23 users", "urgency": "high"},
    headers={"Authorization": f"Token {API_KEY}"},
    timeout=5,
)
```

**Tool contract:**
- Input: endpoint + payload
- Output: response status + body
- Latency: 100–500ms (external)
- Failure modes: network timeout, auth failure, rate limiting, 5xx errors

### Logging Systems (Observability)
**Purpose:** Read application logs to understand error patterns and root causes.

```python
# Agent calls this to find error patterns
logs = elasticsearch.search(
    index="app-logs-*",
    body={"query": {"match": {"message": "payment gateway"}},
          "filter": {"range": {"@timestamp": {"gte": "now-2h"}}}}
)
```

**Tool contract:**
- Input: search query + time range + log level
- Output: matching log lines + count
- Latency: 50–200ms
- Failure modes: index not found, query timeout, cluster unavailable

### Monitoring Systems (Metrics)
**Purpose:** Read system metrics — error rates, latency percentiles, throughput.

```python
# Agent calls this to check system health
metrics = prometheus.query(
    'rate(http_requests_total{status="500"}[5m])'
)
```

**Tool contract:**
- Input: PromQL expression + time range
- Output: metric values + timestamps
- Latency: 20–100ms
- Failure modes: query syntax error, metric not found, scrape lag

---

## Tool Execution Flow

```
User Query
    │
    ▼
Query Understanding Layer (Day 16)
    │ intent, entities, retrieval plan
    ▼
Agent Controller (Day 17)
    │ decides which tool to call
    ▼
Tool Registry
    │ validates tool name + input schema
    ▼
Tool Executor
    │ calls the actual tool with timeout + retry
    ├── Success → return output to agent
    └── Failure → return error + fallback
    │
    ▼
Agent Controller
    │ observes result, decides next tool
    ▼
Context Merger
    │ combines all tool outputs
    ▼
LLM
    │ reasons over assembled context
    ▼
Output Validator
    │ validates response structure + confidence
    ▼
Final Response
```

---

## Infrastructure-Aware Reasoning

The key insight about agent tooling: **agents don't just generate responses — they coordinate systems**.

A well-designed agent with good tooling can:
1. Query Pinot for current error metrics
2. Search vectors for behavioral context
3. Query logs for root cause signals
4. Check monitoring for system health
5. Trigger an Airflow DAG to reprocess affected data
6. Send a PagerDuty alert to the on-call engineer
7. Update the CRM with the investigation findings

This is infrastructure coordination, not text generation. The LLM is the decision-making layer. The tools are the actuators.

**Critical principle:** The agent should never have more tool access than it needs for the task. Principle of least privilege applies to agent tools just as it does to service accounts.

---

## Reliability Challenges

### API Failures
External APIs fail. Networks partition. Services go down.

**Solution:** Every tool call must have:
- A timeout (never wait indefinitely)
- A retry policy (exponential backoff, max 3 retries)
- A fallback (what to return if the tool fails)

```python
def execute_with_retry(tool_fn, args, max_retries=3, timeout_ms=5000):
    for attempt in range(max_retries):
        try:
            return tool_fn(args, timeout=timeout_ms/1000)
        except TimeoutError:
            if attempt == max_retries - 1:
                return {"error": "timeout", "fallback": True}
            time.sleep(2 ** attempt * 0.1)  # exponential backoff
```

### Hallucinated Tool Calls
The LLM may call a tool with incorrect arguments, or call a tool that doesn't exist.

**Solution:** Validate every tool call before execution:
```python
def validate_tool_call(tool_name: str, args: dict) -> tuple[bool, str]:
    if tool_name not in TOOL_REGISTRY:
        return False, f"Unknown tool: {tool_name}"
    schema = TOOL_REGISTRY[tool_name]["input_schema"]
    for required_field in schema.get("required", []):
        if required_field not in args:
            return False, f"Missing required field: {required_field}"
    return True, ""
```

### Timeout Handling
A slow tool blocks the entire agent. Set hard timeouts per tool type:

| Tool type | Timeout |
|-----------|---------|
| Pinot SQL | 2 seconds |
| Vector search | 1 second |
| REST API | 5 seconds |
| Log search | 3 seconds |
| Monitoring | 2 seconds |

### Permissions and Security
Agents should not have unrestricted access to all tools.

**Solution:** Role-based tool access:
```python
TOOL_PERMISSIONS = {
    "support_agent":  ["query_pinot", "search_vectors", "get_user_profile"],
    "on_call_engineer": ["query_pinot", "search_vectors", "query_logs", "send_alert"],
    "admin":          ["*"],  # all tools
}
```

---

## Real-World Example — Root Cause Analysis Workflow

**Task:** *"The checkout error rate spiked 10 minutes ago. What's happening?"*

### Step 1: Query Metrics (Pinot)
```
Tool: query_pinot
SQL:  SELECT COUNT(*) as errors, AVG(error_rate) as avg_rate
      FROM user_events_realtime
      WHERE event_type='system.server_error' AND ts > ago('10m')
Result: {errors: 847, avg_rate: 0.82, affected_users: 23}
```

### Step 2: Inspect Logs (Log Search)
```
Tool: query_logs
Query: "payment gateway timeout"
Time:  last 10 minutes
Result: 847 log lines matching "payment gateway timeout"
        First occurrence: 10 minutes ago
        Pattern: all from same upstream endpoint
```

### Step 3: Retrieve Patterns (Vector DB)
```
Tool: search_vectors
Query: "payment gateway outage recovery"
Result: [
  "2025-11: Gateway outage. Resolved by switching to backup endpoint.",
  "2025-08: Timeout spike. Root cause: upstream rate limiting.",
]
```

### Step 4: Check System Status (Monitoring)
```
Tool: query_monitoring
Metric: rate(payment_gateway_errors[5m])
Result: 847 errors/min (baseline: 2/min) — 400x spike
```

### Step 5: Trigger Response (Workflow)
```
Tool: trigger_airflow_dag
DAG:  payment_gateway_failover
Conf: {switch_to_backup: true, notify_team: true}
Result: {run_id: "dag_run_001", status: "triggered"}
```

### Agent Final Response
```json
{
  "summary": "Payment gateway outage. 847 errors in last 10 minutes (400x baseline). Root cause: upstream provider timeout. Historical pattern: switch to backup endpoint resolves within 2 minutes. Failover DAG triggered.",
  "action": "monitor_failover_progress",
  "confidence": 0.96,
  "evidence": [
    "847 errors in 10 minutes (Pinot)",
    "847 log lines: 'payment gateway timeout' (Logs)",
    "Historical: backup endpoint resolved similar outage (Vector DB)",
    "Failover DAG triggered (Airflow)"
  ]
}
```

---

## Common Mistakes

### 1. Unrestricted Tool Access
```
❌ Give agent access to all tools including send_email, delete_records, deploy_code
✅ Principle of least privilege: only the tools needed for the task
   A support agent doesn't need to trigger deployments
```

### 2. No Validation Layer
```
❌ Execute tool calls directly from LLM output without validation
✅ Validate tool name, input schema, and argument types before execution
   LLMs hallucinate tool names and argument formats
```

### 3. Ignoring Observability
```
❌ Tool calls are black boxes — no logging, no metrics
✅ Log every tool call: name, args, result, latency, success/failure
   You cannot debug an agent you cannot observe
```

### 4. No Timeout or Retry
```
❌ Tool calls with no timeout — agent hangs on slow external API
✅ Every tool has a timeout. Slow tools get retried with backoff.
   A hanging tool call is a production incident.
```

### 5. Mutable State Without Confirmation
```
❌ Agent can send alerts, trigger DAGs, update records without human confirmation
✅ Separate read tools (safe, auto-execute) from write tools (require confirmation)
   Or implement a dry-run mode for write tools
```

---

## Key Takeaways

1. **Tools are interfaces to infrastructure.** They are not simple functions — they are contracts with real systems that have failure modes, latency, and security requirements.

2. **Every tool needs a timeout, retry policy, and fallback.** External systems fail. Design for it.

3. **Validate every tool call before execution.** LLMs hallucinate tool names and argument formats. A validation layer prevents bad calls from reaching production systems.

4. **Principle of least privilege.** Agents should only have access to the tools they need. Role-based tool access prevents accidental or malicious misuse.

5. **Observability is not optional.** Log every tool call with name, args, result, latency, and success/failure. You cannot debug what you cannot observe.

6. **Separate read tools from write tools.** Read tools (Pinot queries, vector search) are safe to auto-execute. Write tools (send alerts, trigger DAGs, update records) should require explicit confirmation or have a dry-run mode.

---

## What's Next

**Day 19** — Decision Systems: how agents and pipelines combine to make automated decisions at scale.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
