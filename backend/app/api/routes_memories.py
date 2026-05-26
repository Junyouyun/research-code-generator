from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import get_current_user
from app.core.database import list_project_memories, list_user_memories
from app.core.models import MemoryItem, User
from app.core.project_access import get_owned_project
from app.core.schemas import (
    ProjectMemoriesResponse,
    ProjectMemoryResponse,
    UpdateUserMemoryRequest,
    UserMemoriesResponse,
    UserMemoryResponse,
)
from app.services.user_memory import archive_user_memory, update_user_memory

router = APIRouter(tags=["memories"])


@router.get("/projects/{project_id}/memories", response_model=ProjectMemoriesResponse)
def get_project_memories(
    project_id: str,
    current_user: User = Depends(get_current_user),
) -> ProjectMemoriesResponse:
    get_owned_project(project_id, current_user)
    memories = list_project_memories(project_id, current_user.user_id)
    return ProjectMemoriesResponse(
        project_id=project_id,
        memories=[_memory_response(project_id, memory) for memory in memories],
    )


@router.get("/memories", response_model=UserMemoriesResponse)
def get_user_memories(
    memory_type: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> UserMemoriesResponse:
    memories = list_user_memories(
        current_user.user_id,
        memory_type=memory_type,
        limit=100,
    )
    return UserMemoriesResponse(
        memories=[_user_memory_response(memory) for memory in memories],
    )


@router.patch("/memories/{memory_id}", response_model=UserMemoryResponse)
def patch_user_memory(
    memory_id: str,
    request: UpdateUserMemoryRequest,
    current_user: User = Depends(get_current_user),
) -> UserMemoryResponse:
    if request.content is not None and not request.content.strip():
        raise HTTPException(status_code=400, detail="content cannot be empty")

    memory = update_user_memory(
        memory_id=memory_id,
        user_id=current_user.user_id,
        content=request.content,
        memory_type=request.memory_type,
        importance=request.importance,
        confidence=request.confidence,
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return _user_memory_response(memory)


@router.delete("/memories/{memory_id}", response_model=UserMemoryResponse)
def delete_user_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
) -> UserMemoryResponse:
    memory = archive_user_memory(memory_id, current_user.user_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return _user_memory_response(memory)


def _memory_response(project_id: str, memory: MemoryItem) -> ProjectMemoryResponse:
    return ProjectMemoryResponse(
        memory_id=memory.memory_id,
        project_id=project_id,
        memory_type=memory.memory_type,
        content=memory.content,
        normalized_key=memory.normalized_key,
        importance=memory.importance,
        confidence=memory.confidence,
        status=memory.status,
        source_type=memory.source_type,
        source_id=memory.source_id,
        evidence=memory.evidence,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


def _user_memory_response(memory: MemoryItem) -> UserMemoryResponse:
    return UserMemoryResponse(
        memory_id=memory.memory_id,
        memory_type=memory.memory_type,
        content=memory.content,
        normalized_key=memory.normalized_key,
        importance=memory.importance,
        confidence=memory.confidence,
        status=memory.status,
        source_type=memory.source_type,
        source_id=memory.source_id,
        evidence=memory.evidence,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )
