"""
Day 24 - model_router.py
Complexity-aware and cost-aware routing across model tiers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelTier:
    name: str
    quality_level: int
    avg_latency_ms: int
    max_context_tokens: int
    input_cost_per_1k: float
    output_cost_per_1k: float


MODEL_TIERS: dict[str, ModelTier] = {
    "small": ModelTier(
        name="small-tier",
        quality_level=1,
        avg_latency_ms=320,
        max_context_tokens=32_000,
        input_cost_per_1k=0.002,
        output_cost_per_1k=0.004,
    ),
    "medium": ModelTier(
        name="medium-tier",
        quality_level=2,
        avg_latency_ms=620,
        max_context_tokens=64_000,
        input_cost_per_1k=0.006,
        output_cost_per_1k=0.012,
    ),
    "large": ModelTier(
        name="large-tier",
        quality_level=3,
        avg_latency_ms=980,
        max_context_tokens=128_000,
        input_cost_per_1k=0.012,
        output_cost_per_1k=0.024,
    ),
}


@dataclass
class TaskProfile:
    task_type: str
    estimated_input_tokens: int
    requires_multi_step_reasoning: bool
    latency_sla_ms: int
    risk_level: str = "normal"
    expected_output_tokens: int = 220


@dataclass
class RoutingDecision:
    selected_model: str
    estimated_cost: float
    estimated_latency_ms: int
    complexity_score: int
    reason: str


class ModelRouter:
    def __init__(self, max_cost_per_request: float = 0.020) -> None:
        self.max_cost_per_request = max_cost_per_request

    def estimate_cost(self, tier_name: str, input_tokens: int, output_tokens: int) -> float:
        tier = MODEL_TIERS.get(tier_name)
        if tier is None:
            return float("inf")
        input_cost = (input_tokens / 1000) * tier.input_cost_per_1k
        output_cost = (output_tokens / 1000) * tier.output_cost_per_1k
        return input_cost + output_cost

    def complexity_score(self, task: TaskProfile) -> int:
        score = 0
        if task.estimated_input_tokens > 1800:
            score += 3
        elif task.estimated_input_tokens > 800:
            score += 2
        else:
            score += 1

        if task.requires_multi_step_reasoning:
            score += 2

        if task.task_type in {"retention_analysis", "root_cause_analysis"}:
            score += 2
        elif task.task_type in {"analysis", "investigation"}:
            score += 1

        if task.risk_level == "high":
            score += 1
        return score

    def preferred_tier(self, task: TaskProfile, score: int) -> str:
        if score <= 2:
            tier = "small"
        elif score <= 5:
            tier = "medium"
        else:
            tier = "large"

        ref = MODEL_TIERS.get(tier)
        if ref and ref.avg_latency_ms > task.latency_sla_ms:
            if tier == "large":
                tier = "medium"
            elif tier == "medium":
                tier = "small"
            else:
                pass
        return tier

    def route(self, task: TaskProfile) -> RoutingDecision:
        score = self.complexity_score(task)
        tier = self.preferred_tier(task, score)

        ref = MODEL_TIERS.get(tier)
        if ref and task.estimated_input_tokens > ref.max_context_tokens:
            for candidate in ["large", "medium", "small"]:
                cref = MODEL_TIERS.get(candidate)
                if cref and task.estimated_input_tokens <= cref.max_context_tokens:
                    tier = candidate
                    break

        estimated_cost = self.estimate_cost(
            tier_name=tier,
            input_tokens=task.estimated_input_tokens,
            output_tokens=task.expected_output_tokens,
        )

        if estimated_cost > self.max_cost_per_request and task.risk_level != "high":
            if tier == "large":
                tier = "medium"
            elif tier == "medium":
                tier = "small"
            estimated_cost = self.estimate_cost(
                tier_name=tier,
                input_tokens=task.estimated_input_tokens,
                output_tokens=task.expected_output_tokens,
            )

        reason = (
            f"type={task.task_type}, score={score}, tokens={task.estimated_input_tokens}, "
            f"risk={task.risk_level}, sla={task.latency_sla_ms}ms"
        )
        return RoutingDecision(
            selected_model=tier,
            estimated_cost=estimated_cost,
            estimated_latency_ms=MODEL_TIERS[tier].avg_latency_ms,
            complexity_score=score,
            reason=reason,
        )

    def route_batch(self, tasks: list[TaskProfile]) -> list[RoutingDecision]:
        return [self.route(t) for t in tasks]


def run_demo() -> None:
    router = ModelRouter(max_cost_per_request=0.018)
    tasks = [
        TaskProfile("faq", 260, False, 1200, "low", 120),
        TaskProfile("operational_lookup", 420, False, 900, "normal", 140),
        TaskProfile("analysis", 1100, True, 2500, "normal", 260),
        TaskProfile("retention_analysis", 2300, True, 4000, "high", 320),
    ]

    total_routed = 0.0
    total_all_large = 0.0
    print("MODEL ROUTER DEMO")
    print("-" * 90)
    print(f"{'task_type':22s} {'tier':8s} {'cost':>10s} {'latency':>10s}  reason")
    for task in tasks:
        decision = router.route(task)
        all_large = router.estimate_cost(
            "large",
            input_tokens=task.estimated_input_tokens,
            output_tokens=task.expected_output_tokens,
        )
        total_routed += decision.estimated_cost
        total_all_large += all_large
        print(
            f"{task.task_type:22s} {decision.selected_model:8s} "
            f"{decision.estimated_cost:10.5f} {decision.estimated_latency_ms:10d}  {decision.reason}"
        )

    savings = 1 - (total_routed / total_all_large) if total_all_large else 0.0
    print("-" * 90)
    print(f"Total routed cost      : {total_routed:.5f}")
    print(f"Total always-large cost: {total_all_large:.5f}")
    print(f"Relative savings       : {savings:.1%}")


if __name__ == "__main__":
    run_demo()
