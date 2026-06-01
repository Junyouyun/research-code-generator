from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import get_current_user
from app.core.models import User
from app.core.project_access import get_owned_project
from app.core.schemas import (
    GraphEntityResponse,
    GraphRelationResponse,
    ProjectGraphContextResponse,
    ProjectGraphResponse,
)
from app.services.knowledge_graph_store import get_project_graph, search_graph_context

router = APIRouter(tags=["graph"])


@router.get("/projects/{project_id}/graph", response_model=ProjectGraphResponse)
def get_graph(
    project_id: str,
    current_user: User = Depends(get_current_user),
) -> ProjectGraphResponse:
    project = get_owned_project(project_id, current_user)
    graph = get_project_graph(project)
    return ProjectGraphResponse(
        project_id=graph["project_id"],
        paper_id=graph["paper_id"],
        paper_version_id=graph["paper_version_id"],
        entities=[
            GraphEntityResponse(**entity)
            for entity in graph["entities"]
        ],
        relations=[
            GraphRelationResponse(**relation)
            for relation in graph["relations"]
        ],
    )


@router.get("/projects/{project_id}/graph/search", response_model=ProjectGraphContextResponse)
def search_graph(
    project_id: str,
    q: str = Query(..., min_length=1),
    limit_entities: int = Query(default=8, ge=1, le=30),
    limit_relations: int = Query(default=20, ge=1, le=80),
    depth: int = Query(default=1, ge=0, le=1),
    current_user: User = Depends(get_current_user),
) -> ProjectGraphContextResponse:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    project = get_owned_project(project_id, current_user)
    graph_context = search_graph_context(
        project_id=project.project_id,
        user_id=current_user.user_id,
        query=query,
        limit_entities=limit_entities,
        limit_relations=limit_relations,
        depth=depth,
    )
    return ProjectGraphContextResponse(
        project_id=project_id,
        query=query,
        entities=[
            GraphEntityResponse(**entity)
            for entity in graph_context["entities"]
        ],
        relations=[
            GraphRelationResponse(**relation)
            for relation in graph_context["relations"]
        ],
        paths=graph_context["paths"],
    )
