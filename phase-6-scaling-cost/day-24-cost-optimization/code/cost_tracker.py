"""
Day 24 - cost_tracker.py
Token and workflow cost tracking with budget-aware execution hooks.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class StageUsage:
    workflow_id: str
    stage: str
    model_tier: str = "none"
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    retries: int = 0
    cache_hit: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass
class RateCard:
    input_per_1k: dict[str, float]
    output_per_1k: dict[str, float]
    flat_stage_cost: dict[str, float]


DEFAULT_RATE_CARD = RateCard(
    input_per_1k={"small": 0.002, "medium": 0.006, "large": 0.012},
    output_per_1k={"small": 0.004, "medium": 0.012, "large": 0.024},
    flat_stage_cost={"retrieval": 0.0004, "embedding": 0.0002, "orchestration": 0.0001},
)


class CostTracker:
    def __init__(
        self,
        rate_card: RateCard | None = None,
        max_cost_per_workflow: float = 0.030,
    ) -> None:
        self.rate_card = rate_card or DEFAULT_RATE_CARD
        self.max_cost_per_workflow = max_cost_per_workflow
        self.events: list[StageUsage] = []
        self.cost_by_workflow: dict[str, float] = defaultdict(float)
        self.cost_by_stage: dict[str, float] = defaultdict(float)
        self.cost_by_model: dict[str, float] = defaultdict(float)
        self.alerts: list[str] = []

    def _event_cost(self, usage: StageUsage) -> float:
        if usage.cache_hit:
            return 0.0
        base = self.rate_card.flat_stage_cost.get(usage.stage, 0.0)
        model = usage.model_tier
        if model in self.rate_card.input_per_1k:
            base += (usage.tokens_in / 1000) * self.rate_card.input_per_1k[model]
            base += (usage.tokens_out / 1000) * self.rate_card.output_per_1k[model]
        if usage.retries > 0:
            base *= 1 + (0.6 * usage.retries)
        if usage.stage in self.rate_card.flat_stage_cost:
            base += self.rate_card.flat_stage_cost[usage.stage]
        return base

    def record(self, usage: StageUsage) -> float:
        cost = self._event_cost(usage)
        self.events.append(usage)
        self.cost_by_workflow[usage.workflow_id] += cost
        self.cost_by_stage[usage.stage] += cost
        self.cost_by_model[usage.model_tier] += cost

        if self.cost_by_workflow[usage.workflow_id] > self.max_cost_per_workflow:
            alert = (
                f"budget_exceeded workflow={usage.workflow_id} "
                f"cost={self.cost_by_workflow[usage.workflow_id]:.5f}"
            )
            if not self.alerts or self.alerts[-1] != alert:
                self.alerts.append(alert)
        return cost

    def workflow_cost(self, workflow_id: str) -> float:
        return self.cost_by_workflow.get(workflow_id, 0.0)

    def projected_cost(self, usage: StageUsage) -> float:
        return self.workflow_cost(usage.workflow_id) + self._event_cost(usage)

    def workflow_summary(self, workflow_id: str) -> dict:
        entries = [e for e in self.events if e.workflow_id == workflow_id]
        if not entries:
            return {}
        return {
            "workflow_id": workflow_id,
            "events": len(entries),
            "cost": self.workflow_cost(workflow_id),
            "avg_latency_ms": sum(e.latency_ms for e in entries) / len(entries),
            "cache_hits": sum(1 for e in entries if e.cache_hit),
            "retries": sum(e.retries for e in entries),
        }

    def summary(self) -> dict:
        if not self.events:
            return {}
        return {
            "events": len(self.events),
            "workflows": len(self.cost_by_workflow),
            "total_cost": sum(self.cost_by_workflow.values()),
            "cost_by_stage": dict(self.cost_by_stage),
            "cost_by_model": dict(self.cost_by_model),
            "alerts": list(self.alerts),
        }

    def expensive_workflows(self, top_n: int = 3) -> list[tuple[str, float]]:
        return sorted(
            self.cost_by_workflow.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:top_n]


async def async_cost_aware_execution(
    tracker: CostTracker,
    workflow_id: str,
    stages: list[StageUsage],
) -> dict:
    """
    Lightweight async orchestration example:
    check projected cost before each stage, abort if budget exceeded.
    """
    for stage in stages:
        if tracker.projected_cost(stage) > tracker.max_cost_per_workflow:
            tracker.record(stage)
            return {
                "workflow_id": workflow_id,
                "status": "aborted",
                "reason": "budget_exceeded",
                "cost": tracker.workflow_cost(workflow_id),
            }
        await asyncio.sleep(0)
        tracker.record(stage)
    return {
        "workflow_id": workflow_id,
        "status": "completed",
        "cost": tracker.workflow_cost(workflow_id),
    }


def run_demo() -> None:
    tracker = CostTracker(max_cost_per_workflow=0.028)

    tracker.record(StageUsage("wf_faq_001", "retrieval", latency_ms=60, cache_hit=True))
    tracker.record(
        StageUsage(
            "wf_faq_001",
            "generation",
            model_tier="small",
            tokens_in=260,
            tokens_out=110,
            latency_ms=320,
        )
    )

    tracker.record(StageUsage("wf_ret_010", "embedding", latency_ms=45))
    tracker.record(StageUsage("wf_ret_010", "retrieval", latency_ms=180))
    tracker.record(
        StageUsage(
            "wf_ret_010",
            "generation",
            model_tier="large",
            tokens_in=2100,
            tokens_out=360,
            latency_ms=980,
            retries=1,
        )
    )

    async_result = asyncio.run(
        async_cost_aware_execution(
            tracker,
            workflow_id="wf_async_100",
            stages=[
                StageUsage("wf_async_100", "retrieval", latency_ms=120),
                StageUsage(
                    "wf_async_100",
                    "generation",
                    model_tier="medium",
                    tokens_in=1400,
                    tokens_out=300,
                    latency_ms=640,
                ),
                StageUsage(
                    "wf_async_100",
                    "generation",
                    model_tier="large",
                    tokens_in=2200,
                    tokens_out=500,
                    latency_ms=1020,
                ),
            ],
        )
    )

    print("COST TRACKER DEMO")
    print("-" * 72)
    for wf_id, cost in tracker.expensive_workflows(top_n=5):
        print(f"{wf_id:16s} cost={cost:.5f}")
    print("-" * 72)
    print("Async workflow result:", async_result)
    print("Summary:", tracker.summary())


if __name__ == "__main__":
    run_demo()
