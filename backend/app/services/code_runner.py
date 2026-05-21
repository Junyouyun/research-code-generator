from __future__ import annotations

import ast
import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from app.config import (
    DEFAULT_CODE_VALIDATION_INSTALL_TIMEOUT_SECONDS,
    DEFAULT_CODE_VALIDATION_KEEP_FAILED_RUNS,
    DEFAULT_CODE_VALIDATION_TIMEOUT_SECONDS,
    VALIDATION_DIR,
    get_bool_env,
    get_int_env,
)


class CodeValidationError(RuntimeError):
    def __init__(self, result: dict):
        self.result = result
        super().__init__(result.get("message") or "Generated code validation failed")


def check_code(code_dir: Path) -> dict:
    """Validate generated code in an isolated temporary venv before packaging."""
    code_dir = code_dir.resolve()
    result_path = code_dir.parent / "validation_result.json"
    diagnostics: list[dict] = []

    try:
        spec = _load_code_spec(code_dir)
        _validate_code_dir(code_dir)
        trees = _parse_python_files(code_dir, diagnostics)
        _check_local_imports(code_dir, trees, diagnostics)
        _check_contract_exports(code_dir, trees, diagnostics)
        _raise_if_diagnostics(diagnostics, stage="static")

        run_result = _run_in_temporary_venv(code_dir, _load_run_command(code_dir), spec)
        result = {
            "success": True,
            "message": "Generated code validation passed",
            "diagnostics": diagnostics,
            "commands": run_result["commands"],
            "experiment_trace": run_result.get("experiment_trace", {}),
        }
        _write_json(result_path, result)
        return result
    except CodeValidationError as exc:
        _write_json(result_path, exc.result)
        raise
    except Exception as exc:
        result = {
            "success": False,
            "message": f"Generated code validation failed: {exc}",
            "diagnostics": diagnostics,
            "commands": [],
        }
        _write_json(result_path, result)
        raise CodeValidationError(result) from exc


def _validate_code_dir(code_dir: Path) -> None:
    if not code_dir.exists():
        raise RuntimeError(f"code directory not found: {code_dir}")
    if not (code_dir / "main.py").exists():
        raise RuntimeError("main.py not found in generated code")


def _parse_python_files(code_dir: Path, diagnostics: list[dict]) -> dict[Path, ast.Module]:
    trees = {}
    for path in sorted(code_dir.rglob("*.py")):
        relative_path = _relative_path(code_dir, path)
        try:
            trees[path] = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative_path)
        except SyntaxError as exc:
            diagnostics.append(
                {
                    "stage": "static",
                    "severity": "error",
                    "code": "invalid_python_syntax",
                    "file": relative_path,
                    "line": exc.lineno,
                    "message": str(exc),
                }
            )
    return trees


def _check_local_imports(code_dir: Path, trees: dict[Path, ast.Module], diagnostics: list[dict]) -> None:
    modules = {_module_name(code_dir, path): path for path in trees}
    exports = {_module_name(code_dir, path): _top_level_exports(tree) for path, tree in trees.items()}

    for path, tree in trees.items():
        importer = _relative_path(code_dir, path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module_name = _resolve_import_module(code_dir, path, node)
            if not module_name or module_name not in modules:
                continue
            exported_names = exports.get(module_name, set())
            for alias in node.names:
                if alias.name == "*":
                    continue
                if alias.name not in exported_names:
                    diagnostics.append(
                        {
                            "stage": "static",
                            "severity": "error",
                            "code": "missing_imported_symbol",
                            "file": importer,
                            "line": node.lineno,
                            "message": (
                                f"{importer} imports {alias.name} from {module_name}, "
                                f"but {module_name} does not define it"
                            ),
                            "related_files": [_relative_path(code_dir, modules[module_name])],
                        }
                    )


def _check_contract_exports(code_dir: Path, trees: dict[Path, ast.Module], diagnostics: list[dict]) -> None:
    spec = _load_code_spec(code_dir)
    if not spec:
        return

    trees_by_relative_path = {_relative_path(code_dir, path): tree for path, tree in trees.items()}
    for contract in spec.get("module_contracts", []):
        if not isinstance(contract, dict):
            continue
        relative_path = _safe_spec_path(contract.get("path"))
        if not relative_path or not relative_path.endswith(".py"):
            continue
        tree = trees_by_relative_path.get(relative_path)
        if tree is None:
            diagnostics.append(
                {
                    "stage": "static",
                    "severity": "error",
                    "code": "missing_contract_module",
                    "file": relative_path,
                    "line": None,
                    "message": f"code_spec declares module {relative_path}, but the file does not exist",
                }
            )
            continue

        actual_exports = _top_level_exports(tree)
        for export_name in _contract_export_names(contract):
            if export_name in actual_exports:
                continue
            diagnostics.append(
                {
                    "stage": "static",
                    "severity": "error",
                    "code": "missing_contract_export",
                    "file": relative_path,
                    "line": None,
                    "message": (
                        f"code_spec declares {relative_path} exports {export_name}, "
                        f"but the file does not define it"
                    ),
                }
            )


def _contract_export_names(contract: dict) -> list[str]:
    names = []
    for export in contract.get("exports", []):
        if isinstance(export, str) and export.strip():
            names.append(export.strip())
        elif isinstance(export, dict) and isinstance(export.get("name"), str) and export["name"].strip():
            names.append(export["name"].strip())
    return names


def _top_level_exports(tree: ast.Module) -> set[str]:
    exports = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            exports.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    exports.add(target.id)
    return exports


def _resolve_import_module(code_dir: Path, importer_path: Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module

    package_parts = _module_name(code_dir, importer_path).split(".")[:-1]
    if node.level > 1:
        package_parts = package_parts[: -(node.level - 1)]
    if node.module:
        package_parts.extend(node.module.split("."))
    return ".".join(part for part in package_parts if part)


def _module_name(code_dir: Path, path: Path) -> str:
    relative = path.relative_to(code_dir).with_suffix("")
    return ".".join(relative.parts)


def _raise_if_diagnostics(diagnostics: list[dict], stage: str) -> None:
    errors = [item for item in diagnostics if item.get("severity") == "error"]
    if not errors:
        return
    result = {
        "success": False,
        "message": f"Generated code validation failed during {stage}: {errors[0]['message']}",
        "diagnostics": diagnostics,
        "commands": [],
    }
    raise CodeValidationError(result)


def _load_run_command(code_dir: Path) -> str:
    spec = _load_code_spec(code_dir)
    if spec:
        command = spec.get("run_command")
        if isinstance(command, str) and command.strip():
            return command
        entrypoint = spec.get("entrypoint")
        if isinstance(entrypoint, dict):
            command = entrypoint.get("run_command")
            if isinstance(command, str) and command.strip():
                return command
    return "python main.py --config config.json"


def _load_code_spec(code_dir: Path) -> dict:
    spec_path = code_dir.parent / "code_spec.json"
    if spec_path.exists():
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
            return spec if isinstance(spec, dict) else {}
        except json.JSONDecodeError:
            pass
    return {}


def _run_in_temporary_venv(code_dir: Path, run_command: str, spec: dict) -> dict:
    run_id = uuid.uuid4().hex[:12]
    run_dir = VALIDATION_DIR / code_dir.parent.name / run_id
    workspace = run_dir / "workspace"
    venv_dir = run_dir / ".venv"
    commands = []
    keep_failed = _keep_failed_runs()

    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(code_dir, workspace)
        _write_smoke_config(workspace)

        commands.append(_run_command([sys.executable, "-m", "venv", str(venv_dir)], cwd=run_dir))
        python_path = _venv_python(venv_dir)
        requirements_path = workspace / "requirements.txt"
        if requirements_path.exists():
            commands.append(
                _run_command(
                    [str(python_path), "-m", "pip", "install", "--no-cache-dir", "-r", str(requirements_path)],
                    cwd=workspace,
                    timeout=_install_timeout(),
                )
            )

        commands.append(_run_command([str(python_path), "-c", "import main"], cwd=workspace))
        smoke_result = _run_command(_smoke_command(run_command, python_path, workspace), cwd=workspace)
        commands.append(smoke_result)
        experiment_trace = _validate_experiment_smoke_result(workspace, smoke_result, spec, commands)
        return {"commands": commands, "experiment_trace": experiment_trace}
    except subprocess.TimeoutExpired as exc:
        result = _command_timeout_result(exc)
        commands.append(result)
        raise CodeValidationError(
            {
                "success": False,
                "message": f"Generated code validation timed out: {result['command']}",
                "diagnostics": [_diagnostic_from_command(result)],
                "commands": commands,
            }
        ) from exc
    except subprocess.CalledProcessError as exc:
        result = _command_error_result(exc)
        commands.append(result)
        raise CodeValidationError(
            {
                "success": False,
                "message": f"Generated code validation command failed: {result['command']}",
                "diagnostics": [_diagnostic_from_command(result)],
                "commands": commands,
            }
        ) from exc
    finally:
        if run_dir.exists() and not keep_failed:
            shutil.rmtree(run_dir, ignore_errors=True)
            try:
                run_dir.parent.rmdir()
            except OSError:
                pass


def _write_smoke_config(workspace: Path) -> None:
    config_path = workspace / "config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            config = {}
    else:
        config = {}

    if not isinstance(config, dict):
        config = {}
    config["output_dir"] = ".validation/outputs"
    config["input_path"] = ".validation/input.csv"
    config["data_path"] = ".validation/input.csv"
    config["dataset_path"] = ".validation/input.csv"
    config["batch_size"] = 1
    config["episodes"] = 1
    config["num_episodes"] = 1
    config["epochs"] = 1
    config["steps"] = 1
    training = config.get("training")
    if not isinstance(training, dict):
        training = {}
    training["num_episodes"] = 1
    training["episodes"] = 1
    training["epochs"] = 1
    training["eval_interval"] = 1
    training["log_dir"] = ".validation/logs"
    config["training"] = training

    validation_dir = workspace / ".validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    (validation_dir / "input.csv").write_text("x,y\n0,0\n1,1\n", encoding="utf-8")
    _write_json(validation_dir / "smoke_config.json", config)


def _smoke_command(run_command: str, python_path: Path, workspace: Path) -> list[str]:
    try:
        command = shlex.split(run_command, posix=os.name != "nt")
    except ValueError:
        command = ["python", "main.py", "--config", "config.json"]
    if not command:
        command = ["python", "main.py", "--config", "config.json"]

    if Path(command[0]).name.lower() in {"python", "python.exe", "python3", "python3.exe"}:
        command[0] = str(python_path)

    smoke_config = str(workspace / ".validation" / "smoke_config.json")
    for index, arg in enumerate(command):
        if arg == "--config" and index + 1 < len(command):
            command[index + 1] = smoke_config
            return command
        if arg.startswith("--config="):
            command[index] = f"--config={smoke_config}"
            return command

    command.extend(["--config", smoke_config])
    return command


def _run_command(command: list[str], cwd: Path, timeout: int | None = None) -> dict:
    timeout = timeout or _run_timeout()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=_validation_env(),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=True,
    )
    return {
        "command": _format_command(command),
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


def _validation_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env.pop("PYTHONPATH", None)
    return env


def _command_error_result(exc: subprocess.CalledProcessError) -> dict:
    return {
        "command": _format_command(exc.cmd if isinstance(exc.cmd, list) else [str(exc.cmd)]),
        "returncode": exc.returncode,
        "stdout": (exc.stdout or "")[-4000:],
        "stderr": (exc.stderr or "")[-4000:],
    }


def _command_timeout_result(exc: subprocess.TimeoutExpired) -> dict:
    stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    return {
        "command": _format_command(exc.cmd if isinstance(exc.cmd, list) else [str(exc.cmd)]),
        "returncode": None,
        "stdout": stdout[-4000:],
        "stderr": stderr[-4000:],
        "timeout": exc.timeout,
    }


def _diagnostic_from_command(result: dict) -> dict:
    message = result.get("stderr") or result.get("stdout") or "validation command failed"
    return {
        "stage": "runtime",
        "severity": "error",
        "code": "validation_command_failed",
        "file": None,
        "line": None,
        "message": message[-1200:],
        "command": result.get("command"),
    }


def _validate_experiment_smoke_result(workspace: Path, command_result: dict, spec: dict, commands: list[dict]) -> dict:
    if not _requires_experiment_trace(spec):
        return {}

    payload = _load_smoke_payload(workspace, command_result)
    trace = payload.get("experiment_trace") if isinstance(payload.get("experiment_trace"), dict) else {}
    if not trace and _looks_like_trace(payload):
        trace = payload

    diagnostics = _experiment_trace_diagnostics(spec, payload, trace)
    if diagnostics:
        raise CodeValidationError(
            {
                "success": False,
                "message": f"Generated code validation failed during experiment_trace: {diagnostics[0]['message']}",
                "diagnostics": diagnostics,
                "commands": commands,
                "experiment_trace": trace,
            }
        )
    return trace


def _requires_experiment_trace(spec: dict) -> bool:
    project_type = _as_text(spec.get("project_type")).lower()
    experiment_spec = spec.get("experiment_spec") if isinstance(spec.get("experiment_spec"), dict) else {}
    experiment_type = _as_text(experiment_spec.get("experiment_type")) or _as_text(spec.get("framework"))
    if experiment_type in TRACE_VALIDATORS:
        return True
    return project_type in {"rl", "ml", "simulation", "optimization"}


def _load_smoke_payload(workspace: Path, command_result: dict) -> dict:
    output_path = workspace / ".validation" / "outputs" / "smoke_result.json"
    if output_path.exists():
        try:
            data = json.loads(output_path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    stdout = _as_text(command_result.get("stdout"))
    for candidate in _json_object_candidates(stdout):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _json_object_candidates(text: str) -> list[str]:
    candidates = []
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)
    for line in reversed(stripped.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            candidates.append(line)
    return candidates


def _looks_like_trace(payload: dict) -> bool:
    trace_keys = {"used_environment", "used_agent", "used_training_loop", "episodes_completed", "total_steps"}
    return bool(trace_keys.intersection(payload))


def _experiment_trace_diagnostics(spec: dict, payload: dict, trace: dict) -> list[dict]:
    if not payload:
        return [_experiment_diagnostic("missing_smoke_result", "Smoke command succeeded but did not produce JSON output or outputs/smoke_result.json")]
    if not trace:
        return [_experiment_diagnostic("missing_experiment_trace", "Smoke result must include experiment_trace with environment/agent/training evidence")]

    return _trace_validator_for_spec(spec)(spec, trace)


def _validate_rl_experiment_trace(spec: dict, trace: dict) -> list[dict]:
    diagnostics = []

    smoke = _smoke_validation_spec(spec)
    min_episodes = _safe_int(smoke.get("episodes"), 1)
    min_steps = _safe_int(smoke.get("steps_per_episode"), 1)
    expected_total_steps = max(1, min_episodes * min_steps)

    if smoke.get("must_use_environment", True) and trace.get("used_environment") is not True:
        diagnostics.append(_experiment_diagnostic("environment_not_used", "experiment_trace.used_environment must be true"))
    if smoke.get("must_use_agent", spec.get("project_type") == "rl") and trace.get("used_agent") is not True:
        diagnostics.append(_experiment_diagnostic("agent_not_used", "experiment_trace.used_agent must be true"))
    if trace.get("used_training_loop") is not True:
        diagnostics.append(_experiment_diagnostic("training_loop_not_used", "experiment_trace.used_training_loop must be true"))

    episodes_completed = _safe_int(trace.get("episodes_completed"), 0)
    total_steps = _safe_int(trace.get("total_steps"), 0)
    if episodes_completed < min_episodes:
        diagnostics.append(
            _experiment_diagnostic(
                "episodes_not_completed",
                f"experiment_trace.episodes_completed must be at least {min_episodes}, got {episodes_completed}",
            )
        )
    if total_steps < expected_total_steps:
        diagnostics.append(
            _experiment_diagnostic(
                "steps_not_completed",
                f"experiment_trace.total_steps must be at least {expected_total_steps}, got {total_steps}",
            )
        )

    return diagnostics


def _trace_validator_for_spec(spec: dict):
    experiment_spec = spec.get("experiment_spec") if isinstance(spec.get("experiment_spec"), dict) else {}
    experiment_type = _as_text(experiment_spec.get("experiment_type")) or _as_text(spec.get("framework"))
    return TRACE_VALIDATORS.get(experiment_type, _validate_rl_experiment_trace)


def registered_trace_validators() -> list[str]:
    return sorted(TRACE_VALIDATORS)


TRACE_VALIDATORS = {
    "rl_resource_allocation_actor_critic": _validate_rl_experiment_trace,
}


def _smoke_validation_spec(spec: dict) -> dict:
    experiment_spec = spec.get("experiment_spec") if isinstance(spec.get("experiment_spec"), dict) else {}
    smoke = experiment_spec.get("smoke_validation") if isinstance(experiment_spec.get("smoke_validation"), dict) else {}
    if smoke:
        return smoke
    contract = spec.get("experiment_contract") if isinstance(spec.get("experiment_contract"), dict) else {}
    return contract.get("smoke_validation") if isinstance(contract.get("smoke_validation"), dict) else {}


def _experiment_diagnostic(code: str, message: str) -> dict:
    return {
        "stage": "experiment_trace",
        "severity": "error",
        "code": code,
        "file": "outputs/smoke_result.json",
        "line": None,
        "message": message,
    }


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _run_timeout() -> int:
    return get_int_env("CODE_VALIDATION_TIMEOUT_SECONDS", DEFAULT_CODE_VALIDATION_TIMEOUT_SECONDS)


def _install_timeout() -> int:
    return get_int_env("CODE_VALIDATION_INSTALL_TIMEOUT_SECONDS", DEFAULT_CODE_VALIDATION_INSTALL_TIMEOUT_SECONDS)


def _keep_failed_runs() -> bool:
    return get_bool_env("CODE_VALIDATION_KEEP_FAILED_RUNS", DEFAULT_CODE_VALIDATION_KEEP_FAILED_RUNS)


def _relative_path(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _safe_spec_path(value: object) -> str:
    if not isinstance(value, str):
        return ""
    path = value.replace("\\", "/").lstrip("/")
    parts = [part for part in path.split("/") if part not in {"", ".", ".."}]
    return "/".join(parts)


def _format_command(command: list[str]) -> str:
    return " ".join(command)


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
