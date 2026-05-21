from fastapi import APIRouter, Depends, HTTPException

from app.core.database import (
    add_project_event,
    list_document_chunks,
    list_project_events,
    list_projects_by_user,
)
from app.core.auth import get_current_user
from app.core.models import User
from app.core.project_access import get_owned_project
from app.core.schemas import (
    ProjectEventResponse,
    ProjectListItem,
    ProjectListResponse,
    ProjectStatusResponse,
    ReindexResponse,
)

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=ProjectListResponse)
def list_projects(current_user: User = Depends(get_current_user)) -> ProjectListResponse:
    projects = list_projects_by_user(current_user.user_id)
    return ProjectListResponse(
        projects=[
            ProjectListItem(
                project_id=project.project_id,
                status=project.status,
                current_step=project.current_step,
                progress=project.progress,
                original_filename=project.original_filename,
                error_message=project.error_message,
                created_at=project.created_at,
                updated_at=project.updated_at,
            )
            for project in projects
        ]
    )


@router.get("/projects/{project_id}", response_model=ProjectStatusResponse)
def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
) -> ProjectStatusResponse:
    project = get_owned_project(project_id, current_user)
    return ProjectStatusResponse(
        project_id=project.project_id,
        status=project.status,
        current_step=project.current_step,
        progress=project.progress,
        error_message=project.error_message,
        events=[
            ProjectEventResponse(
                step=event.step,
                level=event.level,
                message=event.message,
                duration_ms=event.duration_ms,
                details=event.details,
                created_at=event.created_at,
            )
            for event in list_project_events(project_id, limit=30)
        ],
    )


@router.post("/projects/{project_id}/reindex", response_model=ReindexResponse)
def reindex_project_vectors(
    project_id: str,
    current_user: User = Depends(get_current_user),
) -> ReindexResponse:
    get_owned_project(project_id, current_user)

    chunks = list_document_chunks(project_id)
    if not chunks:
        raise HTTPException(status_code=404, detail="document chunks not found")

    from app.services.vector_store import reindex_project

    add_project_event(project_id, "reindex", "开始重建向量索引")
    try:
        result = reindex_project(project_id)
    except Exception as exc:
        add_project_event(project_id, "reindex", f"重建向量索引失败：{exc}", level="error")
        raise

    add_project_event(
        project_id,
        "reindex",
        f"完成重建向量索引：{result.get('indexed', 0)} 个 chunks",
        details={
            "collection": result.get("collection"),
            "embedding_model": result.get("embedding_model"),
            "indexed": result.get("indexed", 0),
            "vector_store": "qdrant",
        },
    )
    return ReindexResponse(
        project_id=project_id,
        indexed=result.get("indexed", 0),
        collection=result.get("collection", ""),
        embedding_model=result.get("embedding_model"),
    )
