from __future__ import annotations

import re


def normalize_symbols(value: object, module_contracts: list[dict], files: list[dict]) -> list[dict]:
    file_paths = {item["path"] for item in files if isinstance(item, dict) and item.get("path")}
    symbols_by_id: dict[str, dict] = {}
    contract_symbols = []
    for contract in module_contracts:
        if not isinstance(contract, dict):
            continue
        path = _safe_relative_path(contract.get("path"))
        if not path or path not in file_paths or not path.endswith(".py"):
            continue
        contract_symbols.extend(_symbols_from_contract(contract))
    allowed_symbol_ids = {symbol["id"] for symbol in contract_symbols}

    for item in _as_list(value):
        symbol = _normalize_symbol(item, file_paths)
        if symbol and (not allowed_symbol_ids or symbol["id"] in allowed_symbol_ids):
            symbols_by_id[symbol["id"]] = symbol

    for symbol in contract_symbols:
        if symbol["id"] in symbols_by_id:
            _merge_symbol_defaults(symbols_by_id[symbol["id"]], symbol)
        else:
            symbols_by_id[symbol["id"]] = symbol

    return [symbols_by_id[symbol_id] for symbol_id in sorted(symbols_by_id)]


def build_symbol_generation_order(symbols: list[dict]) -> list[str]:
    return [symbol["id"] for symbol in sort_symbols(symbols)]


def sort_symbols(symbols: list[dict]) -> list[dict]:
    symbols_by_id = {symbol["id"]: symbol for symbol in symbols if isinstance(symbol, dict) and symbol.get("id")}
    dependencies_by_id: dict[str, set[str]] = {}
    dependents_by_id: dict[str, set[str]] = {symbol_id: set() for symbol_id in symbols_by_id}

    for symbol_id, symbol in symbols_by_id.items():
        dependencies = {
            dep
            for dep in _as_string_list(symbol.get("depends_on"))
            if dep in symbols_by_id and dep != symbol_id
        }
        if symbol.get("kind") == "method":
            class_id = symbol_id.rsplit(".", 1)[0]
            if class_id in symbols_by_id:
                dependencies.add(class_id)
        dependencies_by_id[symbol_id] = dependencies
        for dependency in dependencies:
            dependents_by_id.setdefault(dependency, set()).add(symbol_id)

    ready = sorted(
        [symbol_id for symbol_id, dependencies in dependencies_by_id.items() if not dependencies],
        key=lambda symbol_id: _symbol_sort_key(symbols_by_id[symbol_id]),
    )
    ordered_ids: list[str] = []

    while ready:
        symbol_id = ready.pop(0)
        if symbol_id in ordered_ids:
            continue
        ordered_ids.append(symbol_id)
        for dependent_id in sorted(dependents_by_id.get(symbol_id, set()), key=lambda item: _symbol_sort_key(symbols_by_id[item])):
            dependencies_by_id[dependent_id].discard(symbol_id)
            if not dependencies_by_id[dependent_id] and dependent_id not in ordered_ids and dependent_id not in ready:
                ready.append(dependent_id)
        ready.sort(key=lambda item: _symbol_sort_key(symbols_by_id[item]))

    remaining = [symbol_id for symbol_id in symbols_by_id if symbol_id not in ordered_ids]
    ordered_ids.extend(sorted(remaining, key=lambda symbol_id: _symbol_sort_key(symbols_by_id[symbol_id])))
    return [symbols_by_id[symbol_id] for symbol_id in ordered_ids]


def group_symbols_by_file(symbols: list[dict], generation_order: list[str] | None = None) -> dict[str, list[dict]]:
    symbols_by_id = {symbol["id"]: symbol for symbol in symbols if isinstance(symbol, dict) and symbol.get("id")}
    ordered_ids = generation_order or build_symbol_generation_order(symbols)
    grouped: dict[str, list[dict]] = {}
    for symbol_id in ordered_ids:
        symbol = symbols_by_id.get(symbol_id)
        if not symbol:
            continue
        grouped.setdefault(symbol.get("path", ""), []).append(symbol)
    return grouped


def module_name_for_path(path: str) -> str:
    clean_path = _safe_relative_path(path)
    if clean_path.endswith(".py"):
        clean_path = clean_path[:-3]
    return ".".join(part for part in clean_path.split("/") if part and part != "__init__")


def symbol_id_for_function(path: str, name: str) -> str:
    module_name = module_name_for_path(path)
    return f"{module_name}.{name}" if module_name else name


def symbol_id_for_class(path: str, class_name: str) -> str:
    module_name = module_name_for_path(path)
    return f"{module_name}.{class_name}" if module_name else class_name


def symbol_id_for_method(path: str, class_name: str, method_name: str) -> str:
    return f"{symbol_id_for_class(path, class_name)}.{method_name}"


def _symbols_from_contract(contract: dict) -> list[dict]:
    path = _safe_relative_path(contract.get("path"))
    symbols = []

    for function in _contract_functions(contract):
        name = function["name"]
        symbols.append(
            {
                "id": symbol_id_for_function(path, name),
                "path": path,
                "kind": "function",
                "name": name,
                "signature": _as_text(function.get("signature")),
                "responsibility": _as_text(function.get("responsibility")),
                "depends_on": _as_string_list(function.get("depends_on")),
                "imports": _normalize_imports(function.get("imports")),
            }
        )

    for class_contract in _contract_classes(contract):
        class_name = class_contract["name"]
        symbols.append(
            {
                "id": symbol_id_for_class(path, class_name),
                "path": path,
                "kind": "class",
                "name": class_name,
                "signature": _as_text(class_contract.get("signature")),
                "responsibility": _as_text(class_contract.get("responsibility")),
                "depends_on": _as_string_list(class_contract.get("depends_on")),
                "imports": _normalize_imports(class_contract.get("imports")),
            }
        )
        for method in _contract_methods(class_contract):
            method_name = method["name"]
            symbols.append(
                {
                    "id": symbol_id_for_method(path, class_name, method_name),
                    "path": path,
                    "kind": "method",
                    "class_name": class_name,
                    "name": method_name,
                    "signature": _as_text(method.get("signature")),
                    "responsibility": _as_text(method.get("responsibility")),
                    "depends_on": _as_string_list(method.get("depends_on")),
                    "imports": _normalize_imports(method.get("imports")),
                }
            )

    return symbols


def _normalize_symbol(value: object, file_paths: set[str]) -> dict | None:
    if not isinstance(value, dict):
        return None
    path = _safe_relative_path(value.get("path"))
    if not path or path not in file_paths or not path.endswith(".py"):
        return None
    kind = _as_text(value.get("kind")).lower()
    if kind not in {"class", "function", "method"}:
        return None
    name = _safe_identifier(value.get("name"))
    if not name:
        return None

    class_name = _safe_identifier(value.get("class_name"))
    if kind == "method" and not class_name:
        return None

    if kind == "class":
        symbol_id = _as_text(value.get("id")) or symbol_id_for_class(path, name)
    elif kind == "method":
        symbol_id = _as_text(value.get("id")) or symbol_id_for_method(path, class_name, name)
    else:
        symbol_id = _as_text(value.get("id")) or symbol_id_for_function(path, name)

    symbol = {
        "id": _safe_symbol_id(symbol_id),
        "path": path,
        "kind": kind,
        "name": name,
        "signature": _as_text(value.get("signature")),
        "responsibility": _as_text(value.get("responsibility")) or _as_text(value.get("purpose")),
        "depends_on": _as_string_list(value.get("depends_on")),
        "imports": _normalize_imports(value.get("imports")),
    }
    if class_name:
        symbol["class_name"] = class_name
    return symbol if symbol["id"] else None


def _merge_symbol_defaults(target: dict, defaults: dict) -> None:
    for key in ("signature", "responsibility", "class_name"):
        if not target.get(key) and defaults.get(key):
            target[key] = defaults[key]
    if not target.get("depends_on") and defaults.get("depends_on"):
        target["depends_on"] = defaults["depends_on"]
    if not target.get("imports") and defaults.get("imports"):
        target["imports"] = defaults["imports"]


def _symbol_sort_key(symbol: dict) -> tuple:
    path = _as_text(symbol.get("path"))
    name = _as_text(symbol.get("name"))
    kind = _as_text(symbol.get("kind"))
    if kind == "class":
        kind_rank = 0
    elif kind == "method" and name == "__init__":
        kind_rank = 1
    elif kind == "method":
        kind_rank = 2
    elif name in {"evaluate_agent", "plot_curves"}:
        kind_rank = 3
    elif name == "train":
        kind_rank = 4
    elif name == "run_algorithm":
        kind_rank = 5
    elif name == "run_experiment":
        kind_rank = 8
    elif path == "main.py" or name == "main":
        kind_rank = 9
    else:
        kind_rank = 6
    path_rank = 9 if path == "main.py" else 0
    return (path_rank, kind_rank, path, _as_text(symbol.get("class_name")), name, _as_text(symbol.get("id")))


def _contract_functions(contract: dict) -> list[dict]:
    functions = []
    seen = set()
    for item in _as_list(contract.get("functions")):
        function = _normalize_callable(item, default_type="function")
        if function and function.get("type") == "function" and function["name"] not in seen:
            seen.add(function["name"])
            functions.append(function)
    for item in _as_list(contract.get("exports")):
        export = _normalize_callable(item, default_type="function")
        if export and export.get("type") == "function" and export["name"] not in seen:
            seen.add(export["name"])
            functions.append(export)
    return functions


def _contract_classes(contract: dict) -> list[dict]:
    classes = []
    seen = set()
    for item in _as_list(contract.get("classes")):
        class_contract = _normalize_class(item)
        if class_contract and class_contract["name"] not in seen:
            seen.add(class_contract["name"])
            classes.append(class_contract)
    for item in _as_list(contract.get("exports")):
        class_contract = _normalize_class(item)
        if class_contract and class_contract["name"] not in seen:
            seen.add(class_contract["name"])
            classes.append(class_contract)
    return classes


def _contract_methods(class_contract: dict) -> list[dict]:
    methods = []
    seen = set()
    for item in _as_list(class_contract.get("methods")):
        method = _normalize_callable(item, default_type="method")
        if method and method["name"] not in seen:
            seen.add(method["name"])
            methods.append(method)
    return methods


def _normalize_class(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    if value.get("type") not in {None, "", "class"} and "methods" not in value:
        return None
    name = _safe_identifier(value.get("name"))
    if not name:
        return None
    return {
        "type": "class",
        "name": name,
        "signature": _as_text(value.get("signature")),
        "responsibility": _as_text(value.get("responsibility")) or _as_text(value.get("purpose")),
        "methods": _as_list(value.get("methods")),
        "depends_on": _as_string_list(value.get("depends_on")),
        "imports": _normalize_imports(value.get("imports")),
    }


def _normalize_callable(value: object, default_type: str) -> dict | None:
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
        "depends_on": _as_string_list(value.get("depends_on")),
        "imports": _normalize_imports(value.get("imports")),
    }


def _normalize_imports(value: object) -> list[dict]:
    imports = []
    seen = set()
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        module = _as_text(item.get("from") or item.get("module"))
        name = _as_text(item.get("import") or item.get("name"))
        if not module or not name:
            continue
        key = (module, name)
        if key in seen:
            continue
        seen.add(key)
        imports.append({"from": module, "import": name})
    return imports


def _safe_symbol_id(value: object) -> str:
    text = _as_text(value).replace("/", ".").replace("\\", ".")
    parts = [_safe_identifier(part) for part in text.split(".")]
    return ".".join(part for part in parts if part)


def _safe_relative_path(value: object) -> str:
    text = _as_text(value).replace("\\", "/").lstrip("/")
    parts = [part for part in text.split("/") if part not in {"", ".", ".."}]
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
