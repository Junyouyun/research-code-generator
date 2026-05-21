from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from pathlib import Path

from app.core.database import (
    create_paper_version,
    create_project,
    find_or_create_paper_identity,
    update_project_paper_version,
)
from app.core.auth import get_current_user
from app.core.models import ProjectStatus, User
from app.core.schemas import UploadResponse
from app.core.storage import (
    calculate_file_sha256,
    create_project_workspace,
    save_upload_file,
)
from app.workers.pipeline import run_project_pipeline

router = APIRouter(tags=["upload"])


@router.post("/upload", response_model=UploadResponse)
async def upload_paper(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> UploadResponse:
    workspace = create_project_workspace()
    suffix = Path(file.filename or "").suffix.lower() or ".pdf"
    saved_path = await save_upload_file(file, workspace.upload_dir / f"document{suffix}")
    file_sha256 = calculate_file_sha256(saved_path)
    paper_id = find_or_create_paper_identity(
        file_sha256=file_sha256,
        user_id=current_user.user_id,
    )
    create_project(
        project_id=workspace.project_id,
        original_filename=file.filename or "paper.pdf",
        pdf_path=saved_path,
        user_id=current_user.user_id,
        paper_id=paper_id,
        file_sha256=file_sha256,
    )
    paper_version_id = create_paper_version(
        paper_id=paper_id,
        project_id=workspace.project_id,
        file_sha256=file_sha256,
        original_filename=file.filename or "paper.pdf",
        pdf_path=saved_path,
        user_id=current_user.user_id,
    )
    update_project_paper_version(workspace.project_id, paper_version_id)

    background_tasks.add_task(run_project_pipeline, workspace.project_id, saved_path)

    return UploadResponse(
        project_id=workspace.project_id,
        status=ProjectStatus.UPLOADED,
    )
