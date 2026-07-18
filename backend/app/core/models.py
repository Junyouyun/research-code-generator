from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class User:
    user_id: str
    email: str
    display_name: str | None = None
    avatar_initial: str | None = None
    plan: str = "free"
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
    user_id: str
    project_id: str | None = None
    title: str | None = None
    status: str = "active"
    short_summary: str | None = None
    summary_updated_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class ConversationMessage:
    message_id: str
    conversation_id: str
    user_id: str
    project_id: str | None
    role: str
    content: str
    content_type: str = "text"
    metadata: dict | None = None
    token_count: int | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class MemoryItem:
    memory_id: str
    user_id: str
    scope: str
    scope_id: str | None
    memory_type: str
    content: str
    normalized_key: str | None = None
    importance: float = 0.5
    confidence: float = 0.7
    status: str = "active"
    source_type: str = "system"
    source_id: str | None = None
    evidence: dict | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class GraphEntity:
    entity_id: str
    user_id: str
    project_id: str
    paper_id: str | None
    paper_version_id: str | None
    entity_type: str
    name: str
    normalized_name: str
    description: str | None = None
    importance: float = 0.5
    confidence: float = 0.7
    source_chunk_ids: list[str] | None = None
    evidence: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class GraphRelation:
    relation_id: str
    user_id: str
    project_id: str
    paper_id: str | None
    paper_version_id: str | None
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    description: str | None = None
    confidence: float = 0.7
    source_chunk_ids: list[str] | None = None
    evidence: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class GraphExtractionRun:
    run_id: str
    user_id: str
    project_id: str
    paper_id: str | None
    paper_version_id: str | None
    status: str
    entity_count: int = 0
    relation_count: int = 0
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ProjectStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSING_DOCUMENT = "parsing_document"
    CHUNKING = "chunking"
    SAVING_CHUNKS = "saving_chunks"
    INDEXING_VECTORS = "indexing_vectors"
    ANALYZING = "analyzing"
    SUMMARIZING_CHUNKS = "summarizing_chunks"
    BUILDING_REPORT = "building_report"
    GENERATING_REPORT = "generating_report"
    PLANNING_CODE = "planning_code"
    GENERATING_CODE = "generating_code"
    CHECKING_CODE = "checking_code"
    PACKAGING = "packaging"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class Project:
    project_id: str
    status: ProjectStatus
    current_step: str
    progress: int
    original_filename: str
    pdf_path: str
    user_id: str = "local"
    paper_id: str | None = None
    paper_version_id: str | None = None
    file_sha256: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class Paper:
    paper_id: str
    canonical_title: str | None = None
    normalized_title: str | None = None
    authors: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class PaperVersion:
    paper_version_id: str
    paper_id: str
    user_id: str
    project_id: str
    file_sha256: str
    original_filename: str
    pdf_path: str
    parser_version: str | None = None
    chunker_version: str | None = None
    embedding_model: str | None = None
    version_number: int = 1
    created_at: str | None = None


@dataclass(frozen=True)
class VectorIndexRecord:
    chunk_id: str
    project_id: str
    paper_id: str
    paper_version_id: str
    vector_id: str
    content_hash: str
    embedding_model: str
    vector_store: str
    indexed_at: str | None = None


@dataclass(frozen=True)
class ProjectEvent:
    step: str
    level: str
    message: str
    duration_ms: int | None = None
    details: dict | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class QATrace:
    trace_id: str
    user_id: str
    project_id: str
    paper_id: str | None
    paper_version_id: str | None
    conversation_id: str | None
    question: str
    answer: str | None = None
    rewritten_query: str | None = None
    question_type: str | None = None
    retrieved_chunks: list[dict] | None = None
    retrieval_scores: list[dict] | None = None
    graph_context: dict | None = None
    graph_source_chunk_ids: list[str] | None = None
    project_memory: list[dict] | None = None
    user_memory: list[dict] | None = None
    conversation_context: list[dict] | None = None
    retrieval_trace: dict | None = None
    final_prompt_hash: str | None = None
    final_prompt_path: str | None = None
    context_snapshot_path: str | None = None
    model_name: str | None = None
    model_params: dict | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    status: str = "succeeded"
    error_message: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class CodegenTrace:
    trace_id: str
    user_id: str
    project_id: str
    paper_id: str | None
    paper_version_id: str | None
    trigger_message: str | None = None
    analysis_snapshot_path: str | None = None
    retrieved_chunks_path: str | None = None
    graph_context_path: str | None = None
    experiment_spec_path: str | None = None
    code_plan_path: str | None = None
    generated_files_path: str | None = None
    validation_command: str | None = None
    validation_result: dict | None = None
    validation_error: str | None = None
    repair_attempts: list[dict] | None = None
    final_status: str = "succeeded"
    model_name: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    created_at: str | None = None
    finished_at: str | None = None


@dataclass(frozen=True)
class FeedbackItem:
    feedback_id: str
    user_id: str
    project_id: str
    trace_id: str
    trace_type: str
    rating: str | None = None
    feedback_type: str | None = None
    comment: str | None = None
    reviewer_error_type: str | None = None
    gold_chunk_ids: list[str] | None = None
    negative_chunk_ids: list[str] | None = None
    expected_answer_points: list[str] | None = None
    reviewer_comment: str | None = None
    status: str = "open"
    created_at: str | None = None
    reviewed_at: str | None = None


@dataclass(frozen=True)
class BadCase:
    bad_case_id: str
    feedback_id: str
    user_id: str
    project_id: str
    trace_id: str
    trace_type: str
    error_type: str
    severity: str = "medium"
    question: str | None = None
    feedback_type: str | None = None
    gold_chunk_ids: list[str] | None = None
    negative_chunk_ids: list[str] | None = None
    expected_answer_points: list[str] | None = None
    reviewer_comment: str | None = None
    status: str = "open"
    created_at: str | None = None
    updated_at: str | None = None
