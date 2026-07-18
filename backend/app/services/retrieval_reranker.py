from __future__ import annotations

import re


INTENT_SECTION_KEYWORDS = {
    "problem_goal": {"abstract", "introduction", "contribution", "objective"},
    "system_model": {"system model", "model", "problem formulation", "environment"},
    "state_space": {"system model", "state", "state space", "mdp", "problem formulation"},
    "action_space": {"system model", "action", "action space", "mdp", "problem formulation"},
    "reward_function": {"reward", "objective", "utility", "cost", "penalty", "mdp"},
    "training_process": {"method", "algorithm", "training", "actor", "critic", "a3c"},
    "experiment_setup": {"experiment", "performance evaluation", "settings", "datasets"},
    "baselines": {"experiment", "comparison", "baseline", "baselines"},
    "metrics_results": {"result", "results", "metric", "performance", "comparison"},
}

INTENT_ORDER_PRIORS = {
    "problem_goal": [(1, 12, 1.0), (13, 20, 0.4)],
    "system_model": [(10, 24, 1.0), (25, 32, 0.5)],
    "state_space": [(20, 32, 1.0), (13, 38, 0.5)],
    "action_space": [(20, 32, 1.0), (13, 38, 0.5)],
    "reward_function": [(24, 32, 1.0), (20, 38, 0.5)],
    "training_process": [(32, 52, 1.0), (25, 60, 0.4)],
    "experiment_setup": [(52, 58, 1.0), (52, 66, 0.5)],
    "baselines": [(52, 58, 1.0), (67, 80, 0.5)],
    "metrics_results": [(60, 80, 1.0), (52, 80, 0.5)],
}


def rerank_retrieval_hits(
    question: str,
    intent: str,
    hits: list[dict],
    target_sections: list[str] | None = None,
    graph_source_chunk_ids: set[str] | None = None,
    top_k: int = 8,
) -> list[dict]:
    graph_source_chunk_ids = graph_source_chunk_ids or set()
    question_tokens = _tokens(question)
    reranked = []

    for hit in hits:
        base_score = float(hit.get("score") or 0.0)
        best_vector_score = float(hit.get("best_vector_score") or base_score)
        section_boost = _section_boost(hit, intent, target_sections or [])
        order_boost = _order_boost(hit, intent)
        keyword_score = _keyword_overlap(question_tokens, _hit_text(hit))
        query_coverage = min(len(hit.get("source_queries", []) or []), 4) / 4
        graph_boost = 1.0 if hit.get("chunk_id") in graph_source_chunk_ids else 0.0

        rerank_score = (
            base_score
            + section_boost * 0.03
            + order_boost * 0.015
            + keyword_score * 0.02
            + query_coverage * 0.015
            + graph_boost * 0.05
        )
        item = {
            **hit,
            "score": rerank_score,
            "rerank_score": rerank_score,
            "score_breakdown": {
                "base_score": base_score,
                "best_vector_score": best_vector_score,
                "section_boost": section_boost,
                "order_boost": order_boost,
                "keyword_score": keyword_score,
                "query_coverage": query_coverage,
                "graph_boost": graph_boost,
            },
        }
        reranked.append(item)

    reranked.sort(
        key=lambda hit: (
            hit.get("rerank_score") or 0.0,
            hit.get("best_vector_score") or 0.0,
        ),
        reverse=True,
    )
    return reranked[:top_k]


def _section_boost(hit: dict, intent: str, target_sections: list[str]) -> float:
    section_text = _metadata_text(hit)
    if not section_text:
        return 0.0

    keywords = set(INTENT_SECTION_KEYWORDS.get(intent, set()))
    keywords.update(str(section).lower() for section in target_sections if str(section).strip())
    if not keywords:
        return 0.0

    matched = [keyword for keyword in keywords if keyword and keyword in section_text]
    return min(len(matched) / max(len(keywords), 1), 1.0)


def _order_boost(hit: dict, intent: str) -> float:
    order_index = hit.get("order_index")
    if order_index is None:
        return 0.0
    try:
        order_index = int(order_index)
    except (TypeError, ValueError):
        return 0.0

    for start, end, score in INTENT_ORDER_PRIORS.get(intent, []):
        if start <= order_index <= end:
            return score
    return 0.0


def _keyword_overlap(question_tokens: set[str], text: str) -> float:
    if not question_tokens or not text:
        return 0.0
    text = text.lower()
    matched = [token for token in question_tokens if token in text]
    return min(len(matched) / max(len(question_tokens), 1), 1.0)


def _hit_text(hit: dict) -> str:
    values = [
        _metadata_text(hit),
        " ".join(hit.get("source_queries", []) or []),
        str(hit.get("document_title") or ""),
    ]
    return " ".join(value for value in values if value).lower()


def _metadata_text(hit: dict) -> str:
    return " ".join(
        str(value or "").lower()
        for value in [
            hit.get("section_title"),
            hit.get("hierarchy_path"),
            hit.get("element_type"),
            hit.get("document_title"),
        ]
    )


def _tokens(text: str) -> set[str]:
    lowered = str(text or "").lower()
    tokens = set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", lowered))
    for token in list(tokens):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            tokens.update(token[index : index + 2] for index in range(max(len(token) - 1, 0)))
    return {token for token in tokens if len(token) >= 2}
