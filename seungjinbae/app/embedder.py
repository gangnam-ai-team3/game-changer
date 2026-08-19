import asyncio

DEFAULT_BATCH_SIZE = 100


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def embed_texts(
    client, *, model: str, texts: list[str], batch_size: int = DEFAULT_BATCH_SIZE
) -> list[list[float]]:
    if not texts:
        return []

    batches = list(_batches(texts, batch_size))
    results = await asyncio.gather(
        *(asyncio.to_thread(client.embed, batch, model=model) for batch in batches)
    )

    embeddings: list[list[float]] = []
    for result in results:
        embeddings.extend(result.embeddings)
    return embeddings
