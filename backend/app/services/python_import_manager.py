from __future__ import annotations

import ast
import re

from app.services.symbol_graph import module_name_for_path


BASE_STDLIB_IMPORTS = [
    "import json",
    "import math",
    "import random",
    "from pathlib import Path",
    "from typing import Any, Dict, List, Tuple",
]


def render_python_import_block(spec: dict, target_path: str) -> str:
    lines = [
        "from __future__ import annotations",
        "",
        *BASE_STDLIB_IMPORTS,
    ]

    third_party_lines = _third_party_import_lines(spec)
    if third_party_lines:
        lines.append("")
        lines.extend(third_party_lines)

    local_lines = local_import_lines(spec, target_path)
    if local_lines:
        lines.append("")
        lines.extend(local_lines)

    return "\n".join(lines).rstrip() + "\n"


def apply_managed_imports(module_code: str, spec: dict, target_path: str) -> str:
    imports = local_import_lines(spec, target_path)
    if not imports:
        return module_code
    try:
        ast.parse(module_code)
    except SyntaxError:
        return module_code

    existing_lines = set(module_code.splitlines())
    missing_imports = [line for line in imports if line not in existing_lines]
    if not missing_imports:
        return module_code

    insert_index = _import_insert_index(module_code)
    lines = module_code.splitlines()
    prefix = lines[:insert_index]
    suffix = lines[insert_index:]
    spacer_before = [] if not prefix or prefix[-1] == "" else [""]
    spacer_after = [] if not suffix or suffix[0] == "" else [""]
    updated = "\n".join(prefix + spacer_before + missing_imports + spacer_after + suffix).rstrip() + "\n"
    try:
        ast.parse(updated)
    except SyntaxError:
        return module_code
    return updated


def local_import_lines(spec: dict, target_path: str) -> list[str]:
    target_module = module_name_for_path(target_path)
    symbols = [symbol for symbol in spec.get("symbols", []) if isinstance(symbol, dict)]
    symbols_by_id = {symbol.get("id"): symbol for symbol in symbols if symbol.get("id")}
    target_symbols = [symbol for symbol in symbols if symbol.get("path") == target_path]
    generated_modules = {module_name_for_path(symbol.get("path", "")) for symbol in symbols}

    imports_by_module: dict[str, set[str]] = {}
    for symbol in target_symbols:
        for import_item in symbol.get("imports", []):
            if isinstance(import_item, dict):
                _add_import(
                    imports_by_module,
                    import_item.get("from") or import_item.get("module"),
                    import_item.get("import") or import_item.get("name"),
                    target_module,
                    generated_modules,
                )

        for dependency_id in _as_string_list(symbol.get("depends_on")):
            dependency = symbols_by_id.get(dependency_id)
            if not dependency:
                continue
            module = module_name_for_path(dependency.get("path", ""))
            name = _import_name_for_symbol(dependency)
            _add_import(imports_by_module, module, name, target_module, generated_modules)

    return [
        f"from {module} import {', '.join(sorted(names))}"
        for module, names in sorted(imports_by_module.items())
        if names
    ]


def _third_party_import_lines(spec: dict) -> list[str]:
    dependencies = {str(item).lower() for item in spec.get("dependencies", [])}
    lines = []
    if any("numpy" in item for item in dependencies):
        lines.append("import numpy as np")
    if any("torch" in item for item in dependencies):
        lines.extend(
            [
                "try:",
                "    import torch",
                "except Exception:",
                "    torch = None",
            ]
        )
    return lines


def _import_insert_index(module_code: str) -> int:
    try:
        tree = ast.parse(module_code)
    except SyntaxError:
        return 0

    last_import_line = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_import_line = max(last_import_line, node.end_lineno or node.lineno)
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            last_import_line = max(last_import_line, node.end_lineno or node.lineno)
            continue
        break
    return last_import_line


def _import_name_for_symbol(symbol: dict) -> str:
    if symbol.get("kind") == "method":
        return _as_text(symbol.get("class_name"))
    return _as_text(symbol.get("name"))


def _add_import(
    imports_by_module: dict[str, set[str]],
    module: object,
    name: object,
    target_module: str,
    generated_modules: set[str],
) -> None:
    module_text = _as_text(module)
    name_text = _as_text(name)
    if not _is_safe_module(module_text) or not _is_safe_import_name(name_text):
        return
    if module_text not in generated_modules:
        return
    if module_text == target_module:
        return
    imports_by_module.setdefault(module_text, set()).add(name_text)


def _is_safe_module(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*", value))


def _is_safe_import_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_]\w*", value))


def _as_string_list(value: object) -> list[str]:
    return [text for text in (_as_text(item) for item in _as_list(value)) if text]


def _as_list(value: object) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()
