from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user
from app.core.database import (
    create_feedback_item,
    get_codegen_trace,
    get_feedback_item,
    get_qa_trace,
    list_feedback_items,
    list_bad_cases,
    summarize_bad_cases,
    update_feedback_review,
    upsert_bad_case_from_feedback,
)
from app.core.models import BadCase, FeedbackItem, User
from app.core.schemas import (
    BadCaseListResponse,
    BadCaseResponse,
    BadCaseSummaryResponse,
    FeedbackCreateRequest,
    FeedbackListResponse,
    FeedbackResponse,
    FeedbackReviewRequest,
)

router = APIRouter(tags=["feedback"])

TRACE_TYPES = {"qa", "codegen", "report", "graph"}
RATINGS = {"up", "down", "neutral"}
ERROR_TYPES = {
    "PDF_PARSE_ERROR",
    "CHUNKING_ERROR",
    "RETRIEVAL_MISS",
    "RETRIEVAL_NOISE",
    "RANKING_ERROR",
    "GRAPH_MISSING",
    "GRAPH_WRONG",
    "CONTEXT_ASSEMBLY_ERROR",
    "PROMPT_ERROR",
    "LLM_HALLUCINATION",
    "MEMORY_POLLUTION",
    "CROSS_PAPER_POLLUTION",
    "PAPER_AMBIGUOUS",
    "CODE_CONTRACT_ERROR",
    "CODE_IMPLEMENTATION_ERROR",
    "VALIDATION_GAP",
}
SEVERITIES = {"low", "medium", "high", "critical"}


@router.post("/feedback", response_model=FeedbackResponse)
def create_feedback(
    request: FeedbackCreateRequest,
    current_user: User = Depends(get_current_user),
) -> FeedbackResponse:
    trace_type = request.trace_type.strip().lower()
    if trace_type not in TRACE_TYPES:
        raise HTTPException(status_code=400, detail="invalid trace_type")
    if request.rating and request.rating not in RATINGS:
        raise HTTPException(status_code=400, detail="invalid rating")

    project_id = _project_id_for_trace(trace_type, request.trace_id, current_user.user_id)
    feedback = create_feedback_item(
        user_id=current_user.user_id,
        project_id=project_id,
        trace_id=request.trace_id,
        trace_type=trace_type,
        rating=request.rating,
        feedback_type=request.feedback_type,
        comment=request.comment,
    )
    return _feedback_response(feedback)


@router.get("/feedback", response_model=FeedbackListResponse)
def list_feedback(
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
) -> FeedbackListResponse:
    items = list_feedback_items(current_user.user_id, project_id=project_id)
    return FeedbackListResponse(items=[_feedback_response(item) for item in items])


@router.patch("/feedback/{feedback_id}/review", response_model=FeedbackResponse)
def review_feedback(
    feedback_id: str,
    request: FeedbackReviewRequest,
    current_user: User = Depends(get_current_user),
) -> FeedbackResponse:
    existing = get_feedback_item(feedback_id, current_user.user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="feedback not found")
    if not request.reviewer_error_type:
        raise HTTPException(status_code=400, detail="reviewer_error_type is required")
    if request.reviewer_error_type not in ERROR_TYPES:
        raise HTTPException(status_code=400, detail="invalid reviewer_error_type")
    if request.severity not in SEVERITIES:
        raise HTTPException(status_code=400, detail="invalid severity")

    updated = update_feedback_review(
        feedback_id=feedback_id,
        user_id=current_user.user_id,
        reviewer_error_type=request.reviewer_error_type,
        gold_chunk_ids=request.gold_chunk_ids,
        negative_chunk_ids=request.negative_chunk_ids,
        expected_answer_points=request.expected_answer_points,
        reviewer_comment=request.reviewer_comment,
        status=request.status,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="feedback not found")
    question = _question_for_trace(updated.trace_type, updated.trace_id, current_user.user_id)
    upsert_bad_case_from_feedback(
        feedback=updated,
        error_type=request.reviewer_error_type,
        question=question,
        severity=request.severity,
        gold_chunk_ids=request.gold_chunk_ids,
        negative_chunk_ids=request.negative_chunk_ids,
        expected_answer_points=request.expected_answer_points,
        reviewer_comment=request.reviewer_comment,
        status="open",
    )
    return _feedback_response(updated)


@router.get("/bad-cases", response_model=BadCaseListResponse)
def get_bad_cases(
    project_id: str | None = None,
    status: str | None = None,
    error_type: str | None = None,
    current_user: User = Depends(get_current_user),
) -> BadCaseListResponse:
    if error_type and error_type not in ERROR_TYPES:
        raise HTTPException(status_code=400, detail="invalid error_type")
    items = list_bad_cases(
        current_user.user_id,
        project_id=project_id,
        status=status,
        error_type=error_type,
    )
    return BadCaseListResponse(items=[_bad_case_response(item) for item in items])


@router.get("/bad-cases/summary", response_model=BadCaseSummaryResponse)
def get_bad_case_summary(
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
) -> BadCaseSummaryResponse:
    return BadCaseSummaryResponse(items=summarize_bad_cases(current_user.user_id, project_id=project_id))


@router.get("/bad-cases/retrieval-eval-cases")
def export_retrieval_eval_cases(
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
) -> dict:
    retrieval_error_types = {
        "RETRIEVAL_MISS",
        "RETRIEVAL_NOISE",
        "RANKING_ERROR",
        "CONTEXT_ASSEMBLY_ERROR",
    }
    items = list_bad_cases(current_user.user_id, project_id=project_id, limit=500)
    cases = []
    for item in items:
        if item.trace_type != "qa":
            continue
        if item.error_type not in retrieval_error_types:
            continue
        if not item.question or not item.gold_chunk_ids:
            continue
        cases.append(
            {
                "case_type": "retrieval",
                "case_id": f"bad_case_{item.bad_case_id}",
                "project_id": item.project_id,
                "question": item.question,
                "gold_chunk_ids": item.gold_chunk_ids or [],
                "positive_chunk_ids": item.gold_chunk_ids or [],
                "negative_chunk_ids": item.negative_chunk_ids or [],
                "recall_ks": [5, 10],
                "top_k": 10,
                "source_bad_case_id": item.bad_case_id,
                "source_feedback_id": item.feedback_id,
                "error_type": item.error_type,
            }
        )
    return {"cases": cases}


def _project_id_for_trace(trace_type: str, trace_id: str, user_id: str) -> str:
    if trace_type == "qa":
        trace = get_qa_trace(trace_id, user_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="qa trace not found")
        return trace.project_id

    if trace_type == "codegen":
        trace = get_codegen_trace(trace_id, user_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="codegen trace not found")
        return trace.project_id

    raise HTTPException(status_code=400, detail=f"{trace_type} feedback is not implemented yet")


def _question_for_trace(trace_type: str, trace_id: str, user_id: str) -> str | None:
    if trace_type == "qa":
        trace = get_qa_trace(trace_id, user_id)
        return trace.question if trace else None
    if trace_type == "codegen":
        trace = get_codegen_trace(trace_id, user_id)
        return trace.trigger_message if trace else None
    return None


def _feedback_response(item: FeedbackItem) -> FeedbackResponse:
    return FeedbackResponse(
        feedback_id=item.feedback_id,
        project_id=item.project_id,
        trace_id=item.trace_id,
        trace_type=item.trace_type,
        rating=item.rating,
        feedback_type=item.feedback_type,
        comment=item.comment,
        reviewer_error_type=item.reviewer_error_type,
        gold_chunk_ids=item.gold_chunk_ids or [],
        negative_chunk_ids=item.negative_chunk_ids or [],
        expected_answer_points=item.expected_answer_points or [],
        reviewer_comment=item.reviewer_comment,
        status=item.status,
        created_at=item.created_at,
        reviewed_at=item.reviewed_at,
    )


def _bad_case_response(item: BadCase) -> BadCaseResponse:
    return BadCaseResponse(
        bad_case_id=item.bad_case_id,
        feedback_id=item.feedback_id,
        project_id=item.project_id,
        trace_id=item.trace_id,
        trace_type=item.trace_type,
        error_type=item.error_type,
        severity=item.severity,
        question=item.question,
        feedback_type=item.feedback_type,
        gold_chunk_ids=item.gold_chunk_ids or [],
        negative_chunk_ids=item.negative_chunk_ids or [],
        expected_answer_points=item.expected_answer_points or [],
        reviewer_comment=item.reviewer_comment,
        status=item.status,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
