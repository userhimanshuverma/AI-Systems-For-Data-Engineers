"""
Day 27 — End-to-End System Pipeline
=====================================
Wires together all architecture layers into a complete, observable pipeline:

    Kafka Events → Stream Processing → Apache Pinot + Vector DB
                                            ↓
    User Query → Query Understanding → Retrieval Engine
                                            ↓
                                    Agent Orchestrator
                                            ↓
                                    LLM Reasoning Engine
                                            ↓
                                       User Response

This module demonstrates the FULL flow of a production AI system,
including observability, latency tracking, and failure handling.

Architecture Principle:
    Each layer is INDEPENDENTLY deployable, testable, and scalable.
    The pipeline is the integration point — it validates that the
    system works end-to-end while each component owns its own SLA.
"""

import json
import time
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict

from event_producer import EventProducer, UserEvent
from stream_processor import StreamProcessor
from retrieval_engine import RetrievalEngine
from agent_orchestrator import AgentOrchestrator
from llm_reasoning import LLMReasoningEngine


# ---------------------------------------------------------------------------
# Pipeline Observability
# ---------------------------------------------------------------------------

@dataclass
class PipelineSpan:
    """Distributed tracing span for a pipeline stage."""
    stage: str
    start_time: float = 0.0
    end_time: float = 0.0
    latency_ms: float = 0.0
    status: str = "pending"
    metadata: Dict = field(default_factory=dict)

    def start(self):
        self.start_time = time.time()
        self.status = "running"

    def finish(self, status: str = "success", metadata: Dict = None):
        self.end_time = time.time()
        self.latency_ms = (self.end_time - self.start_time) * 1000
        self.status = status
        if metadata:
            self.metadata.update(metadata)


@dataclass
class PipelineTrace:
    """Full distributed trace across all pipeline stages."""
    trace_id: str = ""
    query: str = ""
    spans: List[PipelineSpan] = field(default_factory=list)
    total_latency_ms: float = 0.0
    final_status: str = "pending"
    response: str = ""

    def add_span(self, stage: str) -> PipelineSpan:
        span = PipelineSpan(stage=stage)
        self.spans.append(span)
        return span

    def summary(self) -> Dict:
        return {
            "trace_id": self.trace_id,
            "query": self.query,
            "total_latency_ms": round(self.total_latency_ms, 1),
            "status": self.final_status,
            "stages": [
                {
                    "stage": s.stage,
                    "latency_ms": round(s.latency_ms, 1),
                    "status": s.status,
                }
                for s in self.spans
            ],
        }


# ---------------------------------------------------------------------------
# End-to-End Pipeline
# ---------------------------------------------------------------------------

class SystemPipeline:
    """
    Production-grade end-to-end AI system pipeline.

    Data Path (Background):
        EventProducer → StreamProcessor → (Pinot + VectorDB + FeatureStore)

    Query Path (User Request):
        UserQuery → QueryUnderstanding → RetrievalEngine → AgentOrchestrator
                 → LLMReasoning → Response

    Both paths are observable via distributed tracing.
    """

    def __init__(self):
        # Data path components
        self.event_producer = EventProducer(topic="user-events", num_partitions=12)
        self.stream_processor = StreamProcessor()

        # Query path components
        self.retrieval_engine = RetrievalEngine()
        self.agent_orchestrator = AgentOrchestrator()
        self.llm_engine = LLMReasoningEngine()

        # Observability
        self.traces: List[PipelineTrace] = []
        self.data_path_metrics = {
            "events_ingested": 0,
            "events_processed": 0,
            "events_failed": 0,
        }

    # ── Data Path ─────────────────────────────────────────────────────────

    def run_data_ingestion(self, event_count: int = 100) -> Dict:
        """
        Simulate the background data ingestion pipeline:
        Kafka -> Stream Processing -> Downstream Sinks
        """
        print(f"\n  > Ingesting {event_count} events...")
        trace = PipelineTrace(
            trace_id=f"data-{int(time.time())}",
            query=f"ingest_{event_count}_events",
        )
        start = time.time()

        # Stage 1: Event Production (Kafka)
        span = trace.add_span("kafka_ingestion")
        span.start()
        events = self.event_producer.produce_batch(event_count)
        span.finish("success", {
            "events_produced": len(events),
            "producer_metrics": self.event_producer.get_metrics(),
        })
        print(f"    [OK] Kafka: {len(events)} events produced ({span.latency_ms:.1f}ms)")

        # Stage 2: Stream Processing
        span = trace.add_span("stream_processing")
        span.start()
        raw_events = [json.loads(e.serialize().decode()) for e in events]
        processed = self.stream_processor.process_batch(raw_events)
        successful = [r for r in processed if r.is_valid]
        failed = [r for r in processed if not r.is_valid]
        span.finish("success", {
            "processed": len(successful),
            "failed": len(failed),
            "processor_metrics": self.stream_processor.get_metrics(),
        })
        print(f"    [OK] Stream Processing: {len(successful)} enriched, "
              f"{len(failed)} failed ({span.latency_ms:.1f}ms)")

        # Update metrics
        self.data_path_metrics["events_ingested"] += event_count
        self.data_path_metrics["events_processed"] += len(successful)
        self.data_path_metrics["events_failed"] += len(failed)

        trace.total_latency_ms = (time.time() - start) * 1000
        trace.final_status = "success"
        self.traces.append(trace)

        return {
            "events_produced": len(events),
            "events_processed": len(successful),
            "events_failed": len(failed),
            "latency_ms": trace.total_latency_ms,
        }

    # ── Query Path ────────────────────────────────────────────────────────

    def process_query(self, query: str) -> PipelineTrace:
        """
        Process a user query through the full intelligence pipeline:
        Query → Retrieval → Orchestration → LLM → Response
        """
        trace = PipelineTrace(
            trace_id=f"query-{int(time.time()*1000) % 100000}",
            query=query,
        )
        start = time.time()

        # Stage 1: Retrieval
        span = trace.add_span("retrieval")
        span.start()
        retrieval_result = self.retrieval_engine.retrieve(query)
        meta = retrieval_result.retrieval_metadata
        span.finish("success", {
            "intent": meta.get("parsed_intent"),
            "structured_results": meta.get("structured_count"),
            "semantic_results": meta.get("semantic_count"),
            "cache_hit": meta.get("cache_hit"),
        })

        intent = meta.get("parsed_intent", "general")

        # Stage 2: Agent Orchestration
        span = trace.add_span("agent_orchestration")
        span.start()
        orchestration_trace = self.agent_orchestrator.orchestrate(query, intent)
        span.finish(orchestration_trace.status, {
            "tool_calls": len(orchestration_trace.tool_calls),
            "tools_used": [tc.tool_name for tc in orchestration_trace.tool_calls],
        })

        # Stage 3: LLM Reasoning
        span = trace.add_span("llm_reasoning")
        span.start()

        # Assemble context from retrieval + orchestration
        context = {
            "retrieval_structured": [str(r) for r in retrieval_result.structured_results[:3]],
            "retrieval_semantic": [str(r) for r in retrieval_result.semantic_results[:3]],
            "orchestration_context": orchestration_trace.context_assembled,
        }

        llm_response = self.llm_engine.reason(query, context, intent)
        span.finish("success", {
            "model": llm_response.model_used,
            "tier": llm_response.model_tier,
            "tokens": llm_response.input_tokens + llm_response.output_tokens,
            "cost_usd": llm_response.cost_usd,
        })

        # Finalize
        trace.response = llm_response.content
        trace.total_latency_ms = (time.time() - start) * 1000
        trace.final_status = "success"
        self.traces.append(trace)

        return trace

    # ── Observability Dashboard ───────────────────────────────────────────

    def get_system_metrics(self) -> Dict:
        """Aggregate metrics across all pipeline components."""
        query_traces = [t for t in self.traces if t.trace_id.startswith("query-")]
        data_traces = [t for t in self.traces if t.trace_id.startswith("data-")]

        # Latency percentiles for query path
        query_latencies = sorted([t.total_latency_ms for t in query_traces])
        p50, p95, p99 = 0, 0, 0
        if query_latencies:
            n = len(query_latencies)
            p50 = query_latencies[int(n * 0.5)] if n > 0 else 0
            p95 = query_latencies[int(n * 0.95)] if n > 1 else query_latencies[-1]
            p99 = query_latencies[int(n * 0.99)] if n > 2 else query_latencies[-1]

        return {
            "data_path": {
                **self.data_path_metrics,
                "producer_metrics": self.event_producer.get_metrics(),
                "processor_metrics": self.stream_processor.get_metrics(),
            },
            "query_path": {
                "total_queries": len(query_traces),
                "latency_p50_ms": round(p50, 1),
                "latency_p95_ms": round(p95, 1),
                "latency_p99_ms": round(p99, 1),
                "retrieval_metrics": self.retrieval_engine.get_metrics(),
                "orchestrator_metrics": self.agent_orchestrator.get_metrics(),
                "llm_metrics": self.llm_engine.get_metrics(),
            },
        }


# ---------------------------------------------------------------------------
# Main — Full System Demonstration
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("+" + "-" * 68 + "+")
    print("|  END-TO-END AI SYSTEM PIPELINE                                    |")
    print("|  Kafka -> Processing -> Retrieval -> Orchestration -> LLM -> Response |")
    print("+" + "-" * 68 + "+")

    pipeline = SystemPipeline()

    # ── Phase 1: Data Ingestion ───────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  PHASE 1: DATA INGESTION PIPELINE")
    print("=" * 70)

    ingestion_result = pipeline.run_data_ingestion(200)
    print(f"\n  Summary: {ingestion_result['events_produced']} events -> "
          f"{ingestion_result['events_processed']} processed "
          f"({ingestion_result['latency_ms']:.0f}ms)")

    # ── Phase 2: Query Processing ─────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  PHASE 2: QUERY PROCESSING PIPELINE")
    print("=" * 70)

    queries = [
        "Which enterprise users are at highest risk of churning this quarter?",
        "Show me users with similar behavior patterns to user_0042",
        "What's the revenue trend for the professional tier this month?",
        "Find users with high support ticket volume and declining engagement",
        "Quick health check overview for our top accounts",
    ]
    for query in queries:
        print(f"\n{'-' * 70}")
        print(f"  Query: {query}")
        print(f"{'-' * 70}")

        trace = pipeline.process_query(query)

        print(f"\n  Trace: {trace.trace_id}")
        print(f"  Status: {trace.final_status}")
        print(f"  Total Latency: {trace.total_latency_ms:.0f}ms")
        print(f"\n  Stage Breakdown:")
        total_stage = 0
        for span in trace.spans:
            pct = (span.latency_ms / max(trace.total_latency_ms, 1)) * 100
            bar = "#" * int(pct / 2)
            print(f"    {span.stage:25s} | {span.latency_ms:7.1f}ms | {pct:5.1f}% | {bar}")
            total_stage += span.latency_ms

        print(f"\n  Response Preview:")
        for line in trace.response.strip().split("\n")[:4]:
            print(f"    {line}")
        print(f"    ...")

    # ── Phase 3: System Observability ─────────────────────────────────────
    print("\n" + "=" * 70)
    print("  PHASE 3: SYSTEM OBSERVABILITY")
    print("=" * 70)

    metrics = pipeline.get_system_metrics()

    print("\n  -- Data Path --")
    dp = metrics["data_path"]
    print(f"    Events Ingested  : {dp['events_ingested']}")
    print(f"    Events Processed : {dp['events_processed']}")
    print(f"    Events Failed    : {dp['events_failed']}")
    print(f"    Error Rate       : {dp['processor_metrics']['error_rate']:.2%}")

    print("\n  -- Query Path --")
    qp = metrics["query_path"]
    print(f"    Total Queries    : {qp['total_queries']}")
    print(f"    Latency P50      : {qp['latency_p50_ms']:.0f}ms")
    print(f"    Latency P95      : {qp['latency_p95_ms']:.0f}ms")
    print(f"    Latency P99      : {qp['latency_p99_ms']:.0f}ms")

    print("\n  -- Retrieval --")
    rm = qp["retrieval_metrics"]
    print(f"    Cache Hit Rate   : {rm['cache_hit_rate']:.0%}")
    print(f"    Avg Latency      : {rm['avg_latency_ms']:.1f}ms")

    print("\n  -- Orchestrator --")
    om = qp["orchestrator_metrics"]
    print(f"    Success Rate     : {om['success_rate']:.0%}")
    print(f"    Total Tool Calls : {om['total_tool_calls']}")
    print(f"    Total Retries    : {om['total_retries']}")
    print(f"    Total Fallbacks  : {om['total_fallbacks']}")

    print("\n  -- LLM --")
    lm = qp["llm_metrics"]
    print(f"    Total Tokens     : {lm['total_tokens']:,}")
    print(f"    Total Cost       : ${lm['total_cost_usd']:.4f}")
    print(f"    Avg Cost/Query   : ${lm['avg_cost_per_query']:.6f}")
    print(f"    Model Usage      : {lm['model_usage']}")

    print("\n" + "=" * 70)
    print("  * End-to-end pipeline demonstration complete.")
    print("=" * 70)
