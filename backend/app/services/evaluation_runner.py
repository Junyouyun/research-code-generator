from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from app.config import EVAL_REPORT_DIR, GENERATED_DIR
from app.core.database import get_project, list_document_chunks_by_ids
from app.services.code_runner import CodeValidationError, check_code
from app.services.context_orchestrator import build_qa_context
from app.services.knowledge_graph_store import get_project_graph
from app.services.llm_paper_analyzer import answer_question_with_chunks, answer_question_with_expanded_context
from app.services.vector_store import search_within_paper_multi_query

DEFAULT_RECALL_KS = [5, 10]
GENERIC_ENTITY_NAMES = {
    "paper",
    "method",
    "approach",
    "result",
    "results",
    "model",
    "algorithm",
    "experiment",
    "dataset",
    "metric",
    "task",
    "system",
    "framework",
    "proposed method",
    "proposed approach",
}


def run_evaluation(cases_path: Path, output_path: Path | None = None) -> dict:
    cases = load_eval_cases(cases_path)
    results = [evaluate_case(case) for case in cases]
    report = build_report(cases_path, results)

    if output_path is None:
        EVAL_REPORT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = EVAL_REPORT_DIR / "latest.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def load_eval_cases(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"eval cases path not found: {path}")

    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    cases: list[dict] = []
    for file in files:
        payload = json.loads(file.read_text(encoding="utf-8"))
        raw_cases = payload.get("cases", []) if isinstance(payload, dict) else payload
        if not isinstance(raw_cases, list):
            raise ValueError(f"eval cases must be a list: {file}")
        for index, case in enumerate(raw_cases):
            if not isinstance(case, dict):
                raise ValueError(f"eval case must be an object: {file}#{index}")
            cases.append({**case, "_source_file": str(file)})
    return cases


def evaluate_case(case: dict) -> dict:
    case_type = str(case.get("case_type") or "").strip().lower()
    try:
        if case_type == "retrieval":
            result = evaluate_retrieval_case(case)
        elif case_type == "graph":
            result = evaluate_graph_case(case)
        elif case_type == "qa":
            result = evaluate_qa_case(case)
        elif case_type == "codegen":
            result = evaluate_codegen_case(case)
        else:
            raise ValueError(f"unsupported case_type: {case_type}")
        return {**_case_base(case), **result}
    except Exception as exc:
        return {
            **_case_base(case),
            "passed": False,
            "error": str(exc),
            "metrics": {},
            "details": {},
        }


def evaluate_retrieval_case(case: dict) -> dict:
    project = _project_for_case(case)
    paper_version_id = str(case.get("paper_version_id") or project.paper_version_id or "")
    if not paper_version_id:
        raise ValueError("retrieval case requires paper_version_id or project.paper_version_id")

    question = _required_text(case, "question")
    top_k = int(case.get("top_k") or max(DEFAULT_RECALL_KS))
    recall_ks = _int_list(case.get("recall_ks")) or DEFAULT_RECALL_KS
    gold_chunk_ids = set(_string_list(case.get("gold_chunk_ids")))
    negative_chunk_ids = set(_string_list(case.get("negative_chunk_ids")))
    if not gold_chunk_ids:
        raise ValueError("retrieval case requires gold_chunk_ids")

    retrieval = search_within_paper_multi_query(
        paper_version_id=paper_version_id,
        question=question,
        top_k=max(top_k, max(recall_ks)),
        per_query_k=int(case.get("per_query_k") or 12),
        user_id=str(case.get("user_id") or project.user_id),
    )
    hits = retrieval["hits"]
    returned_ids = [str(hit.get("chunk_id")) for hit in hits if hit.get("chunk_id")]
    metrics = _retrieval_metrics(returned_ids, gold_chunk_ids, recall_ks)
    negative_hits_by_k = _negative_hits_by_k(returned_ids, negative_chunk_ids, recall_ks)
    for k, hits_at_k in negative_hits_by_k.items():
        metrics[f"negative_hit_count@{k}"] = len(hits_at_k)
    return {
        "passed": bool(metrics.get(f"recall@{max(recall_ks)}")),
        "metrics": metrics,
        "details": {
            "returned_chunk_ids": returned_ids,
            "gold_chunk_ids": sorted(gold_chunk_ids),
            "negative_chunk_ids": sorted(negative_chunk_ids),
            "negative_hits": {str(k): hits for k, hits in negative_hits_by_k.items()},
            "retrieval_mode": retrieval.get("retrieval_mode", "multi_query_dense"),
            "rerank_mode": retrieval.get("rerank_mode"),
            "intent": retrieval.get("intent"),
            "rewritten_queries": retrieval.get("expanded_queries", []),
            "query_results": retrieval.get("query_results", []),
            "keyword_results": retrieval.get("keyword_results", []),
            "hits": _compact_hits(hits),
        },
    }


def evaluate_graph_case(case: dict) -> dict:
    project = _project_for_case(case)
    graph = get_project_graph(project)
    entities = graph.get("entities", [])
    relations = graph.get("relations", [])

    expected_entities = case.get("expected_entities") if isinstance(case.get("expected_entities"), list) else []
    expected_relations = case.get("expected_relations") if isinstance(case.get("expected_relations"), list) else []
    max_generic_ratio = float(case.get("max_generic_entity_ratio", 0.25))
    require_source_chunks = bool(case.get("require_source_chunks", True))

    entity_matches = _match_expected_entities(expected_entities, entities)
    relation_matches = _match_expected_relations(expected_relations, relations)
    generic_ratio = _generic_entity_ratio(entities)
    source_coverage = _source_chunk_coverage(entities, relations)

    passed = (
        entity_matches["recall"] >= float(case.get("min_entity_recall", 1.0))
        and relation_matches["recall"] >= float(case.get("min_relation_recall", 1.0))
        and generic_ratio <= max_generic_ratio
        and (source_coverage >= 1.0 if require_source_chunks else True)
    )
    return {
        "passed": passed,
        "metrics": {
            "entity_recall": entity_matches["recall"],
            "relation_recall": relation_matches["recall"],
            "generic_entity_ratio": generic_ratio,
            "source_chunk_coverage": source_coverage,
        },
        "details": {
            "missing_entities": entity_matches["missing"],
            "missing_relations": relation_matches["missing"],
            "entity_count": len(entities),
            "relation_count": len(relations),
        },
    }


def evaluate_qa_case(case: dict) -> dict:
    project = _project_for_case(case)
    question = _required_text(case, "question")
    qa_context = build_qa_context(
        project=project,
        user_id=str(case.get("user_id") or project.user_id),
        conversation_id=str(case.get("conversation_id") or ""),
        question=question,
    )
    retrieval_trace = qa_context["retrieval_trace"]
    expanded = bool(retrieval_trace["expanded"])
    if expanded:
        result = answer_question_with_expanded_context(
            question,
            qa_context["current_paper_chunks"],
            qa_context["related_papers"],
            conversation_context=qa_context["conversation_context"],
            project_memory_context=qa_context["project_memory_context"],
            user_memory_context=qa_context["user_memory_context"],
            graph_context=qa_context["graph_context"],
        )
    else:
        result = answer_question_with_chunks(
            question,
            qa_context["current_paper_chunks"],
            conversation_context=qa_context["conversation_context"],
            project_memory_context=qa_context["project_memory_context"],
            user_memory_context=qa_context["user_memory_context"],
            graph_context=qa_context["graph_context"],
        )

    answer = str(result.get("answer") or "")
    expected_points = _string_list(case.get("expected_answer_points"))
    required_chunks = set(_string_list(case.get("gold_chunk_ids") or case.get("must_cite_chunks")))
    used_chunks = set(_string_list(result.get("used_chunks")))
    point_hits = [point for point in expected_points if point.lower() in answer.lower()]
    evidence_hit = not required_chunks or bool(required_chunks.intersection(used_chunks))
    passed = len(point_hits) == len(expected_points) and evidence_hit
    return {
        "passed": passed,
        "metrics": {
            "expected_point_recall": len(point_hits) / len(expected_points) if expected_points else 1.0,
            "evidence_hit": 1.0 if evidence_hit else 0.0,
        },
        "details": {
            "answer": answer,
            "used_chunks": sorted(used_chunks),
            "missing_answer_points": [point for point in expected_points if point not in point_hits],
            "required_chunks": sorted(required_chunks),
        },
    }


def evaluate_codegen_case(case: dict) -> dict:
    project = _project_for_case(case) if case.get("project_id") else None
    code_dir_value = str(case.get("code_dir") or "").strip()
    code_dir = Path(code_dir_value) if code_dir_value else None
    if code_dir is None and project:
        code_dir = GENERATED_DIR / project.project_id / "code"
    if code_dir is None:
        raise ValueError("codegen case requires code_dir or project_id")

    run_smoke = bool(case.get("run_smoke", True))
    validation_result: dict[str, Any] = {}
    validation_passed = True
    if run_smoke:
        try:
            validation_result = check_code(code_dir)
        except CodeValidationError as exc:
            validation_result = exc.result
            validation_passed = False

    expected_contracts = case.get("expected_contracts") if isinstance(case.get("expected_contracts"), list) else []
    contract_result = _check_expected_contracts(code_dir, expected_contracts)
    expected_semantics = case.get("expected_semantics") if isinstance(case.get("expected_semantics"), list) else []
    semantic_result = _check_semantic_text(code_dir, expected_semantics)

    passed = validation_passed and contract_result["passed"] and semantic_result["passed"]
    return {
        "passed": passed,
        "metrics": {
            "validation_passed": 1.0 if validation_passed else 0.0,
            "contract_passed": 1.0 if contract_result["passed"] else 0.0,
            "semantic_passed": 1.0 if semantic_result["passed"] else 0.0,
        },
        "details": {
            "code_dir": str(code_dir),
            "validation_result": validation_result,
            "contract": contract_result,
            "semantic": semantic_result,
        },
    }


def build_report(cases_path: Path, results: list[dict]) -> dict:
    by_type: dict[str, list[dict]] = {}
    for result in results:
        by_type.setdefault(result["case_type"], []).append(result)

    summary = {}
    for case_type, typed_results in by_type.items():
        summary[case_type] = {
            "total": len(typed_results),
            "passed": sum(1 for item in typed_results if item["passed"]),
            "pass_rate": _safe_mean([1.0 if item["passed"] else 0.0 for item in typed_results]),
        }

    gate_passed = all(item["passed"] for item in results) if results else False
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cases_path": str(cases_path),
        "total": len(results),
        "passed": sum(1 for item in results if item["passed"]),
        "gate_passed": gate_passed,
        "summary": summary,
        "results": results,
    }


def _retrieval_metrics(returned_ids: list[str], gold_ids: set[str], recall_ks: list[int]) -> dict:
    metrics = {}
    for k in recall_ks:
        metrics[f"recall@{k}"] = 1.0 if gold_ids.intersection(returned_ids[:k]) else 0.0
    reciprocal_rank = 0.0
    for index, chunk_id in enumerate(returned_ids, start=1):
        if chunk_id in gold_ids:
            reciprocal_rank = 1.0 / index
            break
    metrics["mrr"] = reciprocal_rank
    return metrics


def _negative_hits_by_k(returned_ids: list[str], negative_ids: set[str], recall_ks: list[int]) -> dict[int, list[str]]:
    if not negative_ids:
        return {k: [] for k in recall_ks}
    return {k: [chunk_id for chunk_id in returned_ids[:k] if chunk_id in negative_ids] for k in recall_ks}


def _match_expected_entities(expected: list[dict], actual: list[dict]) -> dict:
    missing = []
    for item in expected:
        name = _norm(item.get("name"))
        entity_type = _norm(item.get("type") or item.get("entity_type"))
        matched = any(
            name in _norm(entity.get("name"))
            and (not entity_type or entity_type == _norm(entity.get("entity_type")))
            for entity in actual
        )
        if not matched:
            missing.append(item)
    return {"missing": missing, "recall": 1.0 - (len(missing) / len(expected)) if expected else 1.0}


def _match_expected_relations(expected: list[dict], actual: list[dict]) -> dict:
    missing = []
    for item in expected:
        source = _norm(item.get("source"))
        target = _norm(item.get("target"))
        relation_type = _norm(item.get("relation") or item.get("relation_type"))
        matched = any(
            source in _norm(relation.get("source_name"))
            and target in _norm(relation.get("target_name"))
            and (not relation_type or relation_type == _norm(relation.get("relation_type")))
            for relation in actual
        )
        if not matched:
            missing.append(item)
    return {"missing": missing, "recall": 1.0 - (len(missing) / len(expected)) if expected else 1.0}


def _generic_entity_ratio(entities: list[dict]) -> float:
    if not entities:
        return 0.0
    generic_count = sum(1 for entity in entities if _norm(entity.get("name")) in GENERIC_ENTITY_NAMES)
    return generic_count / len(entities)


def _source_chunk_coverage(entities: list[dict], relations: list[dict]) -> float:
    items = entities + relations
    if not items:
        return 1.0
    covered = sum(1 for item in items if item.get("source_chunk_ids"))
    return covered / len(items)


def _check_expected_contracts(code_dir: Path, contracts: list[dict]) -> dict:
    missing = []
    for contract in contracts:
        path = code_dir / str(contract.get("path", ""))
        if not path.exists():
            missing.append({"path": contract.get("path"), "reason": "missing_file"})
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for exported in _string_list(contract.get("exports")):
            if f"def {exported}" not in content and f"class {exported}" not in content:
                missing.append({"path": contract.get("path"), "export": exported, "reason": "missing_export"})
    return {"passed": not missing, "missing": missing}


def _check_semantic_text(code_dir: Path, expected_items: list[str]) -> dict:
    if not expected_items:
        return {"passed": True, "missing": []}
    combined = []
    for path in code_dir.rglob("*.py"):
        combined.append(path.read_text(encoding="utf-8", errors="ignore").lower())
    text = "\n".join(combined)
    missing = [item for item in expected_items if str(item).lower() not in text]
    return {"passed": not missing, "missing": missing}


def _project_for_case(case: dict):
    project_id = str(case.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("case requires project_id")
    project = get_project(project_id)
    if project is None:
        raise ValueError(f"project not found: {project_id}")
    return project


def _case_base(case: dict) -> dict:
    return {
        "case_id": str(case.get("case_id") or ""),
        "case_type": str(case.get("case_type") or "").strip().lower(),
        "project_id": case.get("project_id"),
        "source_file": case.get("_source_file"),
    }


def _compact_hits(hits: list[dict]) -> list[dict]:
    return [
        {
            "chunk_id": hit.get("chunk_id"),
            "score": hit.get("score"),
            "section_title": hit.get("section_title"),
            "page_start": hit.get("page_start"),
            "page_end": hit.get("page_end"),
            "best_vector_score": hit.get("best_vector_score"),
            "source_queries": hit.get("source_queries", []),
            "keyword_score": hit.get("keyword_score"),
            "keyword_source_queries": hit.get("keyword_source_queries", []),
            "retrieval_sources": hit.get("retrieval_sources", []),
            "rerank_score": hit.get("rerank_score"),
            "score_breakdown": hit.get("score_breakdown", {}),
        }
        for hit in hits
    ]


def _required_text(case: dict, key: str) -> str:
    value = str(case.get(key) or "").strip()
    if not value:
        raise ValueError(f"case requires {key}")
    return value


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _int_list(value: object) -> list[int]:
    result = []
    for item in _string_list(value):
        try:
            result.append(int(item))
        except ValueError:
            continue
    return result


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _safe_mean(values: list[float]) -> float:
    return mean(values) if values else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run unified Research Code evaluation gate.")
    parser.add_argument("--cases", required=True, help="JSON file or directory containing eval cases.")
    parser.add_argument("--output", default="", help="Output JSON report path.")
    parser.add_argument("--fail-on-gate", action="store_true", help="Exit 1 when any case fails.")
    args = parser.parse_args()

    report = run_evaluation(
        cases_path=Path(args.cases),
        output_path=Path(args.output) if args.output else None,
    )
    print(json.dumps({k: report[k] for k in ("total", "passed", "gate_passed", "summary")}, ensure_ascii=False, indent=2))
    if args.fail_on_gate and not report["gate_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
