---
name: generated-code-auto-repair
description: Implement or maintain phase 2 of generated research code quality control: LLM-driven repair after validation failure. Use when adding repair_generated_code, selecting related files from diagnostics, asking the LLM for changed_files JSON, applying safe file patches, retrying validation, or turning phase 1 validation failures into automatic fixes before packaging.
---

# Generated Code Auto Repair

## Goal

Add a repair loop after phase 1 validation fails.

The pipeline should attempt to fix generated code automatically, then re-run validation. Only package when validation passes.

## Prerequisite

Phase 1 must already exist:

```text
generate_code_files
-> check_code
-> build_artifact
```

Phase 2 changes this to:

```text
generate_code_files
-> validate
-> if failed: repair
-> validate again
-> repeat within limit
-> package only if passed
```

## Core Loop

Use a bounded retry loop:

```text
attempt 0: validate generated code
attempt 1: repair from diagnostics, validate again
attempt 2: repair from diagnostics, validate again
attempt 3: repair from diagnostics, validate again
```

Default max repair attempts:

```text
CODE_REPAIR_MAX_ATTEMPTS=3
```

Never run an unbounded repair loop.

## Repair Inputs

For each repair attempt, send the LLM only the minimal useful context:

- `code_spec.json` compacted.
- Current diagnostics from `validation_result`.
- Relevant file contents.
- The exact failed command, stdout tail, and stderr tail when available.
- A concise instruction to preserve runnable behavior and fix the reported contract mismatch.

Do not send the entire project unless diagnostics cannot identify relevant files.

## Related File Selection

Select files by diagnostic type.

For `missing_imported_symbol`:

```text
diagnostic.file
diagnostic.related_files
```

Example:

```text
main.py
src/agent.py
```

For `invalid_python_syntax`:

```text
diagnostic.file
```

For runtime `ImportError: cannot import name X from Y`:

```text
file from traceback top frame
module file for Y if local
main.py
```

For `TypeError: __init__ got an unexpected keyword argument`:

```text
caller file from traceback
class definition file
config.json
code_spec.json
```

For `AttributeError: object has no attribute`:

```text
caller file from traceback
class definition file if local
main.py
```

For generic runtime failure:

```text
main.py
files appearing in traceback
config.json
```

Cap total file content sent to the LLM. Prefer the most directly related files.

## LLM Output Contract

Require strict JSON only:

```json
{
  "reason": "main.py imports DQNAgent, but src.agent defines DDQNAgent. Use one public class name consistently.",
  "changed_files": [
    {
      "path": "main.py",
      "content": "..."
    },
    {
      "path": "src/agent.py",
      "content": "..."
    }
  ]
}
```

Reject outputs that:

- Are not valid JSON.
- Contain paths outside the generated code directory.
- Try to modify files outside `code_dir`.
- Omit `content` for a changed file.
- Include absolute paths.
- Include `..` path traversal.

## Patch Application Rules

Apply only complete-file replacements from `changed_files`.

Before writing:

- Normalize the relative path with the same safe path rules used by code generation.
- Ensure final path stays inside `code_dir`.
- Ensure changed file already exists unless diagnostics justify creating it.
- Prefer modifying existing files over creating new files.

After writing:

- Run static validation immediately.
- Then run isolated venv validation.

## Pipeline Integration

Introduce one orchestration function, for example:

```python
validate_and_repair_code(
    code_dir: Path,
    spec: dict,
    analysis: dict,
    chunks: list[dict],
    max_attempts: int,
) -> dict
```

The function should return the final validation result plus repair metadata:

```json
{
  "success": true,
  "attempts": 2,
  "repairs": [
    {
      "attempt": 1,
      "reason": "...",
      "changed_files": ["main.py", "src/agent.py"]
    }
  ],
  "diagnostics": [],
  "commands": []
}
```

Pipeline should still use `ProjectStatus.CHECKING_CODE`; repair is part of checking.

## Project Events

Emit events for:

- Validation attempt started.
- Validation failed.
- Repair attempt started.
- Files changed by repair.
- Validation passed after repair.
- Repair exhausted.

Use `details.kind = "code_validation"` or `details.kind = "code_repair"`.

Do not expose full file contents in project events.

## Failure Policy

If all repair attempts fail:

- Write final `validation_result.json`.
- Include the final diagnostics and repair history.
- Mark pipeline failed.
- Do not package `result.zip`.

If repair succeeds:

- Continue to packaging.
- Keep the repaired code in `data/generated/<project_id>/code`.
- Include repair history in `validation_result.json`.

## Prompt Requirements

The repair prompt must state:

- Fix the reported validation failure, not unrelated code style.
- Preserve public interfaces already used by other generated files.
- Keep dependencies minimal.
- Keep runtime short under the smoke config.
- Do not add TODO placeholders.
- Return JSON only.

## Acceptance Checks

Before finishing phase 2, verify:

- A `DQNAgent` vs `DDQNAgent` mismatch is repaired automatically.
- A `plot_curves` vs `plot_all` mismatch is repaired automatically.
- A constructor keyword mismatch is repaired automatically when relevant files are supplied.
- The repair loop stops after max attempts.
- Invalid repair JSON fails cleanly and records diagnostics.
- No repair can write outside the generated code directory.
