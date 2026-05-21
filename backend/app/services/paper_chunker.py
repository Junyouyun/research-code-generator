import re


MAX_CHUNK_CHARS = 6000
CHUNK_OVERLAP_CHARS = 600

SECTION_PATTERNS = [
    r"abstract",
    r"keywords?",
    r"introduction",
    r"related work",
    r"background",
    r"method(?:s|ology)?",
    r"approach",
    r"model",
    r"algorithm",
    r"experiment(?:s|al setup)?",
    r"evaluation",
    r"result(?:s)?",
    r"discussion",
    r"conclusion",
    r"references",
    r"摘要",
    r"关键词",
    r"引言",
    r"相关工作",
    r"方法",
    r"模型",
    r"算法",
    r"实验",
    r"结果",
    r"讨论",
    r"结论",
    r"参考文献",
]


def chunk_paper(parsed_paper: dict) -> list[dict]:
    pages = parsed_paper.get("pages", [])
    page_sections = [_split_page_into_sections(page) for page in pages]
    sections = _merge_sections(page_sections)

    chunks = []
    for section in sections:
        chunks.extend(_split_section(section))

    return [
        {
            **chunk,
            "chunk_id": f"chunk_{index:04d}",
        }
        for index, chunk in enumerate(chunks, start=1)
    ]


def _split_page_into_sections(page: dict) -> list[dict]:
    text = page.get("text", "")
    page_number = page.get("page_number")
    sections = []
    current_title = f"Page {page_number}"
    current_lines = []

    for line in text.splitlines():
        if _looks_like_section_title(line):
            if current_lines:
                sections.append(_section(current_title, current_lines, page_number, page_number))
            current_title = _normalize_title(line)
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append(_section(current_title, current_lines, page_number, page_number))

    return sections


def _merge_sections(pages: list[list[dict]]) -> list[dict]:
    merged = []

    for page_sections in pages:
        for section in page_sections:
            if merged and _same_section(merged[-1]["title"], section["title"]):
                merged[-1]["content"] = f"{merged[-1]['content']}\n{section['content']}".strip()
                merged[-1]["page_end"] = section["page_end"]
            else:
                merged.append(section)

    return merged


def _split_section(section: dict) -> list[dict]:
    content = section.get("content", "")
    if len(content) <= MAX_CHUNK_CHARS:
        return [section] if content.strip() else []

    chunks = []
    start = 0
    while start < len(content):
        end = min(start + MAX_CHUNK_CHARS, len(content))
        if end < len(content):
            paragraph_break = content.rfind("\n", start, end)
            if paragraph_break > start + MAX_CHUNK_CHARS // 2:
                end = paragraph_break

        chunk_text = content[start:end].strip()
        if chunk_text:
            chunks.append(
                {
                    "title": section["title"],
                    "content": chunk_text,
                    "page_start": section["page_start"],
                    "page_end": section["page_end"],
                }
            )

        if end >= len(content):
            break
        start = max(end - CHUNK_OVERLAP_CHARS, start + 1)

    return chunks


def _section(title: str, lines: list[str], page_start: int, page_end: int) -> dict:
    return {
        "title": title,
        "content": "\n".join(line for line in lines if line.strip()).strip(),
        "page_start": page_start,
        "page_end": page_end,
    }


def _looks_like_section_title(line: str) -> bool:
    value = _normalize_title(line)
    if not value or len(value) > 120:
        return False

    lowered = value.lower()
    if any(re.fullmatch(pattern, lowered) for pattern in SECTION_PATTERNS):
        return True

    numbered = re.match(r"^\d+(?:\.\d+)*\.?\s+(.+)$", lowered)
    if not numbered:
        return False

    title = numbered.group(1).strip()
    return any(re.search(pattern, title) for pattern in SECTION_PATTERNS)


def _same_section(left: str, right: str) -> bool:
    return _normalize_title(left).lower() == _normalize_title(right).lower()


def _normalize_title(value: str) -> str:
    return " ".join(value.strip().split())
