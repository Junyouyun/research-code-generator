from app.core.database import (
    list_document_chunks_by_ids,
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

    from app.services.vector_store import search_related_papers, search_within_paper

    current_hits = search_within_paper(
        paper_version_id=project.paper_version_id,
        query=question,
        top_k=current_top_k,
        user_id=user_id,
    )
    current_chunk_ids = [hit["chunk_id"] for hit in current_hits if hit.get("chunk_id")]
    current_chunks = list_document_chunks_by_ids(project.project_id, current_chunk_ids)
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
            "chunk_top_k": current_top_k,
            "memory_top_k": memory_top_k,
            "conversation_messages": len(conversation_context),
            "project_memories": len(project_memory_context),
            "user_memories": len(user_memory_context),
            "graph_entities": len(graph_context.get("entities", [])),
            "graph_relations": len(graph_context.get("relations", [])),
            "current_chunk_ids": current_chunk_ids,
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
