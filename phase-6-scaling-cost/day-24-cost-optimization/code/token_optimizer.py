"""
Day 24 - token_optimizer.py
Prompt and context token controls for production LLM systems.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


def estimate_tokens(text: str) -> int:
    """Approximate token count (safe heuristic for offline simulation)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


@dataclass
class ContextChunk:
    chunk_id: str
    text: str
    relevance: float


@dataclass
class OptimizationReport:
    original_tokens: int
    optimized_tokens: int
    token_reduction: int
    reduction_ratio: float
    kept_chunks: int
    dropped_chunks: int


def trim_prompt(prompt: str, max_tokens: int = 120) -> str:
    """
    Trim verbose instruction text to a token budget.
    Keeps line order and truncates only when needed.
    """
    if not prompt:
        return ""
    lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    kept: list[str] = []
    used = 0
    for line in lines:
        line_tokens = estimate_tokens(line)
        if used + line_tokens > max_tokens:
            break
        kept.append(line)
        used += line_tokens
    return "\n".join(kept) if kept else lines[0][:max_tokens * 4]


def deduplicate_chunks(chunks: Iterable[ContextChunk]) -> list[ContextChunk]:
    """Remove exact and near-exact duplicates using normalized text keys."""
    seen: set[str] = set()
    result: list[ContextChunk] = []
    for chunk in chunks:
        key = " ".join(chunk.text.lower().split())
        key = key[:180]
        if key in seen:
            continue
        seen.add(key)
        result.append(chunk)
    return result


def select_relevant_chunks(
    chunks: Iterable[ContextChunk],
    min_relevance: float = 0.65,
    max_chunks: int = 6,
) -> list[ContextChunk]:
    """Filter by relevance and keep highest-value chunks."""
    filtered = [c for c in chunks if c.relevance >= min_relevance]
    filtered.sort(key=lambda c: c.relevance, reverse=True)
    return filtered[:max_chunks]


def build_context(chunks: Iterable[ContextChunk], max_tokens: int = 450) -> str:
    """Build context block under token budget."""
    selected: list[str] = []
    used = 0
    for chunk in chunks:
        line = f"- ({chunk.relevance:.2f}) {chunk.text}"
        line_tokens = estimate_tokens(line)
        if used + line_tokens > max_tokens:
            break
        selected.append(line)
        used += line_tokens
    return "\n".join(selected)


def optimize_request(
    query: str,
    system_prompt: str,
    retrieved_chunks: list[ContextChunk],
    prompt_budget_tokens: int = 120,
    context_budget_tokens: int = 450,
) -> tuple[dict[str, str], OptimizationReport]:
    """
    Apply trimming, ranking, deduplication, and context budgeting.
    Returns optimized prompt payload and optimization report.
    """
    original_prompt = "\n".join(
        [system_prompt, query] + [chunk.text for chunk in retrieved_chunks]
    )
    original_tokens = estimate_tokens(original_prompt)

    compact_system = trim_prompt(system_prompt, prompt_budget_tokens)
    relevant = select_relevant_chunks(retrieved_chunks)
    deduped = deduplicate_chunks(relevant)
    compact_context = build_context(deduped, context_budget_tokens)

    optimized_prompt = "\n".join([compact_system, query, compact_context])
    optimized_tokens = estimate_tokens(optimized_prompt)
    reduction = max(0, original_tokens - optimized_tokens)

    payload = {
        "system": compact_system,
        "query": query,
        "context": compact_context,
    }
    report = OptimizationReport(
        original_tokens=original_tokens,
        optimized_tokens=optimized_tokens,
        token_reduction=reduction,
        reduction_ratio=(reduction / original_tokens) if original_tokens else 0.0,
        kept_chunks=len(deduped),
        dropped_chunks=max(0, len(retrieved_chunks) - len(deduped)),
    )
    return payload, report


def compress_log_events(log_text: str, max_tokens: int = 200) -> str:
    """Compress verbose log/event text into compact summary."""
    if not log_text:
        return ""
    lines = [l.strip() for l in log_text.splitlines() if l.strip()]
    total = estimate_tokens(log_text)
    if total <= max_tokens:
        return log_text
    ratio = max_tokens / max(total, 1)
    keep = max(1, int(len(lines) * ratio))
    head = lines[:max(1, keep // 2)]
    tail = lines[-max(1, keep // 2):]
    summary = head + ["...", f"[compressed: {len(lines)} lines -> {len(head) + len(tail) + 1} lines]"] + tail
    result = "\n".join(summary)
    if estimate_tokens(result) > max_tokens:
        result = "\n".join(summary[:max(1, max_tokens // 20)])
    return result


def run_demo() -> None:
    verbose_system_prompt = """
    You are an analytics assistant for data engineering teams.
    Always include detailed explanation and verbose context restatement.
    Include policy, historical comparisons, and all supporting notes.
    Use a structured JSON object with rationale, confidence, and evidence.
    """
    query = "Explain why account retention dropped for enterprise customers this month."
    chunks = [
        ContextChunk("c1", "Enterprise support tickets increased 28% after release 2.1.", 0.92),
        ContextChunk("c2", "Activation completion dropped from 71% to 63%.", 0.89),
        ContextChunk("c3", "Enterprise support tickets increased 28% after release 2.1.", 0.87),
        ContextChunk("c4", "Mobile usage grew 4% week over week.", 0.41),
        ContextChunk("c5", "Churn cohort cited onboarding friction in surveys.", 0.84),
        ContextChunk("c6", "A/B experiment sample had instrumentation noise.", 0.67),
    ]

    _, report = optimize_request(query, verbose_system_prompt, chunks)

    illustrative_input_cost_per_1k_tokens = 0.002
    cost_before = report.original_tokens / 1000 * illustrative_input_cost_per_1k_tokens
    cost_after = report.optimized_tokens / 1000 * illustrative_input_cost_per_1k_tokens

    print("TOKEN OPTIMIZER DEMO")
    print("-" * 60)
    print(f"Original tokens   : {report.original_tokens}")
    print(f"Optimized tokens  : {report.optimized_tokens}")
    print(f"Token reduction   : {report.token_reduction} ({report.reduction_ratio:.1%})")
    print(f"Chunks kept/dropped: {report.kept_chunks}/{report.dropped_chunks}")
    print(f"Illustrative cost : {cost_before:.6f} -> {cost_after:.6f}")

    print()
    print("LOG COMPRESSION DEMO")
    log = "\n".join([f"2025-01-{d:02d} INFO event_{d} processed value={d*10}" for d in range(1, 31)])
    compressed = compress_log_events(log, max_tokens=60)
    print(f"Original log tokens : {estimate_tokens(log)}")
    print(f"Compressed tokens   : {estimate_tokens(compressed)}")


if __name__ == "__main__":
    run_demo()
