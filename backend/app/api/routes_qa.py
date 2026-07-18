from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user
from app.core.database import (
    add_project_event,
    get_conversation,
    get_or_create_project_conversation,
    save_conversation_message,
)
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
from app.services.context_orchestrator import ContextBuildError, build_qa_context
from app.services.trace_store import new_trace_id, record_qa_trace
from app.services.user_memory import extract_user_memories_from_turn

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

    trace_id = new_trace_id("qa")
    conversation = _resolve_project_conversation(
        project_id=project_id,
        user_id=current_user.user_id,
        conversation_id=request.conversation_id,
        title=project.original_filename,
    )
    save_conversation_message(
        conversation_id=conversation.conversation_id,
        user_id=current_user.user_id,
        project_id=project_id,
        role="user",
        content=question,
    )
    try:
        qa_context = build_qa_context(
            project=project,
            user_id=current_user.user_id,
            conversation_id=conversation.conversation_id,
            question=question,
        )
    except ContextBuildError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    conversation_context = qa_context["conversation_context"]
    project_memory_context = qa_context["project_memory_context"]
    user_memory_context = qa_context["user_memory_context"]
    graph_context = qa_context["graph_context"]
    chunks = qa_context["current_paper_chunks"]
    related_papers = qa_context["related_papers"]
    retrieval_trace = qa_context["retrieval_trace"]
    expanded = bool(retrieval_trace["expanded"])

    started_at = perf_counter()
    if expanded:
        result = answer_question_with_expanded_context(
            question,
            chunks,
            related_papers,
            conversation_context=conversation_context,
            project_memory_context=project_memory_context,
            user_memory_context=user_memory_context,
            graph_context=graph_context,
        )
    else:
        result = answer_question_with_chunks(
            question,
            chunks,
            conversation_context=conversation_context,
            project_memory_context=project_memory_context,
            user_memory_context=user_memory_context,
            graph_context=graph_context,
        )
    latency_ms = int((perf_counter() - started_at) * 1000)

    _record_qa_trace_safely(
        trace_id=trace_id,
        project=project,
        user_id=current_user.user_id,
        conversation_id=conversation.conversation_id,
        question=question,
        qa_context=qa_context,
        answer_result=result,
        latency_ms=latency_ms,
    )

    save_conversation_message(
        conversation_id=conversation.conversation_id,
        user_id=current_user.user_id,
        project_id=project_id,
        role="assistant",
        content=result["answer"],
        metadata={
            "trace_id": trace_id,
            "trace_type": "qa",
            "confidence": result["confidence"],
            "used_chunks": result["used_chunks"],
            "expanded": expanded,
            "used_related_chunks": result.get("used_related_chunks", []),
            "retrieval_trace": retrieval_trace,
            "used_graph_entities": [
                entity.get("entity_id") for entity in graph_context.get("entities", []) if entity.get("entity_id")
            ],
            "used_graph_relations": [
                relation.get("relation_id") for relation in graph_context.get("relations", []) if relation.get("relation_id")
            ],
            "used_user_memories": [
                memory.get("memory_id") for memory in user_memory_context if memory.get("memory_id")
            ],
        },
    )
    _extract_user_memory_safely(
        user_id=current_user.user_id,
        project_id=project_id,
        conversation_id=conversation.conversation_id,
        question=question,
        answer=result["answer"],
    )

    return QuestionResponse(
        project_id=project_id,
        conversation_id=conversation.conversation_id,
        trace_id=trace_id,
        answer=result["answer"],
        used_chunks=result["used_chunks"],
        confidence=result["confidence"],
        expanded=expanded,
        used_related_chunks=result.get("used_related_chunks", []),
        retrieval_trace=retrieval_trace,
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


def _resolve_project_conversation(
    project_id: str,
    user_id: str,
    conversation_id: str | None,
    title: str | None = None,
):
    if not conversation_id:
        return get_or_create_project_conversation(project_id, user_id, title=title)

    conversation = get_conversation(conversation_id, user_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    if conversation.project_id != project_id:
        raise HTTPException(status_code=403, detail="conversation does not belong to project")
    return conversation


def _record_qa_trace_safely(
    trace_id: str,
    project,
    user_id: str,
    conversation_id: str,
    question: str,
    qa_context: dict,
    answer_result: dict,
    latency_ms: int,
) -> None:
    try:
        record_qa_trace(
            trace_id=trace_id,
            project=project,
            user_id=user_id,
            conversation_id=conversation_id,
            question=question,
            qa_context=qa_context,
            answer_result=answer_result,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        add_project_event(
            project.project_id,
            "qa_trace",
            f"QA trace write skipped: {exc}",
            level="warning",
        )


def _extract_user_memory_safely(
    user_id: str,
    project_id: str,
    conversation_id: str,
    question: str,
    answer: str,
) -> None:
    try:
        memories = extract_user_memories_from_turn(
            user_id=user_id,
            user_message=question,
            assistant_message=answer,
            project_id=project_id,
            conversation_id=conversation_id,
        )
        if memories:
            add_project_event(
                project_id,
                "user_memory",
                f"更新 {len(memories)} 条用户长期记忆",
                details={"memory_ids": [memory.memory_id for memory in memories]},
            )
    except Exception as exc:
        add_project_event(
            project_id,
            "user_memory",
            f"用户长期记忆抽取失败：{exc}",
            level="warning",
        )
