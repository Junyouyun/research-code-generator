from app.services.llm_code_generator import build_code_spec


def plan_code_project(
    analysis: dict,
    chunks: list[dict] | None = None,
    experiment_spec: dict | None = None,
    graph_context: dict | None = None,
) -> dict:
    return build_code_spec(
        analysis,
        chunks or [],
        experiment_spec=experiment_spec,
        graph_context=graph_context,
    )
