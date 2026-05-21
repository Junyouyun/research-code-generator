from pathlib import Path

from app.services.llm_code_generator import generate_code_files_from_spec


def generate_code_files(plan: dict, output_dir: Path, analysis: dict | None = None, chunks: list[dict] | None = None) -> list[Path]:
    return generate_code_files_from_spec(plan, analysis or {}, chunks or [], output_dir)
