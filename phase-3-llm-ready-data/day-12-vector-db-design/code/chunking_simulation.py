"""
Day 12 — Vector Storage Design
Chunking Simulation

Demonstrates fixed-size and semantic chunking strategies,
chunk quality evaluation, and how chunk size affects retrieval quality.

Run: python chunking_simulation.py
"""

import re
import math
import random
import hashlib
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

random.seed(42)

# ─────────────────────────────────────────────────────────────────────────────
# MOCK EMBEDDING (inline, no external imports needed)
# ─────────────────────────────────────────────────────────────────────────────

EMBEDDING_DIM = 64  # reduced for simulation speed


def mock_embed(text: str, dim: int = EMBEDDING_DIM) -> List[float]:
    """
    Deterministic mock embedding based on text content.
    Words that appear in both query and document push cosine similarity higher.
    This simulates semantic similarity without a real model.
    """
    # Seed from text hash for determinism
    seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)

    # Base random vector
    vec = [rng.gauss(0, 1) for _ in range(dim)]

    # Inject signal: keywords shift specific dimensions
    keywords = {
        "checkout": [0, 1, 2],
        "payment": [0, 1, 3],
        "error": [0, 2, 4],
        "failed": [1, 2, 5],
        "cart": [0, 6, 7],
        "session": [3, 8, 9],
        "support": [4, 10, 11],
        "refund": [5, 12, 13],
        "account": [6, 14, 15],
        "login": [7, 16, 17],
        "password": [7, 18, 19],
        "shipping": [8, 20, 21],
        "order": [8, 22, 23],
        "billing": [5, 24, 25],
        "timeout": [2, 26, 27],
        "gateway": [1, 28, 29],
    }

    text_lower = text.lower()
    for keyword, dims in keywords.items():
        if keyword in text_lower:
            count = text_lower.count(keyword)
            for d in dims:
                vec[d] += 3.0 * count  # strong signal for matching keywords

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]

    return vec


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ─────────────────────────────────────────────────────────────────────────────
# TOKENIZER (simple whitespace + punctuation tokenizer)
# ─────────────────────────────────────────────────────────────────────────────

def simple_tokenize(text: str) -> List[str]:
    """Split text into tokens (words + punctuation)."""
    return re.findall(r"\w+|[^\w\s]", text)


def detokenize(tokens: List[str]) -> str:
    """Reconstruct text from tokens."""
    result = ""
    for i, tok in enumerate(tokens):
        if i == 0:
            result += tok
        elif re.match(r"[^\w]", tok):
            result += tok
        else:
            result += " " + tok
    return result


# ─────────────────────────────────────────────────────────────────────────────
# CHUNKING FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    """A text chunk with metadata."""
    chunk_id: str
    text: str
    token_count: int
    start_token: int
    end_token: int
    chunk_index: int
    strategy: str
    overlap_tokens: int = 0


def fixed_size_chunk(text: str, chunk_size: int = 512, overlap: int = 50) -> List[Chunk]:
    """
    Split text into fixed-size token chunks with overlap.

    Args:
        text: Input text to chunk
        chunk_size: Number of tokens per chunk
        overlap: Number of tokens to overlap between consecutive chunks

    Returns:
        List of Chunk objects
    """
    tokens = simple_tokenize(text)
    total_tokens = len(tokens)

    if total_tokens == 0:
        return []

    chunks = []
    chunk_index = 0
    start = 0

    while start < total_tokens:
        end = min(start + chunk_size, total_tokens)
        chunk_tokens = tokens[start:end]
        chunk_text = detokenize(chunk_tokens)

        chunk = Chunk(
            chunk_id=f"chunk_{chunk_index}",
            text=chunk_text,
            token_count=len(chunk_tokens),
            start_token=start,
            end_token=end,
            chunk_index=chunk_index,
            strategy=f"fixed_{chunk_size}tok",
            overlap_tokens=overlap if chunk_index > 0 else 0,
        )
        chunks.append(chunk)
        chunk_index += 1

        # Advance by (chunk_size - overlap) to create overlap
        step = chunk_size - overlap
        start += step

        # Avoid infinite loop on very small texts
        if step <= 0:
            break

    return chunks


def semantic_chunk(text: str) -> List[Chunk]:
    """
    Split text at natural semantic boundaries: paragraphs, then sentences.

    Strategy:
    1. First split on double newlines (paragraph boundaries)
    2. If a paragraph is still very long (>600 tokens), split on sentence boundaries
    3. Merge very short chunks (< 20 tokens) with the next chunk

    Args:
        text: Input text to chunk

    Returns:
        List of Chunk objects
    """
    # Step 1: Split on paragraph boundaries
    paragraphs = re.split(r"\n\n+", text.strip())

    # Step 2: Split long paragraphs on sentence boundaries
    raw_chunks = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        tokens = simple_tokenize(para)
        if len(tokens) > 600:
            # Split on sentence boundaries
            sentences = re.split(r"(?<=[.!?])\s+", para)
            raw_chunks.extend([s.strip() for s in sentences if s.strip()])
        else:
            raw_chunks.append(para)

    # Step 3: Merge very short chunks with the next one
    merged = []
    buffer = ""
    for chunk_text in raw_chunks:
        if buffer:
            combined = buffer + " " + chunk_text
            combined_tokens = simple_tokenize(combined)
            if len(simple_tokenize(buffer)) < 20:
                buffer = combined
                continue
            else:
                merged.append(buffer)
                buffer = chunk_text
        else:
            buffer = chunk_text

    if buffer:
        merged.append(buffer)

    # Build Chunk objects
    chunks = []
    token_cursor = 0
    for i, chunk_text in enumerate(merged):
        tokens = simple_tokenize(chunk_text)
        chunk = Chunk(
            chunk_id=f"semantic_chunk_{i}",
            text=chunk_text,
            token_count=len(tokens),
            start_token=token_cursor,
            end_token=token_cursor + len(tokens),
            chunk_index=i,
            strategy="semantic",
            overlap_tokens=0,
        )
        chunks.append(chunk)
        token_cursor += len(tokens)

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# CHUNK QUALITY EVALUATOR
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ChunkQualityReport:
    """Quality metrics for a set of chunks."""
    strategy: str
    num_chunks: int
    avg_token_count: float
    min_token_count: int
    max_token_count: int
    std_token_count: float
    boundary_quality_score: float   # 0–1: how well chunks end at sentence boundaries
    overlap_ratio: float            # fraction of tokens that are overlapping
    coverage_ratio: float           # fraction of original text covered
    quality_score: float            # composite score 0–1


class ChunkQualityEvaluator:
    """
    Evaluates the quality of a chunking strategy.

    Metrics:
    - avg_token_count: average chunk size (closer to target = better)
    - boundary_quality: fraction of chunks ending at sentence/paragraph boundary
    - overlap_ratio: fraction of total tokens that are overlap (lower = more efficient)
    - coverage_ratio: fraction of original text covered (should be ~1.0)
    - quality_score: composite weighted score
    """

    def __init__(self, target_chunk_size: int = 512):
        self.target_chunk_size = target_chunk_size

    def evaluate(self, chunks: List[Chunk], original_text: str) -> ChunkQualityReport:
        """Evaluate chunk quality and return a report."""
        if not chunks:
            return ChunkQualityReport(
                strategy="unknown", num_chunks=0, avg_token_count=0,
                min_token_count=0, max_token_count=0, std_token_count=0,
                boundary_quality_score=0, overlap_ratio=0,
                coverage_ratio=0, quality_score=0
            )

        strategy = chunks[0].strategy
        token_counts = [c.token_count for c in chunks]
        avg_tokens = sum(token_counts) / len(token_counts)
        min_tokens = min(token_counts)
        max_tokens = max(token_counts)

        # Standard deviation
        variance = sum((t - avg_tokens) ** 2 for t in token_counts) / len(token_counts)
        std_tokens = math.sqrt(variance)

        # Boundary quality: fraction of chunks ending at sentence boundary
        sentence_endings = re.compile(r"[.!?]\s*$")
        boundary_count = sum(
            1 for c in chunks if sentence_endings.search(c.text.strip())
        )
        boundary_quality = boundary_count / len(chunks)

        # Overlap ratio: total overlap tokens / total tokens indexed
        total_overlap = sum(c.overlap_tokens for c in chunks)
        total_indexed = sum(c.token_count for c in chunks)
        overlap_ratio = total_overlap / total_indexed if total_indexed > 0 else 0

        # Coverage ratio: unique tokens covered / original tokens
        original_tokens = len(simple_tokenize(original_text))
        # For fixed-size with overlap, unique coverage = last chunk end - first chunk start
        if chunks:
            unique_tokens_covered = chunks[-1].end_token - chunks[0].start_token
        else:
            unique_tokens_covered = 0
        coverage_ratio = min(unique_tokens_covered / original_tokens, 1.0) if original_tokens > 0 else 0

        # Composite quality score (weighted)
        # - boundary quality: 40% weight (most important for semantic coherence)
        # - coverage: 30% weight (must cover the document)
        # - size consistency: 20% weight (predictable chunks)
        # - overlap efficiency: 10% weight (less overlap = more efficient)
        size_consistency = max(0, 1 - (std_tokens / (avg_tokens + 1)))
        overlap_efficiency = 1 - min(overlap_ratio, 1.0)

        quality_score = (
            0.40 * boundary_quality +
            0.30 * coverage_ratio +
            0.20 * size_consistency +
            0.10 * overlap_efficiency
        )

        return ChunkQualityReport(
            strategy=strategy,
            num_chunks=len(chunks),
            avg_token_count=round(avg_tokens, 1),
            min_token_count=min_tokens,
            max_token_count=max_tokens,
            std_token_count=round(std_tokens, 1),
            boundary_quality_score=round(boundary_quality, 3),
            overlap_ratio=round(overlap_ratio, 3),
            coverage_ratio=round(coverage_ratio, 3),
            quality_score=round(quality_score, 3),
        )

    def print_report(self, report: ChunkQualityReport) -> None:
        """Pretty-print a quality report."""
        bar_len = 30
        score_bar = "█" * int(report.quality_score * bar_len) + "░" * (bar_len - int(report.quality_score * bar_len))
        bq_bar = "█" * int(report.boundary_quality_score * bar_len) + "░" * (bar_len - int(report.boundary_quality_score * bar_len))

        print(f"  Strategy:          {report.strategy}")
        print(f"  Chunks:            {report.num_chunks}")
        print(f"  Avg tokens/chunk:  {report.avg_token_count}")
        print(f"  Min/Max tokens:    {report.min_token_count} / {report.max_token_count}")
        print(f"  Std deviation:     {report.std_token_count}")
        print(f"  Boundary quality:  [{bq_bar}] {report.boundary_quality_score:.1%}")
        print(f"  Overlap ratio:     {report.overlap_ratio:.1%}")
        print(f"  Coverage ratio:    {report.coverage_ratio:.1%}")
        print(f"  Quality score:     [{score_bar}] {report.quality_score:.3f}")


# ─────────────────────────────────────────────────────────────────────────────
# RETRIEVAL SIMULATION
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RetrievalResult:
    """A single retrieval result."""
    chunk: Chunk
    score: float
    rank: int


def retrieve(
    query: str,
    chunks: List[Chunk],
    top_k: int = 3,
) -> List[RetrievalResult]:
    """
    Embed query and all chunks, return top-K by cosine similarity.
    """
    query_vec = mock_embed(query)
    scored = []
    for chunk in chunks:
        chunk_vec = mock_embed(chunk.text)
        score = cosine_similarity(query_vec, chunk_vec)
        scored.append((chunk, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    return [
        RetrievalResult(chunk=c, score=round(s, 4), rank=i + 1)
        for i, (c, s) in enumerate(scored[:top_k])
    ]


def print_retrieval_results(results: List[RetrievalResult], query: str) -> None:
    """Print retrieval results with highlighted relevant content."""
    print(f"  Query: \"{query}\"")
    print(f"  Top {len(results)} results:")
    for r in results:
        preview = r.chunk.text[:120].replace("\n", " ")
        if len(r.chunk.text) > 120:
            preview += "..."
        bar = "█" * int(r.score * 20) + "░" * (20 - int(r.score * 20))
        print(f"    #{r.rank} [{bar}] {r.score:.4f} | {r.chunk.strategy} | {r.chunk.token_count} tok")
        print(f"         \"{preview}\"")


# ─────────────────────────────────────────────────────────────────────────────
# DEMO TEXT
# ─────────────────────────────────────────────────────────────────────────────

SUPPORT_TICKET = """
Ticket #TKT-20241215-8821
Customer: Sarah Chen (user_id: usr_4421)
Plan: Professional ($99/month)
Submitted: 2024-12-15 14:32:07 UTC

Subject: Cannot complete checkout - payment keeps failing

Hi support team,

I've been trying to complete my checkout for the past two hours and keep getting an error. I'm trying to upgrade my subscription from the Basic plan to the Professional plan. Every time I click the "Complete Purchase" button, I get a red error message that says "Payment processing failed. Please try again." with error code 402.

I've tried three different credit cards (Visa ending in 4242, Mastercard ending in 5555, and Amex ending in 3782) and all of them fail with the same error. I've also tried in Chrome, Firefox, and Safari. Same result in all browsers.

My billing address is correct. I've double-checked the card numbers, expiration dates, and CVV codes. Everything looks right on my end.

This is really frustrating because I need the Professional plan features for a client presentation tomorrow morning. I'm losing time and I'm worried I won't be able to get this resolved in time.

Can you please help me figure out what's going on? Is there a problem with your payment gateway? Is my account flagged for some reason?

Thanks,
Sarah

---

Agent Response (2024-12-15 14:45:22 UTC)
Agent: Marcus Rodriguez

Hi Sarah,

Thank you for reaching out and I'm sorry you're experiencing this issue. I can see your account in our system and I've pulled up the payment logs.

After reviewing the error logs, I can see that the payment failures are being caused by our payment gateway (Stripe) flagging your account for a security review. This is an automated process that sometimes triggers when multiple payment methods are tried in quick succession. It's not a reflection of any problem with your cards or your account.

Here's what I've done to resolve this:

1. I've manually cleared the security flag on your account
2. I've added a note to your account so this won't trigger again for 30 days
3. I've applied a 10% discount to your first month of Professional as an apology for the inconvenience

Please try the checkout again now. If you still experience issues, please reply to this ticket and I'll escalate to our billing team immediately.

Regarding your timeline: if you need the Professional features urgently for tomorrow, I can manually activate them on your account right now while you complete the payment at your convenience. Just let me know.

Best,
Marcus

---

Customer Reply (2024-12-15 15:02:44 UTC)

Marcus, that worked! I was able to complete the checkout just now using my Visa card. The Professional plan features are showing up in my account.

Thank you so much for the quick response and for the discount. That was really kind. I'll definitely be sticking with this service.

One question: will this security flag issue happen again in the future? I sometimes switch between payment methods depending on which card has the best rewards for that month.

Thanks again,
Sarah

---

Agent Response (2024-12-15 15:18:09 UTC)
Agent: Marcus Rodriguez

Hi Sarah,

Glad to hear it's working! 

Regarding your question about the security flag: the 30-day grace period I added means you can switch payment methods freely for the next month without triggering the automated review. After that, if you switch more than 3 payment methods within a 10-minute window, the system may flag it again. 

My recommendation: if you plan to switch payment methods, do it one at a time with a few minutes between attempts. That should prevent the automated system from flagging your account.

I'm marking this ticket as resolved. If you have any other questions, feel free to open a new ticket.

Best,
Marcus

---

Resolution Summary:
- Root cause: Stripe automated security flag triggered by multiple payment method attempts
- Resolution: Manual flag clearance + 30-day grace period applied
- Compensation: 10% discount on first Professional month
- Time to resolution: 46 minutes
- Customer satisfaction: Positive (explicit thank you in reply)
- Follow-up required: None
- Ticket status: CLOSED
"""


# ─────────────────────────────────────────────────────────────────────────────
# MAIN DEMO
# ─────────────────────────────────────────────────────────────────────────────

def separator(title: str = "", width: int = 80) -> None:
    if title:
        pad = (width - len(title) - 2) // 2
        print("─" * pad + f" {title} " + "─" * (width - pad - len(title) - 2))
    else:
        print("─" * width)


def main():
    print("=" * 80)
    print("  DAY 12 — VECTOR STORAGE DESIGN")
    print("  Chunking Simulation")
    print("=" * 80)
    print()

    # ── 1. Show the source document ──────────────────────────────────────────
    separator("SOURCE DOCUMENT")
    original_tokens = simple_tokenize(SUPPORT_TICKET)
    print(f"  Support ticket: {len(original_tokens)} tokens")
    print(f"  Preview: \"{SUPPORT_TICKET[:200].strip()}...\"")
    print()

    # ── 2. Apply all chunking strategies ─────────────────────────────────────
    separator("CHUNKING STRATEGIES")

    strategies = {
        "Small Fixed (128 tok, 20 overlap)": fixed_size_chunk(SUPPORT_TICKET, chunk_size=128, overlap=20),
        "Medium Fixed (512 tok, 50 overlap)": fixed_size_chunk(SUPPORT_TICKET, chunk_size=512, overlap=50),
        "Large Fixed (1024 tok, 100 overlap)": fixed_size_chunk(SUPPORT_TICKET, chunk_size=1024, overlap=100),
        "Semantic (paragraph/sentence)": semantic_chunk(SUPPORT_TICKET),
    }

    for name, chunks in strategies.items():
        print(f"\n  [{name}]")
        print(f"  → {len(chunks)} chunks produced")
        for i, chunk in enumerate(chunks[:3]):
            preview = chunk.text[:80].replace("\n", " ")
            print(f"    Chunk {i}: {chunk.token_count} tok | \"{preview}...\"")
        if len(chunks) > 3:
            print(f"    ... and {len(chunks) - 3} more chunks")

    # ── 3. Quality evaluation ─────────────────────────────────────────────────
    separator("CHUNK QUALITY EVALUATION")
    evaluator = ChunkQualityEvaluator(target_chunk_size=512)

    reports = {}
    for name, chunks in strategies.items():
        report = evaluator.evaluate(chunks, SUPPORT_TICKET)
        reports[name] = report
        print(f"\n  ┌─ {name}")
        evaluator.print_report(report)

    # ── 4. Quality comparison table ───────────────────────────────────────────
    separator("QUALITY COMPARISON TABLE")
    print(f"\n  {'Strategy':<35} {'Chunks':>6} {'Avg Tok':>8} {'Boundary':>10} {'Quality':>9}")
    print(f"  {'─'*35} {'─'*6} {'─'*8} {'─'*10} {'─'*9}")
    for name, report in reports.items():
        short_name = name[:34]
        print(
            f"  {short_name:<35} {report.num_chunks:>6} "
            f"{report.avg_token_count:>8.0f} "
            f"{report.boundary_quality_score:>9.1%} "
            f"{report.quality_score:>9.3f}"
        )

    # ── 5. Retrieval simulation ───────────────────────────────────────────────
    separator("RETRIEVAL SIMULATION")
    query = "checkout error payment failed"
    print(f"\n  Embedding all chunks and running similarity search...")
    print(f"  Query: \"{query}\"")
    print()

    best_results = {}
    for name, chunks in strategies.items():
        results = retrieve(query, chunks, top_k=3)
        best_results[name] = results
        print(f"  ┌─ {name}")
        print_retrieval_results(results, query)
        print()

    # ── 6. Retrieval comparison ───────────────────────────────────────────────
    separator("RETRIEVAL COMPARISON — TOP-1 SCORE PER STRATEGY")
    print()
    print(f"  {'Strategy':<35} {'Top-1 Score':>12} {'Top-1 Tokens':>13} {'Contains Answer':>16}")
    print(f"  {'─'*35} {'─'*12} {'─'*13} {'─'*16}")

    answer_keywords = {"checkout", "payment", "error", "failed", "402"}
    for name, results in best_results.items():
        if results:
            top = results[0]
            text_lower = top.chunk.text.lower()
            contains = sum(1 for kw in answer_keywords if kw in text_lower)
            has_answer = "✅ YES" if contains >= 3 else ("⚠️  PARTIAL" if contains >= 1 else "❌ NO")
            short_name = name[:34]
            print(
                f"  {short_name:<35} {top.score:>12.4f} "
                f"{top.chunk.token_count:>13} "
                f"{has_answer:>16}"
            )

    # ── 7. Key insights ───────────────────────────────────────────────────────
    separator("KEY INSIGHTS")
    print("""
  1. SMALL CHUNKS (128 tok):
     → High precision: the top result is a tight, focused chunk
     → Low recall: surrounding context is split across many chunks
     → Best for: specific fact lookup ("what was the error code?")

  2. MEDIUM CHUNKS (512 tok):
     → Balanced: top result contains the error + enough context
     → The LLM gets the full picture without noise
     → Best for: general RAG, support assistants

  3. LARGE CHUNKS (1024 tok):
     → High recall: answer is definitely in the retrieved chunk
     → Low precision: chunk contains many unrelated topics
     → LLM must filter through noise to find the answer
     → Best for: summarization tasks

  4. SEMANTIC CHUNKS:
     → Best boundary quality: each chunk is a complete semantic unit
     → Variable sizes but coherent meaning
     → Best for: structured documents like support tickets, articles

  RECOMMENDATION for this series:
  → User events: no chunking (each event is atomic)
  → Support tickets: semantic chunking or medium fixed (512 tok, 50 overlap)
  → Long documents: semantic chunking at paragraph boundaries
""")

    separator()
    print("  Chunking simulation complete.")
    print()


if __name__ == "__main__":
    main()
