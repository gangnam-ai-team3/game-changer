from types import SimpleNamespace

from agents.evidence_rag.retrieval import embedding_rank


def test_embedding_rank_uses_installed_embedding_model(feedback):
    vectors = [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]]

    class Embeddings:
        def create(self, **kwargs):
            assert kwargs["model"] == "text-embedding-3-small"
            assert len(kwargs["input"]) == 3
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=vector) for vector in vectors]
            )

    ranked = embedding_rank(
        "probability",
        feedback.evidence[:2],
        client=SimpleNamespace(embeddings=Embeddings()),
        limit=1,
    )
    assert ranked == [feedback.evidence[0]]
