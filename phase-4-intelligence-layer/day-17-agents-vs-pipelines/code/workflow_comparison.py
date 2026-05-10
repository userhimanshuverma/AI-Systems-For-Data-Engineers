"""
Workflow Comparison — Day 17: Agents vs Pipelines
===================================================
Side-by-side comparison of pipeline vs agent for the same task.

Demonstrates:
  - When the pipeline gives the right answer (simple churn query)
  - When the agent gives a better answer (systemic issue discovery)
  - Latency, cost, and reliability tradeoffs
  - Decision framework: when to use each
"""

import time
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from simple_pipeline  import run_pipeline
from agent_controller import run_agent


# ── COMPARISON RUNNER ─────────────────────────────────────────────────────────

def compare(task: str) -> None:
    print(f"\n{'─'*65}")
    print(f"  Task: \"{task}\"")
    print(f"{'─'*65}")

    # Run pipeline
    print(f"\n  [PIPELINE]  Running deterministic workflow...")
    p_result = run_pipeline(task)
    print(f"  Steps:      {len(p_result.steps_taken)} (fixed)")
    print(f"  Latency:    {p_result.total_ms}ms")
    print(f"  Response:   {p_result.response['summary']}")
    print(f"  Action:     {p_result.response['action']}")
    print(f"  Confidence: {p_result.response['confidence']:.0%}")

    # Run agent
    print(f"\n  [AGENT]     Running adaptive workflow...")
    a_result = run_agent(task)
    print(f"  Steps:      {len(a_result.steps)} (adaptive)")
    print(f"  Tools used: {[s.tool_name for s in a_result.steps]}")
    print(f"  Latency:    {a_result.total_ms}ms")
    print(f"  Response:   {a_result.final_answer.get('summary','')}")
    print(f"  Action:     {a_result.final_answer.get('action','')}")
    print(f"  Confidence: {a_result.final_answer.get('confidence',0):.0%}")
    scope = a_result.final_answer.get("scope", "user-specific")
    if scope != "user-specific":
        print(f"  Scope:      {scope}  ← AGENT DISCOVERED THIS")

    # Verdict
    print(f"\n  VERDICT:")
    if "gateway" in a_result.final_answer.get("summary", "").lower():
        print(f"  Pipeline: ❌ Missed systemic issue — answered as if user-specific")
        print(f"  Agent:    ✅ Discovered gateway outage — correct root cause")
        print(f"  Winner:   AGENT (task required dynamic investigation)")
    else:
        latency_diff = a_result.total_ms - p_result.total_ms
        print(f"  Pipeline: ✅ Correct answer, {p_result.total_ms}ms")
        print(f"  Agent:    ✅ Correct answer, {a_result.total_ms}ms (+{latency_diff:.0f}ms overhead)")
        print(f"  Winner:   PIPELINE (same answer, lower latency, lower cost)")


# ── DECISION FRAMEWORK ────────────────────────────────────────────────────────

def print_decision_framework() -> None:
    print(f"\n{'='*65}")
    print(f"  DECISION FRAMEWORK: Pipeline or Agent?")
    print(f"{'='*65}")

    scenarios = [
        ("Standard churn query",          "pipeline", "Fixed path, predictable, fast"),
        ("Root cause investigation",       "agent",    "Needs dynamic tool selection"),
        ("Embedding pipeline (10K/sec)",   "pipeline", "High throughput, no LLM in hot path"),
        ("Multi-step user investigation",  "agent",    "Each step gates the next"),
        ("Weekly retention report",        "pipeline", "Deterministic aggregation"),
        ("Systemic issue detection",       "agent",    "Unknown scope at query time"),
        ("Real-time fraud detection",      "pipeline", "< 200ms required, no agent latency"),
        ("Open-ended research task",       "agent",    "Unknown steps needed"),
    ]

    print(f"\n  {'Scenario':40s} {'Choice':10s} {'Reason'}")
    print(f"  {'-'*65}")
    for scenario, choice, reason in scenarios:
        icon = "🔄" if choice == "pipeline" else "🤖"
        print(f"  {scenario:40s} {icon} {choice:8s}  {reason}")

    print(f"\n  Rule: Default to pipeline. Use agent only when the execution")
    print(f"  path genuinely needs to adapt based on intermediate results.")


# ── LATENCY COMPARISON ────────────────────────────────────────────────────────

def print_latency_comparison() -> None:
    print(f"\n{'='*65}")
    print(f"  LATENCY COMPARISON")
    print(f"{'='*65}")

    rows = [
        ("Pipeline (2 parallel tools + LLM)", "~300ms",  "Predictable"),
        ("Agent (3 steps × ~300ms each)",     "~900ms",  "Variable (2-8 steps)"),
        ("Agent (5 steps × ~300ms each)",     "~1500ms", "Variable"),
        ("Flink stream processing",           "~18ms",   "No LLM in path"),
        ("Pinot SQL query",                   "~68ms",   "No LLM in path"),
    ]

    print(f"\n  {'Approach':40s} {'Latency':12s} {'Predictability'}")
    print(f"  {'-'*65}")
    for approach, latency, pred in rows:
        print(f"  {approach:40s} {latency:12s} {pred}")

    print(f"\n  Key: Agents are 3-5x slower than pipelines for the same task.")
    print(f"  Use agents only when the adaptive capability justifies the cost.")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("WORKFLOW COMPARISON — Pipeline vs Agent")
    print("=" * 65)

    # Scenario 1: Simple churn query (pipeline wins)
    compare("Why is user u_0012 at risk?")

    # Scenario 2: Root cause with systemic issue (agent wins)
    compare("Why did user u_4821 churn? What should we do?")

    # Decision framework
    print_decision_framework()

    # Latency comparison
    print_latency_comparison()

    print(f"\n{'='*65}")
    print(f"  CONCLUSION")
    print(f"  Pipelines: reliable, fast, predictable. Right default.")
    print(f"  Agents: adaptive, powerful, slower. Use when needed.")
    print(f"  Most data engineering tasks → pipeline.")
    print(f"  Root cause analysis, multi-step investigation → agent.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
