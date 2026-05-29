import json
import re

from app.llm.client import chat_completion


ALLOWED_ENTITY_TYPES = {
    "paper",
    "method",
    "algorithm",
    "model",
    "module",
    "environment",
    "state",
    "action",
    "reward",
    "dataset",
    "metric",
    "objective",
    "baseline",
    "experiment",
    "result",
    "assumption",
    "limitation",
    "code_module",
    "training_step",
    "evaluation_protocol",
}

ALLOWED_RELATION_TYPES = {
    "proposes",
    "uses",
    "contains",
    "depends_on",
    "optimizes",
    "evaluates",
    "evaluated_on",
    "compares_with",
    "outperforms",
    "reports_metric",
    "defines_state",
    "defines_action",
    "defines_reward",
    "has_component",
    "implemented_by",
    "requires_data",
    "produces_output",
    "has_limitation",
    "trained_with",
    "measured_by",
}

PRIORITY_SECTION_KEYWORDS = {
    "abstract",
    "introduction",
    "method",
    "methodology",
    "algorithm",
    "model",
    "experiment",
    "evaluation",
    "result",
    "conclusion",
    "摘要",
    "引言",
    "方法",
    "算法",
    "模型",
    "实验",
    "评估",
    "结果",
    "结论",
}

PREFERRED_ELEMENT_TYPES = {"paragraph", "table", "formula"}
GENERIC_ENTITY_NAMES = {
    "paper",
    "method",
    "methods",
    "result",
    "results",
    "experiment",
    "experiments",
    "model",
    "algorithm",
    "approach",
    "proposed method",
    "this paper",
    "the paper",
}


def build_project_knowledge_graph(
    project_id: str,
    analysis: dict,
    chunks: list[dict],
) -> dict:
    selected_chunks = _select_graph_chunks(chunks)
    if not selected_chunks:
        return {"entities": [], "relations": [], "selected_chunk_ids": []}

    raw_graph = _extract_graph_with_llm(project_id, analysis, selected_chunks)
    graph = _normalize_graph(raw_graph, selected_chunks)
    graph["selected_chunk_ids"] = [chunk.get("chunk_id", "") for chunk in selected_chunks if chunk.get("chunk_id")]
    return graph


def _extract_graph_with_llm(project_id: str, analysis: dict, chunks: list[dict]) -> dict:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a research-paper knowledge graph extraction agent.\n"
                "Extract only entities and relations useful for technical QA, experiment reproduction, or runnable code generation.\n"
                "Use only the allowed entity_type and relation_type values.\n"
                "Every relation source and target must refer to an extracted entity name.\n"
                "Every entity and relation should include source_chunk_ids from the provided chunks.\n"
                "If evidence is weak, lower confidence instead of inventing details.\n"
                "Return one valid JSON object only."
            ),
        },
        {
            "role": "user",
            "content": (
                "Extract a compact knowledge graph from this paper material.\n\n"
                "Return JSON with exactly these top-level fields: entities, relations.\n"
                "Entity object fields: name, entity_type, description, importance, confidence, source_chunk_ids, evidence.\n"
                "Relation object fields: source, relation_type, target, description, confidence, source_chunk_ids, evidence.\n\n"
                f"project_id: {project_id}\n"
                f"allowed_entity_types: {sorted(ALLOWED_ENTITY_TYPES)}\n"
                f"allowed_relation_types: {sorted(ALLOWED_RELATION_TYPES)}\n\n"
                f"paper_analysis:\n{json.dumps(_compact_analysis(analysis), ensure_ascii=False)}\n\n"
                f"chunks:\n{json.dumps(_compact_chunks(chunks), ensure_ascii=False)}"
            ),
        },
    ]
    content = chat_completion(
        messages,
        temperature=0.1,
        max_tokens=3600,
        response_format={"type": "json_object"},
    )
    return _loads_json(content)


def _select_graph_chunks(chunks: list[dict], limit: int = 20) -> list[dict]:
    scored = []
    for index, chunk in enumerate(chunks):
        metadata = chunk.get("metadata", {})
        text = " ".join(
            [
                str(metadata.get("section_title") or ""),
                str(metadata.get("hierarchy_path") or ""),
                str(chunk.get("title") or ""),
            ]
        ).lower()
        element_type = str(metadata.get("element_type") or "").lower()

        score = 0
        if any(keyword in text for keyword in PRIORITY_SECTION_KEYWORDS):
            score += 5
        if element_type in PREFERRED_ELEMENT_TYPES:
            score += 2
        if chunk.get("content"):
            score += 1

        order_index = metadata.get("order_index")
        try:
            order_value = int(order_index)
        except (TypeError, ValueError):
            order_value = index
        scored.append((score, -order_value, chunk))

    ranked = sorted(scored, key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in ranked[:limit]]


def _normalize_graph(raw_graph: dict, chunks: list[dict]) -> dict:
    valid_chunk_ids = {chunk.get("chunk_id") for chunk in chunks if chunk.get("chunk_id")}
    entities_by_name: dict[str, dict] = {}

    for item in raw_graph.get("entities", []):
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        entity_type = _text(item.get("entity_type")).lower()
        normalized_name = _normalize_name(name)
        if not name or not normalized_name or entity_type not in ALLOWED_ENTITY_TYPES:
            continue
        if normalized_name in GENERIC_ENTITY_NAMES:
            continue

        source_chunk_ids = _valid_chunk_ids(item.get("source_chunk_ids"), valid_chunk_ids)
        if not source_chunk_ids:
            continue
        key = f"{entity_type}::{normalized_name}"
        current = entities_by_name.get(key)
        candidate = {
            "name": name,
            "normalized_name": normalized_name,
            "entity_type": entity_type,
            "description": _text(item.get("description")),
            "importance": _bounded_float(item.get("importance"), 0.5),
            "confidence": _bounded_float(item.get("confidence"), 0.7),
            "source_chunk_ids": source_chunk_ids,
            "evidence": _text(item.get("evidence")),
        }
        if current is None or candidate["confidence"] > current["confidence"]:
            entities_by_name[key] = candidate
        elif source_chunk_ids:
            current["source_chunk_ids"] = _merge_unique(current["source_chunk_ids"], source_chunk_ids)

    entities = list(entities_by_name.values())
    entity_key_by_normalized_name = _build_entity_lookup(entities)
    relation_keys: set[str] = set()
    relations = []

    for item in raw_graph.get("relations", []):
        if not isinstance(item, dict):
            continue
        relation_type = _text(item.get("relation_type")).lower()
        if relation_type not in ALLOWED_RELATION_TYPES:
            continue

        source_key = entity_key_by_normalized_name.get(_normalize_name(_text(item.get("source"))))
        target_key = entity_key_by_normalized_name.get(_normalize_name(_text(item.get("target"))))
        if not source_key or not target_key or source_key == target_key:
            continue

        dedupe_key = f"{source_key}:{relation_type}:{target_key}"
        if dedupe_key in relation_keys:
            continue
        relation_keys.add(dedupe_key)

        source_entity = entities_by_name[source_key]
        target_entity = entities_by_name[target_key]
        source_chunk_ids = _valid_chunk_ids(item.get("source_chunk_ids"), valid_chunk_ids)
        if not source_chunk_ids:
            continue
        relations.append(
            {
                "source": source_entity["name"],
                "source_entity_type": source_entity["entity_type"],
                "relation_type": relation_type,
                "target": target_entity["name"],
                "target_entity_type": target_entity["entity_type"],
                "description": _text(item.get("description")),
                "confidence": _bounded_float(item.get("confidence"), 0.7),
                "source_chunk_ids": source_chunk_ids,
                "evidence": _text(item.get("evidence")),
            }
        )

    return {"entities": entities, "relations": relations}


def _compact_analysis(analysis: dict) -> dict:
    final_summary = analysis.get("final_summary") if isinstance(analysis.get("final_summary"), dict) else {}
    return {
        "title": _first_text(final_summary.get("title"), analysis.get("title")),
        "research_problem": _first_text(final_summary.get("research_problem"), analysis.get("research_problem")),
        "method_summary": _first_text(final_summary.get("method_overview"), analysis.get("method_summary")),
        "experiment_summary": _first_text(
            final_summary.get("experiment_or_argument_summary"),
            analysis.get("experiment_summary"),
        ),
        "reproducible_parts": _as_short_list(analysis.get("reproducible_parts")),
        "required_inputs": _as_short_list(analysis.get("required_inputs")),
        "possible_code_modules": analysis.get("possible_code_modules", [])[:8]
        if isinstance(analysis.get("possible_code_modules"), list)
        else [],
        "code_generation_strategy": analysis.get("code_generation_strategy", ""),
    }


def _compact_chunks(chunks: list[dict]) -> list[dict]:
    compact = []
    for chunk in chunks:
        metadata = chunk.get("metadata", {})
        compact.append(
            {
                "chunk_id": chunk.get("chunk_id", ""),
                "section_title": metadata.get("section_title") or chunk.get("title", ""),
                "hierarchy_path": metadata.get("hierarchy_path", ""),
                "element_type": metadata.get("element_type", ""),
                "page_start": chunk.get("page_start"),
                "page_end": chunk.get("page_end"),
                "content": _short_text(chunk.get("content", ""), 1200),
            }
        )
    return compact


def _build_entity_lookup(entities: list[dict]) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    for entity in entities:
        key = f"{entity['entity_type']}::{entity['normalized_name']}"
        grouped.setdefault(entity["normalized_name"], []).append(key)

    return {
        normalized_name: keys[0]
        for normalized_name, keys in grouped.items()
        if len(keys) == 1
    }


def _valid_chunk_ids(value: object, valid_chunk_ids: set[str]) -> list[str]:
    chunk_ids = []
    raw_items = value if isinstance(value, list) else [value]
    for item in raw_items:
        chunk_id = _text(item)
        if chunk_id in valid_chunk_ids and chunk_id not in chunk_ids:
            chunk_ids.append(chunk_id)
    return chunk_ids


def _loads_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise RuntimeError(f"模型返回内容不是 JSON：{content[:500]}") from exc
        data = json.loads(match.group(0))

    if not isinstance(data, dict):
        raise RuntimeError("模型返回 JSON 不是对象。")
    return data


def _normalize_name(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _bounded_float(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(parsed, 1.0))


def _first_text(*values: object) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _as_short_list(value: object, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_short_text(item, 300) for item in value[:limit] if _text(item)]


def _short_text(value: object, limit: int) -> str:
    text = _text(value)
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    result = list(first)
    for item in second:
        if item not in result:
            result.append(item)
    return result
