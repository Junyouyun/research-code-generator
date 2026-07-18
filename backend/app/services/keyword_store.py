from __future__ import annotations

import re
import sqlite3

from app.config import DATABASE_PATH


def search_keyword_chunks(
    paper_version_id: str,
    user_id: str,
    queries: list[str],
    per_query_k: int = 12,
) -> dict:
    _ensure_fts_table()
    _ensure_paper_version_index(paper_version_id, user_id)

    candidates: dict[str, dict] = {}
    query_results = []
    with _connect() as connection:
        for query in queries:
            match_query = _to_fts_query(query)
            if not match_query:
                continue
            try:
                rows = connection.execute(
                    """
                    SELECT
                        chunk_id,
                        project_id,
                        paper_version_id,
                        user_id,
                        document_title,
                        section_title,
                        hierarchy_path,
                        page_start,
                        page_end,
                        element_type,
                        order_index,
                        bm25(document_chunks_fts) AS bm25_score
                    FROM document_chunks_fts
                    WHERE document_chunks_fts MATCH ?
                      AND paper_version_id = ?
                      AND user_id = ?
                    ORDER BY bm25_score ASC
                    LIMIT ?
                    """,
                    (match_query, paper_version_id, user_id, per_query_k),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []

            returned_ids = []
            for rank, row in enumerate(rows, start=1):
                chunk_id = row["chunk_id"]
                returned_ids.append(chunk_id)
                score = 1.0 / rank
                candidate = candidates.setdefault(
                    chunk_id,
                    {
                        "chunk_id": chunk_id,
                        "project_id": row["project_id"],
                        "paper_version_id": row["paper_version_id"],
                        "user_id": row["user_id"],
                        "document_title": row["document_title"] or "",
                        "section_title": row["section_title"] or "",
                        "hierarchy_path": row["hierarchy_path"] or "",
                        "page_start": row["page_start"],
                        "page_end": row["page_end"],
                        "element_type": row["element_type"] or "",
                        "order_index": row["order_index"],
                        "keyword_score": 0.0,
                        "keyword_source_queries": [],
                        "keyword_ranks": {},
                        "retrieval_sources": ["keyword"],
                    },
                )
                candidate["keyword_score"] = max(float(candidate.get("keyword_score") or 0.0), score)
                candidate["keyword_ranks"][query] = rank
                if query not in candidate["keyword_source_queries"]:
                    candidate["keyword_source_queries"].append(query)

            query_results.append(
                {
                    "query": query,
                    "match_query": match_query,
                    "returned_chunk_ids": returned_ids,
                }
            )

    return {"hits": list(candidates.values()), "query_results": query_results}


def _ensure_paper_version_index(paper_version_id: str, user_id: str) -> None:
    with _connect() as connection:
        indexed_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM document_chunks_fts
            WHERE paper_version_id = ?
              AND user_id = ?
            """,
            (paper_version_id, user_id),
        ).fetchone()[0]
        chunk_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM document_chunks
            WHERE paper_version_id = ?
              AND user_id = ?
            """,
            (paper_version_id, user_id),
        ).fetchone()[0]
        if indexed_count == chunk_count and indexed_count > 0:
            return

        connection.execute(
            """
            DELETE FROM document_chunks_fts
            WHERE paper_version_id = ?
              AND user_id = ?
            """,
            (paper_version_id, user_id),
        )
        rows = connection.execute(
            """
            SELECT
                chunk_id,
                project_id,
                paper_version_id,
                user_id,
                document_title,
                section_title,
                hierarchy_path,
                page_start,
                page_end,
                element_type,
                order_index,
                content
            FROM document_chunks
            WHERE paper_version_id = ?
              AND user_id = ?
            ORDER BY order_index ASC
            """,
            (paper_version_id, user_id),
        ).fetchall()
        connection.executemany(
            """
            INSERT INTO document_chunks_fts (
                chunk_id,
                project_id,
                paper_version_id,
                user_id,
                document_title,
                section_title,
                hierarchy_path,
                page_start,
                page_end,
                element_type,
                order_index,
                content
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["chunk_id"],
                    row["project_id"],
                    row["paper_version_id"],
                    row["user_id"],
                    row["document_title"] or "",
                    row["section_title"] or "",
                    row["hierarchy_path"] or "",
                    row["page_start"],
                    row["page_end"],
                    row["element_type"] or "",
                    row["order_index"],
                    row["content"] or "",
                )
                for row in rows
            ],
        )


def _ensure_fts_table() -> None:
    with _connect() as connection:
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
                chunk_id UNINDEXED,
                project_id UNINDEXED,
                paper_version_id UNINDEXED,
                user_id UNINDEXED,
                document_title,
                section_title,
                hierarchy_path,
                page_start UNINDEXED,
                page_end UNINDEXED,
                element_type UNINDEXED,
                order_index UNINDEXED,
                content
            )
            """
        )


def _to_fts_query(query: str) -> str:
    tokens = []
    for token in re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+", str(query or "").lower()):
        if len(token) < 2 or token in _STOPWORDS:
            continue
        if token not in tokens:
            tokens.append(token)
        if len(tokens) >= 12:
            break
    return " OR ".join(tokens)


def _connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "what",
    "which",
    "paper",
    "method",
    "这篇论文",
    "什么",
    "哪些",
}
