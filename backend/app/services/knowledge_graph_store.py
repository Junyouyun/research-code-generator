from app.core.database import (
    list_project_graph_entities,
    list_project_graph_relations,
    record_graph_extraction_run,
    save_project_graph,
)
from app.core.models import GraphEntity, GraphRelation, Project


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
