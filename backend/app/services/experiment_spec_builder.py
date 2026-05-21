import json
import re

from app.llm.client import chat_completion


MAX_EXPERIMENT_SPEC_CHUNKS = 16
MAX_EXPERIMENT_CHUNK_CHARS = 1400


EXPERIMENT_TYPE_RULES = [
    {
        "experiment_type": "rl_resource_allocation_actor_critic",
        "project_type": "rl",
        "prompt": (
            "Use experiment_type rl_resource_allocation_actor_critic only when the paper is about "
            "Actor-Critic/A2C/A3C style reinforcement learning for resource allocation, scheduling, "
            "task offloading, or communication/computing resource management."
        ),
        "keyword_groups": [
            ["actor-critic", "actor critic", "a3c", "a2c", "advantage actor"],
            [
                "resource allocation",
                "resource management",
                "scheduling",
                "offloading",
                "datacenter",
                "data center",
                "cloud",
                "edge",
                "wireless",
                "vehicular",
            ],
        ],
    },
]


def build_experiment_spec(analysis: dict, chunks: list[dict] | None = None) -> dict:
    """Build a paper-specific experiment definition before code planning."""
    relevant_chunks = _select_experiment_chunks(chunks or [], MAX_EXPERIMENT_SPEC_CHUNKS)
    messages = [
        {
            "role": "system",
            "content": (
                "You are an experiment reproduction architect. Convert a paper analysis into one "
                "concrete experiment_spec for runnable research-code generation. Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "Build experiment_spec JSON. It must describe what kind of experiment the generated "
                "code should run, not the final source files.\n"
                "Required fields: experiment_type, project_type, domain, task, algorithm, environment, "
                "data, training, evaluation, smoke_validation, evidence_chunks, assumptions, "
                "missing_details, confidence.\n"
                "project_type must be one of: rl, ml, simulation, optimization, analysis.\n"
                f"{_experiment_type_prompt_text()}\n"
                "For RL papers, explicitly extract state, action, reward, transition/dynamics, agent, "
                "training loop, and minimal smoke run requirements.\n"
                "For missing paper details, put practical defaults in assumptions and missing_details; "
                "do not invent unsupported claims.\n"
                "smoke_validation should include episodes, steps_per_episode, must_complete_steps, "
                "must_use_environment, must_use_agent, and expected_trace_fields.\n\n"
                f"analysis:\n{json.dumps(_compact_analysis(analysis), ensure_ascii=False)}\n\n"
                f"relevant_chunks:\n{json.dumps(relevant_chunks, ensure_ascii=False)}"
            ),
        },
    ]
    try:
        raw_spec = _chat_json(messages, max_tokens=3600)
    except Exception:
        raw_spec = _fallback_experiment_spec(analysis, relevant_chunks)
    return normalize_experiment_spec(raw_spec, analysis)


def normalize_experiment_spec(value: object, analysis: dict | None = None) -> dict:
    spec = value if isinstance(value, dict) else {}
    analysis = analysis or {}
    fallback = _fallback_experiment_spec(analysis, [])

    project_type = _normalize_project_type(spec.get("project_type")) or fallback["project_type"]
    experiment_type = _as_text(spec.get("experiment_type")) or fallback["experiment_type"]
    project_type = _project_type_for_experiment_type(experiment_type) or project_type

    smoke = spec.get("smoke_validation") if isinstance(spec.get("smoke_validation"), dict) else {}
    default_smoke = fallback["smoke_validation"]
    episodes = _safe_int(smoke.get("episodes"), default_smoke["episodes"], minimum=1, maximum=5)
    steps = _safe_int(smoke.get("steps_per_episode"), default_smoke["steps_per_episode"], minimum=1, maximum=20)

    normalized = {
        "experiment_type": experiment_type,
        "project_type": project_type,
        "domain": _as_text(spec.get("domain")) or fallback["domain"],
        "task": _as_text(spec.get("task")) or fallback["task"],
        "algorithm": _normalize_object(spec.get("algorithm"), fallback["algorithm"]),
        "environment": _normalize_object(spec.get("environment"), fallback["environment"]),
        "data": _normalize_object(spec.get("data"), fallback["data"]),
        "training": _normalize_object(spec.get("training"), fallback["training"]),
        "evaluation": _normalize_object(spec.get("evaluation"), fallback["evaluation"]),
        "smoke_validation": {
            "episodes": episodes,
            "steps_per_episode": steps,
            "must_complete_steps": _as_bool(smoke.get("must_complete_steps"), True),
            "must_use_environment": _as_bool(smoke.get("must_use_environment"), project_type in {"rl", "simulation"}),
            "must_use_agent": _as_bool(smoke.get("must_use_agent"), project_type == "rl"),
            "expected_trace_fields": _as_string_list(smoke.get("expected_trace_fields"))
            or default_smoke["expected_trace_fields"],
        },
        "evidence_chunks": _as_string_list(spec.get("evidence_chunks"))[:12],
        "assumptions": (_as_string_list(spec.get("assumptions")) or fallback["assumptions"])[:12],
        "missing_details": (_as_string_list(spec.get("missing_details")) or fallback["missing_details"])[:12],
        "confidence": _normalize_confidence(spec.get("confidence")),
    }
    return normalized


def _fallback_experiment_spec(analysis: dict, chunks: list[dict]) -> dict:
    text = json.dumps(_compact_analysis(analysis), ensure_ascii=False).lower()
    chunk_text = json.dumps(chunks, ensure_ascii=False).lower()
    combined = f"{text}\n{chunk_text}"

    project_type = _guess_project_type(combined)
    experiment_type = _guess_experiment_type(combined, project_type)
    domain = _guess_domain(combined)

    algorithm = {
        "family": "paper_method",
        "variant": "",
        "agent": "",
        "evidence": [],
    }
    environment = {
        "entities": [],
        "state": "",
        "action": "",
        "reward": "",
        "dynamics": "",
        "evidence": [],
    }
    data = {
        "primary": "",
        "fallback": "synthetic minimal data generated from config",
        "generation_strategy": "Use synthetic inputs with the same shape implied by the paper when real data is unavailable.",
        "evidence": [],
    }
    training = {
        "loop": "Run a short smoke loop using configurable episodes and steps.",
        "update_rule": "",
        "metrics": ["episodes_completed", "total_steps"],
    }
    evaluation = {
        "metrics": ["total_reward", "average_reward", "steps_completed"],
        "outputs": ["outputs/smoke_result.json"],
    }

    fallback_applier = EXPERIMENT_FALLBACK_APPLIERS.get(experiment_type)
    if fallback_applier:
        fallback_applier(combined, algorithm, environment, data, training)
    elif project_type == "rl":
        algorithm.update({"family": "reinforcement_learning", "variant": _guess_rl_variant(combined), "agent": "rl_agent"})
        environment.update(
            {
                "entities": ["environment", "agent"],
                "state": "paper-defined observation/state vector",
                "action": "paper-defined action choice",
                "reward": "paper-defined reward or objective signal",
                "dynamics": "paper-inspired transition or simulator step",
            }
        )

    return {
        "experiment_type": experiment_type,
        "project_type": project_type,
        "domain": domain,
        "task": _guess_task(combined, project_type),
        "algorithm": algorithm,
        "environment": environment,
        "data": data,
        "training": training,
        "evaluation": evaluation,
        "smoke_validation": {
            "episodes": 1,
            "steps_per_episode": 3,
            "must_complete_steps": True,
            "must_use_environment": project_type in {"rl", "simulation"},
            "must_use_agent": project_type == "rl",
            "expected_trace_fields": [
                "used_environment",
                "used_agent",
                "used_training_loop",
                "episodes_completed",
                "total_steps",
            ],
        },
        "evidence_chunks": [chunk.get("chunk_id", "") for chunk in chunks if chunk.get("chunk_id")][:8],
        "assumptions": ["Use a short smoke run to verify code structure, not full paper-quality results."],
        "missing_details": ["Full dataset paths, complete hyperparameters, and exact benchmark settings may be unavailable."],
        "confidence": "medium",
    }


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
            raise RuntimeError(f"model response is not JSON: {content[:500]}") from exc
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as nested_exc:
            raise RuntimeError(f"model response is not complete JSON: {content[:500]}") from nested_exc
    if not isinstance(data, dict):
        raise RuntimeError("model JSON response is not an object")
    return data


def _select_experiment_chunks(chunks: list[dict], limit: int) -> list[dict]:
    keywords = [
        "algorithm",
        "method",
        "actor",
        "critic",
        "a3c",
        "a2c",
        "reinforcement",
        "state",
        "action",
        "reward",
        "environment",
        "simulation",
        "experiment",
        "dataset",
        "trace",
        "resource",
        "allocation",
        "scheduling",
        "offloading",
        "energy",
        "qos",
        "算法",
        "方法",
        "状态",
        "动作",
        "奖励",
        "实验",
        "数据",
        "资源",
        "分配",
        "调度",
    ]
    keywords.extend(_experiment_rule_keywords())
    scored = []
    for index, chunk in enumerate(chunks):
        text = _chunk_text(chunk).lower()
        score = sum(2 if keyword in {"state", "action", "reward", "状态", "动作", "奖励"} else 1 for keyword in keywords if keyword.lower() in text)
        scored.append((score, -index, chunk))
    scored.sort(reverse=True)
    selected = [chunk for score, _, chunk in scored if score > 0][:limit]
    if len(selected) < min(limit, len(chunks)):
        selected.extend(chunks[: limit - len(selected)])
    return [_compact_chunk(chunk) for chunk in selected[:limit]]


def _compact_chunk(chunk: dict) -> dict:
    metadata = chunk.get("metadata", {}) if isinstance(chunk.get("metadata"), dict) else {}
    return {
        "chunk_id": chunk.get("chunk_id", ""),
        "title": chunk.get("title") or metadata.get("section_title", ""),
        "page_start": chunk.get("page_start"),
        "page_end": chunk.get("page_end"),
        "content": _short_text(chunk.get("content", ""), MAX_EXPERIMENT_CHUNK_CHARS),
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


def _guess_project_type(text: str) -> str:
    if any(keyword in text for keyword in ["reinforcement learning", "actor-critic", "actor critic", "a3c", "a2c", "dqn", "reward", "state", "action"]):
        return "rl"
    if any(keyword in text for keyword in ["simulation", "simulator", "monte carlo", "仿真"]):
        return "simulation"
    if any(keyword in text for keyword in ["optimization", "optimisation", "solver", "objective function", "constraint"]):
        return "optimization"
    if any(keyword in text for keyword in ["classification", "regression", "neural network", "deep learning", "dataset", "training"]):
        return "ml"
    return "analysis"


def _guess_experiment_type(text: str, project_type: str) -> str:
    for rule in EXPERIMENT_TYPE_RULES:
        rule_project_type = _as_text(rule.get("project_type"))
        if rule_project_type and rule_project_type != project_type:
            continue
        keyword_groups = rule.get("keyword_groups") if isinstance(rule.get("keyword_groups"), list) else []
        if keyword_groups and all(any(keyword in text for keyword in group) for group in keyword_groups):
            return _as_text(rule.get("experiment_type"))
    if project_type == "rl":
        return "rl_general"
    if project_type == "ml":
        return "ml_general"
    if project_type == "simulation":
        return "simulation_general"
    if project_type == "optimization":
        return "optimization_general"
    return "analysis_only"


def _guess_domain(text: str) -> str:
    domain_keywords = [
        ("cloud_datacenter", ["cloud datacenter", "cloud data center", "datacenter", "data center"]),
        ("edge_computing", ["edge computing", "mobile edge", "mec", "offloading"]),
        ("wireless_network", ["wireless", "spectrum", "channel", "v2v", "v2x", "vehicular"]),
        ("resource_allocation", ["resource allocation", "resource management", "scheduling"]),
    ]
    for domain, keywords in domain_keywords:
        if any(keyword in text for keyword in keywords):
            return domain
    return "paper_domain"


def _guess_task(text: str, project_type: str) -> str:
    if "resource allocation" in text:
        return "resource allocation"
    if "scheduling" in text:
        return "scheduling"
    if "offloading" in text:
        return "task offloading"
    if project_type == "rl":
        return "reinforcement learning experiment"
    if project_type == "ml":
        return "machine learning experiment"
    return "paper-inspired smoke experiment"


def _guess_actor_critic_variant(text: str) -> str:
    if "a3c" in text or "asynchronous advantage actor" in text:
        return "A3C"
    if "a2c" in text or "advantage actor" in text:
        return "A2C"
    return "Actor-Critic"


def _guess_rl_variant(text: str) -> str:
    if "dqn" in text:
        return "DQN"
    return _guess_actor_critic_variant(text) if "actor" in text and "critic" in text else "RL"


def _guess_dataset(text: str) -> str:
    if "google" in text and ("trace" in text or "cluster" in text or "datacenter" in text):
        return "Google cloud datacenter traces"
    if "trace" in text:
        return "paper-mentioned trace dataset"
    if "dataset" in text:
        return "paper-mentioned dataset"
    return ""


def _apply_actor_critic_resource_allocation_defaults(
    text: str,
    algorithm: dict,
    environment: dict,
    data: dict,
    training: dict,
) -> None:
    algorithm.update({"family": "actor_critic", "variant": _guess_actor_critic_variant(text), "agent": "actor_critic_agent"})
    environment.update(
        {
            "entities": ["resource_pool", "job_or_request", "scheduler_agent"],
            "state": "resource usage plus current job/request features",
            "action": "choose wait/reject or assign the current job/request to a resource",
            "reward": "combine service quality/resource efficiency objective with resource or energy cost",
            "dynamics": "advance one job/request per step and update resource availability",
        }
    )
    data.update(
        {
            "primary": _guess_dataset(text),
            "fallback": "synthetic resource-allocation trace with servers/resources, jobs, demands, and durations",
        }
    )
    training.update(
        {
            "loop": "Reset the environment, let the actor-critic agent select actions, collect rewards, and perform a small policy/value update.",
            "update_rule": "TD error / advantage update for actor and critic",
            "metrics": ["episodes_completed", "total_steps", "total_reward", "average_reward"],
        }
    )


EXPERIMENT_FALLBACK_APPLIERS = {
    "rl_resource_allocation_actor_critic": _apply_actor_critic_resource_allocation_defaults,
}


def registered_experiment_types() -> list[str]:
    return sorted(_as_text(rule.get("experiment_type")) for rule in EXPERIMENT_TYPE_RULES if rule.get("experiment_type"))


def _experiment_type_prompt_text() -> str:
    prompts = [_as_text(rule.get("prompt")) for rule in EXPERIMENT_TYPE_RULES]
    return "\n".join(prompt for prompt in prompts if prompt)


def _project_type_for_experiment_type(experiment_type: str) -> str:
    for rule in EXPERIMENT_TYPE_RULES:
        if rule.get("experiment_type") == experiment_type:
            return _as_text(rule.get("project_type"))
    return ""


def _experiment_rule_keywords() -> list[str]:
    keywords = []
    for rule in EXPERIMENT_TYPE_RULES:
        for group in rule.get("keyword_groups", []):
            keywords.extend(group)
    return keywords


def _normalize_project_type(value: object) -> str:
    text = _as_text(value).lower().replace("-", "_")
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


def _normalize_object(value: object, fallback: dict) -> dict:
    source = value if isinstance(value, dict) else {}
    result = dict(fallback)
    for key, item in source.items():
        if isinstance(item, (dict, list)):
            result[key] = item
        else:
            text = _as_text(item)
            if text:
                result[key] = text
    return result


def _normalize_confidence(value: object) -> str:
    text = _as_text(value).lower()
    return text if text in {"low", "medium", "high"} else "medium"


def _safe_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "yes", "1"}:
            return True
        if text in {"false", "no", "0"}:
            return False
    return default


def _chunk_text(chunk: dict) -> str:
    metadata = chunk.get("metadata", {}) if isinstance(chunk.get("metadata"), dict) else {}
    return " ".join(
        [
            _as_text(chunk.get("title")),
            _as_text(metadata.get("section_title")),
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
