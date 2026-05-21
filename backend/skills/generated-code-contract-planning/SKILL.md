---
name: generated-code-contract-planning
description: Implement or maintain phase 3 of generated research code quality control: contract-driven code planning and generation. Use when extending code_spec with module contracts, interfaces, config schemas, expected outputs, prompt constraints, contract validation, or reducing multi-file drift before LLM file generation.
---

# Generated Code Contract Planning

## Goal

Prevent multi-file drift before code is generated.

Phase 1 catches bad artifacts. Phase 2 repairs them. Phase 3 reduces how often they happen by making generation contract-driven.

## Problem To Solve

LLM-generated files can each be plausible but mutually inconsistent:

```text
main.py imports DQNAgent
src/agent.py defines DDQNAgent

main.py calls plot_curves
src/visualize.py exports plot_all

main.py calls train(env=..., agent=...)
src/train.py defines train(config)

evaluate.py calls agent.get_action
src/agent.py defines select_action
```

The source problem is that every file invents interfaces independently.

## Desired Generation Shape

Use this order:

```text
1. Analyze paper
2. Generate code_spec with explicit contracts
3. Normalize and validate contracts
4. Generate every file using the same contract
5. Run phase 1 validation
6. Run phase 2 repair if enabled
7. Package only after validation passes
```

## Code Spec Contract Fields

Extend `code_spec` with these fields.

```json
{
  "entrypoint": {
    "path": "main.py",
    "run_command": "python main.py --config config.json",
    "main_function": "main"
  },
  "module_contracts": [
    {
      "path": "src/environment.py",
      "exports": [
        {
          "type": "class",
          "name": "SatelliteEnvironment",
          "methods": [
            {
              "name": "__init__",
              "signature": "(config: dict)"
            },
            {
              "name": "reset",
              "signature": "() -> np.ndarray"
            },
            {
              "name": "step",
              "signature": "(action: int) -> tuple[np.ndarray, float, bool, dict]"
            }
          ]
        }
      ]
    }
  ],
  "interfaces": {
    "agent": {
      "class_name": "DDQNAgent",
      "required_methods": [
        "select_action",
        "store_transition",
        "train_step",
        "save"
      ]
    },
    "environment": {
      "class_name": "SatelliteEnvironment",
      "step_info_keys": [
        "served_users",
        "system_throughput"
      ]
    },
    "evaluation": {
      "function_name": "evaluate_agent",
      "signature": "(agent, env, num_episodes=10, deterministic=True) -> dict"
    },
    "visualization": {
      "function_name": "plot_curves",
      "signature": "(rewards, losses, epsilon_values, save_path=None) -> None"
    }
  },
  "config_schema": {
    "required": ["output_dir", "random_seed"],
    "training_defaults": {
      "num_episodes": 50,
      "eval_interval": 10
    }
  },
  "expected_outputs": [
    "outputs/training_metrics.json",
    "outputs/final_model.pth"
  ]
}
```

Keep the schema flexible enough for non-ML papers, but always require entrypoint, module contracts, run command, and config defaults.

## Planning Prompt Rules

When generating `code_spec`, instruct the LLM:

- Return JSON only.
- Declare every public class/function used across files.
- Pick one canonical name for each concept and reuse it everywhere.
- Prefer one stable entrypoint: `main.py`.
- Prefer one stable config path: `config.json`.
- For ML/RL/simulation papers, declare environment, agent/model, training, evaluation, and visualization interfaces.
- If paper details are missing, put defaults in `config` and assumptions in `assumptions`.
- Do not include more than the maximum file count.

## File Generation Prompt Rules

Every generated file prompt must include:

- Full `module_contracts`.
- Full `interfaces`.
- The target file's own contract.
- The list of files in the project.
- The run command.
- Relevant paper chunks.

State these constraints explicitly:

```text
Implement exactly the exports declared for this target file.
Do not invent alternative names for public classes or functions.
If this file imports another generated module, import only symbols declared in that module's contract.
If a contract and your preferred design conflict, follow the contract.
The generated file must be complete and runnable.
Return only file content, no Markdown.
```

## Contract Normalization

After receiving `code_spec`, normalize it:

- Ensure `main.py`, `requirements.txt`, `Dockerfile`, `config.json`, and `README.md` exist.
- Ensure each Python file has a module contract.
- Ensure every module contract path exists in `files`.
- Ensure every importable path maps to a valid module name.
- Ensure `entrypoint.path` exists.
- Ensure `run_command` targets the entrypoint.
- Ensure config contains smoke-testable defaults.

When fields are missing, infer conservative defaults rather than failing immediately.

## Contract Validation

Before generating file contents, validate the contract itself:

- No duplicate module paths.
- No duplicate export names in the same module.
- `main.py` has an entrypoint contract.
- Referenced interfaces point to declared exports.
- `run_command` uses a generated entry file.
- No paths escape the generated code directory.

After generating files, run phase 1 static validation and compare actual exports against contract exports:

```text
contract says src.agent exports DDQNAgent
actual src/agent.py must define DDQNAgent
```

## Backward Compatibility

Existing `code_spec` may not contain contracts.

When contracts are absent:

- Build a minimal inferred contract from `files`.
- Require `main.py`.
- Allow phase 1 validation to catch inconsistencies.
- Do not break old projects.

## Recommended Module Patterns

For ML/RL generated projects, prefer stable interfaces:

```text
src/environment.py
  class <Environment>
    __init__(config: dict)
    reset()
    step(action)

src/agent.py
  class <Agent>
    __init__(state_dim, action_dim, config: dict | None = None, **kwargs)
    select_action(state, explore=True)
    store_transition(state, action, reward, next_state, done)
    train_step()
    save(path)

src/evaluate.py
  evaluate_agent(agent, env, num_episodes=10, deterministic=True)

src/visualize.py
  plot_curves(rewards, losses, epsilon_values, save_path=None)

main.py
  parse --config
  load config
  instantiate env and agent
  run short/normal training based on config
  save outputs under output_dir
```

Do not force this pattern on non-ML papers. Use it when the paper naturally describes training, simulation, optimization, or reinforcement learning.

## Acceptance Checks

Before finishing phase 3, verify:

- `code_spec.json` contains module contracts.
- File generation prompts include the same contract for every generated Python file.
- `main.py` imports only declared exports.
- Actual generated exports match contract exports.
- Phase 1 validation still runs after generation.
- Phase 2 repair, if enabled, uses contract information as repair context.
