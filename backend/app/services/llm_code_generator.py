import ast
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.config import DEFAULT_CODE_GEN_MAX_WORKERS
from app.llm.client import chat_completion
from app.services.experiment_frameworks import apply_experiment_framework
from app.services.experiment_spec_builder import normalize_experiment_spec
from app.services.language_adapter import get_language_adapter
from app.services.symbol_graph import build_symbol_generation_order, normalize_symbols


MAX_SPEC_CHUNKS = 14
MAX_FILE_CHUNKS = 4
MAX_CHUNK_CHARS = 1200
MAX_FILES = 14
MAX_CLASS_METHODS = 8
MAX_PYTHON_REPAIR_ATTEMPTS = 2
LOCAL_RENDERED_FILES = {"README.md", "requirements.txt", "Dockerfile", "config.json", "main.py"}


def build_code_spec(
    analysis: dict,
    chunks: list[dict],
    experiment_spec: dict | None = None,
    graph_context: dict | None = None,
) -> dict:
    experiment_spec = normalize_experiment_spec(experiment_spec or {}, analysis, graph_context)
    relevant_chunks = _select_relevant_chunks(chunks, MAX_SPEC_CHUNKS)
    compact_graph_context = _compact_graph_context(graph_context or {})
    messages = [
        {
            "role": "system",
            "content": (
                "You are a research-code architect. Plan a concrete runnable code project from the paper analysis "
                "and source chunks. Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "Generate code_spec JSON with these fields: project_name, project_type, language, framework, entry_file, "
                "run_command, docker, dependencies, config, assumptions, missing_details, files, entrypoint, "
                "module_contracts, symbols, interfaces, experiment_contract, graph_alignment, config_schema, expected_outputs.\n"
                "project_type must be one of: rl, ml, simulation, optimization, analysis.\n"
                "files must be an array of objects with path, purpose, kind.\n"
                "Always include src/experiment.py. It must export run_experiment(config: dict) -> dict.\n"
                "main.py must load config and call src.experiment.run_experiment(config); do not make main.py orchestrate modules directly.\n"
                "The generated project should prepare minimal data or a simulation environment, initialize the paper model/agent/algorithm, "
                "and run one short training/simulation/optimization/analysis pass. Validation only checks that this smoke run completes; "
                "do not optimize for paper-quality metrics or full reproduction results.\n"
                "module_contracts must declare every public class/function used across generated files.\n"
                "For each Python module contract, include exports and, when useful, functions/classes/methods.\n"
                "Function contracts should include name, type, signature, responsibility, inputs, outputs.\n"
                "Class contracts should include name, responsibility, and methods with name/signature/responsibility.\n"
                "symbols must list callable generation units with id, path, kind, name, class_name when method, "
                "signature, responsibility, depends_on, imports. Use stable ids like src.algorithm.run_algorithm "
                "and src.agent.Agent.select_action.\n"
                "Example module_contract: "
                '{"path":"src/algorithm.py","exports":[{"type":"function","name":"run_algorithm",'
                '"signature":"run_algorithm(config: dict) -> dict","responsibility":"Run the paper algorithm and return metrics/history."}],'
                '"functions":[{"name":"run_algorithm","signature":"run_algorithm(config: dict) -> dict"}],'
                '"classes":[{"name":"Environment","methods":[{"name":"__init__","signature":"__init__(self, config: dict) -> None"},'
                '{"name":"reset","signature":"reset(self)"},{"name":"step","signature":"step(self, action)"}]}]}.\n'
                "Example symbol: "
                '{"id":"src.algorithm.run_algorithm","path":"src/algorithm.py","kind":"function",'
                '"name":"run_algorithm","signature":"run_algorithm(config: dict) -> dict",'
                '"depends_on":["src.environment.Environment"],'
                '"imports":[{"from":"src.environment","import":"Environment"}]}.\n'
                "Pick one canonical name for each concept and reuse it everywhere.\n"
                "Keep each class focused. If a class would need more than 8 methods, split it during planning into "
                "small helper/coordinator classes in the same module or a separate module. Keep the public facade class stable.\n"
                "Every generated Python file must have a module contract.\n"
                "Always include README.md, requirements.txt, Dockerfile, config.json, main.py.\n"
                "For reinforcement learning, machine learning, simulation, or optimization papers, include real src modules.\n"
                "For ML/RL/simulation projects, prefer stable interfaces: environment, agent/model, training, evaluation, visualization.\n"
                "Use no more than 14 files. Put missing paper parameters into assumptions and missing_details.\n"
                "Treat experiment_spec as the highest-priority experiment definition. Use its state/action/reward/data/training fields "
                "when planning modules and contracts. If analysis and experiment_spec conflict, follow experiment_spec and record "
                "the uncertainty in assumptions or missing_details.\n\n"
                "Use graph_context to map paper entities to code modules: environment -> Environment class, "
                "state -> observation construction, action -> action parser/space, reward -> reward function, "
                "algorithm/model -> Agent/Model class, dataset -> loader or synthetic fallback, metric -> evaluation outputs. "
                "Only use graph facts with source_chunk_ids.\n\n"
                f"experiment_spec:\n{json.dumps(experiment_spec, ensure_ascii=False)}\n\n"
                f"graph_context:\n{json.dumps(compact_graph_context, ensure_ascii=False)}\n\n"
                f"analysis:\n{json.dumps(_compact_analysis(analysis), ensure_ascii=False)}\n\n"
                f"relevant_chunks:\n{json.dumps(relevant_chunks, ensure_ascii=False)}"
            ),
        },
    ]
    try:
        spec = _chat_json(messages, max_tokens=4200)
    except Exception:
        spec = _fallback_code_spec(analysis)
    spec = apply_experiment_framework(spec, experiment_spec)
    return _normalize_code_spec(spec, analysis, experiment_spec, graph_context)


def generate_code_files_from_spec(
    spec: dict,
    analysis: dict,
    chunks: list[dict],
    output_dir: Path,
    graph_context: dict | None = None,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if graph_context and not spec.get("graph_context"):
        spec = {**spec, "graph_context": _compact_graph_context(graph_context)}

    file_plans = [file_plan for file_plan in spec.get("files", []) if file_plan.get("path", "").strip()]
    local_file_plans = [file_plan for file_plan in file_plans if _is_local_rendered_file(file_plan.get("path", ""))]
    llm_file_plans = [file_plan for file_plan in file_plans if not _is_local_rendered_file(file_plan.get("path", ""))]

    generated_files = []
    for file_plan in local_file_plans:
        generated_files.append(_generate_and_write_file(spec, analysis, chunks, output_dir, file_plan))

    max_workers = min(_code_gen_max_workers(), len(llm_file_plans)) if llm_file_plans else 0
    if max_workers <= 1:
        for file_plan in llm_file_plans:
            generated_files.append(_generate_and_write_file(spec, analysis, chunks, output_dir, file_plan))
        return generated_files

    generated_by_path: dict[str, Path] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_generate_and_write_file, spec, analysis, chunks, output_dir, file_plan): file_plan
            for file_plan in llm_file_plans
        }
        for future in as_completed(futures):
            file_plan = futures[future]
            relative_path = file_plan.get("path", "").strip()
            try:
                generated_by_path[relative_path] = future.result()
            except Exception as exc:
                raise RuntimeError(f"生成 {relative_path} 失败：{exc}") from exc

    for file_plan in llm_file_plans:
        relative_path = file_plan.get("path", "").strip()
        if relative_path in generated_by_path:
            generated_files.append(generated_by_path[relative_path])

    return generated_files


def _generate_and_write_file(
    spec: dict,
    analysis: dict,
    chunks: list[dict],
    output_dir: Path,
    file_plan: dict,
) -> Path:
    relative_path = file_plan.get("path", "").strip()
    target_path = output_dir / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        content = _generate_file_content(spec, analysis, chunks, file_plan)
    except Exception as exc:
        raise RuntimeError(f"生成 {relative_path} 失败：{exc}") from exc
    target_path.write_text(content, encoding="utf-8")
    return target_path


def _generate_file_content(spec: dict, analysis: dict, chunks: list[dict], file_plan: dict) -> str:
    path = file_plan["path"]
    language_adapter = get_language_adapter(spec)
    if path == "requirements.txt":
        return _render_requirements(spec)
    if path == "main.py":
        return _render_main_file(spec)
    if path == "config.json":
        return json.dumps(spec.get("config", {}), ensure_ascii=False, indent=2) + "\n"
    if path == "Dockerfile":
        return _render_dockerfile(spec)
    if path == "README.md":
        return _render_readme(spec)

    content = ""
    if language_adapter.can_generate_structured_file(spec, file_plan):
        try:
            content = language_adapter.generate_structured_file(spec, analysis, chunks, file_plan)
        except Exception:
            pass

    if language_adapter.is_source_file(path):
        if not content:
            content = _generate_llm_file(spec, analysis, chunks, file_plan)
        content = language_adapter.apply_post_generation_transforms(content, spec, path)
        content = _ensure_source_syntax(content, spec, analysis, chunks, file_plan)
        content = _ensure_source_contract(content, spec, analysis, chunks, file_plan)
        content = language_adapter.apply_post_generation_transforms(content, spec, path)
        return content

    if not content:
        content = _generate_llm_file(spec, analysis, chunks, file_plan)
    return content


def _generate_llm_file(spec: dict, analysis: dict, chunks: list[dict], file_plan: dict) -> str:
    relevant_chunks = _select_relevant_chunks_for_file(chunks, file_plan, MAX_FILE_CHUNKS)
    messages = _file_generation_messages(spec, analysis, file_plan, relevant_chunks)
    try:
        return _strip_code_fence(chat_completion(messages, temperature=0.1, max_tokens=3200))
    except Exception:
        retry_messages = _compact_file_generation_messages(spec, analysis, file_plan, relevant_chunks[:2])
        return _strip_code_fence(chat_completion(retry_messages, temperature=0, max_tokens=3200))


def _ensure_source_syntax(content: str, spec: dict, analysis: dict, chunks: list[dict], file_plan: dict) -> str:
    language_adapter = get_language_adapter(spec)
    current = content
    last_error: Exception | None = None

    for _ in range(MAX_PYTHON_REPAIR_ATTEMPTS + 1):
        try:
            language_adapter.validate_syntax(current)
            return current
        except SyntaxError as exc:
            last_error = exc
            try:
                current = _repair_python_file(spec, analysis, chunks, file_plan, current, exc)
            except Exception as repair_exc:
                last_error = repair_exc

    return _python_fallback_file(spec, file_plan, last_error, current)


def _ensure_source_contract(content: str, spec: dict, analysis: dict, chunks: list[dict], file_plan: dict) -> str:
    language_adapter = get_language_adapter(spec)
    contract = _contract_for_file(spec, file_plan.get("path", ""))
    if language_adapter.is_empty_contract(contract):
        return content

    current = content
    diagnostics = language_adapter.validate_contract(current, contract)
    if not diagnostics:
        return current

    last_error: Exception | None = RuntimeError(_format_contract_diagnostics(diagnostics))
    for _ in range(MAX_PYTHON_REPAIR_ATTEMPTS):
        try:
            current = _repair_python_contract_file(spec, analysis, chunks, file_plan, current, diagnostics)
            current = _ensure_source_syntax(current, spec, analysis, chunks, file_plan)
            diagnostics = language_adapter.validate_contract(current, contract)
            if not diagnostics:
                return current
            last_error = RuntimeError(_format_contract_diagnostics(diagnostics))
        except Exception as exc:
            last_error = exc

    return _contract_fallback_file(spec, file_plan, last_error, current)


def _repair_python_file(
    spec: dict,
    analysis: dict,
    chunks: list[dict],
    file_plan: dict,
    broken_content: str,
    syntax_error: Exception,
) -> str:
    language_adapter = get_language_adapter(spec)
    messages = [
        {
            "role": "system",
            "content": language_adapter.syntax_repair_system_prompt(),
        },
        {
            "role": "user",
            "content": (
                "Repair this Python file into a complete runnable version.\n"
                f"file: {file_plan.get('path')}\n"
                f"purpose: {file_plan.get('purpose')}\n"
                f"syntax_error: {syntax_error}\n"
                f"code_spec:\n{json.dumps(_compact_spec(spec), ensure_ascii=False)}\n"
                f"analysis:\n{json.dumps(_compact_analysis(analysis), ensure_ascii=False)}\n"
                f"broken_content:\n{broken_content[:5000]}"
            ),
        },
    ]
    return _strip_code_fence(chat_completion(messages, temperature=0, max_tokens=3200))


def _repair_python_contract_file(
    spec: dict,
    analysis: dict,
    chunks: list[dict],
    file_plan: dict,
    broken_content: str,
    diagnostics: list[dict],
) -> str:
    language_adapter = get_language_adapter(spec)
    contract = _contract_for_file(spec, file_plan.get("path", ""))
    relevant_chunks = _select_relevant_chunks_for_file(chunks, file_plan, 3)
    messages = [
        {
            "role": "system",
            "content": language_adapter.contract_repair_system_prompt(),
        },
        {
            "role": "user",
            "content": (
                f"file: {file_plan.get('path')}\n"
                f"purpose: {file_plan.get('purpose')}\n"
                f"target_contract:\n{json.dumps(contract, ensure_ascii=False)}\n\n"
                f"contract_diagnostics:\n{json.dumps(diagnostics, ensure_ascii=False)}\n\n"
                f"code_spec:\n{json.dumps(_compact_spec(spec), ensure_ascii=False)}\n\n"
                f"analysis:\n{json.dumps(_compact_analysis(analysis), ensure_ascii=False)}\n\n"
                f"relevant_chunks:\n{json.dumps(relevant_chunks, ensure_ascii=False)}\n\n"
                f"broken_content:\n{broken_content[:7000]}"
            ),
        },
    ]
    return _strip_code_fence(chat_completion(messages, temperature=0, max_tokens=4200))


def _python_fallback_file(spec: dict, file_plan: dict, error: Exception | None, broken_content: str) -> str:
    return "\n".join(
        [
            '"""Fallback module generated because the LLM output had invalid Python syntax.',
            "",
            f"File: {file_plan.get('path', '')}",
            f"Purpose: {file_plan.get('purpose', '')}",
            f"Original error: {_as_text(error)}",
            '"""',
            "",
            "from __future__ import annotations",
            "",
            "BROKEN_OUTPUT_PREVIEW = " + repr(broken_content[:1200]),
            "",
            "",
            "def run(*args, **kwargs) -> dict:",
            "    return {",
            "        'status': 'fallback_generated',",
            f"        'file': {file_plan.get('path', '')!r},",
            f"        'purpose': {file_plan.get('purpose', '')!r},",
            f"        'error': {_as_text(error)!r},",
            "        'note': 'This module stayed runnable, but the original generated implementation needs review.',",
            "    }",
            "",
        ]
    )


def _contract_fallback_file(spec: dict, file_plan: dict, error: Exception | None, broken_content: str) -> str:
    contract = _contract_for_file(spec, file_plan.get("path", ""))
    lines = [
        '"""Contract fallback module generated because the model output did not satisfy the module contract.',
        "",
        f"File: {file_plan.get('path', '')}",
        f"Purpose: {file_plan.get('purpose', '')}",
        f"Original error: {_as_text(error)}",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
        "BROKEN_OUTPUT_PREVIEW = " + repr(broken_content[:1200]),
        "",
        "",
    ]

    for class_contract in _contract_classes(contract):
        lines.extend(_render_contract_fallback_class(class_contract))
        lines.append("")
        lines.append("")

    for function_contract in _contract_functions(contract):
        lines.extend(_render_contract_fallback_function(function_contract))
        lines.append("")
        lines.append("")

    if not _contract_classes(contract) and not _contract_functions(contract):
        lines.extend(
            [
                "def run(*args: Any, **kwargs: Any) -> dict:",
                "    return {'status': 'contract_fallback_generated'}",
                "",
            ]
        )

    result = "\n".join(lines).rstrip() + "\n"
    ast.parse(result)
    return result


def _file_generation_messages(spec: dict, analysis: dict, file_plan: dict, relevant_chunks: list[dict]) -> list[dict]:
    contract_context = _contract_context(spec, file_plan)
    return [
        {
            "role": "system",
            "content": (
                "You are a careful research-code engineer. Generate one complete file. "
                "Do not output Markdown fences or explanations. The file must be runnable. "
                "Do not use TODO placeholders. If paper parameters are missing, use config defaults and document the assumption in comments. "
                "Implement exactly the exports declared for this target file. "
                "Do not invent alternative names for public classes or functions. "
                "If this file imports another generated module, import only symbols declared in that module's contract. "
                "Project-local imports are managed from symbols/imports/depends_on; do not invent extra local import names. "
                "The project is accepted when a short smoke run completes: prepare minimal inputs/environment, initialize the paper method, "
                "and execute one tiny training/simulation/optimization/analysis loop. Do not chase full paper metrics here. "
                "Use graph_context and graph_alignment to keep state/action/reward, modules, datasets, metrics, and code symbols aligned with the paper. "
                "If a contract and your preferred design conflict, follow the contract."
            ),
        },
        {
            "role": "user",
            "content": (
                f"target_file: {file_plan.get('path')}\n"
                f"purpose: {file_plan.get('purpose')}\n\n"
                f"contract_context:\n{json.dumps(contract_context, ensure_ascii=False)}\n\n"
                f"code_spec:\n{json.dumps(spec, ensure_ascii=False)}\n\n"
                f"analysis:\n{json.dumps(_compact_analysis(analysis), ensure_ascii=False)}\n\n"
                f"relevant_chunks:\n{json.dumps(relevant_chunks, ensure_ascii=False)}"
            ),
        },
    ]


def _compact_file_generation_messages(
    spec: dict,
    analysis: dict,
    file_plan: dict,
    relevant_chunks: list[dict],
) -> list[dict]:
    contract_context = _contract_context(spec, file_plan)
    return [
        {
            "role": "system",
            "content": (
                "Generate only the complete target file content. No Markdown, no explanation. "
                "Keep it concise, runnable, and syntactically valid. Follow the declared module contract exactly. "
                "Do not invent project-local imports outside the symbol graph. Implement only a short runnable smoke experiment, not full result reproduction."
            ),
        },
        {
            "role": "user",
            "content": (
                f"target_file: {file_plan.get('path')}\n"
                f"purpose: {file_plan.get('purpose')}\n\n"
                f"contract_context:\n{json.dumps(contract_context, ensure_ascii=False)}\n\n"
                f"code_spec:\n{json.dumps(_compact_spec(spec), ensure_ascii=False)}\n\n"
                f"analysis:\n{json.dumps(_compact_analysis(analysis), ensure_ascii=False)}\n\n"
                f"relevant_chunks:\n{json.dumps(relevant_chunks, ensure_ascii=False)}"
            ),
        },
    ]


def _chat_json(messages: list[dict], max_tokens: int) -> dict:
    content = chat_completion(messages, temperature=0.1, max_tokens=max_tokens)
    try:
        return _loads_json(content)
    except RuntimeError:
        retry_messages = [
            {
                "role": "system",
                "content": "Return exactly one complete JSON object. No Markdown. All strings and arrays must be closed.",
            },
            *messages[-2:],
            {
                "role": "user",
                "content": f"The previous output was invalid JSON. Return a shorter valid JSON object.\ninvalid_output:\n{content[:1200]}",
            },
        ]
        return _loads_json(chat_completion(retry_messages, temperature=0, max_tokens=max_tokens))


def _loads_json(content: str) -> dict:
    text = _strip_code_fence(content).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise RuntimeError(f"模型返回内容不是 JSON：{content[:500]}") from exc
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as nested_exc:
            raise RuntimeError(f"模型返回内容不是完整 JSON：{content[:500]}") from nested_exc
    if not isinstance(data, dict):
        raise RuntimeError("模型返回 JSON 不是对象。")
    return data


def _normalize_code_spec(
    spec: dict,
    analysis: dict,
    experiment_spec: dict | None = None,
    graph_context: dict | None = None,
) -> dict:
    graph_context = graph_context or spec.get("graph_context") or {}
    experiment_spec = normalize_experiment_spec(
        experiment_spec or spec.get("experiment_spec") or {},
        analysis,
        graph_context,
    )
    project_name = _safe_project_name(spec.get("project_name") or _guess_project_name(analysis))
    project_type = _normalize_project_type(spec.get("project_type")) or experiment_spec.get("project_type") or _guess_project_type(analysis)
    dependencies = _normalize_dependencies(spec.get("dependencies"))
    config = spec.get("config") if isinstance(spec.get("config"), dict) else {}
    files = _normalize_files(spec.get("files"))
    run_command = _entrypoint_run_command(spec) or _as_text(spec.get("run_command")) or "python main.py --config config.json"
    entrypoint = _normalize_entrypoint(spec.get("entrypoint"), run_command, files)
    interfaces = _normalize_interfaces(spec.get("interfaces"))
    module_contracts = _normalize_module_contracts(spec.get("module_contracts"), files, interfaces)
    symbols = normalize_symbols(spec.get("symbols"), module_contracts, files)
    symbol_generation_order = build_symbol_generation_order(symbols)
    config_schema = _normalize_config_schema(spec.get("config_schema"), config)

    normalized = {
        "project_name": project_name,
        "project_type": project_type,
        "language": "python",
        "framework": _as_text(spec.get("framework")) or experiment_spec.get("experiment_type") or _guess_framework(dependencies),
        "entry_file": entrypoint["path"],
        "entrypoint": entrypoint,
        "run_command": entrypoint["run_command"],
        "docker": True,
        "dependencies": dependencies,
        "config": _default_config(config, analysis, experiment_spec),
        "config_schema": config_schema,
        "module_contracts": module_contracts,
        "symbols": symbols,
        "symbol_generation_order": symbol_generation_order,
        "interfaces": interfaces,
        "experiment_spec": experiment_spec,
        "experiment_contract": _normalize_experiment_contract(spec.get("experiment_contract"), project_type, experiment_spec),
        "graph_context": _compact_graph_context(graph_context),
        "graph_alignment": _normalize_graph_alignment(spec.get("graph_alignment"), graph_context, files),
        "expected_outputs": _normalize_expected_outputs(spec.get("expected_outputs")),
        "assumptions": _as_string_list(spec.get("assumptions"))[:12],
        "missing_details": _as_string_list(spec.get("missing_details"))[:12],
        "files": files,
        "source": analysis.get("source", ""),
        "paper_summary": _paper_summary(analysis),
    }
    _validate_code_contract(normalized)
    return normalized


def _normalize_files(value: object) -> list[dict]:
    files = []
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        path = _safe_relative_path(item.get("path", ""))
        if not path:
            continue
        files.append(
            {
                "path": path,
                "purpose": _as_text(item.get("purpose")) or "Generated research code file.",
                "kind": _as_text(item.get("kind")) or "code",
            }
        )

    required = [
        ("README.md", "Explain the generated project and how to run it.", "document"),
        ("requirements.txt", "Declare Python dependencies.", "dependency"),
        ("Dockerfile", "Build a reproducible runtime environment.", "docker"),
        ("config.json", "Runtime configuration.", "config"),
        ("main.py", "Command line entrypoint.", "entrypoint"),
        ("src/experiment.py", "One-stop smoke experiment orchestration.", "code"),
    ]
    normalized = [{"path": path, "purpose": purpose, "kind": kind} for path, purpose, kind in required]
    normalized_paths = {entry["path"] for entry in normalized}
    for item in files:
        if item["path"] not in normalized_paths:
            normalized.append(item)
            normalized_paths.add(item["path"])
    return normalized[:MAX_FILES]


def _entrypoint_run_command(spec: dict) -> str:
    entrypoint = spec.get("entrypoint")
    if isinstance(entrypoint, dict):
        return _as_text(entrypoint.get("run_command"))
    return ""


def _normalize_entrypoint(value: object, run_command: str, files: list[dict]) -> dict:
    entrypoint = value if isinstance(value, dict) else {}
    path = _safe_relative_path(entrypoint.get("path", "")) or _safe_relative_path(entrypoint.get("entry_file", ""))
    file_paths = {item["path"] for item in files}
    if path not in file_paths:
        path = "main.py"
    command = _as_text(entrypoint.get("run_command")) or run_command or "python main.py --config config.json"
    if path not in command:
        command = f"python {path} --config config.json"
    return {
        "path": path,
        "run_command": command,
        "main_function": _as_text(entrypoint.get("main_function")) or "main",
    }


def _normalize_module_contracts(value: object, files: list[dict], interfaces: dict) -> list[dict]:
    file_paths = {item["path"] for item in files}
    contracts_by_path: dict[str, dict] = {}
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        path = _safe_relative_path(item.get("path", ""))
        if not path or path not in file_paths or not path.endswith(".py"):
            continue
        contracts_by_path[path] = _complete_module_contract({
            "path": path,
            "exports": _normalize_exports(item.get("exports")),
            "functions": _normalize_contract_functions(item.get("functions")),
            "classes": _normalize_contract_classes(item.get("classes")),
        })

    for file_plan in files:
        path = file_plan["path"]
        if not path.endswith(".py") or path in contracts_by_path:
            continue
        contracts_by_path[path] = _complete_module_contract(_infer_module_contract(file_plan, interfaces))

    _apply_deterministic_contract_templates(contracts_by_path, files, interfaces)
    _split_large_contract_classes(contracts_by_path)
    return [contracts_by_path[path] for path in sorted(contracts_by_path)]


def _complete_module_contract(contract: dict) -> dict:
    exports = _normalize_exports(contract.get("exports"))
    functions = _normalize_contract_functions(contract.get("functions"))
    classes = _normalize_contract_classes(contract.get("classes"))

    function_names = {item["name"] for item in functions}
    class_names = {item["name"] for item in classes}
    for export in exports:
        if export["type"] == "function" and export["name"] not in function_names:
            functions.append(_default_function_contract(export))
            function_names.add(export["name"])
        elif export["type"] == "class" and export["name"] not in class_names:
            classes.append(_default_class_contract(export))
            class_names.add(export["name"])

    return {
        "path": contract.get("path", ""),
        "exports": exports,
        "functions": functions,
        "classes": classes,
    }


def _default_function_contract(export: dict) -> dict:
    name = export["name"]
    result = dict(export)
    result["type"] = "function"
    result["signature"] = _as_text(result.get("signature")) or _default_function_signature(name)
    result["responsibility"] = _as_text(result.get("responsibility")) or _default_function_responsibility(name)
    return result


def _default_class_contract(export: dict) -> dict:
    return {
        "type": "class",
        "name": export["name"],
        "responsibility": _as_text(export.get("responsibility")) or "Generated research-code class.",
        "methods": _normalize_contract_methods(export.get("methods")),
    }


def _default_function_signature(name: str) -> str:
    if name == "main":
        return "main() -> None"
    if name == "run_experiment":
        return "run_experiment(config: dict) -> dict"
    if name == "run_algorithm":
        return "run_algorithm(config: dict) -> dict"
    if name == "evaluate_agent":
        return "evaluate_agent(*args, **kwargs) -> dict"
    if name == "plot_curves":
        return "plot_curves(*args, **kwargs) -> None"
    return f"{name}(*args, **kwargs) -> dict"


def _default_function_responsibility(name: str) -> str:
    if name == "run_experiment":
        return "Prepare the minimal paper-inspired environment, initialize the algorithm or model, and run a short smoke experiment."
    if name == "run_algorithm":
        return "Run the paper-inspired algorithm or simulation and return metrics, history, and artifacts."
    if name == "evaluate_agent":
        return "Evaluate generated algorithm outputs and return metrics."
    if name == "plot_curves":
        return "Create simple visualizations from generated metrics."
    if name == "main":
        return "Command-line entrypoint."
    return "Generated public function declared by the module contract."


def _normalize_exports(value: object) -> list[dict]:
    exports = []
    seen = set()
    for item in _as_list(value):
        export = _normalize_export(item)
        if not export or export["name"] in seen:
            continue
        seen.add(export["name"])
        exports.append(export)
    return exports


def _normalize_contract_functions(value: object) -> list[dict]:
    functions = []
    seen = set()
    for item in _as_list(value):
        function = _normalize_export(item)
        if not function or function["name"] in seen:
            continue
        function["type"] = "function"
        seen.add(function["name"])
        functions.append(function)
    return functions


def _normalize_contract_classes(value: object) -> list[dict]:
    classes = []
    seen = set()
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        name = _safe_identifier(item.get("name"))
        if not name or name in seen:
            continue
        class_contract = {
            "type": "class",
            "name": name,
            "responsibility": _as_text(item.get("responsibility")) or _as_text(item.get("purpose")),
            "methods": _normalize_contract_methods(item.get("methods")),
        }
        seen.add(name)
        classes.append(class_contract)
    return classes


def _normalize_contract_methods(value: object) -> list[dict]:
    methods = []
    seen = set()
    for item in _as_list(value):
        if isinstance(item, str):
            name = _safe_identifier(item)
            method = {"name": name} if name else None
        elif isinstance(item, dict):
            name = _safe_identifier(item.get("name"))
            method = {"name": name} if name else None
            if method and _as_text(item.get("signature")):
                method["signature"] = _as_text(item.get("signature"))
            if method and (_as_text(item.get("responsibility")) or _as_text(item.get("purpose"))):
                method["responsibility"] = _as_text(item.get("responsibility")) or _as_text(item.get("purpose"))
        else:
            method = None
        if not method or method["name"] in seen:
            continue
        seen.add(method["name"])
        methods.append(method)
    return methods


def _split_large_contract_classes(contracts_by_path: dict[str, dict]) -> None:
    for contract in contracts_by_path.values():
        classes = _normalize_contract_classes(contract.get("classes"))
        updated_classes = []
        split_records = []
        existing_names = {class_contract["name"] for class_contract in classes}

        for class_contract in classes:
            methods = _normalize_contract_methods(class_contract.get("methods"))
            if len(methods) <= MAX_CLASS_METHODS:
                class_contract["methods"] = methods
                updated_classes.append(class_contract)
                continue

            kept_methods, moved_methods = _split_class_methods(methods)
            class_contract["methods"] = kept_methods
            class_contract["responsibility"] = (
                _as_text(class_contract.get("responsibility"))
                or "Public facade class for the generated implementation."
            )
            updated_classes.append(class_contract)

            helper_index = 1
            for method_group in _chunks(moved_methods, MAX_CLASS_METHODS):
                helper_name = _unique_helper_class_name(class_contract["name"], existing_names, helper_index)
                existing_names.add(helper_name)
                helper_index += 1
                updated_classes.append(
                    {
                        "type": "class",
                        "name": helper_name,
                        "responsibility": (
                            f"Helper class extracted from {class_contract['name']} to keep the public class focused."
                        ),
                        "methods": method_group,
                    }
                )
                split_records.append(
                    {
                        "source_class": class_contract["name"],
                        "helper_class": helper_name,
                        "moved_methods": [method["name"] for method in method_group],
                    }
                )

            _sync_export_class_methods(contract, class_contract["name"], kept_methods)

        contract["classes"] = updated_classes
        if split_records:
            contract["class_splits"] = split_records


def _split_class_methods(methods: list[dict]) -> tuple[list[dict], list[dict]]:
    core_names = {
        "__init__",
        "reset",
        "step",
        "forward",
        "select_action",
        "store_transition",
        "train_step",
        "save",
        "load",
        "fit",
        "predict",
        "evaluate",
    }
    kept = []
    moved = []

    for method in methods:
        if method["name"] in core_names and len(kept) < MAX_CLASS_METHODS:
            kept.append(method)
        else:
            moved.append(method)

    while len(kept) < MAX_CLASS_METHODS and moved:
        kept.append(moved.pop(0))
    return kept, moved


def _unique_helper_class_name(class_name: str, existing_names: set[str], helper_index: int) -> str:
    suffix = "Helper" if helper_index == 1 else f"Helper{helper_index}"
    candidate = f"{class_name}{suffix}"
    while candidate in existing_names:
        helper_index += 1
        candidate = f"{class_name}Helper{helper_index}"
    return candidate


def _sync_export_class_methods(contract: dict, class_name: str, methods: list[dict]) -> None:
    exports = _normalize_exports(contract.get("exports"))
    for export in exports:
        if export.get("type") == "class" and export.get("name") == class_name:
            export["methods"] = methods
            break
    contract["exports"] = exports


def _chunks(values: list[dict], size: int) -> list[list[dict]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _apply_deterministic_contract_templates(contracts_by_path: dict[str, dict], files: list[dict], interfaces: dict) -> None:
    for file_plan in files:
        path = file_plan["path"]
        if not path.endswith(".py"):
            continue
        contract = contracts_by_path.get(path) or {"path": path, "exports": [], "functions": [], "classes": []}
        lower_path = path.lower()

        if path == "main.py":
            _merge_function_contract(
                contract,
                {
                    "name": "main",
                    "signature": "main() -> None",
                    "responsibility": "Command-line entrypoint that loads config and runs the generated experiment.",
                    "outputs": [],
                },
            )
        elif lower_path.endswith("src/experiment.py") or lower_path.endswith("experiment.py"):
            _merge_function_contract(
                contract,
                {
                    "name": "run_experiment",
                    "signature": "run_experiment(config: dict) -> dict",
                    "responsibility": "Prepare minimal inputs or environment, initialize the paper-inspired algorithm/model/agent, run a short smoke experiment, and return run status.",
                    "inputs": ["config"],
                    "outputs": ["status", "project_type", "summary"],
                },
            )
        elif lower_path.endswith("src/algorithm.py") or lower_path.endswith("algorithm.py"):
            _merge_function_contract(
                contract,
                {
                    "name": "run_algorithm",
                    "signature": "run_algorithm(config: dict) -> dict",
                    "responsibility": "Run the paper-inspired algorithm or simulation and return metrics, history, and artifacts.",
                    "inputs": ["config"],
                    "outputs": ["metrics", "history", "artifacts"],
                },
            )
        elif "evaluate" in lower_path or lower_path.endswith("eval.py"):
            function_name = _interface_text(interfaces, "evaluation", "function_name") or "evaluate_agent"
            _merge_function_contract(
                contract,
                {
                    "name": _safe_identifier(function_name) or "evaluate_agent",
                    "signature": f"{_safe_identifier(function_name) or 'evaluate_agent'}(*args, **kwargs) -> dict",
                    "responsibility": "Evaluate generated algorithm outputs and return metrics.",
                    "outputs": ["metrics"],
                },
            )
        elif "visual" in lower_path or "plot" in lower_path:
            function_name = _interface_text(interfaces, "visualization", "function_name") or "plot_curves"
            _merge_function_contract(
                contract,
                {
                    "name": _safe_identifier(function_name) or "plot_curves",
                    "signature": f"{_safe_identifier(function_name) or 'plot_curves'}(*args, **kwargs) -> None",
                    "responsibility": "Create simple visualizations from generated metrics.",
                    "outputs": ["plots"],
                },
            )
        elif "train" in lower_path:
            _merge_function_contract(
                contract,
                {
                    "name": "train",
                    "signature": "train(*args, **kwargs) -> dict",
                    "responsibility": "Run the training loop or simulation loop and return training history.",
                    "outputs": ["history"],
                },
            )
        elif "agent" in lower_path or "model" in lower_path:
            class_name = _existing_class_name(contract) or _interface_text(interfaces, "agent", "class_name") or _interface_text(interfaces, "model", "class_name") or "Agent"
            _merge_class_contract(
                contract,
                {
                    "name": _safe_identifier(class_name) or "Agent",
                    "responsibility": "Agent or model implementation used by the generated experiment.",
                    "methods": [
                        {"name": "__init__", "signature": "__init__(self, *args, **kwargs) -> None", "responsibility": "Initialize model or agent state."},
                        {"name": "select_action", "signature": "select_action(self, state, explore=True)", "responsibility": "Choose an action for the current state."},
                        {"name": "store_transition", "signature": "store_transition(self, *args, **kwargs)", "responsibility": "Store one training transition when applicable."},
                        {"name": "train_step", "signature": "train_step(self) -> dict", "responsibility": "Run one lightweight optimization step when applicable."},
                        {"name": "save", "signature": "save(self, path)", "responsibility": "Persist model or agent artifacts."},
                    ],
                },
            )
        elif "environment" in lower_path or lower_path.endswith("env.py"):
            class_name = _existing_class_name(contract) or _interface_text(interfaces, "environment", "class_name") or "Environment"
            _merge_class_contract(
                contract,
                {
                    "name": _safe_identifier(class_name) or "Environment",
                    "responsibility": "Environment or simulator used by the generated experiment.",
                    "methods": [
                        {"name": "__init__", "signature": "__init__(self, config: dict) -> None", "responsibility": "Initialize environment configuration and state."},
                        {"name": "reset", "signature": "reset(self)", "responsibility": "Reset the environment and return the initial state."},
                        {"name": "step", "signature": "step(self, action)", "responsibility": "Apply one action and return next state, reward, done, and info."},
                    ],
                },
            )

        contracts_by_path[path] = _complete_module_contract(contract)


def _merge_function_contract(contract: dict, template: dict) -> None:
    name = _safe_identifier(template.get("name"))
    if not name:
        return
    template = _default_function_contract({"type": "function", **template, "name": name})
    _merge_export(contract, {"type": "function", "name": name, "signature": template.get("signature"), "responsibility": template.get("responsibility")})

    functions = _normalize_contract_functions(contract.get("functions"))
    for function in functions:
        if function["name"] == name:
            for key in ("signature", "responsibility", "inputs", "outputs"):
                if not function.get(key) and template.get(key):
                    function[key] = template[key]
            contract["functions"] = functions
            return
    functions.append(template)
    contract["functions"] = functions


def _merge_class_contract(contract: dict, template: dict) -> None:
    name = _safe_identifier(template.get("name"))
    if not name:
        return
    template = {
        "type": "class",
        "name": name,
        "responsibility": _as_text(template.get("responsibility")) or "Generated research-code class.",
        "methods": _normalize_contract_methods(template.get("methods")),
    }
    _merge_export(contract, {"type": "class", "name": name, "responsibility": template.get("responsibility"), "methods": template.get("methods")})

    classes = _normalize_contract_classes(contract.get("classes"))
    for class_contract in classes:
        if class_contract["name"] == name:
            class_contract["responsibility"] = class_contract.get("responsibility") or template["responsibility"]
            class_contract["methods"] = _merge_methods(class_contract.get("methods"), template["methods"])
            contract["classes"] = classes
            return
    classes.append(template)
    contract["classes"] = classes


def _merge_export(contract: dict, export: dict) -> None:
    exports = _normalize_exports(contract.get("exports"))
    for existing in exports:
        if existing["name"] == export["name"]:
            for key, value in export.items():
                if key != "name" and value and not existing.get(key):
                    existing[key] = value
            contract["exports"] = exports
            return
    exports.append({key: value for key, value in export.items() if value})
    contract["exports"] = exports


def _merge_methods(current: object, templates: list[dict]) -> list[dict]:
    methods = _normalize_contract_methods(current)
    by_name = {method["name"]: method for method in methods}
    for template in templates:
        name = template["name"]
        if name in by_name:
            for key in ("signature", "responsibility"):
                if not by_name[name].get(key) and template.get(key):
                    by_name[name][key] = template[key]
        else:
            methods.append(template)
            by_name[name] = template
    return methods


def _existing_class_name(contract: dict) -> str:
    for class_contract in _normalize_contract_classes(contract.get("classes")):
        if class_contract.get("name"):
            return class_contract["name"]
    for export in _normalize_exports(contract.get("exports")):
        if export.get("type") == "class":
            return export["name"]
    return ""


def _normalize_export(value: object) -> dict | None:
    if isinstance(value, str):
        name = _safe_identifier(value)
        return {"type": "function", "name": name} if name else None
    if not isinstance(value, dict):
        return None
    name = _safe_identifier(value.get("name"))
    if not name:
        return None
    export_type = _as_text(value.get("type")).lower()
    if export_type not in {"class", "function"}:
        export_type = "function"
    result = {
        "type": export_type,
        "name": name,
    }
    if _as_text(value.get("signature")):
        result["signature"] = _as_text(value.get("signature"))
    if _as_text(value.get("responsibility")) or _as_text(value.get("purpose")):
        result["responsibility"] = _as_text(value.get("responsibility")) or _as_text(value.get("purpose"))
    inputs = _as_string_list(value.get("inputs"))
    outputs = _as_string_list(value.get("outputs"))
    if inputs:
        result["inputs"] = inputs
    if outputs:
        result["outputs"] = outputs
    methods = []
    for method in _as_list(value.get("methods")):
        if not isinstance(method, dict):
            continue
        method_name = _safe_identifier(method.get("name"))
        if not method_name:
            continue
        normalized = {"name": method_name}
        if _as_text(method.get("signature")):
            normalized["signature"] = _as_text(method.get("signature"))
        if _as_text(method.get("responsibility")) or _as_text(method.get("purpose")):
            normalized["responsibility"] = _as_text(method.get("responsibility")) or _as_text(method.get("purpose"))
        methods.append(normalized)
    if methods:
        result["methods"] = methods
    return result


def _infer_module_contract(file_plan: dict, interfaces: dict) -> dict:
    path = file_plan["path"]
    lower_path = path.lower()
    if path == "main.py":
        exports = [{"type": "function", "name": "main", "signature": "() -> None"}]
    elif "experiment" in lower_path:
        exports = [{"type": "function", "name": "run_experiment", "signature": "run_experiment(config: dict) -> dict"}]
    elif "agent" in lower_path or "model" in lower_path:
        class_name = _interface_text(interfaces, "agent", "class_name") or _interface_text(interfaces, "model", "class_name")
        exports = [
            {
                "type": "class",
                "name": _safe_identifier(class_name) or "Agent",
                "methods": [
                    {"name": "__init__", "signature": "(*args, **kwargs)"},
                    {"name": "select_action", "signature": "(state, explore=True)"},
                    {"name": "save", "signature": "(path)"},
                ],
            }
        ]
    elif "environment" in lower_path or "env" in lower_path:
        class_name = _interface_text(interfaces, "environment", "class_name")
        exports = [
            {
                "type": "class",
                "name": _safe_identifier(class_name) or "Environment",
                "methods": [
                    {"name": "__init__", "signature": "(config: dict)"},
                    {"name": "reset", "signature": "()"},
                    {"name": "step", "signature": "(action)"},
                ],
            }
        ]
    elif "evaluate" in lower_path or "eval" in lower_path:
        function_name = _interface_text(interfaces, "evaluation", "function_name")
        exports = [{"type": "function", "name": _safe_identifier(function_name) or "evaluate_agent"}]
    elif "visual" in lower_path or "plot" in lower_path:
        function_name = _interface_text(interfaces, "visualization", "function_name")
        exports = [{"type": "function", "name": _safe_identifier(function_name) or "plot_curves"}]
    elif "train" in lower_path:
        exports = [{"type": "function", "name": "train"}]
    else:
        exports = [{"type": "function", "name": "run_algorithm"}]
    return {"path": path, "exports": exports}


def _normalize_interfaces(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    interfaces = {}
    for name, details in value.items():
        key = _safe_identifier(name)
        if not key:
            continue
        if isinstance(details, dict):
            interfaces[key] = _normalize_interface_details(details)
        else:
            interfaces[key] = _as_text(details)
    return interfaces


def _normalize_interface_details(value: dict) -> dict:
    details = {}
    for key, item in value.items():
        normalized_key = _safe_identifier(key)
        if not normalized_key:
            continue
        if isinstance(item, list):
            details[normalized_key] = [_as_text(entry) for entry in item if _as_text(entry)]
        elif isinstance(item, dict):
            details[normalized_key] = _normalize_interface_details(item)
        else:
            details[normalized_key] = _as_text(item)
    return details


def _normalize_project_type(value: object) -> str:
    text = _as_text(value).strip().lower()
    aliases = {
        "reinforcement_learning": "rl",
        "reinforcement learning": "rl",
        "deep_reinforcement_learning": "rl",
        "machine_learning": "ml",
        "deep_learning": "ml",
        "data_analysis": "analysis",
    }
    text = aliases.get(text, text)
    return text if text in {"rl", "ml", "simulation", "optimization", "analysis"} else ""


def _normalize_experiment_contract(value: object, project_type: str, experiment_spec: dict | None = None) -> dict:
    contract = value if isinstance(value, dict) else {}
    experiment_spec = experiment_spec or {}
    smoke = experiment_spec.get("smoke_validation") if isinstance(experiment_spec.get("smoke_validation"), dict) else {}
    stages = _as_string_list(contract.get("stages")) or [
        "prepare_minimal_inputs_or_environment",
        "initialize_algorithm_model_or_agent",
        "run_short_training_simulation_optimization_or_analysis",
    ]
    if experiment_spec.get("experiment_type") == "rl_resource_allocation_actor_critic":
        stages = [
            "prepare_resource_allocation_environment_or_synthetic_trace",
            "initialize_actor_critic_agent",
            "run_short_actor_critic_training_loop",
            "return_experiment_trace",
        ]
    return {
        "entry_function": _as_text(contract.get("entry_function")) or "run_experiment(config: dict) -> dict",
        "project_type": project_type,
        "experiment_type": _as_text(experiment_spec.get("experiment_type")),
        "stages": stages[:8],
        "smoke_validation": {
            "episodes": smoke.get("episodes", 1),
            "steps_per_episode": smoke.get("steps_per_episode", 3),
            "must_complete_steps": smoke.get("must_complete_steps", True),
            "must_use_environment": smoke.get("must_use_environment", project_type in {"rl", "simulation"}),
            "must_use_agent": smoke.get("must_use_agent", project_type == "rl"),
        },
        "validation_goal": "Complete a short smoke run; scientific metrics and full reproduction are handled later.",
    }


def _normalize_config_schema(value: object, config: dict) -> dict:
    schema = value if isinstance(value, dict) else {}
    required = _as_string_list(schema.get("required")) or ["output_dir", "random_seed"]
    defaults = schema.get("training_defaults") if isinstance(schema.get("training_defaults"), dict) else {}
    return {
        "required": _dedupe(required),
        "training_defaults": {
            "num_episodes": defaults.get("num_episodes", config.get("num_episodes", config.get("episodes", 50))),
            "eval_interval": defaults.get("eval_interval", config.get("eval_interval", 10)),
        },
    }


def _normalize_expected_outputs(value: object) -> list[str]:
    outputs = _as_string_list(value)
    if outputs:
        return outputs[:8]
    return ["outputs/training_metrics.json"]


def _validate_code_contract(spec: dict) -> None:
    file_paths = {item["path"] for item in spec.get("files", [])}
    if spec.get("entrypoint", {}).get("path") not in file_paths:
        spec["entrypoint"]["path"] = "main.py"
        spec["entry_file"] = "main.py"
    seen_paths = set()
    for contract in spec.get("module_contracts", []):
        path = contract.get("path")
        if path in seen_paths or path not in file_paths:
            continue
        seen_paths.add(path)
        seen_exports = set()
        normalized_exports = []
        for export in contract.get("exports", []):
            name = export.get("name")
            if not name or name in seen_exports:
                continue
            seen_exports.add(name)
            normalized_exports.append(export)
        contract["exports"] = normalized_exports

    seen_symbol_ids = set()
    normalized_symbols = []
    for symbol in spec.get("symbols", []):
        if not isinstance(symbol, dict):
            continue
        symbol_id = symbol.get("id")
        path = symbol.get("path")
        if not symbol_id or symbol_id in seen_symbol_ids or path not in file_paths:
            continue
        seen_symbol_ids.add(symbol_id)
        normalized_symbols.append(symbol)
    spec["symbols"] = normalized_symbols
    symbol_ids = {symbol["id"] for symbol in normalized_symbols}
    spec["symbol_generation_order"] = [
        symbol_id
        for symbol_id in _as_string_list(spec.get("symbol_generation_order"))
        if symbol_id in symbol_ids
    ] or build_symbol_generation_order(normalized_symbols)


def _contract_context(spec: dict, file_plan: dict) -> dict:
    target_path = file_plan.get("path", "")
    language_adapter = get_language_adapter(spec)
    return {
        "entrypoint": spec.get("entrypoint", {}),
        "run_command": spec.get("run_command", ""),
        "project_type": spec.get("project_type", ""),
        "experiment_spec": spec.get("experiment_spec", {}),
        "experiment_contract": spec.get("experiment_contract", {}),
        "graph_alignment": spec.get("graph_alignment", {}),
        "graph_context": spec.get("graph_context", {}),
        "files": spec.get("files", []),
        "module_contracts": spec.get("module_contracts", []),
        "symbols": spec.get("symbols", []),
        "symbol_generation_order": spec.get("symbol_generation_order", []),
        "interfaces": spec.get("interfaces", {}),
        "target_contract": _contract_for_file(spec, target_path),
        "target_symbols": _symbols_for_file(spec, target_path),
        "managed_imports": language_adapter.managed_import_lines(spec, target_path),
    }


def _symbols_for_file(spec: dict, target_path: str) -> list[dict]:
    return [symbol for symbol in spec.get("symbols", []) if isinstance(symbol, dict) and symbol.get("path") == target_path]


def _contract_for_file(spec: dict, target_path: str) -> dict:
    for contract in spec.get("module_contracts", []):
        if contract.get("path") == target_path:
            return contract
    return {"path": target_path, "exports": []}


def _contract_functions(contract: dict) -> list[dict]:
    functions = []
    seen = set()
    for item in _as_list(contract.get("functions")):
        function = _normalize_export(item)
        if function and function.get("type") == "function" and function["name"] not in seen:
            seen.add(function["name"])
            functions.append(function)

    for item in _as_list(contract.get("exports")):
        export = _normalize_export(item)
        if export and export.get("type") == "function" and export["name"] not in seen:
            seen.add(export["name"])
            functions.append(export)
    return functions


def _contract_classes(contract: dict) -> list[dict]:
    classes = []
    seen = set()
    for item in _as_list(contract.get("classes")):
        if not isinstance(item, dict):
            continue
        name = _safe_identifier(item.get("name"))
        if name and name not in seen:
            seen.add(name)
            classes.append(
                {
                    "type": "class",
                    "name": name,
                    "responsibility": _as_text(item.get("responsibility")) or _as_text(item.get("purpose")),
                    "methods": _normalize_contract_methods(item.get("methods")),
                }
            )

    for item in _as_list(contract.get("exports")):
        export = _normalize_export(item)
        if export and export.get("type") == "class" and export["name"] not in seen:
            seen.add(export["name"])
            classes.append(
                {
                    "type": "class",
                    "name": export["name"],
                    "responsibility": _as_text(export.get("responsibility")),
                    "methods": _normalize_contract_methods(export.get("methods")),
                }
            )
    return classes


def _render_contract_fallback_class(class_contract: dict) -> list[str]:
    lines = [
        f"class {class_contract['name']}:",
        f'    """{_fallback_docstring(class_contract)}"""',
    ]
    methods = _normalize_contract_methods(class_contract.get("methods"))
    if not methods:
        lines.append("    pass")
        return lines

    for index, method in enumerate(methods):
        if index:
            lines.append("")
        signature = _fallback_signature(method, is_method=True)
        lines.append(f"    def {signature}:")
        lines.append(f'        """{_fallback_docstring(method)}"""')
        lines.extend(_fallback_return_lines(method, indent=8, method_name=method["name"]))
    return lines


def _render_contract_fallback_function(function_contract: dict) -> list[str]:
    signature = _fallback_signature(function_contract, is_method=False)
    lines = [
        f"def {signature}:",
        f'    """{_fallback_docstring(function_contract)}"""',
    ]
    lines.extend(_fallback_return_lines(function_contract, indent=4, method_name=function_contract["name"]))
    return lines


def _fallback_signature(contract: dict, is_method: bool) -> str:
    name = contract["name"]
    signature = _as_text(contract.get("signature")).removeprefix("def ").strip()
    signature = signature[:-1] if signature.endswith(":") else signature
    if signature.startswith(name):
        return signature
    if signature.startswith("("):
        return _prefix_signature_name(name, signature, is_method=is_method)
    if is_method:
        if name == "__init__":
            return "__init__(self, *args: Any, **kwargs: Any) -> None"
        return f"{name}(self, *args: Any, **kwargs: Any) -> dict"
    return f"{name}(*args: Any, **kwargs: Any) -> dict"


def _prefix_signature_name(name: str, signature: str, is_method: bool) -> str:
    close_index = signature.find(")")
    if close_index < 0:
        return f"{name}{signature}"
    params = signature[1:close_index].strip()
    suffix = signature[close_index + 1 :]
    if is_method and not params.startswith(("self", "cls")):
        params = "self" + (f", {params}" if params else "")
    return f"{name}({params}){suffix}"


def _fallback_return_lines(contract: dict, indent: int, method_name: str) -> list[str]:
    prefix = " " * indent
    if method_name == "__init__":
        return [
            f"{prefix}self.config = args[0] if args else kwargs.get('config', {{}})",
            f"{prefix}self.state = {{}}",
            f"{prefix}return None",
        ]
    if method_name == "main":
        return [
            f"{prefix}return None",
        ]
    if method_name == "reset":
        return [
            f"{prefix}return {{'status': 'reset', 'source': 'contract_fallback'}}",
        ]
    if method_name == "step":
        return [
            f"{prefix}return {{'status': 'step', 'source': 'contract_fallback'}}, 0.0, True, {{}}",
        ]
    return [
        f"{prefix}return {{",
        f"{prefix}    'status': 'contract_fallback_generated',",
        f"{prefix}    'name': {method_name!r},",
        f"{prefix}    'outputs': {_as_string_list(contract.get('outputs'))!r},",
        f"{prefix}}}",
    ]


def _fallback_docstring(contract: dict) -> str:
    text = _as_text(contract.get("responsibility")) or "Contract fallback block."
    return text.replace('"""', '\\"\\"\\"')


def _format_contract_diagnostics(diagnostics: list[dict]) -> str:
    return "; ".join(_as_text(item.get("message")) for item in diagnostics if isinstance(item, dict))


def _interface_text(interfaces: dict, section: str, field: str) -> str:
    details = interfaces.get(section)
    if isinstance(details, dict):
        return _as_text(details.get(field))
    return ""


def _fallback_code_spec(analysis: dict) -> dict:
    dependencies = _guess_dependencies(analysis)
    project_type = _guess_project_type(analysis)
    files = [
        {"path": "README.md", "purpose": "Explain the generated project.", "kind": "document"},
        {"path": "requirements.txt", "purpose": "Declare dependencies.", "kind": "dependency"},
        {"path": "Dockerfile", "purpose": "Build runtime image.", "kind": "docker"},
        {"path": "config.json", "purpose": "Runtime configuration.", "kind": "config"},
        {"path": "main.py", "purpose": "Runnable experiment entrypoint.", "kind": "entrypoint"},
        {"path": "src/experiment.py", "purpose": "One-stop smoke experiment orchestration.", "kind": "code"},
        {"path": "src/algorithm.py", "purpose": "Paper-inspired algorithm implementation.", "kind": "code"},
    ]
    if project_type in {"rl", "simulation"}:
        files.extend(
            [
                {"path": "src/environment.py", "purpose": "Minimal paper-inspired environment or simulator.", "kind": "code"},
                {"path": "src/train.py", "purpose": "Short training or simulation loop.", "kind": "code"},
            ]
        )
        if project_type == "rl":
            files.append({"path": "src/agent.py", "purpose": "Paper-inspired agent implementation.", "kind": "code"})
    elif project_type == "ml":
        files.extend(
            [
                {"path": "src/data.py", "purpose": "Minimal dataset preparation.", "kind": "code"},
                {"path": "src/model.py", "purpose": "Paper-inspired model implementation.", "kind": "code"},
                {"path": "src/train.py", "purpose": "Short training loop.", "kind": "code"},
            ]
        )
    elif project_type == "optimization":
        files.extend(
            [
                {"path": "src/problem.py", "purpose": "Optimization problem setup.", "kind": "code"},
                {"path": "src/train.py", "purpose": "Short optimization loop.", "kind": "code"},
            ]
        )
    return {
        "project_name": _guess_project_name(analysis),
        "project_type": project_type,
        "language": "python",
        "framework": _guess_framework(dependencies),
        "entry_file": "main.py",
        "run_command": "python main.py --config config.json",
        "docker": True,
        "dependencies": dependencies,
        "config": {},
        "assumptions": ["The paper lacks full implementation details; configurable defaults are used."],
        "missing_details": ["Some hyperparameters, data formats, or full equations are missing."],
        "experiment_contract": _normalize_experiment_contract({}, project_type),
        "files": files,
    }


def _render_main_file(spec: dict) -> str:
    return "\n".join(
        [
            "from __future__ import annotations",
            "",
            "import argparse",
            "import json",
            "from pathlib import Path",
            "",
            "from src.experiment import run_experiment",
            "",
            "",
            "def load_config(path: str) -> dict:",
            "    config_path = Path(path)",
            "    if not config_path.exists():",
            "        return {}",
            "    return json.loads(config_path.read_text(encoding='utf-8'))",
            "",
            "",
            "def main() -> None:",
            "    parser = argparse.ArgumentParser(description='Run generated research-code smoke experiment.')",
            "    parser.add_argument('--config', default='config.json')",
            "    args = parser.parse_args()",
            "",
            "    config = load_config(args.config)",
            "    result = run_experiment(config)",
            "    if not isinstance(result, dict):",
            "        result = {'status': 'ok', 'result': result}",
            "",
            "    output_dir = Path(config.get('output_dir', 'outputs'))",
            "    output_dir.mkdir(parents=True, exist_ok=True)",
            "    (output_dir / 'smoke_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')",
            "    print(json.dumps(result, ensure_ascii=False))",
            "",
            "",
            "if __name__ == '__main__':",
            "    main()",
            "",
        ]
    )


def _render_requirements(spec: dict) -> str:
    dependencies = _normalize_dependencies(spec.get("dependencies", []))
    return "\n".join(dependencies) + ("\n" if dependencies else "")


def _render_dockerfile(spec: dict) -> str:
    return "\n".join(
        [
            "FROM python:3.11-slim",
            "",
            "WORKDIR /app",
            "COPY requirements.txt ./",
            "RUN pip install --no-cache-dir -r requirements.txt",
            "COPY . .",
            f'CMD {json.dumps(spec.get("run_command", "python main.py --config config.json").split())}',
            "",
        ]
    )


def _render_readme(spec: dict) -> str:
    files = "\n".join(f"- `{item['path']}`: {item.get('purpose', '')}" for item in spec.get("files", []))
    dependencies = "\n".join(f"- {item}" for item in spec.get("dependencies", [])) or "- No external dependencies"
    assumptions = "\n".join(f"- {item}" for item in spec.get("assumptions", [])) or "- No extra assumptions recorded."
    missing = "\n".join(f"- {item}" for item in spec.get("missing_details", [])) or "- No missing details recorded."
    summary = spec.get("paper_summary", {})

    return "\n".join(
        [
            f"# {spec.get('project_name', 'generated_research_code')}",
            "",
            "Generated research code package based on the uploaded paper analysis.",
            "",
            "## Paper Summary",
            "",
            summary.get("summary", ""),
            "",
            "## Run Locally",
            "",
            "```powershell",
            "python -m venv .venv",
            ".venv\\Scripts\\activate",
            "pip install -r requirements.txt",
            spec.get("run_command", "python main.py --config config.json"),
            "```",
            "",
            "## Run With Docker",
            "",
            "```powershell",
            f"docker build -t {spec.get('project_name', 'generated_research_code')} .",
            f"docker run --rm -v ${{PWD}}/outputs:/app/outputs {spec.get('project_name', 'generated_research_code')}",
            "```",
            "",
            "## Files",
            "",
            files,
            "",
            "## Dependencies",
            "",
            dependencies,
            "",
            "## Assumptions",
            "",
            assumptions,
            "",
            "## Missing Paper Details",
            "",
            missing,
            "",
        ]
    )


def _default_config(config: dict, analysis: dict, experiment_spec: dict | None = None) -> dict:
    smoke = (experiment_spec or {}).get("smoke_validation") if isinstance((experiment_spec or {}).get("smoke_validation"), dict) else {}
    result = {
        "input_path": "data/input.csv",
        "output_dir": "outputs",
        "random_seed": 42,
        "episodes": smoke.get("episodes", 1),
        "steps_per_episode": smoke.get("steps_per_episode", 3),
        "batch_size": 32,
        "learning_rate": 0.001,
    }
    result.update(config)
    result["paper_title"] = result.get("paper_title") or (analysis.get("final_summary") or {}).get("title") or analysis.get("title", "")
    return result


def _select_relevant_chunks(chunks: list[dict], limit: int) -> list[dict]:
    keywords = [
        "algorithm",
        "method",
        "model",
        "equation",
        "reward",
        "state",
        "action",
        "experiment",
        "simulation",
        "parameter",
        "dataset",
        "baseline",
        "算法",
        "方法",
        "模型",
        "公式",
        "奖励",
        "状态",
        "动作",
        "实验",
        "仿真",
        "参数",
    ]
    scored = []
    for chunk in chunks:
        text = _chunk_text(chunk).lower()
        score = sum(1 for keyword in keywords if keyword.lower() in text)
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [chunk for score, chunk in scored if score > 0][:limit]
    if len(selected) < min(limit, len(chunks)):
        selected.extend(chunks[: limit - len(selected)])
    return [_compact_chunk(chunk) for chunk in selected[:limit]]


def _select_relevant_chunks_for_file(chunks: list[dict], file_plan: dict, limit: int) -> list[dict]:
    purpose = f"{file_plan.get('path', '')} {file_plan.get('purpose', '')}".lower()
    scored = []
    for chunk in chunks:
        text = _chunk_text(chunk).lower()
        score = sum(1 for word in re.findall(r"[a-zA-Z_]{3,}|[\u4e00-\u9fff]{2,}", purpose) if word.lower() in text)
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
        "content": _short_text(chunk.get("content", ""), MAX_CHUNK_CHARS),
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


def _compact_graph_context(graph_context: dict) -> dict:
    if not isinstance(graph_context, dict):
        return {"entities": [], "relations": [], "paths": []}

    entities = []
    for entity in _as_list(graph_context.get("entities"))[:24]:
        if not isinstance(entity, dict) or not entity.get("source_chunk_ids"):
            continue
        entities.append(
            {
                "entity_id": _as_text(entity.get("entity_id")),
                "entity_type": _as_text(entity.get("entity_type")),
                "name": _as_text(entity.get("name")),
                "description": _short_text(entity.get("description"), 500),
                "source_chunk_ids": _as_string_list(entity.get("source_chunk_ids"))[:6],
            }
        )

    relations = []
    for relation in _as_list(graph_context.get("relations"))[:40]:
        if not isinstance(relation, dict) or not relation.get("source_chunk_ids"):
            continue
        relations.append(
            {
                "relation_id": _as_text(relation.get("relation_id")),
                "source": _as_text(relation.get("source_name") or relation.get("source")),
                "relation_type": _as_text(relation.get("relation_type")),
                "target": _as_text(relation.get("target_name") or relation.get("target")),
                "description": _short_text(relation.get("description"), 500),
                "source_chunk_ids": _as_string_list(relation.get("source_chunk_ids"))[:6],
            }
        )

    return {
        "entities": entities,
        "relations": relations,
        "paths": _as_list(graph_context.get("paths"))[:5],
    }


def _normalize_graph_alignment(value: object, graph_context: dict, files: list[dict]) -> dict:
    source = value if isinstance(value, dict) else {}
    compact_graph = _compact_graph_context(graph_context)
    module_mapping = [
        item
        for item in _as_list(source.get("module_mapping"))
        if isinstance(item, dict) and _as_text(item.get("entity"))
    ]
    if not module_mapping:
        module_mapping = _infer_graph_module_mapping(compact_graph, files)

    return {
        "entities_used": _as_string_list(source.get("entities_used"))[:30]
        or [entity["name"] for entity in compact_graph["entities"] if entity.get("name")][:30],
        "relations_used": _as_string_list(source.get("relations_used"))[:40]
        or [
            f"{relation.get('source', '')} {relation.get('relation_type', '')} {relation.get('target', '')}".strip()
            for relation in compact_graph["relations"]
        ][:40],
        "module_mapping": module_mapping[:30],
    }


def _infer_graph_module_mapping(graph_context: dict, files: list[dict]) -> list[dict]:
    file_paths = {file_plan.get("path", "") for file_plan in files}
    mapping = []
    for entity in graph_context.get("entities", []):
        entity_type = entity.get("entity_type", "")
        target = _target_file_for_graph_entity(entity_type, file_paths)
        if not target:
            continue
        mapping.append(
            {
                "entity": entity.get("name", ""),
                "entity_type": entity_type,
                "target_file": target,
                "target_symbol": _target_symbol_for_graph_entity(entity_type),
                "source_chunk_ids": entity.get("source_chunk_ids", []),
            }
        )
    return mapping


def _target_file_for_graph_entity(entity_type: str, file_paths: set[str]) -> str:
    candidates = {
        "environment": ["src/environment.py", "src/experiment.py"],
        "state": ["src/environment.py", "src/experiment.py"],
        "action": ["src/environment.py", "src/experiment.py"],
        "reward": ["src/environment.py", "src/evaluation.py", "src/experiment.py"],
        "algorithm": ["src/agent.py", "src/algorithm.py", "src/experiment.py"],
        "model": ["src/model.py", "src/agent.py", "src/algorithm.py"],
        "module": ["src/algorithm.py", "src/experiment.py"],
        "code_module": ["src/experiment.py"],
        "dataset": ["src/data.py", "src/experiment.py"],
        "metric": ["src/evaluation.py", "src/experiment.py"],
        "training_step": ["src/training.py", "src/experiment.py"],
        "evaluation_protocol": ["src/evaluation.py", "src/experiment.py"],
    }.get(entity_type, ["src/experiment.py"])
    for candidate in candidates:
        if candidate in file_paths:
            return candidate
    return ""


def _target_symbol_for_graph_entity(entity_type: str) -> str:
    return {
        "environment": "Environment",
        "state": "Environment._get_state",
        "action": "Environment.step",
        "reward": "Environment._compute_reward",
        "algorithm": "Agent",
        "model": "Model",
        "dataset": "load_data",
        "metric": "evaluate",
        "training_step": "train",
        "evaluation_protocol": "evaluate",
    }.get(entity_type, "run_experiment")


def _compact_spec(spec: dict) -> dict:
    return {
        "project_name": spec.get("project_name", ""),
        "project_type": spec.get("project_type", ""),
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
        "experiment_spec": spec.get("experiment_spec", {}),
        "experiment_contract": spec.get("experiment_contract", {}),
        "graph_context": spec.get("graph_context", {}),
        "graph_alignment": spec.get("graph_alignment", {}),
        "expected_outputs": spec.get("expected_outputs", []),
        "assumptions": spec.get("assumptions", [])[:6],
        "missing_details": spec.get("missing_details", [])[:6],
        "files": spec.get("files", []),
    }


def _paper_summary(analysis: dict) -> dict:
    final_summary = analysis.get("final_summary") or {}
    return {
        "title": final_summary.get("title") or analysis.get("title", ""),
        "summary": final_summary.get("one_sentence_summary") or final_summary.get("executive_summary") or analysis.get("abstract", ""),
    }


def _guess_project_type(analysis: dict) -> str:
    text = json.dumps(_compact_analysis(analysis), ensure_ascii=False).lower()
    if any(keyword in text for keyword in ["reinforcement learning", "dqn", "ddqn", "policy", "reward", "state", "action"]):
        return "rl"
    if any(keyword in text for keyword in ["simulation", "simulator", "monte carlo", "discrete event", "仿真"]):
        return "simulation"
    if any(keyword in text for keyword in ["optimization", "optimisation", "solver", "objective function", "constraint"]):
        return "optimization"
    if any(keyword in text for keyword in ["classification", "regression", "neural network", "deep learning", "dataset", "training"]):
        return "ml"
    return "analysis"


def _guess_dependencies(analysis: dict) -> list[str]:
    text = json.dumps(_compact_analysis(analysis), ensure_ascii=False).lower()
    dependencies = ["numpy"]
    if any(keyword in text for keyword in ["actor-critic", "actor critic", "a3c", "a2c", "reinforcement learning"]):
        dependencies.append("torch")
    if any(keyword in text for keyword in ["torch", "ddqn", "dqn", "deep reinforcement", "深度强化学习", "神经网络"]):
        dependencies.append("torch")
    if any(keyword in text for keyword in ["pandas", "csv", "dataset", "数据"]):
        dependencies.append("pandas")
    if any(keyword in text for keyword in ["plot", "figure", "visual", "图", "可视化"]):
        dependencies.append("matplotlib")
    if any(keyword in text for keyword in ["sklearn", "classification", "regression", "机器学习"]):
        dependencies.append("scikit-learn")
    return _dedupe(dependencies)


def _guess_framework(dependencies: list[str]) -> str:
    if "torch" in dependencies:
        return "pytorch"
    if "scikit-learn" in dependencies:
        return "scikit-learn"
    return "python"


def _normalize_dependencies(value: object) -> list[str]:
    raw_items: list[str] = []
    for item in _as_list(value):
        text = _as_text(item)
        if not text:
            continue
        text = re.sub(r"\bpip\s+install\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\bpip(?=[a-zA-Z])", " ", text, flags=re.IGNORECASE)
        text = _split_joined_dependencies(text)
        raw_items.extend(part for part in re.split(r"[\s,;]+", text) if part)

    dependencies = []
    blocked = {"pip", "python", "argparse", "setuptools", "wheel"}
    for item in raw_items:
        dependency = _safe_dependency(item)
        name = re.split(r"[<>=!~\[]", dependency, maxsplit=1)[0].lower()
        if not dependency or name in blocked:
            continue
        dependencies.append(dependency)
    return _dedupe(dependencies)


def _split_joined_dependencies(text: str) -> str:
    known_names = [
        "torch",
        "numpy",
        "matplotlib",
        "pandas",
        "scikit-learn",
        "sklearn",
        "scipy",
        "tqdm",
        "gymnasium",
        "gym",
        "networkx",
        "seaborn",
        "argparse",
    ]
    result = text
    for name in known_names:
        result = re.sub(rf"(?<!^)(?<![\s,;])({re.escape(name)}(?=[<>=!~\[]|$))", r" \1", result)
    return result


def _guess_project_name(analysis: dict) -> str:
    title = (analysis.get("final_summary") or {}).get("title") or analysis.get("title") or "generated_research_code"
    return _safe_project_name(title)


def _safe_project_name(value: object) -> str:
    text = _as_text(value).lower()
    name = "".join(char if char.isalnum() else "_" for char in text)
    name = "_".join(part for part in name.split("_") if part)
    return name[:80] or "generated_research_code"


def _safe_relative_path(value: object) -> str:
    path = _as_text(value).replace("\\", "/").lstrip("/")
    parts = [part for part in path.split("/") if part not in {"", ".", ".."}]
    if not parts:
        return ""
    return "/".join(parts)


def _safe_identifier(value: object) -> str:
    text = _as_text(value)
    if not text:
        return ""
    if re.fullmatch(r"__\w+__", text):
        return text
    text = re.sub(r"\W+", "_", text)
    text = text.strip("_")
    if not text or text[0].isdigit():
        return ""
    return text


def _safe_dependency(value: object) -> str:
    return re.sub(r"[^a-zA-Z0-9_.<>=!-]", "", _as_text(value))


def _is_local_rendered_file(path: str) -> bool:
    return path in LOCAL_RENDERED_FILES


def _code_gen_max_workers() -> int:
    value = os.getenv("CODE_GEN_MAX_WORKERS", str(DEFAULT_CODE_GEN_MAX_WORKERS))
    try:
        parsed = int(value)
    except ValueError:
        return DEFAULT_CODE_GEN_MAX_WORKERS
    return max(1, min(parsed, 6))


def _strip_code_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.rstrip() + "\n"


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


def _as_string_list(value: object) -> list[str]:
    return [text for text in (_as_text(item) for item in _as_list(value)) if text]


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _dedupe(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
