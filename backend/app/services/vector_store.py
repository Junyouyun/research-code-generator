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
from app.services.keyword_store import search_keyword_chunks
from app.services.retrieval_query import build_retrieval_queries
from app.services.retrieval_reranker import rerank_retrieval_hits

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


def search_within_paper_multi_query(
    paper_version_id: str,
    question: str,
    top_k: int = 8,
    per_query_k: int = 12,
    user_id: str = "local",
    max_queries: int = 6,
) -> dict:
    query_plan = build_retrieval_queries(question, max_queries=max_queries)
    queries = query_plan["expanded_queries"]
    if not queries:
        raise ValueError("检索问题不能为空。")

    query_vectors = embed_texts(queries)
    if len(query_vectors) != len(queries):
        raise RuntimeError("embedding 结果数量和 query 数量不一致。")

    query_filter = Filter(
        must=[
            _match("paper_version_id", paper_version_id),
            _match("user_id", user_id),
        ]
    )
    client = _client()
    if not _collection_exists(client):
        return {**query_plan, "hits": [], "query_results": []}

    candidates: dict[str, dict] = {}
    query_results = []
    for query, query_vector in zip(queries, query_vectors, strict=True):
        hits = _search_with_client(client, query_vector, query_filter, limit=per_query_k)
        query_results.append(
            {
                "query": query,
                "returned_chunk_ids": [hit.get("chunk_id") for hit in hits if hit.get("chunk_id")],
            }
        )
        for rank, hit in enumerate(hits, start=1):
            chunk_id = hit.get("chunk_id")
            if not chunk_id:
                continue
            candidate = candidates.setdefault(
                chunk_id,
                {
                    **hit,
                    "source_queries": [],
                    "source_scores": {},
                    "query_ranks": {},
                    "best_vector_score": hit.get("score") or 0.0,
                },
            )
            score = float(hit.get("score") or 0.0)
            candidate["best_vector_score"] = max(float(candidate.get("best_vector_score") or 0.0), score)
            candidate["source_scores"][query] = score
            candidate["query_ranks"][query] = rank
            if query not in candidate["source_queries"]:
                candidate["source_queries"].append(query)

    keyword_retrieval = search_keyword_chunks(
        paper_version_id=paper_version_id,
        user_id=user_id,
        queries=queries,
        per_query_k=per_query_k,
    )
    for keyword_hit in keyword_retrieval["hits"]:
        chunk_id = keyword_hit.get("chunk_id")
        if not chunk_id:
            continue
        candidate = candidates.setdefault(
            chunk_id,
            {
                **keyword_hit,
                "source_queries": [],
                "source_scores": {},
                "query_ranks": {},
                "best_vector_score": 0.0,
                "retrieval_sources": [],
            },
        )
        candidate["keyword_score"] = max(
            float(candidate.get("keyword_score") or 0.0),
            float(keyword_hit.get("keyword_score") or 0.0),
        )
        candidate.setdefault("keyword_source_queries", [])
        for query in keyword_hit.get("keyword_source_queries", []):
            if query not in candidate["keyword_source_queries"]:
                candidate["keyword_source_queries"].append(query)
        candidate.setdefault("keyword_ranks", {})
        candidate["keyword_ranks"].update(keyword_hit.get("keyword_ranks", {}))
        candidate.setdefault("retrieval_sources", [])
        if "keyword" not in candidate["retrieval_sources"]:
            candidate["retrieval_sources"].append("keyword")

    merged_hits = []
    for candidate in candidates.values():
        candidate.setdefault("retrieval_sources", [])
        if candidate.get("best_vector_score") and "dense" not in candidate["retrieval_sources"]:
            candidate["retrieval_sources"].append("dense")
        candidate["score"] = _hybrid_score(candidate)
        merged_hits.append(candidate)
    merged_hits.sort(key=lambda hit: (hit.get("score") or 0.0, hit.get("best_vector_score") or 0.0), reverse=True)
    rerank_pool = merged_hits[:top_k]
    reranked_hits = rerank_retrieval_hits(
        question=question,
        intent=query_plan.get("intent") or "general",
        hits=rerank_pool,
        target_sections=query_plan.get("target_sections", []),
        top_k=top_k,
    )

    return {
        **query_plan,
        "hits": reranked_hits,
        "query_results": query_results,
        "keyword_results": keyword_retrieval["query_results"],
        "rerank_mode": "lightweight_section_boost",
        "retrieval_mode": "hybrid_dense_keyword",
    }


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

    return _search_with_client(client, query_vector, query_filter, limit)


def _search_with_client(
    client: QdrantClient,
    query_vector: list[float],
    query_filter: Filter,
    limit: int,
) -> list[dict]:
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


def _multi_query_score(hit: dict) -> float:
    best_vector_score = float(hit.get("best_vector_score") or 0.0)
    source_queries = hit.get("source_queries") if isinstance(hit.get("source_queries"), list) else []
    query_ranks = hit.get("query_ranks") if isinstance(hit.get("query_ranks"), dict) else {}
    coverage_bonus = min(len(source_queries), 4) * 0.025
    rank_bonus = 0.0
    for rank in query_ranks.values():
        try:
            rank_bonus += 0.04 / max(int(rank), 1)
        except (TypeError, ValueError):
            continue
    return best_vector_score + coverage_bonus + rank_bonus


def _hybrid_score(hit: dict) -> float:
    dense_score = _multi_query_score(hit)
    keyword_score = float(hit.get("keyword_score") or 0.0)
    keyword_queries = hit.get("keyword_source_queries") if isinstance(hit.get("keyword_source_queries"), list) else []
    keyword_signal = min(keyword_score + len(keyword_queries) * 0.02, 1.0)
    if float(hit.get("best_vector_score") or 0.0) > 0:
        return dense_score + keyword_signal * 0.04
    return 0.45 + keyword_signal * 0.08


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
