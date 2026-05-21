from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.config import ARTIFACT_DIR, GENERATED_DIR
from app.core.auth import get_current_user
from app.core.models import User
from app.core.project_access import get_owned_project
from app.core.schemas import CodeFile, CodeFilesResponse

router = APIRouter(tags=["code"])


@router.get("/projects/{project_id}/code", response_model=CodeFilesResponse)
def get_code_files(
    project_id: str,
    current_user: User = Depends(get_current_user),
) -> CodeFilesResponse:
    get_owned_project(project_id, current_user)
    code_dir = GENERATED_DIR / project_id / "code"
    if not code_dir.exists():
        raise HTTPException(status_code=404, detail="code not found")

    files = []
    for file_path in sorted(code_dir.rglob("*")):
        if file_path.is_file():
            files.append(
                CodeFile(
                    path=str(file_path.relative_to(code_dir)).replace("\\", "/"),
                    content=file_path.read_text(encoding="utf-8"),
                )
            )

    return CodeFilesResponse(project_id=project_id, files=files)


@router.get("/projects/{project_id}/artifact")
def download_artifact(
    project_id: str,
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    get_owned_project(project_id, current_user)
    artifact_path = ARTIFACT_DIR / project_id / "result.zip"
    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail="artifact not found")

    return FileResponse(
        artifact_path,
        media_type="application/zip",
        filename=f"{project_id}_result.zip",
    )
