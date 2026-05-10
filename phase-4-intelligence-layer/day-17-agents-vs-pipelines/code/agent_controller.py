"""
Agent Controller — Day 17: Agents vs Pipelines
================================================
Simulates an LLM-driven agent that dynamically selects tools
based on what it finds at each step.

The agent:
  1. Receives a task and available tools
  2. Decides which tool to call (mock LLM decision)
  3. Executes the tool
  4. Observes the result
  5. Decides what to do next
  6. Repeats until done or max steps reached

Key difference from pipeline: the execution path is NOT predetermined.
The agent discovers the payment gateway outage by dynamically querying
for it — something the pipeline would never do.
"""

import time
from dataclasses import dataclass, field
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from tool_executor import execute_tool, TOOL_REGISTRY, ToolResult


# ── AGENT STATE ───────────────────────────────────────────────────────────────

@dataclass
class AgentStep:
    step_num:   int
    tool_name:  str
    tool_args:  dict
    result:     ToolResult
    reasoning:  str   # why the agent chose this tool


@dataclass
class AgentResult:
    task:        str
    steps:       list[AgentStep] = field(default_factory=list)
    final_answer:dict            = field(default_factory=dict)
    total_ms:    float           = 0.0
    stopped_by:  str             = "answer"  # "answer", "max_steps", "error"


# ── MOCK LLM DECISION ENGINE ──────────────────────────────────────────────────
# In production: replace with actual LLM call using tool_use / function_calling API
# e.g., openai.chat.completions.create(tools=TOOL_REGISTRY, ...)

def mock_llm_decide(task: str, history: list[AgentStep]) -> dict | None:
    """
    Simulates LLM tool selection based on task and history.
    Returns: {"tool": name, "args": dict, "reasoning": str}
    or None if the agent should generate a final answer.

    In production:
        response = openai.chat.completions.create(
            model="gpt-4o",
            tools=[...],  # tool schemas
            messages=[
                {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                {"role": "user",   "content": task},
                *[format_step(s) for s in history],
            ]
        )
        tool_call = response.choices[0].message.tool_calls[0]
        return {"tool": tool_call.function.name, "args": json.loads(tool_call.function.arguments)}
    """
    step_num = len(history)

    # Extract context from history
    found_errors    = any(s.tool_name == "query_pinot" and
                          isinstance(s.result.output, dict) and
                          s.result.output.get("errors", 0) > 0
                          for s in history)
    found_gateway   = any(s.tool_name == "check_system_status" for s in history)
    found_profile   = any(s.tool_name == "get_user_profile" for s in history)
    found_vectors   = any(s.tool_name == "search_vectors" for s in history)
    found_similar   = any(s.tool_name == "get_similar_cases" for s in history)
    gateway_degraded = any(
        s.tool_name == "check_system_status" and
        isinstance(s.result.output, dict) and
        s.result.output.get("status") == "degraded"
        for s in history
    )

    # Extract user_id from task
    import re
    uid_match = re.search(r"u_\d{4}", task)
    user_id   = uid_match.group(0) if uid_match else "u_4821"

    # Step 0: Always start with user metrics
    if step_num == 0:
        return {
            "tool": "query_pinot",
            "args": {"user_id": user_id, "query_type": "user_metrics", "time_h": 2},
            "reasoning": f"Start by getting current metrics for {user_id}",
        }

    # Step 1: If errors found, get behavioral context
    if step_num == 1 and found_errors and not found_vectors:
        return {
            "tool": "search_vectors",
            "args": {"query": f"checkout errors {user_id}", "user_id": user_id, "top_k": 3},
            "reasoning": "Errors found — get behavioral context from vector store",
        }

    # Step 2: If vectors mention gateway/payment, check system status
    if step_num == 2 and found_vectors and not found_gateway:
        vector_texts = []
        for s in history:
            if s.tool_name == "search_vectors" and s.result.success:
                vector_texts = [r["text"] for r in s.result.output]
        if any("gateway" in t.lower() or "payment" in t.lower() for t in vector_texts):
            return {
                "tool": "check_system_status",
                "args": {"component": "payment_gateway", "time_h": 2},
                "reasoning": "Vector context mentions payment gateway — check if systemic",
            }

    # Step 3: If gateway is degraded, find similar cases
    if step_num == 3 and gateway_degraded and not found_similar:
        return {
            "tool": "get_similar_cases",
            "args": {"description": "payment gateway outage churn", "top_k": 2},
            "reasoning": "Gateway outage confirmed — find similar historical cases for recovery strategy",
        }

    # Step 4+: Enough context, generate answer
    return None


def mock_llm_answer(task: str, steps: list[AgentStep]) -> dict:
    """Generates final answer from accumulated tool results."""
    time.sleep(0.200)  # simulate LLM call

    # Collect all findings
    user_metrics   = None
    vector_context = []
    gateway_status = None
    similar_cases  = []

    for step in steps:
        if step.tool_name == "query_pinot" and step.result.success:
            if isinstance(step.result.output, dict) and "errors" in step.result.output:
                user_metrics = step.result.output
        if step.tool_name == "search_vectors" and step.result.success:
            vector_context = [r["text"] for r in step.result.output]
        if step.tool_name == "check_system_status" and step.result.success:
            gateway_status = step.result.output
        if step.tool_name == "get_similar_cases" and step.result.success:
            similar_cases = step.result.output

    # Build response
    if gateway_status and gateway_status.get("status") == "degraded":
        affected = gateway_status.get("affected_users", 0)
        recovery = "83%" if similar_cases else "unknown"
        return {
            "summary":    f"Root cause: {gateway_status.get('root_cause', 'unknown')}. "
                          f"{affected} users affected. Historical recovery rate: {recovery}.",
            "action":     "proactive_outreach_all_affected_users",
            "confidence": 0.94,
            "evidence":   [
                f"{user_metrics.get('errors',0)} errors ({user_metrics.get('error_rate',0):.0%} rate)" if user_metrics else "errors detected",
                f"Gateway status: {gateway_status.get('status')} ({affected} users affected)",
                similar_cases[0]["description"][:60] + "..." if similar_cases else "no similar cases",
            ],
            "scope": f"systemic — {affected} users affected, not just this user",
        }
    elif user_metrics and user_metrics.get("churn"):
        return {
            "summary":    f"User is at HIGH churn risk. {user_metrics.get('errors',0)} errors "
                          f"({user_metrics.get('error_rate',0):.0%} rate).",
            "action":     "trigger_retention_workflow",
            "confidence": 0.87,
            "evidence":   vector_context[:2],
        }
    else:
        return {
            "summary":    "No significant issues detected.",
            "action":     "no_action",
            "confidence": 0.70,
            "evidence":   [],
        }


# ── AGENT RUNNER ──────────────────────────────────────────────────────────────

MAX_STEPS = 8

def run_agent(task: str) -> AgentResult:
    """
    Runs the agent loop: decide → execute → observe → repeat.
    Stops when the LLM decides to generate a final answer or max steps reached.
    """
    t0     = time.perf_counter()
    result = AgentResult(task=task)

    for step_num in range(MAX_STEPS):
        # LLM decides next action
        decision = mock_llm_decide(task, result.steps)

        if decision is None:
            # LLM decided to generate final answer
            result.final_answer = mock_llm_answer(task, result.steps)
            result.stopped_by   = "answer"
            break

        # Execute the chosen tool
        tool_result = execute_tool(decision["tool"], decision["args"])

        step = AgentStep(
            step_num=step_num + 1,
            tool_name=decision["tool"],
            tool_args=decision["args"],
            result=tool_result,
            reasoning=decision["reasoning"],
        )
        result.steps.append(step)

    else:
        # Hit max steps
        result.final_answer = mock_llm_answer(task, result.steps)
        result.stopped_by   = "max_steps"

    result.total_ms = round((time.perf_counter() - t0) * 1000, 1)
    return result


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("AGENT CONTROLLER — Adaptive tool selection")
    print("=" * 65)

    task = "Why did user u_4821 churn? What should we do?"
    print(f"\n  Task: \"{task}\"\n")

    result = run_agent(task)

    print(f"  Agent took {len(result.steps)} steps (stopped by: {result.stopped_by})\n")
    for step in result.steps:
        print(f"  Step {step.step_num}: {step.tool_name}({step.tool_args})")
        print(f"    Reasoning: {step.reasoning}")
        output_str = str(step.result.output)
        print(f"    Result:    {output_str[:70]}{'...' if len(output_str)>70 else ''}")
        print(f"    Latency:   {step.result.latency_ms}ms")
        print()

    print(f"  Final Answer:")
    print(f"    Summary:    {result.final_answer.get('summary','')}")
    print(f"    Action:     {result.final_answer.get('action','')}")
    print(f"    Confidence: {result.final_answer.get('confidence',0):.0%}")
    print(f"    Scope:      {result.final_answer.get('scope','user-specific')}")
    print(f"    Evidence:")
    for e in result.final_answer.get("evidence", []):
        print(f"      ✅ {e}")
    print(f"\n  Total latency: {result.total_ms}ms")
    print(f"\n  KEY: Agent discovered the gateway outage by dynamically")
    print(f"  querying for it. A pipeline would have missed this.")


if __name__ == "__main__":
    run()
