from __future__ import annotations

import ast

from app.services.python_import_manager import apply_managed_imports, local_import_lines
from app.services.structured_python_generator import (
    can_generate_structured_python_module,
    generate_structured_python_module,
    validate_module_contract,
)


class PythonLanguageAdapter:
    language = "python"

    def is_source_file(self, path: str) -> bool:
        return path.endswith(".py")

    def can_generate_structured_file(self, spec: dict, file_plan: dict) -> bool:
        return can_generate_structured_python_module(spec, file_plan)

    def generate_structured_file(
        self,
        spec: dict,
        analysis: dict,
        chunks: list[dict],
        file_plan: dict,
    ) -> str:
        return generate_structured_python_module(spec, analysis, chunks, file_plan)

    def apply_post_generation_transforms(self, content: str, spec: dict, target_path: str) -> str:
        return apply_managed_imports(content, spec, target_path)

    def managed_import_lines(self, spec: dict, target_path: str) -> list[str]:
        return local_import_lines(spec, target_path)

    def validate_syntax(self, content: str) -> None:
        ast.parse(content)

    def validate_contract(self, content: str, contract: dict) -> list[dict]:
        return validate_module_contract(content, contract)

    def is_empty_contract(self, contract: dict) -> bool:
        return not contract.get("exports") and not contract.get("functions") and not contract.get("classes")

    def syntax_repair_system_prompt(self) -> str:
        return "You repair Python files. Output only the full repaired Python file content. No Markdown."

    def contract_repair_system_prompt(self) -> str:
        return (
            "You repair a generated Python file so it satisfies its module contract. "
            "Output only the complete repaired Python file content. No Markdown. "
            "Preserve existing public names that are already correct. "
            "Add missing exported functions/classes/methods exactly as declared."
        )


def get_language_adapter(spec: dict) -> PythonLanguageAdapter:
    language = _as_text(spec.get("language")).lower() or "python"
    if language != "python":
        raise RuntimeError(f"unsupported generated code language: {language}")
    return PythonLanguageAdapter()


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()
