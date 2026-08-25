import numpy as np


def top_n_candidates(
    claim_embedding: list[float],
    chunk_embeddings: list[list[float]],
    chunk_ids: list[str],
    *,
    n: int,
) -> list[str]:
    if not chunk_embeddings:
        return []
    claim_vec = np.array(claim_embedding)
    chunk_matrix = np.array(chunk_embeddings)
    claim_norm = claim_vec / (np.linalg.norm(claim_vec) + 1e-10)
    chunk_norms = chunk_matrix / (np.linalg.norm(chunk_matrix, axis=1, keepdims=True) + 1e-10)
    similarities = chunk_norms @ claim_norm
    top_indices = np.argsort(-similarities)[:n]
    return [chunk_ids[i] for i in top_indices]
