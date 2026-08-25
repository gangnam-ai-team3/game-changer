from app.retriever import top_n_candidates


def test_top_n_candidates_orders_by_cosine_similarity():
    claim_embedding = [1.0, 0.0]
    chunk_embeddings = [[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]]
    chunk_ids = ["exact-match", "orthogonal", "close-match"]

    result = top_n_candidates(claim_embedding, chunk_embeddings, chunk_ids, n=2)

    assert result == ["exact-match", "close-match"]


def test_top_n_candidates_returns_empty_for_no_chunks():
    assert top_n_candidates([1.0, 0.0], [], [], n=5) == []


def test_top_n_candidates_caps_at_n():
    claim_embedding = [1.0, 0.0]
    chunk_embeddings = [[1.0, 0.0], [0.9, 0.1], [0.8, 0.2], [0.7, 0.3]]
    chunk_ids = ["a", "b", "c", "d"]

    result = top_n_candidates(claim_embedding, chunk_embeddings, chunk_ids, n=2)

    assert result == ["a", "b"]
