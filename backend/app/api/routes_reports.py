from fastapi import APIRouter, Depends, HTTPException

from app.config import GENERATED_DIR
from app.core.auth import get_current_user
from app.core.models import User
from app.core.project_access import get_owned_project
from app.core.schemas import ReportResponse

router = APIRouter(tags=["reports"])


@router.get("/projects/{project_id}/report", response_model=ReportResponse)
def get_report(
    project_id: str,
    current_user: User = Depends(get_current_user),
) -> ReportResponse:
    get_owned_project(project_id, current_user)
    report_path = GENERATED_DIR / project_id / "report.md"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="report not found")

    return ReportResponse(
        project_id=project_id,
        content=report_path.read_text(encoding="utf-8"),
    )
