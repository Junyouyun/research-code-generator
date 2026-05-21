import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.config import ARTIFACT_DIR, GENERATED_DIR, PARSED_DIR, UPLOAD_DIR


@dataclass(frozen=True)
class ProjectWorkspace:
    project_id: str
    upload_dir: Path
    parsed_dir: Path
    generated_dir: Path
    artifact_dir: Path


def create_project_workspace() -> ProjectWorkspace:
    project_id = uuid4().hex
    workspace = ProjectWorkspace(
        project_id=project_id,
        upload_dir=UPLOAD_DIR / project_id,
        parsed_dir=PARSED_DIR / project_id,
        generated_dir=GENERATED_DIR / project_id,
        artifact_dir=ARTIFACT_DIR / project_id,
    )

    for directory in (
        workspace.upload_dir,
        workspace.parsed_dir,
        workspace.generated_dir,
        workspace.artifact_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    return workspace


async def save_upload_file(file: UploadFile, target_path: Path) -> Path:
    content = await file.read()
    target_path.write_bytes(content)
    return target_path


def calculate_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
