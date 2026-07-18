import hashlib
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app.config import DEFAULT_LLM_MODEL, TRACE_DIR
from app.core.database import save_codegen_trace, save_qa_trace
from app.core.models import CodegenTrace, Project, QATrace


def new_trace_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def record_qa_trace(
    trace_id: str,
    project: Project,
    user_id: str,
    conversation_id: str,
    question: str,
    qa_context: dict,
    answer_result: dict | None,
    latency_ms: int | None = None,
    status: str = "succeeded",
    error_message: str | None = None,
) -> QATrace:
    trace_dir = TRACE_DIR / "qa" / trace_id
    trace_dir.mkdir(parents=True, exist_ok=True)

    chunks = _compact_chunks(qa_context.get("current_paper_chunks", []))
    graph_context = qa_context.get("graph_context") or {}
    graph_source_chunk_ids = _graph_source_chunk_ids(graph_context)
    prompt_snapshot = {
        "question": question,
        "conversation_context": qa_context.get("conversation_context", []),
        "project_memory_context": qa_context.get("project_memory_context", []),
        "user_memory_context": qa_context.get("user_memory_context", []),
        "graph_context": graph_context,
        "chunks": chunks,
        "related_papers": qa_context.get("related_papers", []),
    }
    prompt_hash = _stable_hash(prompt_snapshot)

    context_path = trace_dir / "context.json"
    prompt_path = trace_dir / "prompt_snapshot.json"
    response_path = trace_dir / "response.json"
    _write_json(context_path, {"qa_context": _compact_qa_context(qa_context)})
    _write_json(prompt_path, prompt_snapshot)
    _write_json(response_path, answer_result or {"error": error_message})

    trace = QATrace(
        trace_id=trace_id,
        user_id=user_id,
        project_id=project.project_id,
        paper_id=project.paper_id,
        paper_version_id=project.paper_version_id,
        conversation_id=conversation_id,
        question=question,
        rewritten_query=(qa_context.get("retrieval_trace") or {}).get("rewritten_query"),
        question_type=(qa_context.get("retrieval_trace") or {}).get("question_type"),
        retrieved_chunks=chunks,
        retrieval_scores=_retrieval_scores(qa_context.get("retrieval_trace") or {}),
        graph_context=graph_context,
        graph_source_chunk_ids=graph_source_chunk_ids,
        project_memory=qa_context.get("project_memory_context", []),
        user_memory=qa_context.get("user_memory_context", []),
        conversation_context=qa_context.get("conversation_context", []),
        retrieval_trace=qa_context.get("retrieval_trace", {}),
        final_prompt_hash=prompt_hash,
        final_prompt_path=str(prompt_path),
        context_snapshot_path=str(context_path),
        model_name=DEFAULT_LLM_MODEL,
        model_params={},
        answer=(answer_result or {}).get("answer"),
        latency_ms=latency_ms,
        status=status,
        error_message=error_message,
    )
    return save_qa_trace(trace)


def record_codegen_trace(
    trace_id: str,
    project: Project,
    trace_dir: Path,
    final_status: str,
    analysis: dict | None = None,
    chunks: list[dict] | None = None,
    graph_context: dict | None = None,
    experiment_spec: dict | None = None,
    code_plan: dict | None = None,
    generated_files: list[dict] | None = None,
    validation_result: dict | None = None,
    validation_error: str | None = None,
    started_at: float | None = None,
) -> CodegenTrace:
    trace_dir.mkdir(parents=True, exist_ok=True)
    analysis_path = trace_dir / "analysis.json"
    chunks_path = trace_dir / "retrieved_chunks.json"
    graph_path = trace_dir / "graph_context.json"
    spec_path = trace_dir / "experiment_spec.json"
    plan_path = trace_dir / "code_plan.json"
    files_path = trace_dir / "generated_files_manifest.json"
    validation_path = trace_dir / "validation_result.json"

    _write_json(analysis_path, analysis or {})
    _write_json(chunks_path, _compact_chunks(chunks or [], include_content=False))
    _write_json(graph_path, graph_context or {})
    _write_json(spec_path, experiment_spec or {})
    _write_json(plan_path, code_plan or {})
    _write_json(files_path, generated_files or [])
    _write_json(validation_path, validation_result or {"error": validation_error})

    commands = (validation_result or {}).get("commands") if isinstance(validation_result, dict) else []
    validation_command = ""
    if isinstance(commands, list) and commands:
        first = commands[0] if isinstance(commands[0], dict) else {}
        validation_command = str(first.get("command") or "")

    latency_ms = int((perf_counter() - started_at) * 1000) if started_at else None
    trace = CodegenTrace(
        trace_id=trace_id,
        user_id=project.user_id,
        project_id=project.project_id,
        paper_id=project.paper_id,
        paper_version_id=project.paper_version_id,
        trigger_message="project_pipeline",
        analysis_snapshot_path=str(analysis_path),
        retrieved_chunks_path=str(chunks_path),
        graph_context_path=str(graph_path),
        experiment_spec_path=str(spec_path),
        code_plan_path=str(plan_path),
        generated_files_path=str(files_path),
        validation_command=validation_command,
        validation_result=validation_result or {},
        validation_error=validation_error,
        repair_attempts=(validation_result or {}).get("repairs", []) if isinstance(validation_result, dict) else [],
        final_status=final_status,
        model_name=DEFAULT_LLM_MODEL,
        latency_ms=latency_ms,
    )
    return save_codegen_trace(trace)


def generated_files_manifest(code_dir: Path) -> list[dict]:
    if not code_dir.exists():
        return []
    files = []
    for path in sorted(code_dir.rglob("*")):
        if path.is_file():
            files.append(
                {
                    "path": str(path.relative_to(code_dir)).replace("\\", "/"),
                    "size": path.stat().st_size,
                }
            )
    return files


def _compact_qa_context(context: dict) -> dict:
    return {
        "conversation_context": context.get("conversation_context", []),
        "project_memory_context": context.get("project_memory_context", []),
        "user_memory_context": context.get("user_memory_context", []),
        "graph_context": context.get("graph_context", {}),
        "current_paper_chunks": _compact_chunks(context.get("current_paper_chunks", [])),
        "related_papers": context.get("related_papers", []),
        "retrieval_trace": context.get("retrieval_trace", {}),
    }


def _compact_chunks(chunks: list[dict], include_content: bool = True) -> list[dict]:
    compact = []
    for chunk in chunks:
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        item = {
            "chunk_id": chunk.get("chunk_id"),
            "title": chunk.get("title") or metadata.get("section_title"),
            "section_title": metadata.get("section_title") or chunk.get("section_title"),
            "page_start": metadata.get("page_start") or chunk.get("page_start"),
            "page_end": metadata.get("page_end") or chunk.get("page_end"),
            "order_index": metadata.get("order_index") or chunk.get("order_index"),
        }
        if include_content:
            item["content"] = str(chunk.get("content", ""))[:4000]
        compact.append(item)
    return compact


def _graph_source_chunk_ids(graph_context: dict) -> list[str]:
    ids = []
    for key in ("entities", "relations"):
        for item in graph_context.get(key, []) if isinstance(graph_context.get(key), list) else []:
            for chunk_id in item.get("source_chunk_ids", []) if isinstance(item, dict) else []:
                if chunk_id and chunk_id not in ids:
                    ids.append(chunk_id)
    return ids


def _retrieval_scores(retrieval_trace: dict) -> list[dict]:
    hits = retrieval_trace.get("current_hits")
    if isinstance(hits, list):
        return hits
    return [{"chunk_id": chunk_id} for chunk_id in retrieval_trace.get("current_chunk_ids", [])]


def _stable_hash(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
