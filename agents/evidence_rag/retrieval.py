from __future__ import annotations

from math import sqrt

from contracts import EvidenceItem


def embedding_rank(
    query: str,
    evidence: list[EvidenceItem],
    *,
    client,
    model: str = "text-embedding-3-small",
    limit: int = 100,
) -> list[EvidenceItem]:
    if not evidence:
        return []
    response = client.embeddings.create(
        model=model,
        input=[query, *(item.summary for item in evidence)],
    )
    vectors = [item.embedding for item in response.data]
    query_vector = vectors[0]
    scored = [
        (_cosine(query_vector, vector), item)
        for vector, item in zip(vectors[1:], evidence, strict=True)
    ]
    return [item for _, item in sorted(scored, key=lambda pair: pair[0], reverse=True)[:limit]]


def _cosine(left: list[float], right: list[float]) -> float:
    denominator = sqrt(sum(value * value for value in left)) * sqrt(sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator if denominator else 0
