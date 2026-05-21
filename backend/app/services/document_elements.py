from typing import Any


ELEMENT_TYPES = {
    "title",
    "paragraph",
    "table",
    "formula",
    "code",
    "figure",
    "list",
    "reference",
    "unknown",
}


def make_document_element(
    *,
    document_id: str,
    source_file_type: str,
    element_type: str,
    text: str,
    order_index: int,
    markdown: str | None = None,
    page_start: int | None = None,
    page_end: int | None = None,
    bbox: list[float] | None = None,
    section_title: str = "",
    hierarchy_path: str = "",
    confidence: float = 1.0,
    needs_review: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_type = element_type if element_type in ELEMENT_TYPES else "unknown"

    return {
        "element_id": f"element_{order_index:06d}",
        "document_id": document_id,
        "source_file_type": source_file_type,
        "type": normalized_type,
        "text": _clean_text(text),
        "markdown": _clean_text(markdown if markdown is not None else text),
        "page_start": page_start,
        "page_end": page_end,
        "bbox": bbox or [],
        "section_title": section_title,
        "hierarchy_path": hierarchy_path,
        "order_index": order_index,
        "confidence": confidence,
        "needs_review": needs_review or normalized_type == "unknown",
        "extra": extra or {},
    }


def _clean_text(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.strip().splitlines()).strip()
