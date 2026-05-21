import os
import re
from collections import defaultdict
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

from app.config import DEFAULT_QDRANT_COLLECTION, QDRANT_PATH
from app.core.database import (
    delete_vector_index_records,
    list_document_chunks,
    save_vector_index_records,
)
from app.services.embedding_client import (
    embed_texts,
    get_embedding_dimensions,
    get_embedding_model,
)

VECTOR_STORE_NAME = "qdrant"


def index_document_chunks(project_id: str, chunks: list[dict]) -> dict:
    valid_chunks = [chunk for chunk in chunks if chunk.get("content", "").strip()]
    if not valid_chunks:
        delete_project_vectors(project_id)
        return {"indexed": 0, "collection": _collection_name()}

    texts = [chunk["content"] for chunk in valid_chunks]
    vectors = embed_texts(texts)
    if len(vectors) != len(valid_chunks):
        raise RuntimeError("embedding 结果数量和 chunks 数量不一致。")

    client = _client()
    _ensure_collection(client, len(vectors[0]))
    _delete_project_vectors(client, project_id)

    embedding_model = get_embedding_model()
    indexed_at = _now()
    points = []
    records = []

    for chunk, vector in zip(valid_chunks, vectors, strict=True):
        payload = _chunk_payload(project_id, chunk, embedding_model)
        vector_id = _vector_id(payload["chunk_id"])
        points.append(PointStruct(id=vector_id, vector=vector, payload=payload))
        records.append(
            {
                "chunk_id": payload["chunk_id"],
                "project_id": payload["project_id"],
                "paper_id": payload["paper_id"],
                "paper_version_id": payload["paper_version_id"],
                "vector_id": vector_id,
                "content_hash": payload["content_hash"],
                "embedding_model": embedding_model,
                "vector_store": VECTOR_STORE_NAME,
                "indexed_at": indexed_at,
            }
        )

    client.upsert(collection_name=_collection_name(), points=points)
    save_vector_index_records(records)

    return {
        "indexed": len(points),
        "collection": _collection_name(),
        "embedding_model": embedding_model,
    }


def search_within_paper(
    paper_version_id: str,
    query: str,
    top_k: int = 8,
    user_id: str = "local",
) -> list[dict]:
    query_vector = _embed_query(query)
    query_filter = Filter(
        must=[
            _match("paper_version_id", paper_version_id),
            _match("user_id", user_id),
        ]
    )
    return _search(query_vector, query_filter, limit=top_k)


def search_related_papers(
    source_paper_id: str,
    query: str,
    top_papers: int = 5,
    chunks_per_paper: int = 3,
    user_id: str = "local",
) -> list[dict]:
    query_vector = _embed_query(query)
    query_filter = Filter(
        must=[_match("user_id", user_id)],
        must_not=[_match("paper_id", source_paper_id)],
    )
    hits = _search(query_vector, query_filter, limit=max(top_papers * chunks_per_paper * 8, 40))
    grouped = _group_hits_by_paper(hits, chunks_per_paper)
    return grouped[:top_papers]


def delete_project_vectors(project_id: str) -> None:
    client = _client()
    _delete_project_vectors(client, project_id)


def reindex_project(project_id: str) -> dict:
    chunks = list_document_chunks(project_id)
    return index_document_chunks(project_id, chunks)


def _delete_project_vectors(client: QdrantClient, project_id: str) -> None:
    if not _collection_exists(client):
        delete_vector_index_records(project_id)
        return

    client.delete(
        collection_name=_collection_name(),
        points_selector=FilterSelector(
            filter=Filter(must=[_match("project_id", project_id)])
        ),
    )
    delete_vector_index_records(project_id)


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
    if not _collection_exists(client):
        return []

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


def _chunk_payload(project_id: str, chunk: dict, embedding_model: str) -> dict:
    metadata = chunk.get("metadata", {})
    return {
        "project_id": project_id,
        "paper_id": _required(metadata, "paper_id"),
        "paper_version_id": _required(metadata, "paper_version_id"),
        "user_id": _required(metadata, "user_id"),
        "chunk_id": _required(chunk, "chunk_id"),
        "document_title": metadata.get("document_title") or "",
        "section_title": metadata.get("section_title") or "",
        "hierarchy_path": metadata.get("hierarchy_path") or "",
        "page_start": metadata.get("page_start"),
        "page_end": metadata.get("page_end"),
        "element_type": metadata.get("element_type") or "unknown",
        "order_index": metadata.get("order_index") or 0,
        "content_hash": _required(metadata, "content_hash"),
        "embedding_model": embedding_model,
        "created_at": _now(),
    }


def _group_hits_by_paper(hits: list[dict], chunks_per_paper: int) -> list[dict]:
    grouped_hits: dict[str, list[dict]] = defaultdict(list)
    for hit in hits:
        paper_id = hit.get("paper_id")
        if not paper_id:
            continue
        if len(grouped_hits[paper_id]) < chunks_per_paper:
            grouped_hits[paper_id].append(hit)

    papers = []
    for paper_id, paper_hits in grouped_hits.items():
        scores = [hit["score"] for hit in paper_hits if hit.get("score") is not None]
        paper_score = max(scores) if scores else 0.0
        papers.append(
            {
                "paper_id": paper_id,
                "title": paper_hits[0].get("document_title") or "",
                "score": paper_score,
                "chunks": paper_hits,
            }
        )

    return sorted(papers, key=lambda item: item["score"], reverse=True)


def _point_to_hit(point: object) -> dict:
    payload = dict(getattr(point, "payload", {}) or {})
    payload["score"] = getattr(point, "score", None)
    payload["vector_id"] = str(getattr(point, "id", ""))
    return payload


def _embed_query(query: str) -> list[float]:
    if not query.strip():
        raise ValueError("检索问题不能为空。")
    return embed_texts([query])[0]


def _match(key: str, value: object) -> FieldCondition:
    return FieldCondition(key=key, match=MatchValue(value=value))


def _vector_id(chunk_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, chunk_id))


def _required(data: dict, key: str) -> str:
    value = data.get(key)
    if value is None or value == "":
        raise ValueError(f"缺少向量索引必要字段：{key}")
    return str(value)


def _collection_name() -> str:
    configured_collection = os.getenv("QDRANT_COLLECTION")
    if configured_collection:
        return configured_collection

    model = _safe_collection_part(get_embedding_model())
    dimensions = get_embedding_dimensions() or "auto"
    return f"{DEFAULT_QDRANT_COLLECTION}_{model}_{dimensions}"


def _safe_collection_part(value: str) -> str:
    safe_value = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return safe_value or "embedding"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
