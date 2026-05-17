"""
Day 24 - cache_simulation.py
Simulate response/retrieval/embedding/semantic cache behavior.
"""

from __future__ import annotations

import random
import time
from collections import OrderedDict
from dataclasses import dataclass


def _now() -> float:
    return time.time()


class TTLStore:
    def __init__(self, ttl_seconds: int, max_items: int = 2000) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self.store: OrderedDict[str, tuple[float, object]] = OrderedDict()

    def get(self, key: str) -> object | None:
        item = self.store.get(key)
        if item is None:
            return None
        ts, value = item
        if _now() - ts > self.ttl_seconds:
            self.store.pop(key, None)
            return None
        self.store.move_to_end(key)
        return value

    def set(self, key: str, value: object) -> None:
        self.store[key] = (_now(), value)
        self.store.move_to_end(key)
        while len(self.store) > self.max_items:
            self.store.popitem(last=False)

    def clear(self) -> None:
        self.store.clear()


class ResponseCache:
    def __init__(self, ttl_seconds: int = 600) -> None:
        self._store = TTLStore(ttl_seconds=ttl_seconds)
        self.hits = 0
        self.misses = 0

    def get(self, query: str) -> object | None:
        value = self._store.get(query.lower().strip())
        if value is None:
            self.misses += 1
            return None
        self.hits += 1
        return value

    def set(self, query: str, value: object) -> None:
        self._store.set(query.lower().strip(), value)

    def reset_stats(self) -> None:
        self.hits = 0
        self.misses = 0
        self._store.clear()


class RetrievalCache:
    def __init__(self, ttl_seconds: int = 300) -> None:
        self._store = TTLStore(ttl_seconds=ttl_seconds)
        self.hits = 0
        self.misses = 0

    def key(self, query_signature: str, depth: int) -> str:
        return f"{query_signature}|depth:{depth}"

    def get(self, cache_key: tuple[str, int]) -> object | None:
        key = self.key(*cache_key)
        value = self._store.get(key)
        if value is None:
            self.misses += 1
            return None
        self.hits += 1
        return value

    def set(self, cache_key: tuple[str, int], value: object) -> None:
        self._store.set(self.key(*cache_key), value)

    def reset_stats(self) -> None:
        self.hits = 0
        self.misses = 0
        self._store.clear()


class EmbeddingCache:
    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._store = TTLStore(ttl_seconds=ttl_seconds)
        self.hits = 0
        self.misses = 0

    def get(self, text: str) -> list[float] | None:
        key = text.lower().strip()
        if not key:
            self.misses += 1
            return None
        value = self._store.get(key)
        if value is None:
            self.misses += 1
            return None
        self.hits += 1
        return value  # type: ignore[return-value]

    def set(self, text: str, vector: list[float]) -> None:
        self._store.set(text.lower().strip(), vector)

    def reset_stats(self) -> None:
        self.hits = 0
        self.misses = 0
        self._store.clear()


class SemanticCache:
    def __init__(self, ttl_seconds: int = 3600, min_overlap: float = 0.75) -> None:
        self._store = TTLStore(ttl_seconds=ttl_seconds)
        self.min_overlap = min_overlap
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _terms(text: str) -> set[str]:
        return set(token for token in text.lower().split() if token.isalpha() or token.isalnum())

    def get(self, query: str) -> object | None:
        if not query:
            self.misses += 1
            return None
        query_terms = self._terms(query)
        if not query_terms:
            self.misses += 1
            return None
        for key in list(self._store.store.keys()):
            raw = self._store.get(key)
            if raw is None:
                continue
            cached_query, response = raw  # type: ignore[misc]
            cached_terms = self._terms(cached_query)
            if not cached_terms:
                continue
            overlap = len(query_terms & cached_terms) / len(query_terms | cached_terms)
            if overlap >= self.min_overlap:
                self.hits += 1
                return response
        self.misses += 1
        return None

    def set(self, query: str, response: object) -> None:
        if not query:
            return
        self._store.set(f"q:{len(self._store.store)}", (query, response))

    def reset_stats(self) -> None:
        self.hits = 0
        self.misses = 0
        self._store.clear()


@dataclass
class RequestResult:
    source: str
    cost: float
    latency_ms: int
    input_tokens: int
    output_tokens: int


def _query_signature(query: str) -> str:
    words = query.lower().split()
    return " ".join(words[:4])


def _simulate_embedding(query: str) -> list[float]:
    random.seed(hash(query) % (2**16))
    return [random.random() for _ in range(8)]


def _simulate_retrieval_tokens(depth: int) -> int:
    return depth * random.randint(90, 130)


def simulate_request(
    query: str,
    retrieval_depth: int,
    enable_caching: bool,
    response_cache: ResponseCache,
    retrieval_cache: RetrievalCache,
    embedding_cache: EmbeddingCache,
    semantic_cache: SemanticCache,
) -> RequestResult:
    if not query:
        return RequestResult("error", 0.0, 0, 0, 0)

    if enable_caching:
        cached = response_cache.get(query)
        if cached is not None:
            return RequestResult("response_cache", 0.0, 18, 0, 0)

        sem = semantic_cache.get(query)
        if sem is not None:
            return RequestResult("semantic_cache", 0.0, 28, 0, 0)

    if enable_caching:
        emb = embedding_cache.get(query)
        if emb is None:
            emb = _simulate_embedding(query)
            embedding_cache.set(query, emb)
    else:
        emb = _simulate_embedding(query)

    signature = _query_signature(query)
    if enable_caching:
        docs = retrieval_cache.get((signature, retrieval_depth))
        if docs is None:
            docs = {"token_load": _simulate_retrieval_tokens(retrieval_depth)}
            retrieval_cache.set((signature, retrieval_depth), docs)
    else:
        docs = {"token_load": _simulate_retrieval_tokens(retrieval_depth)}

    retrieved_tokens = docs["token_load"]
    base_prompt_tokens = random.randint(120, 220)
    output_tokens = random.randint(80, 180)
    input_tokens = base_prompt_tokens + retrieved_tokens

    input_cost_per_1k = 0.002
    output_cost_per_1k = 0.004
    cost = (input_tokens / 1000) * input_cost_per_1k + (output_tokens / 1000) * output_cost_per_1k

    latency = 220 + retrieval_depth * 35
    response = {"summary": "simulated answer"}
    if enable_caching:
        response_cache.set(query, response)
        semantic_cache.set(query, response)

    return RequestResult("llm", cost, latency, input_tokens, output_tokens)


def _build_workload(size: int = 200) -> list[str]:
    faq = [
        "what is churn score",
        "how is retention calculated",
        "what does activation mean",
    ]
    lookups = [f"show account health user_{i:03d}" for i in range(30)]
    complex_q = [f"analyze retention cohort segment_{i:02d}" for i in range(40)]
    workload: list[str] = []
    for _ in range(size):
        r = random.random()
        if r < 0.45:
            workload.append(random.choice(faq))
        elif r < 0.78:
            workload.append(random.choice(lookups))
        else:
            workload.append(random.choice(complex_q))
    return workload


def run_simulation(enable_caching: bool, retrieval_depth: int = 4, requests: int = 220) -> dict:
    response_cache = ResponseCache(ttl_seconds=900)
    retrieval_cache = RetrievalCache(ttl_seconds=300)
    embedding_cache = EmbeddingCache(ttl_seconds=3600)
    semantic_cache = SemanticCache(ttl_seconds=900, min_overlap=0.80)

    results: list[RequestResult] = []
    for query in _build_workload(requests):
        result = simulate_request(
            query=query,
            retrieval_depth=retrieval_depth,
            enable_caching=enable_caching,
            response_cache=response_cache,
            retrieval_cache=retrieval_cache,
            embedding_cache=embedding_cache,
            semantic_cache=semantic_cache,
        )
        results.append(result)

    total_cost = sum(r.cost for r in results)
    avg_latency = sum(r.latency_ms for r in results) / len(results) if results else 0
    llm_calls = sum(1 for r in results if r.source == "llm")

    return {
        "requests": len(results),
        "llm_calls": llm_calls,
        "total_cost": total_cost,
        "avg_latency_ms": avg_latency,
        "response_cache_hits": response_cache.hits,
        "semantic_cache_hits": semantic_cache.hits,
        "retrieval_cache_hits": retrieval_cache.hits,
        "embedding_cache_hits": embedding_cache.hits,
    }


def run_demo() -> None:
    random.seed(11)
    with_cache = run_simulation(enable_caching=True, retrieval_depth=4, requests=260)
    no_cache = run_simulation(enable_caching=False, retrieval_depth=4, requests=260)

    cost_reduction = 1 - (with_cache["total_cost"] / no_cache["total_cost"])
    latency_reduction = 1 - (with_cache["avg_latency_ms"] / no_cache["avg_latency_ms"])

    print("CACHE SIMULATION DEMO")
    print("-" * 72)
    print(f"Requests                    : {with_cache['requests']}")
    print(f"LLM calls (with cache)      : {with_cache['llm_calls']}")
    print(f"LLM calls (without cache)   : {no_cache['llm_calls']}")
    print(f"Total cost (with cache)     : {with_cache['total_cost']:.5f}")
    print(f"Total cost (without cache)  : {no_cache['total_cost']:.5f}")
    print(f"Average latency with cache  : {with_cache['avg_latency_ms']:.1f}ms")
    print(f"Average latency no cache    : {no_cache['avg_latency_ms']:.1f}ms")
    print(f"Response cache hits         : {with_cache['response_cache_hits']}")
    print(f"Semantic cache hits         : {with_cache['semantic_cache_hits']}")
    print(f"Retrieval cache hits        : {with_cache['retrieval_cache_hits']}")
    print(f"Embedding cache hits        : {with_cache['embedding_cache_hits']}")
    print(f"Cost reduction              : {cost_reduction:.1%}")
    print(f"Latency reduction           : {latency_reduction:.1%}")


if __name__ == "__main__":
    run_demo()
