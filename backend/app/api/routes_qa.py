from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user
from app.core.database import list_document_chunks_by_ids
from app.core.models import User
from app.core.project_access import get_owned_project
from app.core.schemas import (
    QuestionRequest,
    QuestionResponse,
    RelatedPapersRequest,
    RelatedPapersResponse,
)
from app.services.llm_paper_analyzer import (
    answer_question_with_chunks,
    answer_question_with_expanded_context,
)
from app.services.query_intent import should_expand_to_related_papers

router = APIRouter(tags=["qa"])


@router.post("/projects/{project_id}/qa", response_model=QuestionResponse)
def ask_project_question(
    project_id: str,
    request: QuestionRequest,
    current_user: User = Depends(get_current_user),
) -> QuestionResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    project = get_owned_project(project_id, current_user)
    if not project.paper_version_id:
        raise HTTPException(status_code=409, detail="project has no paper_version_id")

    expanded = should_expand_to_related_papers(question)

    from app.services.vector_store import search_related_papers, search_within_paper

    hits = search_within_paper(
        paper_version_id=project.paper_version_id,
        query=question,
        top_k=6 if expanded else 8,
        user_id=current_user.user_id,
    )
    chunk_ids = [hit["chunk_id"] for hit in hits if hit.get("chunk_id")]
    chunks = list_document_chunks_by_ids(project_id, chunk_ids)
    if not chunks:
        raise HTTPException(status_code=404, detail="relevant document chunks not found")

    related_papers = []
    if expanded:
        if not project.paper_id:
            raise HTTPException(status_code=409, detail="project has no paper_id")
        related_papers = search_related_papers(
            source_paper_id=project.paper_id,
            query=question,
            top_papers=5,
            chunks_per_paper=3,
            user_id=current_user.user_id,
        )
        related_papers = _attach_related_chunk_content(related_papers)
        result = answer_question_with_expanded_context(question, chunks, related_papers)
    else:
        result = answer_question_with_chunks(question, chunks)

    return QuestionResponse(
        project_id=project_id,
        answer=result["answer"],
        used_chunks=result["used_chunks"],
        confidence=result["confidence"],
        expanded=expanded,
        used_related_chunks=result.get("used_related_chunks", []),
    )


@router.post("/projects/{project_id}/related-papers", response_model=RelatedPapersResponse)
def search_project_related_papers(
    project_id: str,
    request: RelatedPapersRequest,
    current_user: User = Depends(get_current_user),
) -> RelatedPapersResponse:
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    project = get_owned_project(project_id, current_user)
    if not project.paper_id:
        raise HTTPException(status_code=409, detail="project has no paper_id")

    from app.services.vector_store import search_related_papers

    papers = search_related_papers(
        source_paper_id=project.paper_id,
        query=query,
        top_papers=request.top_papers,
        chunks_per_paper=request.chunks_per_paper,
        user_id=current_user.user_id,
    )
    return RelatedPapersResponse(
        project_id=project_id,
        source_paper_id=project.paper_id,
        papers=papers,
    )


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
