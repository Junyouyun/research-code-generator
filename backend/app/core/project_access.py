from fastapi import HTTPException, status

from app.core.database import get_project
from app.core.models import Project, User


def get_owned_project(project_id: str, current_user: User) -> Project:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    if project.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问该项目",
        )

    return project
