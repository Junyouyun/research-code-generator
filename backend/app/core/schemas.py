from pydantic import BaseModel, Field

from app.core.models import ProjectStatus


class AuthRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(AuthRequest):
    display_name: str | None = None


class UserResponse(BaseModel):
    user_id: str
    email: str
    display_name: str | None = None
    avatar_initial: str | None = None
    plan: str = "free"


class AuthResponse(BaseModel):
    user: UserResponse


class UploadResponse(BaseModel):
    project_id: str
    status: ProjectStatus


class ProjectEventResponse(BaseModel):
    step: str
    level: str
    message: str
    duration_ms: int | None = None
    details: dict | None = None
    created_at: str | None = None


class ProjectStatusResponse(BaseModel):
    project_id: str
    status: ProjectStatus
    current_step: str
    progress: int
    error_message: str | None = None
    events: list[ProjectEventResponse] = Field(default_factory=list)


class ProjectListItem(BaseModel):
    project_id: str
    status: ProjectStatus
    current_step: str
    progress: int
    original_filename: str
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ProjectListResponse(BaseModel):
    projects: list[ProjectListItem] = Field(default_factory=list)


class ReportResponse(BaseModel):
    project_id: str
    content: str


class CodeFile(BaseModel):
    path: str
    content: str


class CodeFilesResponse(BaseModel):
    project_id: str
    files: list[CodeFile]


class QuestionRequest(BaseModel):
    question: str
    conversation_id: str | None = None


class QuestionResponse(BaseModel):
    project_id: str
    conversation_id: str | None = None
    answer: str
    used_chunks: list[str]
    confidence: str
    expanded: bool = False
    used_related_chunks: list[str] = Field(default_factory=list)
    retrieval_trace: dict | None = None


class RelatedPapersRequest(BaseModel):
    query: str
    top_papers: int = Field(default=5, ge=1, le=20)
    chunks_per_paper: int = Field(default=3, ge=1, le=10)


class RelatedPaperChunk(BaseModel):
    chunk_id: str
    project_id: str | None = None
    paper_id: str | None = None
    paper_version_id: str | None = None
    document_title: str | None = None
    section_title: str | None = None
    hierarchy_path: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    element_type: str | None = None
    order_index: int | None = None
    content_hash: str | None = None
    embedding_model: str | None = None
    score: float | None = None
    vector_id: str | None = None


class RelatedPaper(BaseModel):
    paper_id: str
    title: str = ""
    score: float
    chunks: list[RelatedPaperChunk] = Field(default_factory=list)


class RelatedPapersResponse(BaseModel):
    project_id: str
    source_paper_id: str
    papers: list[RelatedPaper] = Field(default_factory=list)


class ReindexResponse(BaseModel):
    project_id: str
    indexed: int
    collection: str
    embedding_model: str | None = None


class ConversationResponse(BaseModel):
    conversation_id: str
    user_id: str
    project_id: str | None = None
    title: str | None = None
    status: str
    short_summary: str | None = None
    summary_updated_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ConversationMessageResponse(BaseModel):
    message_id: str
    conversation_id: str
    project_id: str | None = None
    role: str
    content: str
    content_type: str = "text"
    metadata: dict | None = None
    created_at: str | None = None


class ConversationMessagesResponse(BaseModel):
    conversation_id: str
    messages: list[ConversationMessageResponse] = Field(default_factory=list)


class ProjectMemoryResponse(BaseModel):
    memory_id: str
    project_id: str
    memory_type: str
    content: str
    normalized_key: str | None = None
    importance: float
    confidence: float
    status: str
    source_type: str
    source_id: str | None = None
    evidence: dict | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ProjectMemoriesResponse(BaseModel):
    project_id: str
    memories: list[ProjectMemoryResponse] = Field(default_factory=list)


class UserMemoryResponse(BaseModel):
    memory_id: str
    memory_type: str
    content: str
    normalized_key: str | None = None
    importance: float
    confidence: float
    status: str
    source_type: str
    source_id: str | None = None
    evidence: dict | None = None
    created_at: str | None = None
    updated_at: str | None = None


class UserMemoriesResponse(BaseModel):
    memories: list[UserMemoryResponse] = Field(default_factory=list)


class UpdateUserMemoryRequest(BaseModel):
    content: str | None = None
    memory_type: str | None = None
    importance: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
