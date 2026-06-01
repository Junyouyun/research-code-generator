from app.core.database import (
    list_project_graph_entities,
    list_project_graph_relations,
    record_graph_extraction_run,
    save_project_graph,
)
from app.core.models import GraphEntity, GraphRelation, Project

QUERY_INTENT_RULES = [
    {
        "keywords": {"reward", "rewards", "objective", "loss", "奖励", "回报", "目标", "优化目标"},
        "entity_types": {"reward", "objective"},
        "relation_types": {"defines_reward", "optimizes"},
    },
    {
        "keywords": {"state", "states", "observation", "observations", "状态", "观测"},
        "entity_types": {"state", "environment"},
        "relation_types": {"defines_state"},
    },
    {
        "keywords": {"action", "actions", "decision", "allocation", "动作", "行为", "决策", "分配"},
        "entity_types": {"action", "environment"},
        "relation_types": {"defines_action"},
    },
    {
        "keywords": {"environment", "simulation", "simulator", "env", "环境", "仿真"},
        "entity_types": {"environment", "state", "action", "reward"},
        "relation_types": {"defines_state", "defines_action", "defines_reward"},
    },
    {
        "keywords": {"dataset", "data", "benchmark", "trace", "数据", "数据集", "基准"},
        "entity_types": {"dataset"},
        "relation_types": {"requires_data", "evaluated_on"},
    },
    {
        "keywords": {"metric", "metrics", "result", "accuracy", "latency", "指标", "结果", "性能"},
        "entity_types": {"metric", "result"},
        "relation_types": {"reports_metric", "measured_by"},
    },
    {
        "keywords": {"code", "module", "class", "function", "implement", "代码", "模块", "类", "函数", "实现"},
        "entity_types": {"code_module", "module", "algorithm", "environment"},
        "relation_types": {"implemented_by", "has_component", "depends_on"},
    },
    {
        "keywords": {"algorithm", "model", "method", "agent", "network", "算法", "模型", "方法", "智能体", "网络"},
        "entity_types": {"algorithm", "model", "method", "module"},
        "relation_types": {"uses", "has_component", "depends_on", "trained_with"},
    },
]

CODE_GENERATION_ENTITY_TYPES = {
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
    "experiment",
    "code_module",
    "training_step",
    "evaluation_protocol",
}

CODE_GENERATION_RELATION_TYPES = {
    "defines_state",
    "defines_action",
    "defines_reward",
    "has_component",
    "uses",
    "depends_on",
    "implemented_by",
    "requires_data",
    "reports_metric",
    "trained_with",
    "measured_by",
    "evaluated_on",
    "produces_output",
    "optimizes",
}


def build_and_save_project_graph(
    project: Project,
    analysis: dict,
    chunks: list[dict],
) -> dict:
    from app.services.knowledge_graph_extractor import build_project_knowledge_graph

    graph = build_project_knowledge_graph(project.project_id, analysis, chunks)
    result = save_project_graph(project.project_id, project.user_id, graph)
    record_graph_extraction_run(
        project_id=project.project_id,
        user_id=project.user_id,
        status="completed",
        entity_count=result["entity_count"],
        relation_count=result["relation_count"],
    )
    return {
        **graph,
        "entity_count": result["entity_count"],
        "relation_count": result["relation_count"],
    }


def record_project_graph_failure(project: Project, error_message: str) -> None:
    record_graph_extraction_run(
        project_id=project.project_id,
        user_id=project.user_id,
        status="failed",
        error_message=error_message[:1000],
    )


def get_project_graph(project: Project) -> dict:
    entities = list_project_graph_entities(project.project_id, project.user_id)
    relations = list_project_graph_relations(project.project_id, project.user_id)
    entity_names = {entity.entity_id: entity.name for entity in entities}

    return {
        "project_id": project.project_id,
        "paper_id": project.paper_id,
        "paper_version_id": project.paper_version_id,
        "entities": [_entity_to_dict(entity) for entity in entities],
        "relations": [_relation_to_dict(relation, entity_names) for relation in relations],
    }


def get_code_generation_graph_context(
    project: Project,
    limit_entities: int = 24,
    limit_relations: int = 40,
) -> dict:
    graph = get_project_graph(project)
    entities = [
        entity
        for entity in graph["entities"]
        if entity.get("entity_type") in CODE_GENERATION_ENTITY_TYPES
        and entity.get("source_chunk_ids")
    ]
    entity_ids = {entity["entity_id"] for entity in entities}
    relations = [
        relation
        for relation in graph["relations"]
        if relation.get("relation_type") in CODE_GENERATION_RELATION_TYPES
        and relation.get("source_chunk_ids")
        and (
            relation.get("source_entity_id") in entity_ids
            or relation.get("target_entity_id") in entity_ids
        )
    ]

    connected_ids = set()
    for relation in relations:
        connected_ids.add(relation.get("source_entity_id"))
        connected_ids.add(relation.get("target_entity_id"))
    ranked_entities = sorted(
        entities,
        key=lambda entity: (
            entity["entity_id"] in connected_ids,
            entity.get("importance", 0.5),
            entity.get("confidence", 0.7),
        ),
        reverse=True,
    )
    selected_entities = ranked_entities[:limit_entities]
    selected_ids = {entity["entity_id"] for entity in selected_entities}
    selected_relations = [
        relation
        for relation in relations
        if relation.get("source_entity_id") in selected_ids
        or relation.get("target_entity_id") in selected_ids
    ][:limit_relations]

    return {
        "entities": selected_entities,
        "relations": selected_relations,
        "paths": [],
    }


def search_graph_context(
    project_id: str,
    user_id: str,
    query: str,
    limit_entities: int = 8,
    limit_relations: int = 20,
    depth: int = 1,
) -> dict:
    query = query.strip()
    if not query:
        return {"entities": [], "relations": [], "paths": []}

    entities = list_project_graph_entities(project_id, user_id)
    relations = list_project_graph_relations(project_id, user_id)
    if not entities:
        return {"entities": [], "relations": [], "paths": []}

    query_tokens = _tokenize_query(query)
    intent_entity_types, intent_relation_types = _detect_query_intent(query)

    entity_scores = {
        entity.entity_id: _score_entity(entity, query_tokens, intent_entity_types)
        for entity in entities
    }
    primary_entities = [
        entity
        for entity in entities
        if entity_scores.get(entity.entity_id, 0.0) > 0
    ]
    primary_entities.sort(
        key=lambda entity: (
            entity_scores[entity.entity_id],
            entity.importance,
            entity.confidence,
        ),
        reverse=True,
    )
    primary_entities = primary_entities[:limit_entities]
    primary_ids = {entity.entity_id for entity in primary_entities}

    relation_scores: dict[str, float] = {}
    relation_candidates = []
    for relation in relations:
        relation_score = _score_relation(
            relation,
            query_tokens,
            intent_relation_types,
            entity_scores,
            primary_ids,
        )
        if relation_score <= 0:
            continue
        relation_scores[relation.relation_id] = relation_score
        relation_candidates.append(relation)

    relation_candidates.sort(
        key=lambda relation: (relation_scores[relation.relation_id], relation.confidence),
        reverse=True,
    )
    selected_relations = relation_candidates[:limit_relations]

    entity_by_id = {entity.entity_id: entity for entity in entities}
    selected_ids = set(primary_ids)
    if depth >= 1:
        for relation in selected_relations:
            selected_ids.add(relation.source_entity_id)
            selected_ids.add(relation.target_entity_id)

    selected_entities = [
        entity_by_id[entity_id]
        for entity_id in selected_ids
        if entity_id in entity_by_id
    ]
    selected_entities.sort(
        key=lambda entity: (
            entity_scores.get(entity.entity_id, 0.0),
            entity.importance,
            entity.confidence,
        ),
        reverse=True,
    )
    selected_entities = selected_entities[:limit_entities]
    selected_ids = {entity.entity_id for entity in selected_entities}
    selected_relations = [
        relation
        for relation in selected_relations
        if relation.source_entity_id in selected_ids or relation.target_entity_id in selected_ids
    ][:limit_relations]

    entity_names = {entity.entity_id: entity.name for entity in entities}
    return {
        "entities": [_entity_to_dict(entity) for entity in selected_entities],
        "relations": [_relation_to_dict(relation, entity_names) for relation in selected_relations],
        "paths": [],
    }


def _entity_to_dict(entity: GraphEntity) -> dict:
    return {
        "entity_id": entity.entity_id,
        "entity_type": entity.entity_type,
        "name": entity.name,
        "normalized_name": entity.normalized_name,
        "description": entity.description,
        "importance": entity.importance,
        "confidence": entity.confidence,
        "source_chunk_ids": entity.source_chunk_ids or [],
        "evidence": entity.evidence,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def _relation_to_dict(relation: GraphRelation, entity_names: dict[str, str]) -> dict:
    return {
        "relation_id": relation.relation_id,
        "source_entity_id": relation.source_entity_id,
        "target_entity_id": relation.target_entity_id,
        "source_name": entity_names.get(relation.source_entity_id),
        "target_name": entity_names.get(relation.target_entity_id),
        "relation_type": relation.relation_type,
        "description": relation.description,
        "confidence": relation.confidence,
        "source_chunk_ids": relation.source_chunk_ids or [],
        "evidence": relation.evidence,
        "created_at": relation.created_at,
        "updated_at": relation.updated_at,
    }


def _detect_query_intent(query: str) -> tuple[set[str], set[str]]:
    query_text = query.lower()
    entity_types: set[str] = set()
    relation_types: set[str] = set()
    for rule in QUERY_INTENT_RULES:
        if any(keyword in query_text for keyword in rule["keywords"]):
            entity_types.update(rule["entity_types"])
            relation_types.update(rule["relation_types"])
    return entity_types, relation_types


def _score_entity(
    entity: GraphEntity,
    query_tokens: set[str],
    intent_entity_types: set[str],
) -> float:
    searchable_text = " ".join(
        value
        for value in [
            entity.name,
            entity.normalized_name,
            entity.description or "",
            entity.evidence or "",
            entity.entity_type,
        ]
        if value
    )
    overlap = _query_overlap(query_tokens, searchable_text)
    intent_weight = 1.5 if entity.entity_type in intent_entity_types else 0.0
    if overlap <= 0 and intent_weight <= 0:
        return 0.0
    return overlap * 2.5 + intent_weight + entity.importance + entity.confidence


def _score_relation(
    relation: GraphRelation,
    query_tokens: set[str],
    intent_relation_types: set[str],
    entity_scores: dict[str, float],
    primary_entity_ids: set[str],
) -> float:
    searchable_text = " ".join(
        value
        for value in [
            relation.relation_type,
            relation.description or "",
            relation.evidence or "",
        ]
        if value
    )
    overlap = _query_overlap(query_tokens, searchable_text)
    intent_weight = 1.5 if relation.relation_type in intent_relation_types else 0.0
    endpoint_score = max(
        entity_scores.get(relation.source_entity_id, 0.0),
        entity_scores.get(relation.target_entity_id, 0.0),
    )
    is_neighbor = (
        relation.source_entity_id in primary_entity_ids
        or relation.target_entity_id in primary_entity_ids
    )
    if overlap <= 0 and intent_weight <= 0 and not is_neighbor:
        return 0.0
    return overlap * 2.0 + intent_weight + endpoint_score * 0.4 + relation.confidence


def _query_overlap(query_tokens: set[str], text: str) -> float:
    if not query_tokens or not text:
        return 0.0
    text = text.lower()
    matched = [token for token in query_tokens if token and token in text]
    return min(len(matched) / max(len(query_tokens), 1), 1.0)


def _tokenize_query(query: str) -> set[str]:
    import re

    lowered = query.lower()
    tokens = set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", lowered))
    for phrase in list(tokens):
        if re.fullmatch(r"[\u4e00-\u9fff]+", phrase):
            tokens.update(phrase[index : index + 2] for index in range(max(len(phrase) - 1, 0)))
    return {token for token in tokens if len(token) >= 2}
