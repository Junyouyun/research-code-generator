from __future__ import annotations

import copy


def apply_experiment_framework(spec: dict, experiment_spec: dict | None = None) -> dict:
    """Apply a reusable experiment framework to the code plan before normalization."""
    experiment_spec = experiment_spec or {}
    builder = FRAMEWORK_BUILDERS.get(experiment_spec.get("experiment_type"))
    if not builder:
        return spec

    result = copy.deepcopy(spec) if isinstance(spec, dict) else {}
    framework = builder(experiment_spec)
    return _apply_framework_payload(result, framework)


def registered_experiment_frameworks() -> list[str]:
    return sorted(FRAMEWORK_BUILDERS)


def _apply_framework_payload(result: dict, framework: dict) -> dict:
    result["project_type"] = framework.get("project_type", result.get("project_type", "analysis"))
    result["framework"] = framework["framework"]
    result["files"] = _merge_files(framework["files"], result.get("files"))
    result["dependencies"] = _merge_list(result.get("dependencies"), framework["dependencies"])
    result["interfaces"] = _merge_dict(result.get("interfaces"), framework["interfaces"])
    result["module_contracts"] = _merge_contracts(framework["module_contracts"], result.get("module_contracts"))
    result["symbols"] = _merge_symbols(framework["symbols"], result.get("symbols"))
    result["config"] = _merge_dict(framework["config"], result.get("config"))
    result["config_schema"] = _merge_dict(result.get("config_schema"), framework["config_schema"])
    result["expected_outputs"] = _merge_list(result.get("expected_outputs"), framework["expected_outputs"])
    result["assumptions"] = _merge_list(result.get("assumptions"), framework["assumptions"])
    result["missing_details"] = _merge_list(result.get("missing_details"), framework["missing_details"])
    return result


def _rl_resource_allocation_actor_critic_framework(experiment_spec: dict) -> dict:
    smoke = experiment_spec.get("smoke_validation") if isinstance(experiment_spec.get("smoke_validation"), dict) else {}
    episodes = smoke.get("episodes", 1)
    steps_per_episode = smoke.get("steps_per_episode", 3)
    domain = experiment_spec.get("domain") or "resource_allocation"
    algorithm = experiment_spec.get("algorithm") if isinstance(experiment_spec.get("algorithm"), dict) else {}
    variant = algorithm.get("variant") or "Actor-Critic"

    return {
        "framework": "rl_resource_allocation_actor_critic",
        "project_type": "rl",
        "files": [
            {"path": "README.md", "purpose": "Explain the generated experiment project.", "kind": "document"},
            {"path": "requirements.txt", "purpose": "Declare Python dependencies.", "kind": "dependency"},
            {"path": "Dockerfile", "purpose": "Build a reproducible runtime environment.", "kind": "docker"},
            {"path": "config.json", "purpose": "Runtime configuration for the smoke experiment.", "kind": "config"},
            {"path": "main.py", "purpose": "Command-line entrypoint.", "kind": "entrypoint"},
            {"path": "src/environment.py", "purpose": "Resource-allocation environment derived from the paper experiment spec.", "kind": "code"},
            {"path": "src/agent.py", "purpose": "Actor-Critic networks and A3C-style agent.", "kind": "code"},
            {"path": "src/train.py", "purpose": "Short Actor-Critic smoke training loop.", "kind": "code"},
            {"path": "src/experiment.py", "purpose": "One-stop experiment orchestration.", "kind": "code"},
        ],
        "dependencies": ["numpy", "torch"],
        "config": {
            "domain": domain,
            "algorithm_variant": variant,
            "num_servers": 4,
            "server_capacity": 1.0,
            "episodes": episodes,
            "steps_per_episode": steps_per_episode,
            "learning_rate": 0.001,
            "gamma": 0.95,
        },
        "config_schema": {
            "required": ["output_dir", "random_seed", "episodes", "steps_per_episode"],
            "training_defaults": {
                "num_episodes": episodes,
                "eval_interval": 1,
            },
        },
        "interfaces": {
            "environment": {
                "class_name": "CloudDatacenterEnv",
                "state_source": _text_from_nested(experiment_spec, "environment", "state") or "resource usage plus current job/request features",
                "action_source": _text_from_nested(experiment_spec, "environment", "action") or "wait or assign current job/request to a server/resource",
                "reward_source": _text_from_nested(experiment_spec, "environment", "reward") or "QoS/resource efficiency minus resource or energy cost",
                "step_info_keys": ["allocated", "server_id", "job_demand", "energy_cost", "qos_reward"],
            },
            "agent": {
                "class_name": "A3CAgent",
                "required_methods": ["select_action", "store_transition", "train_step", "save"],
                "algorithm_family": "actor_critic",
                "algorithm_variant": variant,
            },
            "training": {
                "function_name": "train_a3c_smoke",
                "signature": "train_a3c_smoke(config: dict) -> dict",
            },
            "experiment": {
                "function_name": "run_experiment",
                "signature": "run_experiment(config: dict) -> dict",
            },
        },
        "module_contracts": _rl_actor_critic_contracts(experiment_spec),
        "symbols": _rl_actor_critic_symbols(),
        "expected_outputs": ["outputs/smoke_result.json"],
        "assumptions": [
            "The framework keeps the experiment smoke-sized and verifies code structure, not full paper metrics.",
            "If the original dataset is unavailable, the environment must generate a synthetic trace with the same resource-allocation shape.",
        ],
        "missing_details": [
            "Exact production-scale hyperparameters, trace preprocessing, and benchmark settings may need manual completion.",
        ],
    }


def _rl_actor_critic_contracts(experiment_spec: dict) -> list[dict]:
    state = _text_from_nested(experiment_spec, "environment", "state") or "server utilization plus current job demand and duration"
    action = _text_from_nested(experiment_spec, "environment", "action") or "0 means wait/reject; 1..N assigns the job to a server"
    reward = _text_from_nested(experiment_spec, "environment", "reward") or "QoS/resource efficiency reward minus energy/resource cost"
    training_loop = _text_from_nested(experiment_spec, "training", "loop") or "short Actor-Critic smoke training loop"

    return [
        {
            "path": "src/environment.py",
            "exports": [
                {
                    "type": "class",
                    "name": "CloudDatacenterEnv",
                    "responsibility": "Simulate the paper's resource-allocation environment with paper-specific state, action, and reward semantics.",
                    "methods": [
                        {"name": "__init__", "signature": "__init__(self, config: dict) -> None", "responsibility": "Initialize server capacities, synthetic or provided jobs, and environment counters."},
                        {"name": "reset", "signature": "reset(self)", "responsibility": f"Reset the environment and return the initial state: {state}."},
                        {"name": "step", "signature": "step(self, action: int)", "responsibility": f"Apply action semantics ({action}), update resources, compute reward ({reward}), and return next_state, reward, done, info."},
                        {"name": "state_dimension", "signature": "state_dimension(self) -> int", "responsibility": "Return the numeric state vector dimension."},
                        {"name": "action_space_size", "signature": "action_space_size(self) -> int", "responsibility": "Return the number of valid discrete actions."},
                    ],
                }
            ],
        },
        {
            "path": "src/agent.py",
            "exports": [
                {
                    "type": "class",
                    "name": "ActorNetwork",
                    "responsibility": "Policy network for the actor branch of the Actor-Critic agent.",
                    "methods": [
                        {"name": "__init__", "signature": "__init__(self, state_dim: int, action_dim: int, hidden_dim: int = 64) -> None", "responsibility": "Initialize a small policy model."},
                        {"name": "forward", "signature": "forward(self, state)", "responsibility": "Return action probabilities or scores for a state."},
                    ],
                },
                {
                    "type": "class",
                    "name": "CriticNetwork",
                    "responsibility": "Value network for the critic branch of the Actor-Critic agent.",
                    "methods": [
                        {"name": "__init__", "signature": "__init__(self, state_dim: int, hidden_dim: int = 64) -> None", "responsibility": "Initialize a small value model."},
                        {"name": "forward", "signature": "forward(self, state)", "responsibility": "Return the estimated state value."},
                    ],
                },
                {
                    "type": "class",
                    "name": "A3CAgent",
                    "responsibility": "A3C-style Actor-Critic agent that selects actions, stores transitions, and performs lightweight smoke updates.",
                    "methods": [
                        {"name": "__init__", "signature": "__init__(self, state_dim: int, action_dim: int, config: dict | None = None) -> None", "responsibility": "Create actor, critic, optimizers or fallback numeric state."},
                        {"name": "select_action", "signature": "select_action(self, state, explore: bool = True) -> int", "responsibility": "Choose an action from the actor policy for the current environment state."},
                        {"name": "store_transition", "signature": "store_transition(self, state, action: int, reward: float, next_state, done: bool) -> None", "responsibility": "Store one transition for the next actor-critic update."},
                        {"name": "train_step", "signature": "train_step(self) -> dict", "responsibility": "Run one TD-error/advantage update and return lightweight losses or counters."},
                        {"name": "save", "signature": "save(self, path) -> None", "responsibility": "Persist a minimal model or metadata artifact."},
                    ],
                },
            ],
        },
        {
            "path": "src/train.py",
            "exports": [
                {
                    "type": "function",
                    "name": "train_a3c_smoke",
                    "signature": "train_a3c_smoke(config: dict) -> dict",
                    "responsibility": f"Run {training_loop}, using CloudDatacenterEnv and A3CAgent, then return metrics and experiment_trace.",
                    "inputs": ["config"],
                    "outputs": ["metrics", "history", "experiment_trace"],
                }
            ],
        },
        {
            "path": "src/experiment.py",
            "exports": [
                {
                    "type": "function",
                    "name": "run_experiment",
                    "signature": "run_experiment(config: dict) -> dict",
                    "responsibility": "Run the fixed Actor-Critic resource-allocation framework and return a validation-friendly result object.",
                    "inputs": ["config"],
                    "outputs": ["status", "framework", "metrics", "experiment_trace"],
                }
            ],
        },
    ]


def _rl_actor_critic_symbols() -> list[dict]:
    return [
        {"id": "src.environment.CloudDatacenterEnv", "path": "src/environment.py", "kind": "class", "name": "CloudDatacenterEnv"},
        {"id": "src.environment.CloudDatacenterEnv.__init__", "path": "src/environment.py", "kind": "method", "class_name": "CloudDatacenterEnv", "name": "__init__"},
        {"id": "src.environment.CloudDatacenterEnv.reset", "path": "src/environment.py", "kind": "method", "class_name": "CloudDatacenterEnv", "name": "reset"},
        {"id": "src.environment.CloudDatacenterEnv.step", "path": "src/environment.py", "kind": "method", "class_name": "CloudDatacenterEnv", "name": "step"},
        {"id": "src.environment.CloudDatacenterEnv.state_dimension", "path": "src/environment.py", "kind": "method", "class_name": "CloudDatacenterEnv", "name": "state_dimension"},
        {"id": "src.environment.CloudDatacenterEnv.action_space_size", "path": "src/environment.py", "kind": "method", "class_name": "CloudDatacenterEnv", "name": "action_space_size"},
        {"id": "src.agent.ActorNetwork", "path": "src/agent.py", "kind": "class", "name": "ActorNetwork"},
        {"id": "src.agent.ActorNetwork.__init__", "path": "src/agent.py", "kind": "method", "class_name": "ActorNetwork", "name": "__init__"},
        {"id": "src.agent.ActorNetwork.forward", "path": "src/agent.py", "kind": "method", "class_name": "ActorNetwork", "name": "forward"},
        {"id": "src.agent.CriticNetwork", "path": "src/agent.py", "kind": "class", "name": "CriticNetwork"},
        {"id": "src.agent.CriticNetwork.__init__", "path": "src/agent.py", "kind": "method", "class_name": "CriticNetwork", "name": "__init__"},
        {"id": "src.agent.CriticNetwork.forward", "path": "src/agent.py", "kind": "method", "class_name": "CriticNetwork", "name": "forward"},
        {
            "id": "src.agent.A3CAgent",
            "path": "src/agent.py",
            "kind": "class",
            "name": "A3CAgent",
            "depends_on": ["src.agent.ActorNetwork", "src.agent.CriticNetwork"],
        },
        {"id": "src.agent.A3CAgent.__init__", "path": "src/agent.py", "kind": "method", "class_name": "A3CAgent", "name": "__init__", "depends_on": ["src.agent.ActorNetwork", "src.agent.CriticNetwork"]},
        {"id": "src.agent.A3CAgent.select_action", "path": "src/agent.py", "kind": "method", "class_name": "A3CAgent", "name": "select_action"},
        {"id": "src.agent.A3CAgent.store_transition", "path": "src/agent.py", "kind": "method", "class_name": "A3CAgent", "name": "store_transition"},
        {"id": "src.agent.A3CAgent.train_step", "path": "src/agent.py", "kind": "method", "class_name": "A3CAgent", "name": "train_step"},
        {"id": "src.agent.A3CAgent.save", "path": "src/agent.py", "kind": "method", "class_name": "A3CAgent", "name": "save"},
        {
            "id": "src.train.train_a3c_smoke",
            "path": "src/train.py",
            "kind": "function",
            "name": "train_a3c_smoke",
            "depends_on": ["src.environment.CloudDatacenterEnv", "src.agent.A3CAgent"],
            "imports": [
                {"from": "src.environment", "import": "CloudDatacenterEnv"},
                {"from": "src.agent", "import": "A3CAgent"},
            ],
        },
        {
            "id": "src.experiment.run_experiment",
            "path": "src/experiment.py",
            "kind": "function",
            "name": "run_experiment",
            "depends_on": ["src.train.train_a3c_smoke"],
            "imports": [{"from": "src.train", "import": "train_a3c_smoke"}],
        },
    ]


FRAMEWORK_BUILDERS = {
    "rl_resource_allocation_actor_critic": _rl_resource_allocation_actor_critic_framework,
}


def _merge_files(priority_files: list[dict], value: object) -> list[dict]:
    result = []
    seen = set()
    for item in [*priority_files, *_as_list(value)]:
        if not isinstance(item, dict):
            continue
        path = _as_text(item.get("path"))
        if not path or path in seen:
            continue
        result.append(item)
        seen.add(path)
    return result


def _merge_contracts(priority_contracts: list[dict], value: object) -> list[dict]:
    contracts_by_path = {}
    for item in _as_list(value):
        if isinstance(item, dict) and item.get("path"):
            contracts_by_path[item["path"]] = item
    for item in priority_contracts:
        contracts_by_path[item["path"]] = item
    return list(contracts_by_path.values())


def _merge_symbols(priority_symbols: list[dict], value: object) -> list[dict]:
    symbols_by_id = {}
    for item in _as_list(value):
        if isinstance(item, dict) and item.get("id"):
            symbols_by_id[item["id"]] = item
    for item in priority_symbols:
        symbols_by_id[item["id"]] = item
    return list(symbols_by_id.values())


def _merge_dict(priority: object, value: object) -> dict:
    result = priority if isinstance(priority, dict) else {}
    result = dict(result)
    if isinstance(value, dict):
        result.update(value)
    return result


def _merge_list(value: object, priority: object) -> list:
    result = []
    seen = set()
    for item in [*_as_list(value), *_as_list(priority)]:
        marker = repr(item)
        if marker in seen:
            continue
        result.append(item)
        seen.add(marker)
    return result


def _text_from_nested(source: dict, section: str, key: str) -> str:
    value = source.get(section)
    if isinstance(value, dict):
        return _as_text(value.get(key))
    return ""


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
