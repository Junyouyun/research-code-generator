from app.core.database import get_project, list_project_memories, upsert_project_memory
from app.core.models import MemoryItem


def record_project_memory(
    project_id: str,
    memory_type: str,
    content: str,
    normalized_key: str,
    importance: float = 0.6,
    confidence: float = 0.8,
    source_type: str = "pipeline",
    source_id: str | None = None,
    evidence: dict | None = None,
) -> MemoryItem | None:
    project = get_project(project_id)
    if project is None or not content.strip():
        return None

    return upsert_project_memory(
        project_id=project_id,
        user_id=project.user_id,
        memory_type=memory_type,
        content=content.strip(),
        normalized_key=normalized_key,
        importance=importance,
        confidence=confidence,
        source_type=source_type,
        source_id=source_id,
        evidence=evidence,
    )


def record_analysis_memory(project_id: str, analysis: dict) -> None:
    final_summary = analysis.get("final_summary") if isinstance(analysis.get("final_summary"), dict) else {}
    title = _first_text(final_summary.get("title"), analysis.get("title"))
    research_problem = _first_text(final_summary.get("research_problem"), analysis.get("research_problem"))
    method = _first_text(final_summary.get("method_overview"), analysis.get("method_summary"))
    experiment = _first_text(
        final_summary.get("experiment_or_argument_summary"),
        analysis.get("experiment_summary"),
    )
    code_relevance = _first_text(final_summary.get("code_relevance"), analysis.get("code_relevance"))

    if title:
        record_project_memory(
            project_id,
            "paper_fact",
            f"Paper title: {title}",
            "paper:title",
            importance=0.85,
            confidence=0.9,
            source_id="analysis",
        )
    if research_problem:
        record_project_memory(
            project_id,
            "paper_fact",
            f"Research problem: {research_problem}",
            "paper:research_problem",
            importance=0.8,
            confidence=0.85,
            source_id="analysis",
        )
    if method:
        record_project_memory(
            project_id,
            "paper_fact",
            f"Method overview: {method}",
            "paper:method",
            importance=0.8,
            confidence=0.85,
            source_id="analysis",
        )
    if experiment:
        record_project_memory(
            project_id,
            "paper_fact",
            f"Experiment or argument summary: {experiment}",
            "paper:experiment",
            importance=0.75,
            confidence=0.8,
            source_id="analysis",
        )
    if code_relevance:
        record_project_memory(
            project_id,
            "code_generation_decision",
            f"Code relevance: {code_relevance}",
            "code:relevance",
            importance=0.75,
            confidence=0.8,
            source_id="analysis",
        )


def record_experiment_spec_memory(project_id: str, experiment_spec: dict) -> None:
    experiment_type = _text(experiment_spec.get("experiment_type"))
    project_type = _text(experiment_spec.get("project_type"))
    domain = _text(experiment_spec.get("domain"))
    task = _text(experiment_spec.get("task"))
    algorithm = experiment_spec.get("algorithm") if isinstance(experiment_spec.get("algorithm"), dict) else {}
    environment = experiment_spec.get("environment") if isinstance(experiment_spec.get("environment"), dict) else {}
    smoke = experiment_spec.get("smoke_validation") if isinstance(experiment_spec.get("smoke_validation"), dict) else {}

    if experiment_type or project_type:
        record_project_memory(
            project_id,
            "experiment_decision",
            f"Experiment type: {experiment_type or 'unknown'}; project type: {project_type or 'unknown'}; domain: {domain or 'unknown'}; task: {task or 'unknown'}.",
            "experiment:type",
            importance=0.95,
            confidence=_confidence_value(experiment_spec.get("confidence")),
            source_id="experiment_spec",
            evidence={"experiment_type": experiment_type, "project_type": project_type},
        )

    algorithm_text = _compact_object(algorithm)
    if algorithm_text:
        record_project_memory(
            project_id,
            "experiment_decision",
            f"Algorithm extracted for reproduction: {algorithm_text}",
            "experiment:algorithm",
            importance=0.85,
            confidence=0.8,
            source_id="experiment_spec",
        )

    environment_text = _compact_object(environment)
    if environment_text:
        record_project_memory(
            project_id,
            "experiment_decision",
            f"Environment extracted for reproduction: {environment_text}",
            "experiment:environment",
            importance=0.85,
            confidence=0.8,
            source_id="experiment_spec",
        )

    if smoke:
        record_project_memory(
            project_id,
            "validation_decision",
            f"Smoke validation target: episodes={smoke.get('episodes')}, steps_per_episode={smoke.get('steps_per_episode')}, expected_trace_fields={smoke.get('expected_trace_fields')}.",
            "validation:smoke",
            importance=0.8,
            confidence=0.85,
            source_id="experiment_spec",
        )


def record_code_plan_memory(project_id: str, code_plan: dict) -> None:
    project_type = _text(code_plan.get("project_type"))
    framework = _text(code_plan.get("framework"))
    entry_file = _text(code_plan.get("entry_file"))
    language = _text(code_plan.get("language"))
    files = code_plan.get("files") if isinstance(code_plan.get("files"), list) else []
    file_paths = [_text(item.get("path")) for item in files if isinstance(item, dict)]
    file_paths = [path for path in file_paths if path][:12]

    record_project_memory(
        project_id,
        "code_generation_decision",
        f"Generated code plan: language={language or 'unknown'}, project_type={project_type or 'unknown'}, framework={framework or 'unknown'}, entry_file={entry_file or 'main.py'}, files={file_paths}.",
        "code:plan",
        importance=0.9,
        confidence=0.85,
        source_id="code_spec",
        evidence={"files": file_paths},
    )


def record_validation_memory(project_id: str, validation_result: dict) -> None:
    success = bool(validation_result.get("success"))
    message = _text(validation_result.get("message"))
    repairs = validation_result.get("repairs") if isinstance(validation_result.get("repairs"), list) else []

    record_project_memory(
        project_id,
        "validation_decision",
        f"Generated code validation {'passed' if success else 'failed'}: {message or 'no message'}; repair_attempts={len(repairs)}.",
        "validation:result",
        importance=0.8,
        confidence=0.9,
        source_id="code_validation",
        evidence={"success": success, "repair_attempts": len(repairs)},
    )


def get_project_memory_context(project_id: str, user_id: str, limit: int = 12) -> list[dict]:
    memories = list_project_memories(project_id, user_id, limit=limit)
    return [
        {
            "memory_id": memory.memory_id,
            "memory_type": memory.memory_type,
            "content": memory.content,
            "importance": memory.importance,
            "confidence": memory.confidence,
        }
        for memory in memories
    ]


def _first_text(*values: object) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _compact_object(value: dict) -> str:
    parts = []
    for key, item in value.items():
        text = _text(item)
        if text:
            parts.append(f"{key}={text}")
    return "; ".join(parts)[:1200]


def _confidence_value(value: object) -> float:
    text = _text(value).lower()
    if text == "high":
        return 0.9
    if text == "medium":
        return 0.75
    if text == "low":
        return 0.55
    return 0.75
