from app.core.database import (
    list_document_chunks_by_ids,
    list_neighbor_document_chunks,
    list_recent_conversation_messages,
)
from app.core.models import Project
from app.services.project_memory import get_project_memory_context
from app.services.query_intent import should_expand_to_related_papers
from app.services.user_memory import get_user_memory_context


class ContextBuildError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def build_qa_context(
    project: Project,
    user_id: str,
    conversation_id: str,
    question: str,
) -> dict:
    if not project.paper_version_id:
        raise ContextBuildError(409, "project has no paper_version_id")

    expanded = should_expand_to_related_papers(question)
    current_top_k = 6 if expanded else 8
    memory_top_k = 6

    conversation_context = _conversation_context(
        list_recent_conversation_messages(
            conversation_id,
            user_id,
            limit=12,
        )
    )
    project_memory_context = get_project_memory_context(project.project_id, user_id, limit=12)
    user_memory_context = get_user_memory_context(user_id, question, limit=memory_top_k)
    graph_context = _search_graph_context_safely(project, user_id, question)

    from app.services.vector_store import search_related_papers, search_within_paper_multi_query

    current_retrieval = search_within_paper_multi_query(
        paper_version_id=project.paper_version_id,
        question=question,
        top_k=current_top_k,
        per_query_k=max(current_top_k * 2, 12),
        user_id=user_id,
    )
    current_hits = current_retrieval["hits"]
    vector_chunk_ids = [hit["chunk_id"] for hit in current_hits if hit.get("chunk_id")]
    vector_chunks = list_document_chunks_by_ids(project.project_id, vector_chunk_ids)
    graph_evidence_chunk_ids = _graph_source_chunk_ids(graph_context, limit=6)
    graph_evidence_chunks = list_document_chunks_by_ids(project.project_id, graph_evidence_chunk_ids)
    neighbor_chunks = _neighbor_chunks(project.project_id, current_hits, vector_chunk_ids)
    current_chunks = _merge_context_chunks(
        graph_evidence_chunks,
        vector_chunks,
        neighbor_chunks,
        limit=current_top_k + 14,
    )
    current_chunk_ids = [chunk["chunk_id"] for chunk in current_chunks if chunk.get("chunk_id")]
    if not current_chunks:
        raise ContextBuildError(404, "relevant document chunks not found")

    related_papers = []
    if expanded:
        if not project.paper_id:
            raise ContextBuildError(409, "project has no paper_id")
        related_papers = search_related_papers(
            source_paper_id=project.paper_id,
            query=question,
            top_papers=5,
            chunks_per_paper=3,
            user_id=user_id,
        )
        related_papers = _attach_related_chunk_content(related_papers)

    return {
        "conversation_context": conversation_context,
        "project_memory_context": project_memory_context,
        "user_memory_context": user_memory_context,
        "graph_context": graph_context,
        "current_paper_chunks": current_chunks,
        "related_papers": related_papers,
        "retrieval_trace": {
            "expanded": expanded,
            "retrieval_mode": current_retrieval.get("retrieval_mode", "multi_query_dense"),
            "intent": current_retrieval.get("intent"),
            "question_type": current_retrieval.get("question_type"),
            "original_query": current_retrieval.get("original_query"),
            "rewritten_query": " | ".join(current_retrieval.get("expanded_queries", [])),
            "rewritten_queries": current_retrieval.get("expanded_queries", []),
            "query_results": current_retrieval.get("query_results", []),
            "keyword_results": current_retrieval.get("keyword_results", []),
            "rerank_mode": current_retrieval.get("rerank_mode"),
            "chunk_top_k": current_top_k,
            "memory_top_k": memory_top_k,
            "conversation_messages": len(conversation_context),
            "project_memories": len(project_memory_context),
            "user_memories": len(user_memory_context),
            "graph_entities": len(graph_context.get("entities", [])),
            "graph_relations": len(graph_context.get("relations", [])),
            "vector_chunk_ids": vector_chunk_ids,
            "graph_evidence_chunk_ids": [chunk["chunk_id"] for chunk in graph_evidence_chunks if chunk.get("chunk_id")],
            "neighbor_chunk_ids": [chunk["chunk_id"] for chunk in neighbor_chunks if chunk.get("chunk_id")],
            "current_chunk_ids": current_chunk_ids,
            "final_chunk_ids": current_chunk_ids,
            "current_hits": _compact_hits(current_hits),
            "related_papers": len(related_papers),
        },
    }


def _conversation_context(messages: list) -> list[dict]:
    return [
        {
            "role": message.role,
            "content": message.content,
        }
        for message in messages
        if message.role in {"user", "assistant"} and message.content
    ]


def _search_graph_context_safely(project: Project, user_id: str, question: str) -> dict:
    try:
        from app.services.knowledge_graph_store import search_graph_context

        return search_graph_context(
            project_id=project.project_id,
            user_id=user_id,
            query=question,
            limit_entities=8,
            limit_relations=20,
            depth=1,
        )
    except Exception:
        return {"entities": [], "relations": [], "paths": []}


def _graph_source_chunk_ids(graph_context: dict, limit: int = 6) -> list[str]:
    ids = []
    for key in ("relations", "entities"):
        items = graph_context.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for chunk_id in item.get("source_chunk_ids", []):
                if chunk_id and chunk_id not in ids:
                    ids.append(str(chunk_id))
                if len(ids) >= limit:
                    return ids
    return ids


def _neighbor_chunks(project_id: str, hits: list[dict], vector_chunk_ids: list[str]) -> list[dict]:
    order_indices = []
    for hit in hits[:4]:
        order_index = hit.get("order_index")
        if order_index is None:
            continue
        try:
            order_indices.append(int(order_index))
        except (TypeError, ValueError):
            continue

    excluded_ids = set(vector_chunk_ids)
    chunks = []
    for chunk in list_neighbor_document_chunks(project_id, order_indices, window=1, limit=16):
        chunk_id = chunk.get("chunk_id")
        if not chunk_id or chunk_id in excluded_ids or _is_reference_chunk(chunk):
            continue
        chunks.append(chunk)
        if len(chunks) >= 8:
            break
    return chunks


def _merge_context_chunks(*groups: list[dict], limit: int) -> list[dict]:
    merged = []
    seen = set()
    for group in groups:
        for chunk in group:
            chunk_id = chunk.get("chunk_id")
            if not chunk_id or chunk_id in seen or _is_reference_chunk(chunk):
                continue
            seen.add(chunk_id)
            merged.append(chunk)
            if len(merged) >= limit:
                return merged
    return merged


def _is_reference_chunk(chunk: dict) -> bool:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    section_title = str(metadata.get("section_title") or chunk.get("title") or "").lower()
    element_type = str(metadata.get("element_type") or "").lower()
    return section_title.strip() in {"references", "reference"} or element_type == "reference"


def _attach_related_chunk_content(related_papers: list[dict]) -> list[dict]:
    chunks_by_project: dict[str, list[str]] = {}
    for paper in related_papers:
        for chunk in paper.get("chunks", []):
            project_id = chunk.get("project_id")
            chunk_id = chunk.get("chunk_id")
            if project_id and chunk_id:
                chunks_by_project.setdefault(project_id, []).append(chunk_id)

    content_by_chunk_id = {}
    for related_project_id, chunk_ids in chunks_by_project.items():
        for chunk in list_document_chunks_by_ids(related_project_id, chunk_ids):
            content_by_chunk_id[chunk["chunk_id"]] = chunk

    enriched_papers = []
    for paper in related_papers:
        enriched_chunks = []
        for chunk in paper.get("chunks", []):
            full_chunk = content_by_chunk_id.get(chunk.get("chunk_id"))
            if full_chunk:
                enriched_chunks.append(
                    {
                        **chunk,
                        "content": full_chunk.get("content", ""),
                        "title": full_chunk.get("title", ""),
                    }
                )
            else:
                enriched_chunks.append(chunk)
        enriched_papers.append({**paper, "chunks": enriched_chunks})

    return enriched_papers


def _compact_hits(hits: list[dict]) -> list[dict]:
    compact = []
    for hit in hits:
        compact.append(
            {
                "chunk_id": hit.get("chunk_id"),
                "score": hit.get("score"),
                "section_title": hit.get("section_title"),
                "page_start": hit.get("page_start"),
                "page_end": hit.get("page_end"),
                "order_index": hit.get("order_index"),
                "vector_id": hit.get("vector_id"),
                "best_vector_score": hit.get("best_vector_score"),
                "source_queries": hit.get("source_queries", []),
                "keyword_score": hit.get("keyword_score"),
                "keyword_source_queries": hit.get("keyword_source_queries", []),
                "retrieval_sources": hit.get("retrieval_sources", []),
                "rerank_score": hit.get("rerank_score"),
                "score_breakdown": hit.get("score_breakdown", {}),
            }
        )
    return compact
