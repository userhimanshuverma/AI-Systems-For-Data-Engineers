"""
Simple Pipeline — Day 17: Agents vs Pipelines
===============================================
Demonstrates a deterministic pipeline for user churn analysis.

The execution path is fixed: always the same steps, always the same order.
No LLM makes orchestration decisions. The pipeline is hardcoded.

Properties:
  - Deterministic: same input → same execution path
  - Reliable: easy to test, monitor, debug
  - Fast: no LLM overhead for orchestration
  - Predictable: latency and cost are bounded
"""

import time
import random
from dataclasses import dataclass, field


# ── SIMULATED DATA STORES ─────────────────────────────────────────────────────

PINOT_DATA = {
    "u_4821": {"errors": 5, "error_rate": 0.50, "intent": 0.82, "churn": True,  "plan": "free"},
    "u_0012": {"errors": 0, "error_rate": 0.00, "intent": 0.30, "churn": False, "plan": "pro"},
    "u_7734": {"errors": 2, "error_rate": 0.33, "intent": 0.40, "churn": True,  "plan": "free"},
}

VECTOR_DOCS = {
    "u_4821": [
        "User u_4821 hit 500 error on /checkout. Churn risk: TRUE.",
        "User u_4821 clicked Upgrade to Pro. Intent: 0.82.",
        "Support ticket: checkout keeps failing.",
    ],
    "u_7734": [
        "User u_7734 hit 500 error on /checkout.",
        "User u_7734 visited /pricing twice.",
    ],
}


# ── PIPELINE STEPS ────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    task:          str
    user_id:       str
    steps_taken:   list[str] = field(default_factory=list)
    structured:    dict      = field(default_factory=dict)
    semantic:      list[str] = field(default_factory=list)
    context:       str       = ""
    response:      dict      = field(default_factory=dict)
    total_ms:      float     = 0.0


def step_parse_query(task: str) -> tuple[str, str]:
    """Step 1: Extract user_id from task. Always runs."""
    import re
    match = re.search(r"u_\d{4}", task)
    user_id = match.group(0) if match else "u_4821"
    return "churn_analysis", user_id


def step_query_pinot(user_id: str) -> dict:
    """Step 2: Query Pinot for structured metrics. Always runs."""
    time.sleep(0.068)  # simulate ~68ms
    return PINOT_DATA.get(user_id, {})


def step_search_vectors(user_id: str, top_k: int = 3) -> list[str]:
    """Step 3: Semantic search. Always runs."""
    time.sleep(0.050)  # simulate ~50ms
    return VECTOR_DOCS.get(user_id, [])[:top_k]


def step_filter_context(structured: dict, semantic: list[str]) -> str:
    """Step 4: Format context for LLM. Always runs."""
    lines = []
    if structured:
        lines.append(f"Metrics: errors={structured.get('errors',0)}, "
                     f"rate={structured.get('error_rate',0):.0%}, "
                     f"churn={structured.get('churn',False)}, "
                     f"intent={structured.get('intent',0):.2f}")
    if semantic:
        lines.append("Context:")
        for s in semantic:
            lines.append(f"  - {s}")
    return "\n".join(lines)


def step_call_llm(context: str, task: str, user_id: str) -> dict:
    """Step 5: Call LLM with assembled context. Always runs."""
    time.sleep(0.180)  # simulate ~180ms
    # Mock response based on context
    if "churn" in context.lower() and "TRUE" in context:
        return {
            "summary":    f"User {user_id} is at HIGH churn risk due to checkout errors.",
            "action":     "trigger_retention_workflow",
            "confidence": 0.87,
            "evidence":   ["5 errors (50% rate)", "Clicked Upgrade to Pro"],
        }
    return {
        "summary":    f"User {user_id} appears healthy.",
        "action":     "no_action",
        "confidence": 0.75,
        "evidence":   [],
    }


# ── PIPELINE RUNNER ───────────────────────────────────────────────────────────

def run_pipeline(task: str) -> PipelineResult:
    """
    Runs the deterministic pipeline. Always executes the same 5 steps.
    No LLM makes orchestration decisions.
    """
    t0 = time.perf_counter()
    result = PipelineResult(task=task, user_id="")

    # Step 1: Parse
    intent, user_id = step_parse_query(task)
    result.user_id = user_id
    result.steps_taken.append(f"parse_query → intent={intent}, user_id={user_id}")

    # Step 2: Pinot (always)
    result.structured = step_query_pinot(user_id)
    result.steps_taken.append(f"query_pinot → {len(result.structured)} fields")

    # Step 3: Vector search (always)
    result.semantic = step_search_vectors(user_id)
    result.steps_taken.append(f"search_vectors → {len(result.semantic)} chunks")

    # Step 4: Filter context (always)
    result.context = step_filter_context(result.structured, result.semantic)
    result.steps_taken.append(f"filter_context → {len(result.context)} chars")

    # Step 5: LLM (always)
    result.response = step_call_llm(result.context, task, user_id)
    result.steps_taken.append(f"call_llm → confidence={result.response['confidence']:.0%}")

    result.total_ms = round((time.perf_counter() - t0) * 1000, 1)
    return result


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("SIMPLE PIPELINE — Deterministic workflow")
    print("=" * 65)

    tasks = [
        "Why is user u_4821 at risk of churning?",
        "What's going on with user u_7734?",
        "Is user u_0012 healthy?",
    ]

    for task in tasks:
        result = run_pipeline(task)
        print(f"\n  Task:    \"{task}\"")
        print(f"  Steps:   {len(result.steps_taken)} (always the same)")
        for step in result.steps_taken:
            print(f"    → {step}")
        print(f"  Response: {result.response['summary']}")
        print(f"  Action:   {result.response['action']}")
        print(f"  Latency:  {result.total_ms}ms")

    print(f"\n{'='*65}")
    print(f"  Pipeline: same 5 steps for every query.")
    print(f"  Reliable, predictable, fast.")
    print(f"  Cannot adapt based on what it finds.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
