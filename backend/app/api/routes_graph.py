from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.models import User
from app.core.project_access import get_owned_project
from app.core.schemas import (
    GraphEntityResponse,
    GraphRelationResponse,
    ProjectGraphResponse,
)
from app.services.knowledge_graph_store import get_project_graph

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
