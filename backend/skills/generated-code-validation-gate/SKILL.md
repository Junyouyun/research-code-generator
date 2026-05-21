---
name: generated-code-validation-gate
description: Implement or maintain phase 1 of generated research code quality control: static validation plus isolated temporary venv smoke testing before packaging. Use when working on check_code, pipeline CHECKING_CODE, validation_result.json, temporary validation workspaces, requirements installation isolation, import smoke tests, or preventing invalid generated zip artifacts from being packaged.
---

# Generated Code Validation Gate

## Goal

Make generated code pass a packaging gate before `result.zip` is created.

The gate must catch common multi-file mismatches before users download the artifact:

- `main.py` imports a class/function that the target module does not export.
- Generated Python has syntax errors.
- `config.json` is invalid.
- `requirements.txt` cannot be installed in an isolated environment.
- `import main` fails.
- The entry command fails under a short smoke config.

## Scope

Work only on phase 1:

```text
generate_code_files
-> check_code
-> build_artifact
```

Do not implement LLM repair in this phase. Validation failure should stop packaging and surface structured diagnostics.

## Required Behavior

Use a three-part validation flow.

1. Static validation

Do not execute generated code yet.

- Parse every generated `.py` file with `ast.parse`.
- Use `utf-8-sig` when reading Python files so BOM does not create false failures.
- Collect top-level exports from classes, functions, async functions, assigned names, and annotated assigned names.
- Check local `from module import symbol` imports when the module exists inside the generated code tree.
- Report missing imported symbols as structured diagnostics.
- Avoid `py_compile` in the generated source directory because it writes `__pycache__`.

2. Isolated temporary venv validation

Never install generated requirements into the backend environment, system Python, Anaconda, or the generated code directory.

Use this shape:

```text
data/validation_runs/<project_id>/<run_id>/
  workspace/       copied generated code
  .venv/           temporary dependencies
```

Then run:

```text
<backend-python> -m venv <run_dir>/.venv
<venv-python> -m pip install --no-cache-dir -r workspace/requirements.txt
<venv-python> -c "import main"
<venv-python> <entry-file> --config workspace/.validation/smoke_config.json
```

3. Cleanup

- Delete the run directory after success.
- Delete the run directory after failure unless `CODE_VALIDATION_KEEP_FAILED_RUNS=true`.
- If the project-level validation directory becomes empty, remove it too.

## Smoke Config Rules

Create `workspace/.validation/smoke_config.json`.

Start from generated `config.json` if it is valid JSON. Then override common long-running or output fields:

```json
{
  "output_dir": ".validation/outputs",
  "input_path": ".validation/input.csv",
  "data_path": ".validation/input.csv",
  "dataset_path": ".validation/input.csv",
  "batch_size": 1,
  "episodes": 1,
  "num_episodes": 1,
  "epochs": 1,
  "steps": 1,
  "training": {
    "num_episodes": 1,
    "episodes": 1,
    "epochs": 1,
    "eval_interval": 1,
    "log_dir": ".validation/logs"
  }
}
```

Also create a tiny fallback CSV:

```csv
x,y
0,0
1,1
```

## Entry Command Rules

Prefer `code_spec.json` next to the generated `code/` directory:

```json
{
  "run_command": "python main.py --config config.json"
}
```

If it is missing or invalid, default to:

```text
python main.py --config config.json
```

When executing the smoke command:

- Parse with `shlex.split`.
- Replace `python`, `python.exe`, `python3`, or `python3.exe` with the temporary venv Python path.
- Replace any existing `--config` value with `.validation/smoke_config.json`.
- If no `--config` exists, append it.
- Never use `shell=True`.

## Diagnostics Contract

Return and persist structured results to:

```text
data/generated/<project_id>/validation_result.json
```

Use this shape:

```json
{
  "success": false,
  "message": "Generated code validation failed during static: main.py imports DQNAgent from src.agent, but src.agent does not define it",
  "diagnostics": [
    {
      "stage": "static",
      "severity": "error",
      "code": "missing_imported_symbol",
      "file": "main.py",
      "line": 8,
      "message": "main.py imports DQNAgent from src.agent, but src.agent does not define it",
      "related_files": ["src/agent.py"]
    }
  ],
  "commands": []
}
```

For runtime command failures, include the command, return code, stdout tail, and stderr tail.

## Pipeline Integration

Use existing `ProjectStatus.CHECKING_CODE`.

Insert validation between code generation and packaging:

```python
_run_step(... ProjectStatus.GENERATING_CODE ..., generate_code_files)
validation_result = _run_step(... ProjectStatus.CHECKING_CODE ..., check_code)
_run_step(... ProjectStatus.PACKAGING ..., build_artifact)
```

On validation failure:

- Add a project event with `level="error"`.
- Include `details.kind = "code_validation"`.
- Include `diagnostics` and `commands`.
- Re-raise the validation error so the pipeline fails.
- Do not create `result.zip`.

On validation success:

- Add a project event with `details.kind = "code_validation"`.
- Continue packaging.

## Configuration

Keep defaults conservative:

```python
VALIDATION_DIR = DATA_DIR / "validation_runs"
DEFAULT_CODE_VALIDATION_TIMEOUT_SECONDS = 90
DEFAULT_CODE_VALIDATION_INSTALL_TIMEOUT_SECONDS = 180
DEFAULT_CODE_VALIDATION_KEEP_FAILED_RUNS = False
```

Read overrides from env:

```text
CODE_VALIDATION_TIMEOUT_SECONDS
CODE_VALIDATION_INSTALL_TIMEOUT_SECONDS
CODE_VALIDATION_KEEP_FAILED_RUNS
```

## Acceptance Checks

Before finishing phase 1, verify:

- A generated project with `from src.agent import MissingAgent` fails before venv creation.
- A small valid generated project creates a temporary venv, runs `import main`, runs the smoke command, and cleans `data/validation_runs`.
- `validation_result.json` is written on success and failure.
- Packaging is skipped when validation fails.
- The final zip still contains `Dockerfile`; backend does not run Docker in phase 1.
