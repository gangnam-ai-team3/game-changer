import asyncio

from . import claim_extractor, embedder, judge, retriever


async def run_audit(
    *,
    anthropic_client,
    voyage_client,
    settings,
    response_text: str,
    source_chunks: list[dict],
) -> dict:
    if not response_text.strip():
        return {"claims": [], "grounded_ratio": None}

    claims = await claim_extractor.extract_claims(
        anthropic_client, model=settings.claim_extract_model, response_text=response_text
    )
    if not claims:
        return {"claims": [], "grounded_ratio": None}

    if not source_chunks:
        return {
            "claims": [
                {
                    "claim_text": c,
                    "verdict": "not_grounded",
                    "citations": [],
                    "rationale": "no source chunks provided",
                }
                for c in claims
            ],
            "grounded_ratio": 0.0,
        }

    chunk_ids = [c["id"] for c in source_chunks]
    chunk_by_id = {c["id"]: c["text"] for c in source_chunks}

    chunk_embeddings, claim_embeddings = await asyncio.gather(
        embedder.embed_texts(
            voyage_client, model=settings.embedding_model,
            texts=[c["text"] for c in source_chunks],
        ),
        embedder.embed_texts(voyage_client, model=settings.embedding_model, texts=claims),
    )

    semaphore = asyncio.Semaphore(settings.judge_concurrency)

    async def judge_one(claim_text: str, claim_embedding: list[float]) -> dict:
        candidate_ids = retriever.top_n_candidates(
            claim_embedding, chunk_embeddings, chunk_ids, n=settings.top_n_candidates
        )
        candidate_chunks = [{"id": cid, "text": chunk_by_id[cid]} for cid in candidate_ids]
        async with semaphore:
            try:
                result = await judge.judge_claim(
                    anthropic_client,
                    model=settings.claim_judge_model,
                    claim_text=claim_text,
                    candidate_chunks=candidate_chunks,
                )
                return {"claim_text": claim_text, **result}
            except judge.JudgeError:
                return {
                    "claim_text": claim_text,
                    "verdict": "judgment_failed",
                    "citations": [],
                    "rationale": "judge failed after retries",
                }

    results = await asyncio.gather(
        *(judge_one(c, e) for c, e in zip(claims, claim_embeddings))
    )

    gradeable = [r for r in results if r["verdict"] != "judgment_failed"]
    grounded = [r for r in gradeable if r["verdict"] == "grounded"]
    grounded_ratio = (len(grounded) / len(gradeable)) if gradeable else None

    return {"claims": results, "grounded_ratio": grounded_ratio}
