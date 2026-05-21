from __future__ import annotations

import ast
import json
import re
import textwrap

from app.llm.client import chat_completion
from app.services.python_import_manager import local_import_lines, render_python_import_block


MAX_STRUCTURED_CHUNKS = 3
MAX_BODY_REPAIR_ATTEMPTS = 1


def can_generate_structured_python_module(spec: dict, file_plan: dict) -> bool:
    path = file_plan.get("path", "")
    if not path.endswith(".py") or path == "main.py":
        return False

    contract = _contract_for_file(spec, path)
    return bool(_callable_symbols_for_file(spec, path) or _contract_functions(contract) or _contract_classes(contract))


def generate_structured_python_module(
    spec: dict,
    analysis: dict,
    chunks: list[dict],
    file_plan: dict,
) -> str:
    contract = _contract_for_file(spec, file_plan.get("path", ""))
    module_code = _render_module_skeleton(spec, contract)
    relevant_chunks = _select_relevant_chunks_for_file(chunks, file_plan, MAX_STRUCTURED_CHUNKS)

    for target in _ordered_generation_targets(spec, contract, file_plan.get("path", "")):
        if target["kind"] == "method":
            class_contract = target["class_contract"]
            method_contract = target["method_contract"]
            target_symbol = target["symbol"]
            method_code = _generate_method_code(
                spec,
                analysis,
                relevant_chunks,
                file_plan,
                contract,
                class_contract,
                method_contract,
                target_symbol,
                module_code,
            )
            module_code = replace_class_method(
                module_code,
                class_contract["name"],
                method_contract["name"],
                method_code,
            )
        elif target["kind"] == "function":
            function_contract = target["function_contract"]
            target_symbol = target["symbol"]
            function_code = _generate_function_code(
                spec,
                analysis,
                relevant_chunks,
                file_plan,
                contract,
                function_contract,
                target_symbol,
                module_code,
            )
            module_code = replace_top_level_function(module_code, function_contract["name"], function_code)

    diagnostics = validate_module_contract(module_code, contract)
    if diagnostics:
        messages = "; ".join(item["message"] for item in diagnostics)
        raise RuntimeError(f"structured module contract validation failed: {messages}")
    return module_code.rstrip() + "\n"


def _ordered_generation_targets(spec: dict, contract: dict, target_path: str) -> list[dict]:
    functions_by_name = {function["name"]: function for function in _contract_functions(contract)}
    methods_by_key = {}
    for class_contract in _contract_classes(contract):
        for method_contract in _class_methods(class_contract):
            methods_by_key[(class_contract["name"], method_contract["name"])] = (class_contract, method_contract)

    symbols_by_id = {
        symbol["id"]: symbol
        for symbol in spec.get("symbols", [])
        if isinstance(symbol, dict) and symbol.get("id") and symbol.get("path") == target_path
    }
    ordered_ids = [symbol_id for symbol_id in _as_list(spec.get("symbol_generation_order")) if isinstance(symbol_id, str)]
    if not ordered_ids:
        ordered_ids = sorted(symbols_by_id)

    targets = []
    seen = set()
    for symbol_id in ordered_ids:
        symbol = symbols_by_id.get(symbol_id)
        if not symbol:
            continue
        if symbol.get("kind") == "method":
            key = (symbol.get("class_name"), symbol.get("name"))
            if key in methods_by_key and ("method", *key) not in seen:
                class_contract, method_contract = methods_by_key[key]
                targets.append(
                    {
                        "kind": "method",
                        "class_contract": class_contract,
                        "method_contract": _merge_symbol_into_callable(method_contract, symbol),
                        "symbol": _merge_callable_into_symbol(symbol, method_contract),
                    }
                )
                seen.add(("method", *key))
        elif symbol.get("kind") == "function":
            name = symbol.get("name")
            if name in functions_by_name and ("function", name) not in seen:
                targets.append(
                    {
                        "kind": "function",
                        "function_contract": _merge_symbol_into_callable(functions_by_name[name], symbol),
                        "symbol": _merge_callable_into_symbol(symbol, functions_by_name[name]),
                    }
                )
                seen.add(("function", name))

    for (class_name, method_name), (class_contract, method_contract) in methods_by_key.items():
        if ("method", class_name, method_name) not in seen:
            targets.append(
                {
                    "kind": "method",
                    "class_contract": class_contract,
                    "method_contract": method_contract,
                    "symbol": _symbol_from_method_contract(target_path, class_name, method_contract),
                }
            )
            seen.add(("method", class_name, method_name))

    for name, function_contract in functions_by_name.items():
        if ("function", name) not in seen:
            targets.append(
                {
                    "kind": "function",
                    "function_contract": function_contract,
                    "symbol": _symbol_from_function_contract(target_path, function_contract),
                }
            )
            seen.add(("function", name))

    return targets


def _merge_symbol_into_callable(callable_contract: dict, symbol: dict) -> dict:
    result = dict(callable_contract)
    result["symbol_id"] = symbol.get("id", "")
    for key in ("signature", "responsibility", "depends_on", "imports"):
        if not result.get(key) and symbol.get(key):
            result[key] = symbol[key]
    return result


def _merge_callable_into_symbol(symbol: dict, callable_contract: dict) -> dict:
    result = dict(symbol)
    for key in ("signature", "responsibility", "inputs", "outputs"):
        if not result.get(key) and callable_contract.get(key):
            result[key] = callable_contract[key]
    return result


def _symbol_from_function_contract(path: str, function_contract: dict) -> dict:
    name = function_contract["name"]
    return {
        "id": f"{_module_name_for_path(path)}.{name}",
        "path": path,
        "kind": "function",
        "name": name,
        "signature": function_contract.get("signature", ""),
        "responsibility": function_contract.get("responsibility", ""),
        "depends_on": function_contract.get("depends_on", []),
        "imports": function_contract.get("imports", []),
    }


def _symbol_from_method_contract(path: str, class_name: str, method_contract: dict) -> dict:
    name = method_contract["name"]
    return {
        "id": f"{_module_name_for_path(path)}.{class_name}.{name}",
        "path": path,
        "kind": "method",
        "class_name": class_name,
        "name": name,
        "signature": method_contract.get("signature", ""),
        "responsibility": method_contract.get("responsibility", ""),
        "depends_on": method_contract.get("depends_on", []),
        "imports": method_contract.get("imports", []),
    }


def _module_name_for_path(path: str) -> str:
    clean_path = path.replace("\\", "/")
    if clean_path.endswith(".py"):
        clean_path = clean_path[:-3]
    return ".".join(part for part in clean_path.split("/") if part and part != "__init__")


def _symbol_generation_context(spec: dict, target_symbol: dict) -> dict:
    symbols = [symbol for symbol in spec.get("symbols", []) if isinstance(symbol, dict)]
    symbols_by_id = {symbol.get("id"): symbol for symbol in symbols if symbol.get("id")}
    dependency_symbols = [
        _compact_symbol(symbols_by_id[dependency_id])
        for dependency_id in _as_list(target_symbol.get("depends_on"))
        if isinstance(dependency_id, str) and dependency_id in symbols_by_id
    ]
    target_path = target_symbol.get("path", "")
    same_file_symbols = [
        _compact_symbol(symbol)
        for symbol in symbols
        if symbol.get("path") == target_path and symbol.get("id") != target_symbol.get("id")
    ]
    return {
        "generation_mode": "symbol_driven",
        "target_symbol_id": target_symbol.get("id", ""),
        "dependency_symbols": dependency_symbols,
        "same_file_symbols": same_file_symbols,
        "managed_imports": _managed_imports_for_file(spec, target_path),
        "symbol_generation_order": spec.get("symbol_generation_order", []),
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
    }


def _managed_imports_for_file(spec: dict, target_path: str) -> list[str]:
    return local_import_lines(spec, target_path)


def _callable_symbols_for_file(spec: dict, target_path: str) -> list[dict]:
    return [
        symbol
        for symbol in spec.get("symbols", [])
        if isinstance(symbol, dict)
        and symbol.get("path") == target_path
        and symbol.get("kind") in {"function", "method"}
    ]


def validate_module_contract(module_code: str, contract: dict) -> list[dict]:
    diagnostics = []
    try:
        tree = ast.parse(module_code)
    except SyntaxError as exc:
        return [{"code": "invalid_python_syntax", "message": str(exc)}]

    top_level = {node.name: node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}
    for function_contract in _contract_functions(contract):
        name = function_contract["name"]
        node = top_level.get(name)
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            diagnostics.append({"code": "missing_function", "message": f"missing top-level function {name}"})

    for class_contract in _contract_classes(contract):
        class_name = class_contract["name"]
        class_node = top_level.get(class_name)
        if not isinstance(class_node, ast.ClassDef):
            diagnostics.append({"code": "missing_class", "message": f"missing class {class_name}"})
            continue
        method_names = {node.name for node in class_node.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for method_contract in _class_methods(class_contract):
            method_name = method_contract["name"]
            if method_name not in method_names:
                diagnostics.append(
                    {
                        "code": "missing_method",
                        "message": f"missing method {class_name}.{method_name}",
                    }
                )

    return diagnostics


def replace_top_level_function(module_code: str, function_name: str, new_function_code: str) -> str:
    tree = ast.parse(module_code)
    replacement = _normalize_block(new_function_code, indent=0)
    _assert_single_function(replacement, function_name)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return _replace_lines(module_code, node.lineno, node.end_lineno, replacement)

    raise RuntimeError(f"top-level function not found: {function_name}")


def replace_class_method(module_code: str, class_name: str, method_name: str, new_method_code: str) -> str:
    tree = ast.parse(module_code)
    replacement = _normalize_block(new_method_code, indent=4)
    _assert_single_function(textwrap.dedent(replacement), method_name)

    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                return _replace_lines(module_code, child.lineno, child.end_lineno, replacement)

    raise RuntimeError(f"class method not found: {class_name}.{method_name}")


def _generate_function_code(
    spec: dict,
    analysis: dict,
    relevant_chunks: list[dict],
    file_plan: dict,
    module_contract: dict,
    function_contract: dict,
    target_symbol: dict,
    module_code: str,
) -> str:
    messages = _function_messages(
        spec,
        analysis,
        relevant_chunks,
        file_plan,
        module_contract,
        function_contract,
        target_symbol,
        module_code,
    )
    return _generate_valid_block(messages, function_contract["name"])


def _generate_method_code(
    spec: dict,
    analysis: dict,
    relevant_chunks: list[dict],
    file_plan: dict,
    module_contract: dict,
    class_contract: dict,
    method_contract: dict,
    target_symbol: dict,
    module_code: str,
) -> str:
    messages = _method_messages(
        spec,
        analysis,
        relevant_chunks,
        file_plan,
        module_contract,
        class_contract,
        method_contract,
        target_symbol,
        module_code,
    )
    return _generate_valid_block(messages, method_contract["name"])


def _generate_valid_block(messages: list[dict], expected_name: str) -> str:
    last_error: Exception | None = None
    for attempt in range(MAX_BODY_REPAIR_ATTEMPTS + 1):
        content = _strip_code_fence(chat_completion(messages, temperature=0 if attempt else 0.1, max_tokens=2600))
        block = _extract_function_block(content)
        try:
            _assert_single_function(block, expected_name)
            return block
        except Exception as exc:
            last_error = exc
            messages = [
                {
                    "role": "system",
                    "content": "Return only one complete Python def block. No Markdown, no explanation.",
                },
                {
                    "role": "user",
                    "content": (
                        f"The previous function block was invalid for {expected_name}: {exc}\n"
                        f"Return a corrected complete def block named {expected_name}.\n"
                        f"previous_output:\n{content[:2200]}"
                    ),
                },
            ]

    raise RuntimeError(f"failed to generate valid function block {expected_name}: {last_error}")


def _function_messages(
    spec: dict,
    analysis: dict,
    relevant_chunks: list[dict],
    file_plan: dict,
    module_contract: dict,
    function_contract: dict,
    target_symbol: dict,
    module_code: str,
) -> list[dict]:
    symbol_context = _symbol_generation_context(spec, target_symbol)
    return [
        {
            "role": "system",
            "content": (
                "You fill exactly one symbol-level function in generated research code. "
                "Return only one complete Python def block. No Markdown. "
                "Keep it smoke-test friendly: short runtime, no network, no large downloads. "
                "Use imports and names already present in the module skeleton. "
                "Do not add project-local imports inside the function body. "
                "Use local imports only for optional third-party dependencies that may be unavailable."
            ),
        },
        {
            "role": "user",
            "content": (
                f"target_file: {file_plan.get('path')}\n"
                f"target_symbol:\n{json.dumps(target_symbol, ensure_ascii=False)}\n\n"
                f"symbol_context:\n{json.dumps(symbol_context, ensure_ascii=False)}\n\n"
                f"module_contract:\n{json.dumps(module_contract, ensure_ascii=False)}\n\n"
                f"function_contract:\n{json.dumps(function_contract, ensure_ascii=False)}\n\n"
                f"current_module_code:\n{module_code[:7000]}\n\n"
                f"code_spec:\n{json.dumps(_compact_spec(spec), ensure_ascii=False)}\n\n"
                f"analysis:\n{json.dumps(_compact_analysis(analysis), ensure_ascii=False)}\n\n"
                f"relevant_chunks:\n{json.dumps(relevant_chunks, ensure_ascii=False)}"
            ),
        },
    ]


def _method_messages(
    spec: dict,
    analysis: dict,
    relevant_chunks: list[dict],
    file_plan: dict,
    module_contract: dict,
    class_contract: dict,
    method_contract: dict,
    target_symbol: dict,
    module_code: str,
) -> list[dict]:
    symbol_context = _symbol_generation_context(spec, target_symbol)
    return [
        {
            "role": "system",
            "content": (
                "You fill exactly one symbol-level class method in generated research code. "
                "Return only one complete Python def block for the method. No Markdown. "
                "Use existing attribute names from __init__ when available. "
                "Keep it smoke-test friendly and deterministic. "
                "Do not add project-local imports inside the method body."
            ),
        },
        {
            "role": "user",
            "content": (
                f"target_file: {file_plan.get('path')}\n"
                f"target_symbol:\n{json.dumps(target_symbol, ensure_ascii=False)}\n\n"
                f"symbol_context:\n{json.dumps(symbol_context, ensure_ascii=False)}\n\n"
                f"module_contract:\n{json.dumps(module_contract, ensure_ascii=False)}\n\n"
                f"class_contract:\n{json.dumps(class_contract, ensure_ascii=False)}\n\n"
                f"method_contract:\n{json.dumps(method_contract, ensure_ascii=False)}\n\n"
                f"current_module_code:\n{module_code[:7000]}\n\n"
                f"code_spec:\n{json.dumps(_compact_spec(spec), ensure_ascii=False)}\n\n"
                f"analysis:\n{json.dumps(_compact_analysis(analysis), ensure_ascii=False)}\n\n"
                f"relevant_chunks:\n{json.dumps(relevant_chunks, ensure_ascii=False)}"
            ),
        },
    ]


def _render_module_skeleton(spec: dict, contract: dict) -> str:
    lines = render_python_import_block(spec, contract.get("path", "")).rstrip().splitlines()
    lines.append("")
    lines.append("")
    for class_contract in _contract_classes(contract):
        lines.extend(_render_class_skeleton(class_contract))
        lines.append("")
        lines.append("")

    for function_contract in _contract_functions(contract):
        lines.extend(_render_function_skeleton(function_contract))
        lines.append("")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_class_skeleton(class_contract: dict) -> list[str]:
    class_name = class_contract["name"]
    lines = [f"class {class_name}:", f'    """{_docstring(class_contract)}"""']
    methods = _class_methods(class_contract)
    if not methods:
        lines.append("    pass")
        return lines

    for index, method_contract in enumerate(methods):
        if index:
            lines.append("")
        for line in _render_function_skeleton(method_contract, indent=4):
            lines.append(line)
    return lines


def _render_function_skeleton(function_contract: dict, indent: int = 0) -> list[str]:
    prefix = " " * indent
    signature = _signature(function_contract)
    return [
        f"{prefix}def {signature}:",
        f'{prefix}    """{_docstring(function_contract)}"""',
        f"{prefix}    pass",
    ]


def _contract_for_file(spec: dict, target_path: str) -> dict:
    for contract in spec.get("module_contracts", []):
        if isinstance(contract, dict) and contract.get("path") == target_path:
            return contract
    return {"path": target_path, "exports": []}


def _contract_functions(contract: dict) -> list[dict]:
    functions = []
    for item in _as_list(contract.get("functions")):
        normalized = _normalize_callable_contract(item, default_type="function")
        if normalized:
            functions.append(normalized)

    for export in _as_list(contract.get("exports")):
        normalized = _normalize_callable_contract(export, default_type="function")
        if normalized and normalized.get("type") == "function" and normalized["name"] not in {item["name"] for item in functions}:
            functions.append(normalized)
    return functions


def _contract_classes(contract: dict) -> list[dict]:
    classes = []
    for item in _as_list(contract.get("classes")):
        normalized = _normalize_class_contract(item)
        if normalized:
            classes.append(normalized)

    for export in _as_list(contract.get("exports")):
        normalized = _normalize_class_contract(export)
        if normalized and normalized["name"] not in {item["name"] for item in classes}:
            classes.append(normalized)
    return classes


def _class_methods(class_contract: dict) -> list[dict]:
    methods = []
    for item in _as_list(class_contract.get("methods")):
        normalized = _normalize_callable_contract(item, default_type="method")
        if normalized:
            methods.append(normalized)
    return methods


def _normalize_class_contract(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    if value.get("type") not in {None, "class"} and "methods" not in value:
        return None
    name = _safe_identifier(value.get("name"))
    if not name:
        return None
    return {
        "type": "class",
        "name": name,
        "responsibility": _as_text(value.get("responsibility")) or _as_text(value.get("purpose")),
        "methods": _as_list(value.get("methods")),
    }


def _normalize_callable_contract(value: object, default_type: str) -> dict | None:
    if isinstance(value, str):
        name = _safe_identifier(value)
        return {"type": default_type, "name": name} if name else None
    if not isinstance(value, dict):
        return None
    name = _safe_identifier(value.get("name"))
    if not name:
        return None
    return {
        "type": _as_text(value.get("type")) or default_type,
        "name": name,
        "signature": _as_text(value.get("signature")),
        "responsibility": _as_text(value.get("responsibility")) or _as_text(value.get("purpose")),
        "inputs": _as_list(value.get("inputs")),
        "outputs": _as_list(value.get("outputs")),
    }


def _signature(contract: dict) -> str:
    signature = _as_text(contract.get("signature"))
    name = contract["name"]
    if signature:
        signature = signature.removeprefix("def ").strip()
        signature = signature[:-1] if signature.endswith(":") else signature
        if signature.startswith(name):
            return signature
        if signature.startswith("("):
            return _prefix_signature_name(name, signature, is_method=contract.get("type") == "method")

    if name == "__init__":
        return "__init__(self, *args, **kwargs) -> None"
    if contract.get("type") == "method":
        return f"{name}(self, *args, **kwargs)"
    return f"{name}(*args, **kwargs) -> dict"


def _prefix_signature_name(name: str, signature: str, is_method: bool) -> str:
    close_index = signature.find(")")
    if close_index < 0:
        return f"{name}{signature}"
    params = signature[1:close_index].strip()
    suffix = signature[close_index + 1 :]
    if is_method and not params.startswith(("self", "cls")):
        params = "self" + (f", {params}" if params else "")
    return f"{name}({params}){suffix}"


def _docstring(contract: dict) -> str:
    text = _as_text(contract.get("responsibility")) or "Generated research-code contract block."
    return text.replace('"""', '\\"\\"\\"')


def _extract_function_block(content: str) -> str:
    text = _strip_code_fence(content).strip()
    match = re.search(r"(?ms)^(async\s+def|def)\s+\w+\s*\(.*", text)
    if not match:
        return text
    return text[match.start() :].rstrip() + "\n"


def _assert_single_function(block: str, expected_name: str) -> None:
    tree = ast.parse(block)
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(functions) != 1 or functions[0].name != expected_name:
        raise RuntimeError(f"expected one function named {expected_name}")


def _normalize_block(block: str, indent: int) -> str:
    text = textwrap.dedent(_strip_code_fence(block)).strip()
    if indent:
        text = textwrap.indent(text, " " * indent)
    return text.rstrip()


def _replace_lines(module_code: str, start_line: int, end_line: int | None, replacement: str) -> str:
    if end_line is None:
        raise RuntimeError("AST node end line is unavailable")
    lines = module_code.splitlines()
    updated = lines[: start_line - 1] + replacement.splitlines() + lines[end_line:]
    result = "\n".join(updated).rstrip() + "\n"
    ast.parse(result)
    return result


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


def _select_relevant_chunks_for_file(chunks: list[dict], file_plan: dict, limit: int) -> list[dict]:
    purpose = f"{file_plan.get('path', '')} {file_plan.get('purpose', '')}".lower()
    words = re.findall(r"[a-zA-Z_]{3,}|[\u4e00-\u9fff]{2,}", purpose)
    scored = []
    for chunk in chunks:
        text = _chunk_text(chunk).lower()
        score = sum(1 for word in words if word.lower() in text)
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [chunk for score, chunk in scored if score > 0][:limit]
    if not selected:
        selected = [item[1] for item in scored[:limit]]
    return [_compact_chunk(chunk) for chunk in selected[:limit]]


def _compact_chunk(chunk: dict) -> dict:
    metadata = chunk.get("metadata", {})
    return {
        "chunk_id": chunk.get("chunk_id", ""),
        "title": chunk.get("title") or metadata.get("section_title", ""),
        "element_type": metadata.get("element_type", ""),
        "page_start": chunk.get("page_start"),
        "page_end": chunk.get("page_end"),
        "content": _short_text(chunk.get("content", ""), 1200),
    }


def _compact_analysis(analysis: dict) -> dict:
    final_summary = analysis.get("final_summary") or {}
    return {
        "title": final_summary.get("title") or analysis.get("title", ""),
        "summary": final_summary.get("executive_summary") or analysis.get("abstract", ""),
        "method": final_summary.get("method_overview") or analysis.get("method_summary", ""),
        "experiment": final_summary.get("experiment_or_argument_summary") or analysis.get("experiment_summary", ""),
        "reproducible_parts": analysis.get("reproducible_parts", []),
        "required_inputs": analysis.get("required_inputs", []),
        "possible_code_modules": analysis.get("possible_code_modules", []),
        "reproducibility_notes": final_summary.get("reproducibility_notes", []),
        "limitations": final_summary.get("limitations", []),
        "code_relevance": final_summary.get("code_relevance", ""),
        "code_generation_strategy": analysis.get("code_generation_strategy", "analysis_tool"),
        "reproducibility_risk": analysis.get("reproducibility_risk", "medium"),
    }


def _compact_spec(spec: dict) -> dict:
    return {
        "project_name": spec.get("project_name", ""),
        "framework": spec.get("framework", ""),
        "entrypoint": spec.get("entrypoint", {}),
        "run_command": spec.get("run_command", ""),
        "dependencies": spec.get("dependencies", []),
        "config": spec.get("config", {}),
        "config_schema": spec.get("config_schema", {}),
        "module_contracts": spec.get("module_contracts", []),
        "symbols": spec.get("symbols", []),
        "symbol_generation_order": spec.get("symbol_generation_order", []),
        "interfaces": spec.get("interfaces", {}),
        "expected_outputs": spec.get("expected_outputs", []),
        "assumptions": spec.get("assumptions", [])[:6],
        "missing_details": spec.get("missing_details", [])[:6],
        "files": spec.get("files", []),
    }


def _chunk_text(chunk: dict) -> str:
    metadata = chunk.get("metadata", {})
    return " ".join(
        [
            _as_text(chunk.get("title")),
            _as_text(metadata.get("section_title")),
            _as_text(metadata.get("element_type")),
            _as_text(chunk.get("content")),
        ]
    )


def _short_text(value: object, limit: int) -> str:
    text = _as_text(value)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _strip_code_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.rstrip() + "\n"
