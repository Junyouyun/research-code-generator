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
