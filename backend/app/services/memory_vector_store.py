import os
import re
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.config import QDRANT_PATH
from app.core.database import list_user_memories
from app.core.models import MemoryItem
from app.services.embedding_client import (
    embed_texts,
    get_embedding_dimensions,
    get_embedding_model,
)

VECTOR_STORE_NAME = "qdrant"
MEMORY_COLLECTION_PREFIX = "memory_items"


def index_memory_item(memory: MemoryItem) -> dict:
    if memory.scope != "user" or memory.status != "active":
        delete_memory_item_vector(memory.memory_id)
        return {"indexed": 0, "collection": _collection_name()}

    content = memory.content.strip()
    if not content:
        delete_memory_item_vector(memory.memory_id)
        return {"indexed": 0, "collection": _collection_name()}

    vector = embed_texts([content])[0]
    client = _client()
    _ensure_collection(client, len(vector))

    vector_id = _vector_id(memory.memory_id)
    client.upsert(
        collection_name=_collection_name(),
        points=[
            PointStruct(
                id=vector_id,
                vector=vector,
                payload=_memory_payload(memory),
            )
        ],
    )
    return {
        "indexed": 1,
        "collection": _collection_name(),
        "embedding_model": get_embedding_model(),
        "vector_store": VECTOR_STORE_NAME,
    }


def delete_memory_item_vector(memory_id: str) -> None:
    client = _client()
    if not _collection_exists(client):
        return

    client.delete(
        collection_name=_collection_name(),
        points_selector=FilterSelector(
            filter=Filter(must=[_match("memory_id", memory_id)])
        ),
    )


def search_user_memories(
    user_id: str,
    query: str,
    top_k: int = 6,
    score_threshold: float = 0.15,
) -> list[dict]:
    if not query.strip():
        return []

    client = _client()
    if not _collection_exists(client):
        return []

    query_vector = embed_texts([query])[0]
    query_filter = Filter(
        must=[
            _match("user_id", user_id),
            _match("scope", "user"),
            _match("status", "active"),
        ]
    )
    hits = _search(query_vector, query_filter, limit=max(top_k * 3, top_k))
    filtered_hits = [
        hit for hit in hits if hit.get("score") is None or hit.get("score", 0) >= score_threshold
    ]
    return sorted(filtered_hits, key=_rank_hit, reverse=True)[:top_k]


def reindex_user_memories(user_id: str) -> dict:
    memories = list_user_memories(user_id, limit=500)
    indexed = 0
    for memory in memories:
        result = index_memory_item(memory)
        indexed += int(result.get("indexed", 0))
    return {
        "indexed": indexed,
        "collection": _collection_name(),
        "embedding_model": get_embedding_model(),
        "vector_store": VECTOR_STORE_NAME,
    }


def _client() -> QdrantClient:
    qdrant_url = os.getenv("QDRANT_URL")
    if qdrant_url:
        return QdrantClient(
            url=qdrant_url,
            api_key=os.getenv("QDRANT_API_KEY"),
        )

    QDRANT_PATH.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(QDRANT_PATH))


def _ensure_collection(client: QdrantClient, vector_size: int) -> None:
    if _collection_exists(client):
        return

    client.create_collection(
        collection_name=_collection_name(),
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )


def _collection_exists(client: QdrantClient) -> bool:
    return client.collection_exists(collection_name=_collection_name())


def _search(query_vector: list[float], query_filter: Filter, limit: int) -> list[dict]:
    client = _client()
    if hasattr(client, "query_points"):
        response = client.query_points(
            collection_name=_collection_name(),
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        points = response.points
    else:
        points = client.search(
            collection_name=_collection_name(),
            query_vector=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )

    return [_point_to_hit(point) for point in points]


def _memory_payload(memory: MemoryItem) -> dict:
    return {
        "memory_id": memory.memory_id,
        "user_id": memory.user_id,
        "scope": memory.scope,
        "scope_id": memory.scope_id,
        "memory_type": memory.memory_type,
        "content": memory.content,
        "normalized_key": memory.normalized_key or "",
        "importance": memory.importance,
        "confidence": memory.confidence,
        "status": memory.status,
        "source_type": memory.source_type,
        "source_id": memory.source_id or "",
        "updated_at": memory.updated_at or _now(),
        "embedding_model": get_embedding_model(),
    }


def _point_to_hit(point: object) -> dict:
    payload = dict(getattr(point, "payload", {}) or {})
    payload["score"] = getattr(point, "score", None)
    payload["vector_id"] = str(getattr(point, "id", ""))
    return payload


def _rank_hit(hit: dict) -> float:
    score = hit.get("score")
    importance = hit.get("importance")
    confidence = hit.get("confidence")
    score_value = float(score) if isinstance(score, (int, float)) else 0.0
    importance_value = float(importance) if isinstance(importance, (int, float)) else 0.5
    confidence_value = float(confidence) if isinstance(confidence, (int, float)) else 0.7
    return score_value * 0.7 + importance_value * 0.2 + confidence_value * 0.1


def _match(key: str, value: object) -> FieldCondition:
    return FieldCondition(key=key, match=MatchValue(value=value))


def _vector_id(memory_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"memory:{memory_id}"))


def _collection_name() -> str:
    configured_collection = os.getenv("QDRANT_MEMORY_COLLECTION")
    if configured_collection:
        return configured_collection

    model = _safe_collection_part(get_embedding_model())
    dimensions = get_embedding_dimensions() or "auto"
    return f"{MEMORY_COLLECTION_PREFIX}_{model}_{dimensions}"


def _safe_collection_part(value: str) -> str:
    safe_value = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return safe_value or "embedding"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
