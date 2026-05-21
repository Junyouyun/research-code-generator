from __future__ import annotations

import ast
import json
import re
import textwrap
from pathlib import Path
from typing import Callable

from app.config import DEFAULT_CODE_REPAIR_MAX_ATTEMPTS, DEFAULT_CODE_REPAIR_MAX_TOKENS, get_int_env
from app.llm.client import chat_completion
from app.services.code_runner import CodeValidationError, check_code
from app.services.llm_code_generator import _compact_analysis, _compact_spec, _strip_code_fence
from app.services.structured_python_generator import replace_class_method, replace_top_level_function


MAX_REPAIR_FILES = 6
MAX_FILE_CHARS = 5000
MAX_TOTAL_FILE_CHARS = 14000


def validate_and_repair_code(
    code_dir: Path,
    spec: dict,
    analysis: dict,
    chunks: list[dict],
    max_attempts: int | None = None,
    event_callback: Callable[[dict], None] | None = None,
) -> dict:
    code_dir = code_dir.resolve()
    attempts_limit = _repair_max_attempts() if max_attempts is None else max(0, max_attempts)
    repairs: list[dict] = []
    last_result: dict = {}

    for validation_attempt in range(attempts_limit + 1):
        _emit(event_callback, "validation_attempt_started", validation_attempt, "Generated code validation started")
        try:
            result = check_code(code_dir)
            result["attempts"] = validation_attempt
            result["repairs"] = repairs
            if repairs:
                result["message"] = f"Generated code validation passed after {len(repairs)} repair attempt(s)"
                _emit(event_callback, "validation_passed_after_repair", validation_attempt, result["message"])
            _write_validation_result(code_dir, result)
            return result
        except CodeValidationError as exc:
            last_result = exc.result
            last_result["attempts"] = validation_attempt
            last_result["repairs"] = repairs
            _emit(
                event_callback,
                "validation_failed",
                validation_attempt,
                last_result.get("message", "Generated code validation failed"),
                diagnostics=last_result.get("diagnostics", []),
                commands=last_result.get("commands", []),
            )
            if validation_attempt >= attempts_limit:
                break

            repair_attempt = validation_attempt + 1
            _emit(event_callback, "repair_attempt_started", repair_attempt, "Generated code repair started")
            try:
                repair = repair_generated_code(code_dir, spec, analysis, chunks, last_result)
                repairs.append(repair)
                _emit(
                    event_callback,
                    "repair_files_changed",
                    repair_attempt,
                    repair.get("reason", "Generated code repaired"),
                    changed_files=repair.get("changed_files", []),
                )
            except Exception as repair_exc:
                repair = {
                    "attempt": repair_attempt,
                    "success": False,
                    "reason": str(repair_exc),
                    "changed_files": [],
                }
                repairs.append(repair)
                last_result = _repair_failure_result(last_result, repairs, repair_exc, validation_attempt)
                _write_validation_result(code_dir, last_result)
                raise CodeValidationError(last_result) from repair_exc

    exhausted = {
        "success": False,
        "message": "Generated code repair exhausted",
        "attempts": attempts_limit,
        "repairs": repairs,
        "diagnostics": last_result.get("diagnostics", []),
        "commands": last_result.get("commands", []),
    }
    _emit(
        event_callback,
        "repair_exhausted",
        attempts_limit,
        exhausted["message"],
        diagnostics=exhausted["diagnostics"],
        commands=exhausted["commands"],
    )
    _write_validation_result(code_dir, exhausted)
    raise CodeValidationError(exhausted)


def repair_generated_code(
    code_dir: Path,
    spec: dict,
    analysis: dict,
    chunks: list[dict],
    validation_result: dict,
) -> dict:
    related_paths = _select_related_files(code_dir, validation_result)
    file_context = _read_related_files(code_dir, related_paths)
    repair_response = _ask_llm_for_repair(code_dir, spec, analysis, chunks, validation_result, file_context)
    try:
        changed_files = _apply_repair_response(code_dir, repair_response, validation_result, spec)
    except Exception as exc:
        operations = _compact_repair_operations(repair_response.get("operations", []))
        raise RuntimeError(f"{exc}; attempted operations: {json.dumps(operations, ensure_ascii=False)}") from exc
    return {
        "attempt": validation_result.get("attempts", 0) + 1,
        "success": True,
        "reason": _as_text(repair_response.get("reason")) or "Applied generated code repair",
        "changed_files": changed_files,
        "operations": _compact_repair_operations(repair_response.get("operations", [])),
    }


def _ask_llm_for_repair(
    code_dir: Path,
    spec: dict,
    analysis: dict,
    chunks: list[dict],
    validation_result: dict,
    file_context: list[dict],
) -> dict:
    messages = [
        {
            "role": "system",
            "content": (
                "You repair generated research code. Return strict JSON only. "
                "Fix the reported validation failure, not unrelated code style. "
                "Preserve public interfaces already used by other generated files. "
                "Keep dependencies minimal and runtime short under the smoke config. "
                "Do not add TODO placeholders."
            ),
        },
        {
            "role": "user",
            "content": (
                "Prefer operation-based Python repairs. Return exactly this JSON shape: "
                '{"reason":"...","operations":[{"op":"replace_symbol","symbol_id":"src.experiment.run_experiment",'
                '"content":"def run_experiment(config: dict) -> dict:\\n    ..."}],'
                '"changed_files":[]}.\n'
                "Supported operations: add_symbol, replace_symbol, add_function, replace_function, add_method, replace_method, add_class, replace_class, replace_text.\n"
                "Prefer symbol_id from code_spec.symbols whenever the failure maps to a declared function or method. "
                "For symbol operations, omit path/name/class_name unless you need to override the symbol graph.\n"
                "Use replace_text for small exact text edits such as imports, call names, argument names, or config keys: "
                '{"op":"replace_text","path":"main.py","old":"from src.algorithm import train",'
                '"new":"from src.experiment import run_experiment"}.\n'
                "Use changed_files only when an operation cannot express the fix.\n\n"
                f"code_spec:\n{json.dumps(_compact_spec(spec), ensure_ascii=False)}\n\n"
                f"repair_symbol_context:\n{json.dumps(_repair_symbol_context(spec, validation_result, file_context), ensure_ascii=False)}\n\n"
                f"analysis:\n{json.dumps(_compact_analysis(analysis), ensure_ascii=False)}\n\n"
                f"diagnostics:\n{json.dumps(validation_result.get('diagnostics', []), ensure_ascii=False)}\n\n"
                f"commands:\n{json.dumps(_compact_commands(validation_result.get('commands', [])), ensure_ascii=False)}\n\n"
                f"file_context:\n{json.dumps(file_context, ensure_ascii=False)}\n\n"
                f"relevant_chunks:\n{json.dumps(_compact_chunks(chunks), ensure_ascii=False)}"
            ),
        },
    ]
    content = chat_completion(
        messages,
        temperature=0,
        max_tokens=_repair_max_tokens(),
        response_format={"type": "json_object"},
    )
    try:
        return _loads_repair_json(content)
    except RuntimeError as first_exc:
        first_path = _write_repair_raw_response(code_dir, 1, content)
        retry_content = _ask_llm_to_reformat_repair_json(content)
        try:
            return _loads_repair_json(retry_content)
        except RuntimeError as second_exc:
            second_path = _write_repair_raw_response(code_dir, 2, retry_content)
            raise RuntimeError(
                "repair response is not valid JSON; "
                f"raw responses saved to {first_path} and {second_path}"
            ) from second_exc


def _ask_llm_to_reformat_repair_json(raw_content: str) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "You convert an invalid generated-code repair response into strict JSON. "
                "Return JSON only. Do not include Markdown, comments, or explanation."
            ),
        },
        {
            "role": "user",
            "content": (
                "Convert the following response into exactly this JSON shape: "
                '{"reason":"...","operations":[{"op":"replace_symbol","symbol_id":"src.experiment.run_experiment",'
                '"content":"def run_experiment(config: dict) -> dict:\\n    ..."}],'
                '"changed_files":[]}.\n'
                "Keep operation repairs when possible. Use replace_text for small exact text edits. "
                "Keep complete-file replacements in changed_files only when needed. "
                "If the response contains extra text, remove it. "
                "If it contains fenced JSON, unwrap it. If JSON strings need escaping, escape them.\n\n"
                f"raw_response:\n{raw_content}"
            ),
        },
    ]
    return chat_completion(
        messages,
        temperature=0,
        max_tokens=_repair_max_tokens(),
        response_format={"type": "json_object"},
    )


def _loads_repair_json(content: str) -> dict:
    text = _strip_code_fence(content).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise RuntimeError("repair response is not valid JSON") from exc
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as nested_exc:
            raise RuntimeError("repair response is not valid JSON") from nested_exc
    if not isinstance(data, dict):
        raise RuntimeError("repair response must be a JSON object")
    operations = data.get("operations")
    changed_files = data.get("changed_files")
    if operations is None:
        operations = []
        data["operations"] = operations
    if changed_files is None:
        changed_files = []
        data["changed_files"] = changed_files
    if not isinstance(operations, list):
        raise RuntimeError("repair response operations must be a list")
    if not isinstance(changed_files, list):
        raise RuntimeError("repair response changed_files must be a list")
    if not operations and not changed_files:
        raise RuntimeError("repair response must include operations or changed_files")
    return data


def _apply_repair_response(code_dir: Path, repair_response: dict, validation_result: dict, spec: dict | None = None) -> list[str]:
    changed_paths = []
    for operation in repair_response.get("operations", []):
        changed_path = _apply_repair_operation(code_dir, operation, spec or {})
        if changed_path not in changed_paths:
            changed_paths.append(changed_path)

    for item in repair_response.get("changed_files", []):
        if not isinstance(item, dict):
            raise RuntimeError("each changed_files item must be an object")
        relative_path = _safe_relative_path(item.get("path"))
        content = item.get("content")
        if not relative_path:
            raise RuntimeError("repair changed_files contains an unsafe path")
        if not isinstance(content, str):
            raise RuntimeError(f"repair for {relative_path} is missing content")

        target_path = (code_dir / relative_path).resolve()
        if not _is_inside(code_dir, target_path):
            raise RuntimeError(f"repair path escapes code directory: {relative_path}")
        if not target_path.exists() and not _can_create_file(relative_path, validation_result):
            raise RuntimeError(f"repair cannot create unrelated file: {relative_path}")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content.rstrip() + "\n", encoding="utf-8")
        if relative_path not in changed_paths:
            changed_paths.append(relative_path)

    if not changed_paths:
        raise RuntimeError("repair did not change any files")
    return changed_paths


def _apply_repair_operation(code_dir: Path, operation: object, spec: dict | None = None) -> str:
    if not isinstance(operation, dict):
        raise RuntimeError("each repair operation must be an object")

    if _as_text(operation.get("op")) == "replace_text":
        return _apply_replace_text_operation(code_dir, operation)

    target = _resolve_repair_operation_target(operation, spec or {})
    op = target["op"]
    relative_path = target["path"]
    if op not in {"add_function", "replace_function", "add_method", "replace_method", "add_class", "replace_class"}:
        raise RuntimeError(f"unsupported repair operation: {op}")

    target_path = (code_dir / relative_path).resolve()
    if not _is_inside(code_dir, target_path):
        raise RuntimeError(f"repair operation path escapes code directory: {relative_path}")
    if not target_path.exists():
        raise RuntimeError(f"repair operation target does not exist: {relative_path}")

    content = operation.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(f"repair operation for {relative_path} is missing content")

    module_code = target_path.read_text(encoding="utf-8-sig", errors="replace")
    if op in {"add_function", "replace_function"}:
        name = target["name"]
        block = _normalize_def_block(content, name, indent=0)
        updated = _replace_or_add_top_level_function(module_code, name, block)
    elif op in {"add_method", "replace_method"}:
        class_name = target["class_name"]
        name = target["name"]
        block = _normalize_def_block(content, name, indent=0)
        updated = _replace_or_add_class_method(module_code, class_name, name, block)
    else:
        name = target["name"]
        block = _normalize_class_block(content, name)
        updated = _replace_or_add_top_level_class(module_code, name, block)

    target_path.write_text(updated.rstrip() + "\n", encoding="utf-8")
    return relative_path


def _resolve_repair_operation_target(operation: dict, spec: dict) -> dict:
    op = _as_text(operation.get("op"))
    if op not in {"add_symbol", "replace_symbol", "add_function", "replace_function", "add_method", "replace_method", "add_class", "replace_class"}:
        raise RuntimeError(f"unsupported repair operation: {op}")

    symbol = _symbol_for_operation(operation, spec)
    relative_path = _safe_relative_path(operation.get("path")) or _safe_relative_path(symbol.get("path"))
    name = _safe_identifier(operation.get("name")) or _safe_identifier(symbol.get("name"))
    class_name = _safe_identifier(operation.get("class_name")) or _safe_identifier(symbol.get("class_name"))
    kind = _as_text(symbol.get("kind")).lower()

    if not relative_path or not relative_path.endswith(".py"):
        raise RuntimeError("repair operation requires a safe Python path")
    if op in {"add_symbol", "replace_symbol"}:
        if kind == "function":
            op = "replace_function" if op == "replace_symbol" else "add_function"
        elif kind == "method":
            op = "replace_method" if op == "replace_symbol" else "add_method"
        elif kind == "class":
            op = "replace_class" if op == "replace_symbol" else "add_class"
        else:
            raise RuntimeError("symbol repair operation requires a class, function, or method symbol")

    if op in {"add_function", "replace_function"} and not name:
        raise RuntimeError("function repair operation requires name or symbol_id")
    if op in {"add_method", "replace_method"} and (not class_name or not name):
        raise RuntimeError("method repair operation requires class_name/name or symbol_id")
    if op in {"add_class", "replace_class"} and not name:
        raise RuntimeError("class repair operation requires name or symbol_id")

    return {
        "op": op,
        "path": relative_path,
        "name": name,
        "class_name": class_name,
        "symbol_id": _as_text(operation.get("symbol_id")) or _as_text(symbol.get("id")),
    }


def _symbol_for_operation(operation: dict, spec: dict) -> dict:
    symbol_id = _as_text(operation.get("symbol_id"))
    if not symbol_id:
        return {}
    for symbol in spec.get("symbols", []):
        if isinstance(symbol, dict) and symbol.get("id") == symbol_id:
            return symbol
    raise RuntimeError(f"repair operation references unknown symbol_id: {symbol_id}")


def _apply_replace_text_operation(code_dir: Path, operation: dict) -> str:
    relative_path = _safe_relative_path(operation.get("path"))
    if not relative_path:
        raise RuntimeError("replace_text operation requires a safe path")

    target_path = (code_dir / relative_path).resolve()
    if not _is_inside(code_dir, target_path):
        raise RuntimeError(f"replace_text path escapes code directory: {relative_path}")
    if not target_path.exists() or not target_path.is_file():
        raise RuntimeError(f"replace_text target does not exist: {relative_path}")

    old = operation.get("old")
    new = operation.get("new")
    if not isinstance(old, str) or old == "":
        raise RuntimeError(f"replace_text for {relative_path} requires non-empty old text")
    if not isinstance(new, str):
        raise RuntimeError(f"replace_text for {relative_path} requires new text")

    original = target_path.read_text(encoding="utf-8-sig", errors="replace")
    occurrence_count = original.count(old)
    if occurrence_count == 0:
        raise RuntimeError(f"replace_text old text not found in {relative_path}")
    replace_all = bool(operation.get("replace_all"))
    if occurrence_count > 1 and not replace_all:
        raise RuntimeError(
            f"replace_text old text appears {occurrence_count} times in {relative_path}; "
            "set replace_all=true only if all occurrences should change"
        )

    updated = original.replace(old, new) if replace_all else original.replace(old, new, 1)
    if updated == original:
        raise RuntimeError(f"replace_text did not change {relative_path}")
    if relative_path.endswith(".py"):
        try:
            ast.parse(updated)
        except SyntaxError as exc:
            raise RuntimeError(f"replace_text would make {relative_path} invalid Python: {exc}") from exc

    target_path.write_text(updated.rstrip() + "\n", encoding="utf-8")
    return relative_path


def _replace_or_add_top_level_function(module_code: str, function_name: str, block: str) -> str:
    try:
        return replace_top_level_function(module_code, function_name, block)
    except RuntimeError:
        updated = module_code.rstrip() + "\n\n\n" + block.rstrip() + "\n"
        ast_tree = ast.parse(updated)
        if not any(getattr(node, "name", None) == function_name for node in ast_tree.body):
            raise RuntimeError(f"failed to add top-level function {function_name}")
        return updated


def _replace_or_add_top_level_class(module_code: str, class_name: str, block: str) -> str:
    tree = ast.parse(module_code)
    lines = module_code.splitlines()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            if node.end_lineno is None:
                raise RuntimeError(f"AST node end line is unavailable for class {class_name}")
            updated_lines = lines[: node.lineno - 1] + block.splitlines() + lines[node.end_lineno :]
            updated = "\n".join(updated_lines).rstrip() + "\n"
            _assert_top_level_class(updated, class_name)
            return updated

    updated = module_code.rstrip() + "\n\n\n" + block.rstrip() + "\n"
    _assert_top_level_class(updated, class_name)
    return updated


def _replace_or_add_class_method(module_code: str, class_name: str, method_name: str, block: str) -> str:
    try:
        return replace_class_method(module_code, class_name, method_name, block)
    except RuntimeError:
        return _add_class_method(module_code, class_name, method_name, _indent_block(block, indent=4))


def _add_class_method(module_code: str, class_name: str, method_name: str, block: str) -> str:
    tree = ast.parse(module_code)
    lines = module_code.splitlines()
    class_node = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            class_node = node
            break
    if class_node is None or class_node.end_lineno is None:
        raise RuntimeError(f"class not found for method repair: {class_name}")

    for child in class_node.body:
        if isinstance(child, ast.Pass) and child.lineno and child.end_lineno:
            updated_lines = lines[: child.lineno - 1] + block.splitlines() + lines[child.end_lineno :]
            updated = "\n".join(updated_lines).rstrip() + "\n"
            ast.parse(updated)
            return updated

    insert_at = class_node.end_lineno
    updated_lines = lines[:insert_at] + ["", *block.splitlines()] + lines[insert_at:]
    updated = "\n".join(updated_lines).rstrip() + "\n"
    ast.parse(updated)
    class_tree = next(node for node in ast.parse(updated).body if isinstance(node, ast.ClassDef) and node.name == class_name)
    if method_name not in {node.name for node in class_tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}:
        raise RuntimeError(f"failed to add method {class_name}.{method_name}")
    return updated


def _normalize_def_block(content: str, expected_name: str, indent: int) -> str:
    text = _strip_code_fence(content).strip()
    match = re.search(r"(?ms)^(async\s+def|def)\s+\w+\s*\(.*", text)
    if match:
        text = text[match.start() :].rstrip()
    dedented = textwrap.dedent(text).strip()
    tree = ast.parse(dedented)
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(tree.body) != 1 or len(functions) != 1 or functions[0].name != expected_name:
        raise RuntimeError(f"expected one function named {expected_name}")
    if indent:
        return _indent_block(dedented, indent)
    return dedented.rstrip()


def _normalize_class_block(content: str, expected_name: str) -> str:
    text = _strip_code_fence(content).strip()
    match = re.search(rf"(?ms)^class\s+{re.escape(expected_name)}\b.*", text)
    if match:
        text = text[match.start() :].rstrip()
    dedented = textwrap.dedent(text).strip()
    tree = ast.parse(dedented)
    if len(tree.body) == 1 and isinstance(tree.body[0], ast.ClassDef) and tree.body[0].name == expected_name:
        return dedented.rstrip()

    lines = dedented.splitlines()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == expected_name and node.end_lineno is not None:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno]).rstrip()
    raise RuntimeError(f"expected one class named {expected_name}")


def _assert_top_level_class(module_code: str, class_name: str) -> None:
    tree = ast.parse(module_code)
    if not any(isinstance(node, ast.ClassDef) and node.name == class_name for node in tree.body):
        raise RuntimeError(f"failed to add top-level class {class_name}")


def _indent_block(block: str, indent: int) -> str:
    return "\n".join((" " * indent + line) if line else "" for line in block.splitlines()).rstrip()


def _select_related_files(code_dir: Path, validation_result: dict) -> list[str]:
    selected: list[str] = []
    diagnostics = validation_result.get("diagnostics", [])
    commands = validation_result.get("commands", [])

    for diagnostic in diagnostics if isinstance(diagnostics, list) else []:
        if not isinstance(diagnostic, dict):
            continue
        code = diagnostic.get("code")
        if code in {"missing_imported_symbol", "invalid_python_syntax", "missing_contract_export", "missing_contract_module"}:
            _add_path(selected, diagnostic.get("file"))
            for related_file in diagnostic.get("related_files", []) if isinstance(diagnostic.get("related_files"), list) else []:
                _add_path(selected, related_file)
        elif code == "validation_command_failed":
            _add_path(selected, "main.py")
            _add_path(selected, "src/experiment.py")
            _add_path(selected, "config.json")
            for path in _paths_from_runtime_text(code_dir, _as_text(diagnostic.get("message"))):
                _add_path(selected, path)
        else:
            _add_path(selected, diagnostic.get("file"))

    for command in commands if isinstance(commands, list) else []:
        if not isinstance(command, dict):
            continue
        runtime_text = "\n".join([_as_text(command.get("stdout")), _as_text(command.get("stderr"))])
        for path in _paths_from_runtime_text(code_dir, runtime_text):
            _add_path(selected, path)

    if not selected:
        _add_path(selected, "main.py")
        _add_path(selected, "src/experiment.py")
        _add_path(selected, "config.json")

    for fallback in ("main.py", "src/experiment.py", "config.json"):
        if len(selected) < MAX_REPAIR_FILES:
            _add_path(selected, fallback)

    return selected[:MAX_REPAIR_FILES]


def _paths_from_runtime_text(code_dir: Path, text: str) -> list[str]:
    paths = []
    for match in re.finditer(r'File "([^"]+)"', text):
        raw_path = Path(match.group(1))
        try:
            resolved = raw_path.resolve()
            if _is_inside(code_dir, resolved):
                paths.append(_relative_path(code_dir, resolved))
        except OSError:
            continue

    for module in re.findall(r"from '([a-zA-Z_][\w.]*)'", text):
        module_path = code_dir / (module.replace(".", "/") + ".py")
        if module_path.exists():
            paths.append(_relative_path(code_dir, module_path.resolve()))
    return paths


def _read_related_files(code_dir: Path, related_paths: list[str]) -> list[dict]:
    result = []
    total_chars = 0
    for relative_path in related_paths:
        safe_path = _safe_relative_path(relative_path)
        if not safe_path:
            continue
        path = (code_dir / safe_path).resolve()
        if not _is_inside(code_dir, path) or not path.exists() or not path.is_file():
            continue
        content = path.read_text(encoding="utf-8-sig", errors="replace")
        remaining = MAX_TOTAL_FILE_CHARS - total_chars
        if remaining <= 0:
            break
        content = content[: min(MAX_FILE_CHARS, remaining)]
        total_chars += len(content)
        result.append({"path": safe_path, "content": content})
    return result


def _compact_commands(commands: object) -> list[dict]:
    result = []
    for command in commands if isinstance(commands, list) else []:
        if not isinstance(command, dict):
            continue
        result.append(
            {
                "command": command.get("command"),
                "returncode": command.get("returncode"),
                "stdout": _as_text(command.get("stdout"))[-1200:],
                "stderr": _as_text(command.get("stderr"))[-1200:],
            }
        )
    return result[-3:]


def _compact_chunks(chunks: list[dict]) -> list[dict]:
    result = []
    for chunk in chunks[:3]:
        result.append(
            {
                "chunk_id": chunk.get("chunk_id", ""),
                "title": chunk.get("title", ""),
                "content": _as_text(chunk.get("content"))[:800],
            }
        )
    return result


def _repair_symbol_context(spec: dict, validation_result: dict, file_context: list[dict]) -> dict:
    related_paths = {_safe_relative_path(item.get("path")) for item in file_context if isinstance(item, dict)}
    for diagnostic in validation_result.get("diagnostics", []):
        if not isinstance(diagnostic, dict):
            continue
        path = _safe_relative_path(diagnostic.get("file"))
        if path:
            related_paths.add(path)
        for related_file in diagnostic.get("related_files", []) if isinstance(diagnostic.get("related_files"), list) else []:
            path = _safe_relative_path(related_file)
            if path:
                related_paths.add(path)

    symbols = [
        _compact_symbol(symbol)
        for symbol in spec.get("symbols", [])
        if isinstance(symbol, dict) and (not related_paths or symbol.get("path") in related_paths)
    ]
    if not symbols:
        symbols = [_compact_symbol(symbol) for symbol in spec.get("symbols", []) if isinstance(symbol, dict)][:24]

    return {
        "related_paths": sorted(path for path in related_paths if path),
        "related_symbols": symbols[:32],
        "symbol_generation_order": spec.get("symbol_generation_order", [])[:80],
    }


def _compact_symbol(symbol: dict) -> dict:
    return {
        "id": symbol.get("id", ""),
        "path": symbol.get("path", ""),
        "kind": symbol.get("kind", ""),
        "class_name": symbol.get("class_name", ""),
        "name": symbol.get("name", ""),
        "signature": symbol.get("signature", ""),
        "responsibility": symbol.get("responsibility", ""),
        "depends_on": symbol.get("depends_on", []),
        "imports": symbol.get("imports", []),
    }


def _compact_repair_operations(operations: object) -> list[dict]:
    result = []
    for operation in operations if isinstance(operations, list) else []:
        if not isinstance(operation, dict):
            continue
        result.append(
            {
                "op": operation.get("op"),
                "symbol_id": operation.get("symbol_id"),
                "path": operation.get("path"),
                "class_name": operation.get("class_name"),
                "name": operation.get("name"),
                "old_preview": _as_text(operation.get("old"))[:120],
                "new_preview": _as_text(operation.get("new"))[:120],
                "replace_all": bool(operation.get("replace_all")),
            }
        )
    return result


def _repair_failure_result(last_result: dict, repairs: list[dict], repair_exc: Exception, attempts: int) -> dict:
    diagnostics = list(last_result.get("diagnostics", []))
    diagnostics.append(
        {
            "stage": "repair",
            "severity": "error",
            "code": "repair_failed",
            "file": None,
            "line": None,
            "message": str(repair_exc),
        }
    )
    return {
        "success": False,
        "message": f"Generated code repair failed: {repair_exc}",
        "attempts": attempts,
        "repairs": repairs,
        "diagnostics": diagnostics,
        "commands": last_result.get("commands", []),
    }


def _can_create_file(relative_path: str, validation_result: dict) -> bool:
    for diagnostic in validation_result.get("diagnostics", []):
        if not isinstance(diagnostic, dict):
            continue
        if diagnostic.get("code") == "missing_contract_module" and _safe_relative_path(diagnostic.get("file")) == relative_path:
            return True
    return False


def _add_path(selected: list[str], value: object) -> None:
    path = _safe_relative_path(value)
    if path and path not in selected:
        selected.append(path)


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str):
        return ""
    if Path(value).is_absolute():
        return ""
    path = value.replace("\\", "/").lstrip("/")
    parts = [part for part in path.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        return ""
    return "/".join(parts)


def _safe_identifier(value: object) -> str:
    text = _as_text(value)
    if not text:
        return ""
    if re.fullmatch(r"__\w+__", text):
        return text
    text = re.sub(r"\W+", "_", text).strip("_")
    if not text or text[0].isdigit():
        return ""
    return text


def _relative_path(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _is_inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _repair_max_attempts() -> int:
    return get_int_env("CODE_REPAIR_MAX_ATTEMPTS", DEFAULT_CODE_REPAIR_MAX_ATTEMPTS)


def _repair_max_tokens() -> int:
    value = get_int_env("CODE_REPAIR_MAX_TOKENS", DEFAULT_CODE_REPAIR_MAX_TOKENS)
    return max(1000, min(value, 16000))


def _write_repair_raw_response(code_dir: Path, attempt: int, content: str) -> str:
    path = code_dir.parent / f"repair_raw_response_attempt_{attempt}.txt"
    path.write_text(content, encoding="utf-8")
    return str(path)


def _write_validation_result(code_dir: Path, result: dict) -> None:
    path = code_dir.parent / "validation_result.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def _emit(
    event_callback: Callable[[dict], None] | None,
    event: str,
    attempt: int,
    message: str,
    **details: object,
) -> None:
    if event_callback is None:
        return
    event_callback(
        {
            "event": event,
            "attempt": attempt,
            "message": message,
            **details,
        }
    )


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()
