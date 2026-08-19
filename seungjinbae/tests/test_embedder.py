from types import SimpleNamespace
from unittest.mock import MagicMock

from app.embedder import embed_texts


async def test_embed_texts_returns_embeddings_from_client():
    client = MagicMock()
    client.embed.return_value = SimpleNamespace(embeddings=[[0.1, 0.2], [0.3, 0.4]])

    result = await embed_texts(client, model="voyage-3", texts=["a", "b"])

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    client.embed.assert_called_once_with(["a", "b"], model="voyage-3")


async def test_embed_texts_returns_empty_list_for_no_texts():
    client = MagicMock()

    result = await embed_texts(client, model="voyage-3", texts=[])

    assert result == []
    client.embed.assert_not_called()


async def test_embed_texts_batches_large_inputs_and_preserves_order():
    client = MagicMock()

    def fake_embed(batch, model):
        return SimpleNamespace(embeddings=[[float(i)] for i in range(len(batch))])

    client.embed.side_effect = fake_embed

    texts = [f"text-{i}" for i in range(5)]
    result = await embed_texts(client, model="voyage-3", texts=texts, batch_size=2)

    assert result == [[0.0], [1.0], [0.0], [1.0], [0.0]]
    assert client.embed.call_count == 3
