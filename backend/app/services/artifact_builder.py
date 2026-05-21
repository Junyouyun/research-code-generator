from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def build_artifact(project_dir: Path, artifact_path: Path) -> Path:
    artifact_path.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(artifact_path, "w", ZIP_DEFLATED) as zip_file:
        for file_path in project_dir.rglob("*"):
            if file_path.is_file():
                zip_file.write(file_path, file_path.relative_to(project_dir))

    return artifact_path
