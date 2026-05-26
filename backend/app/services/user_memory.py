import json
import re

from app.core.database import (
    get_memory_item,
    list_user_memories,
    update_memory_item_content,
    update_memory_item_status,
    upsert_user_memory,
)
from app.core.models import MemoryItem
from app.llm.client import chat_completion

ALLOWED_MEMORY_TYPES = {
    "user_preference",
    "research_interest",
    "coding_preference",
    "workflow_preference",
    "domain_knowledge",
}


def record_user_memory(
    user_id: str,
    memory_type: str,
    content: str,
    normalized_key: str | None = None,
    importance: float = 0.5,
    confidence: float = 0.7,
    source_type: str = "conversation",
    source_id: str | None = None,
    evidence: dict | None = None,
) -> MemoryItem | None:
    clean_content = content.strip()
    if not clean_content:
        return None

    clean_type = _clean_memory_type(memory_type)
    memory = upsert_user_memory(
        user_id=user_id,
        memory_type=clean_type,
        content=clean_content[:1600],
        normalized_key=normalized_key,
        importance=_bounded_float(importance, 0.1, 1.0, 0.5),
        confidence=_bounded_float(confidence, 0.1, 1.0, 0.7),
        source_type=source_type,
        source_id=source_id,
        evidence=evidence,
    )
    _index_memory_item(memory)
    return memory


def get_user_memory_context(user_id: str, query: str, limit: int = 6) -> list[dict]:
    hits = _search_user_memories(user_id=user_id, query=query, top_k=limit)
    if hits:
        return [_memory_hit_context(hit) for hit in hits]

    memories = list_user_memories(user_id=user_id, limit=limit)
    return [_memory_item_context(memory) for memory in memories]


def extract_user_memories_from_turn(
    user_id: str,
    user_message: str,
    assistant_message: str,
    project_id: str | None = None,
    conversation_id: str | None = None,
) -> list[MemoryItem]:
    candidates = _extract_memory_candidates(user_message, assistant_message)
    saved: list[MemoryItem] = []
    for candidate in candidates:
        memory = record_user_memory(
            user_id=user_id,
            memory_type=_as_text(candidate.get("memory_type")),
            content=_as_text(candidate.get("content")),
            normalized_key=_as_text(candidate.get("normalized_key")),
            importance=_as_float(candidate.get("importance"), 0.6),
            confidence=_as_float(candidate.get("confidence"), 0.7),
            source_type="conversation",
            source_id=conversation_id,
            evidence={
                "project_id": project_id,
                "reason": _as_text(candidate.get("reason"))[:500],
            },
        )
        if memory is not None:
            saved.append(memory)
    return saved


def update_user_memory(
    memory_id: str,
    user_id: str,
    content: str | None = None,
    memory_type: str | None = None,
    importance: float | None = None,
    confidence: float | None = None,
) -> MemoryItem | None:
    existing = get_memory_item(memory_id, user_id)
    if existing is None or existing.scope != "user":
        return None

    memory = update_memory_item_content(
        memory_id=memory_id,
        user_id=user_id,
        content=content.strip() if content is not None else existing.content,
        memory_type=_clean_memory_type(memory_type) if memory_type else None,
        importance=importance,
        confidence=confidence,
    )
    if memory is not None:
        _index_memory_item(memory)
    return memory


def archive_user_memory(memory_id: str, user_id: str) -> MemoryItem | None:
    memory = update_memory_item_status(memory_id, user_id, status="archived")
    if memory is not None:
        _delete_memory_item_vector(memory_id)
    return memory


def _index_memory_item(memory: MemoryItem) -> None:
    from app.services.memory_vector_store import index_memory_item

    index_memory_item(memory)


def _delete_memory_item_vector(memory_id: str) -> None:
    from app.services.memory_vector_store import delete_memory_item_vector

    delete_memory_item_vector(memory_id)


def _search_user_memories(user_id: str, query: str, top_k: int) -> list[dict]:
    from app.services.memory_vector_store import search_user_memories

    return search_user_memories(user_id=user_id, query=query, top_k=top_k)


def _extract_memory_candidates(user_message: str, assistant_message: str) -> list[dict]:
    if not user_message.strip() or not assistant_message.strip():
        return []

    messages = [
        {
            "role": "system",
            "content": (
                "You extract durable user long-term memories for a research coding product. "
                "Only keep stable preferences, research interests, coding preferences, workflow preferences, "
                "or reusable domain knowledge. Do not save one-off questions, temporary facts, secrets, API keys, "
                "or unsupported guesses. Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "Extract at most 3 long-term memories from this turn.\n"
                "Allowed memory_type values: user_preference, research_interest, coding_preference, workflow_preference, domain_knowledge.\n"
                "Return schema: {\"memories\":[{\"memory_type\":\"...\",\"content\":\"...\",\"normalized_key\":\"...\",\"importance\":0.5,\"confidence\":0.7,\"reason\":\"...\"}]}.\n\n"
                f"user_message:\n{user_message[:3000]}\n\n"
                f"assistant_message:\n{assistant_message[:3000]}"
            ),
        },
    ]
    content = chat_completion(
        messages,
        temperature=0,
        max_tokens=1200,
        response_format={"type": "json_object"},
    )
    data = _loads_json(content)
    raw_memories = data.get("memories")
    if not isinstance(raw_memories, list):
        return []

    candidates = []
    for item in raw_memories[:3]:
        if not isinstance(item, dict):
            continue
        memory_type = _clean_memory_type(_as_text(item.get("memory_type")))
        content_text = _as_text(item.get("content"))
        normalized_key = _as_text(item.get("normalized_key"))
        if not content_text or not normalized_key:
            continue
        candidates.append(
            {
                "memory_type": memory_type,
                "content": content_text,
                "normalized_key": normalized_key[:120].lower(),
                "importance": _as_float(item.get("importance"), 0.6),
                "confidence": _as_float(item.get("confidence"), 0.7),
                "reason": _as_text(item.get("reason")),
            }
        )
    return candidates


def _memory_item_context(memory: MemoryItem) -> dict:
    return {
        "memory_id": memory.memory_id,
        "memory_type": memory.memory_type,
        "content": memory.content,
        "importance": memory.importance,
        "confidence": memory.confidence,
    }


def _memory_hit_context(hit: dict) -> dict:
    return {
        "memory_id": _as_text(hit.get("memory_id")),
        "memory_type": _as_text(hit.get("memory_type")),
        "content": _as_text(hit.get("content")),
        "importance": hit.get("importance"),
        "confidence": hit.get("confidence"),
        "score": hit.get("score"),
    }


def _clean_memory_type(memory_type: str | None) -> str:
    clean_type = _as_text(memory_type)
    return clean_type if clean_type in ALLOWED_MEMORY_TYPES else "user_preference"


def _loads_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}

    return data if isinstance(data, dict) else {}


def _as_text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _as_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bounded_float(value: float, minimum: float, maximum: float, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))
