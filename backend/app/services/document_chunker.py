import re


MIN_CHUNK_TOKENS = 100
TARGET_CHUNK_TOKENS = 768
MAX_CHUNK_TOKENS = 1024
OVERLAP_TOKENS = 128

SPECIAL_ELEMENT_TYPES = {"table", "formula", "code", "figure", "reference"}
NORMAL_ELEMENT_TYPES = {"title", "paragraph", "list", "unknown"}


def chunk_document_elements(elements: list[dict]) -> list[dict]:
    ordered_elements = sorted(elements, key=lambda item: item.get("order_index", 0))
    raw_chunks = _build_raw_chunks(ordered_elements)
    return _add_overlap_and_ids(raw_chunks)


def _build_raw_chunks(elements: list[dict]) -> list[dict]:
    chunks = []
    buffer: list[dict] = []

    def flush_buffer() -> None:
        nonlocal buffer
        if not buffer:
            return
        chunks.extend(_split_normal_elements(buffer))
        buffer = []

    for element in elements:
        element_type = element.get("type", "unknown")
        if element_type in SPECIAL_ELEMENT_TYPES:
            flush_buffer()
            chunks.append(_special_element_to_chunk(element))
            continue

        if element_type not in NORMAL_ELEMENT_TYPES:
            element = {**element, "type": "unknown", "needs_review": True}

        if buffer and _should_flush_before_append(buffer, element):
            flush_buffer()

        buffer.append(element)
        if _count_tokens(_join_element_markdown(buffer)) >= TARGET_CHUNK_TOKENS:
            flush_buffer()

    flush_buffer()
    return chunks


def _should_flush_before_append(buffer: list[dict], element: dict) -> bool:
    current_path = buffer[-1].get("hierarchy_path", "")
    next_path = element.get("hierarchy_path", "")
    if current_path and next_path and current_path != next_path:
        return True

    current_tokens = _count_tokens(_join_element_markdown(buffer))
    next_tokens = _count_tokens(_element_content(element))
    return current_tokens + next_tokens > MAX_CHUNK_TOKENS


def _split_normal_elements(elements: list[dict]) -> list[dict]:
    content = _join_element_markdown(elements)
    if not content:
        return []

    base_metadata = _metadata_from_elements(elements)
    if _count_tokens(content) <= MAX_CHUNK_TOKENS:
        return [_make_chunk(content, base_metadata)]

    chunks = []
    for piece, flags in _split_text_by_tokens(content):
        metadata = {
            **base_metadata,
            "chunk_size_tokens": _count_tokens(piece),
            "is_split_sentence": flags["is_split_sentence"],
            "is_forced_split": flags["is_forced_split"],
            "needs_review": base_metadata["needs_review"] or flags["is_forced_split"],
        }
        chunks.append(_make_chunk(piece, metadata))
    return chunks


def _special_element_to_chunk(element: dict) -> dict:
    content = _element_content(element)
    metadata = _metadata_from_elements([element])
    token_count = _count_tokens(content)
    metadata.update(
        {
            "element_type": element.get("type", "unknown"),
            "chunk_size_tokens": token_count,
            "is_special_element": True,
            "is_cross_page": _is_cross_page(element.get("page_start"), element.get("page_end")),
            "is_split_sentence": False,
            "is_forced_split": False,
            "needs_review": element.get("needs_review", False) or token_count > MAX_CHUNK_TOKENS,
        }
    )
    return _make_chunk(content, metadata)


def _split_text_by_tokens(text: str) -> list[tuple[str, dict]]:
    sentences = _split_sentences(text)
    chunks: list[tuple[str, dict]] = []
    current: list[str] = []

    for sentence in sentences:
        sentence_tokens = _count_tokens(sentence)
        if sentence_tokens > MAX_CHUNK_TOKENS:
            if current:
                chunks.append((_join_sentences(current), _flags()))
                current = []
            chunks.extend(_split_long_sentence(sentence))
            continue

        current_text = _join_sentences(current)
        current_tokens = _count_tokens(current_text)
        if current and current_tokens + sentence_tokens > MAX_CHUNK_TOKENS:
            chunks.append((current_text, _flags()))
            current = [sentence]
        else:
            current.append(sentence)

        if _count_tokens(_join_sentences(current)) >= TARGET_CHUNK_TOKENS:
            chunks.append((_join_sentences(current), _flags()))
            current = []

    if current:
        chunks.append((_join_sentences(current), _flags()))

    return chunks


def _split_long_sentence(sentence: str) -> list[tuple[str, dict]]:
    parts = _split_by_commas(sentence)
    chunks = []
    current: list[str] = []

    for part in parts:
        part_tokens = _count_tokens(part)
        if part_tokens > MAX_CHUNK_TOKENS:
            if current:
                chunks.append((_join_sentences(current), _flags(is_split_sentence=True)))
                current = []
            chunks.extend(_force_split_text(part))
            continue

        current_text = _join_sentences(current)
        if current and _count_tokens(current_text) + part_tokens > MAX_CHUNK_TOKENS:
            chunks.append((current_text, _flags(is_split_sentence=True)))
            current = [part]
        else:
            current.append(part)

    if current:
        chunks.append((_join_sentences(current), _flags(is_split_sentence=True)))
    return chunks


def _force_split_text(text: str) -> list[tuple[str, dict]]:
    pieces = []
    start = 0
    step = MAX_CHUNK_TOKENS * 2
    while start < len(text):
        piece = text[start : start + step].strip()
        if piece:
            pieces.append((piece, _flags(is_split_sentence=True, is_forced_split=True)))
        start += step
    return pieces


def _add_overlap_and_ids(chunks: list[dict]) -> list[dict]:
    result = []
    previous_normal_content = ""

    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk["metadata"]
        content = chunk["content"]
        if not metadata["is_special_element"] and previous_normal_content:
            overlap = _take_overlap(previous_normal_content)
            if overlap and not content.startswith(overlap):
                content = f"{overlap}\n\n{content}"
                metadata = {
                    **metadata,
                    "chunk_size_tokens": _count_tokens(content),
                    "needs_review": metadata["needs_review"] or _count_tokens(content) > MAX_CHUNK_TOKENS,
                }

        chunk_id = f"doc_{metadata['document_id']}_chunk_{index:03d}"
        result.append(
            {
                "chunk_id": chunk_id,
                "content": content,
                "title": metadata.get("section_title", ""),
                "page_start": metadata.get("page_start"),
                "page_end": metadata.get("page_end"),
                "metadata": {**metadata, "order_index": index},
            }
        )

        if not metadata["is_special_element"]:
            previous_normal_content = chunk["content"]

    return result


def _make_chunk(content: str, metadata: dict) -> dict:
    normalized_content = content.strip()
    return {
        "content": normalized_content,
        "metadata": {
            **metadata,
            "chunk_size_tokens": _count_tokens(normalized_content),
        },
    }


def _metadata_from_elements(elements: list[dict]) -> dict:
    first = elements[0]
    last = elements[-1]
    page_start = _first_present(element.get("page_start") for element in elements)
    page_end = _last_present(element.get("page_end") for element in elements)

    return {
        "document_id": first.get("document_id", ""),
        "document_title": _document_title(elements),
        "section_title": last.get("section_title") or first.get("section_title", ""),
        "hierarchy_path": last.get("hierarchy_path") or first.get("hierarchy_path", ""),
        "page_start": page_start,
        "page_end": page_end,
        "element_type": first.get("type", "unknown") if len(elements) == 1 else "paragraph",
        "chunk_size_tokens": 0,
        "is_special_element": False,
        "is_cross_page": _is_cross_page(page_start, page_end),
        "is_split_sentence": False,
        "is_forced_split": False,
        "needs_review": any(element.get("needs_review", False) for element in elements),
        "source_file_type": first.get("source_file_type", ""),
        "order_index": first.get("order_index", 0),
    }


def _document_title(elements: list[dict]) -> str:
    for element in elements:
        if element.get("type") == "title":
            return element.get("text", "")
    return ""


def _join_element_markdown(elements: list[dict]) -> str:
    return "\n\n".join(_element_content(element) for element in elements if _element_content(element))


def _element_content(element: dict) -> str:
    return (element.get("markdown") or element.get("text") or "").strip()


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。？！.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def _split_by_commas(text: str) -> list[str]:
    parts = re.split(r"(?<=[，,；;])\s*", text.strip())
    return [part.strip() for part in parts if part.strip()]


def _join_sentences(sentences: list[str]) -> str:
    return " ".join(sentence.strip() for sentence in sentences if sentence.strip()).strip()


def _take_overlap(text: str) -> str:
    sentences = _split_sentences(text)
    selected: list[str] = []

    for sentence in reversed(sentences):
        candidate = [sentence] + selected
        if _count_tokens(_join_sentences(candidate)) > OVERLAP_TOKENS and selected:
            break
        selected = candidate
        if len(selected) >= 2:
            break

    overlap = _join_sentences(selected)
    return overlap if _count_tokens(overlap) <= OVERLAP_TOKENS * 2 else ""


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    other_chars = len(text) - chinese_chars
    return max(1, int(chinese_chars / 1.8 + other_chars / 4))


def _flags(is_split_sentence: bool = False, is_forced_split: bool = False) -> dict:
    return {
        "is_split_sentence": is_split_sentence,
        "is_forced_split": is_forced_split,
    }


def _first_present(values) -> int | None:
    for value in values:
        if value is not None:
            return value
    return None


def _last_present(values) -> int | None:
    result = None
    for value in values:
        if value is not None:
            result = value
    return result


def _is_cross_page(page_start: int | None, page_end: int | None) -> bool:
    return page_start is not None and page_end is not None and page_start != page_end


def _split_sentences(text: str) -> list[str]:
    parts = re.findall(r"[^。？！.!?]+[。？！.!?]?", text.strip())
    return [part.strip() for part in parts if part.strip()]


def _split_by_commas(text: str) -> list[str]:
    parts = re.findall(r"[^，,；;]+[，,；;]?", text.strip())
    return [part.strip() for part in parts if part.strip()]
