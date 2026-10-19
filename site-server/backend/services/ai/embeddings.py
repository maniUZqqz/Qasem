"""Semantic (vector) product search on top of Ollama embeddings.

Feature-flagged: EMBEDDINGS_ENABLED=false (the default) means no embedding
call is ever made and every consumer falls back to keyword retrieval — the
main system does not have an embedding model installed yet. When enabled,
OLLAMA_MODEL_EMBEDDING must name a pulled Ollama embedding model
(e.g. `ollama pull nomic-embed-text`).
"""
import hashlib
import logging
import math

import requests
from django.conf import settings

from .ollama import OllamaError

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    if not settings.UPMARKET_AI.get("EMBEDDINGS_ENABLED"):
        return False
    # Embeddings are the one Ollama call not relayed through the processing
    # node (apps.compute carries chat/generate only). With Ollama on a node
    # there is nothing to POST to here, so say so once instead of raising on
    # every product save; keyword retrieval takes over as when disabled.
    if str(settings.UPMARKET_AI.get("OLLAMA_BASE_URL", "")).startswith("agent://"):
        logger.info("EMBEDDINGS_ENABLED ignored: Ollama is on a processing node (agent://), embeddings need a direct URL")
        return False
    return True


def embedding_model() -> str:
    return settings.UPMARKET_AI.get("MODEL_EMBEDDING", "nomic-embed-text")


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via the Ollama /api/embed endpoint."""
    conf = settings.UPMARKET_AI
    url = f"{conf['OLLAMA_BASE_URL'].rstrip('/')}/api/embed"
    try:
        response = requests.post(
            url,
            json={"model": embedding_model(), "input": texts},
            timeout=conf["OLLAMA_TIMEOUT"],
        )
        response.raise_for_status()
        embeddings = response.json().get("embeddings")
    except requests.RequestException as exc:
        raise OllamaError(f"Embedding request failed (model={embedding_model()}): {exc}") from exc
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise OllamaError("Embedding response did not contain one vector per input")
    return embeddings


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def product_text(product) -> str:
    """The text that represents a product in vector space."""
    parts = [product.name, product.brand, product.short_description, product.description]
    parts += [f"{a.key}: {a.value}" for a in product.attributes.all()]
    return "\n".join(p for p in parts if p)


def source_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def ensure_product_embedding(product):
    """Create/refresh the stored vector for one product. Returns the row, or
    None when the feature is disabled. Raises OllamaError on provider failure."""
    from apps.ai.models import ProductEmbedding

    if not is_enabled():
        return None
    text = product_text(product)
    digest = source_hash(text)
    row = ProductEmbedding.objects.filter(product=product).first()
    if row is not None and row.source_hash == digest and row.model == embedding_model():
        return row  # unchanged — no re-embed
    vector = embed_texts([text])[0]
    if row is None:
        row = ProductEmbedding(product=product)
    row.vector = vector
    row.model = embedding_model()
    row.source_hash = digest
    row.save()
    return row


def semantic_product_ids(store, query: str, limit: int = 12) -> list[int]:
    """Top product ids of `store` by cosine similarity to `query`.

    Returns [] when the feature is disabled, no vectors exist yet, or the
    embedding call fails — callers then use keyword retrieval, so a missing
    embedding model can never break the sales agent.
    """
    from apps.ai.models import ProductEmbedding

    if not is_enabled() or not query.strip():
        return []
    rows = list(
        ProductEmbedding.objects.filter(
            product__store=store, product__is_available=True
        ).values_list("product_id", "vector")
    )
    if not rows:
        return []
    try:
        query_vector = embed_texts([query])[0]
    except OllamaError as exc:
        logger.warning("Semantic search unavailable, falling back to keywords: %s", exc)
        return []
    scored = sorted(
        ((cosine(query_vector, vector), pid) for pid, vector in rows), reverse=True
    )
    return [pid for score, pid in scored[:limit] if score > 0]
