from pathlib import Path


def parse_paper(pdf_path: Path) -> dict:
    pages = _extract_pages(pdf_path)
    full_text = "\n\n".join(page["text"] for page in pages if page["text"])

    return {
        "source": str(pdf_path),
        "title": _extract_title(pages),
        "abstract": _extract_abstract(full_text),
        "page_count": len(pages),
        "pages": pages,
        "sections": _build_page_sections(pages),
        "full_text": full_text,
        "tables": [],
        "figures": [],
        "references": [],
    }


def _extract_pages(pdf_path: Path) -> list[dict]:
    try:
        import fitz
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 PyMuPDF 依赖，请先安装 backend/requirements.txt") from exc

    pages = []

    with fitz.open(pdf_path) as document:
        for index, page in enumerate(document, start=1):
            text = _clean_text(page.get_text("text"))
            pages.append(
                {
                    "page_number": index,
                    "text": text,
                }
            )

    return pages


def _clean_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _extract_title(pages: list[dict]) -> str:
    if not pages:
        return ""

    first_page_text = pages[0]["text"]
    for line in first_page_text.splitlines():
        if 5 <= len(line) <= 180:
            return line

    return ""


def _extract_abstract(full_text: str) -> str:
    if not full_text:
        return ""

    lowered_text = full_text.lower()
    markers = ["abstract", "摘要"]
    end_markers = ["keywords", "key words", "introduction", "关键词", "引言"]

    start = -1
    for marker in markers:
        index = lowered_text.find(marker.lower())
        if index != -1:
            start = index + len(marker)
            break

    if start == -1:
        return ""

    end_candidates = [
        lowered_text.find(marker.lower(), start)
        for marker in end_markers
        if lowered_text.find(marker.lower(), start) != -1
    ]
    end = min(end_candidates) if end_candidates else start + 1500

    return _clean_text(full_text[start:end])


def _build_page_sections(pages: list[dict]) -> list[dict]:
    return [
        {
            "title": f"Page {page['page_number']}",
            "content": page["text"],
            "page_start": page["page_number"],
            "page_end": page["page_number"],
        }
        for page in pages
    ]
