import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from app.config import DATABASE_PATH
from app.core.models import (
    Conversation,
    ConversationMessage,
    GraphEntity,
    GraphExtractionRun,
    GraphRelation,
    MemoryItem,
    Project,
    ProjectEvent,
    ProjectStatus,
    User,
)

DEFAULT_USER_ID = "local"


USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    avatar_initial TEXT,
    plan TEXT NOT NULL DEFAULT 'free',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


USER_SESSIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS user_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
)
"""


CONVERSATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    project_id TEXT,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    short_summary TEXT,
    summary_updated_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (user_id),
    FOREIGN KEY (project_id) REFERENCES projects (project_id)
)
"""


CONVERSATION_MESSAGES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS conversation_messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    project_id TEXT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'text',
    metadata TEXT,
    token_count INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id),
    FOREIGN KEY (user_id) REFERENCES users (user_id),
    FOREIGN KEY (project_id) REFERENCES projects (project_id)
)
"""


MEMORY_ITEMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_items (
    memory_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    scope_id TEXT,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    normalized_key TEXT,
    importance REAL NOT NULL DEFAULT 0.5,
    confidence REAL NOT NULL DEFAULT 0.7,
    status TEXT NOT NULL DEFAULT 'active',
    source_type TEXT NOT NULL,
    source_id TEXT,
    evidence TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
)
"""


PAPERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY,
    canonical_title TEXT,
    normalized_title TEXT,
    authors TEXT,
    doi TEXT,
    arxiv_id TEXT,
    abstract TEXT,
    year INTEGER,
    venue TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


PAPER_VERSIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS paper_versions (
    paper_version_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    parser_version TEXT,
    chunker_version TEXT,
    embedding_model TEXT,
    version_number INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (paper_id) REFERENCES papers (paper_id),
    FOREIGN KEY (project_id) REFERENCES projects (project_id)
)
"""


PROJECTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'local',
    paper_id TEXT,
    paper_version_id TEXT,
    file_sha256 TEXT,
    status TEXT NOT NULL,
    current_step TEXT NOT NULL,
    progress INTEGER NOT NULL,
    original_filename TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


CHUNKS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT 'local',
    paper_id TEXT,
    paper_version_id TEXT,
    content TEXT NOT NULL,
    content_hash TEXT,
    document_title TEXT,
    section_title TEXT,
    hierarchy_path TEXT,
    page_start INTEGER,
    page_end INTEGER,
    element_type TEXT NOT NULL,
    chunk_size_tokens INTEGER NOT NULL,
    is_special_element INTEGER NOT NULL,
    is_cross_page INTEGER NOT NULL,
    is_split_sentence INTEGER NOT NULL,
    is_forced_split INTEGER NOT NULL,
    needs_review INTEGER NOT NULL,
    source_file_type TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    created_at TEXT NOT NULL
)
"""

VECTOR_INDEX_RECORDS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS vector_index_records (
    chunk_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    paper_version_id TEXT NOT NULL,
    vector_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    vector_store TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    FOREIGN KEY (chunk_id) REFERENCES document_chunks (chunk_id),
    FOREIGN KEY (project_id) REFERENCES projects (project_id),
    FOREIGN KEY (paper_id) REFERENCES papers (paper_id),
    FOREIGN KEY (paper_version_id) REFERENCES paper_versions (paper_version_id)
)
"""

PROJECT_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS project_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    step TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    duration_ms INTEGER,
    details TEXT,
    created_at TEXT NOT NULL
)
"""

GRAPH_ENTITIES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS graph_entities (
    entity_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    paper_id TEXT,
    paper_version_id TEXT,
    entity_type TEXT NOT NULL,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    description TEXT,
    importance REAL NOT NULL DEFAULT 0.5,
    confidence REAL NOT NULL DEFAULT 0.7,
    source_chunk_ids TEXT,
    evidence TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects (project_id)
)
"""

GRAPH_RELATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS graph_relations (
    relation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    paper_id TEXT,
    paper_version_id TEXT,
    source_entity_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    description TEXT,
    confidence REAL NOT NULL DEFAULT 0.7,
    source_chunk_ids TEXT,
    evidence TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects (project_id),
    FOREIGN KEY (source_entity_id) REFERENCES graph_entities (entity_id),
    FOREIGN KEY (target_entity_id) REFERENCES graph_entities (entity_id)
)
"""

GRAPH_EXTRACTION_RUNS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS graph_extraction_runs (
    run_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    paper_id TEXT,
    paper_version_id TEXT,
    status TEXT NOT NULL,
    entity_count INTEGER NOT NULL DEFAULT 0,
    relation_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects (project_id)
)
"""


def _now() -> str:
    # return datetime.utcnow().isoformat(timespec="seconds")
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_database() -> None:
    with _connect() as connection:
        connection.execute(USERS_TABLE_SQL)
        connection.execute(USER_SESSIONS_TABLE_SQL)
        connection.execute(PROJECTS_TABLE_SQL)
        connection.execute(CONVERSATIONS_TABLE_SQL)
        connection.execute(CONVERSATION_MESSAGES_TABLE_SQL)
        connection.execute(MEMORY_ITEMS_TABLE_SQL)
        connection.execute(PAPERS_TABLE_SQL)
        connection.execute(PAPER_VERSIONS_TABLE_SQL)
        connection.execute(CHUNKS_TABLE_SQL)
        connection.execute(VECTOR_INDEX_RECORDS_TABLE_SQL)
        connection.execute(PROJECT_EVENTS_TABLE_SQL)
        connection.execute(GRAPH_ENTITIES_TABLE_SQL)
        connection.execute(GRAPH_RELATIONS_TABLE_SQL)
        connection.execute(GRAPH_EXTRACTION_RUNS_TABLE_SQL)
        _ensure_projects_identity_columns(connection)
        _ensure_document_chunks_identity_columns(connection)
        _ensure_project_events_details_column(connection)
        _ensure_indexes(connection)


def create_user(
    email: str,
    password_hash: str,
    display_name: str | None = None,
) -> User:
    init_database()
    now = _now()
    user_id = uuid4().hex
    avatar_initial = _build_avatar_initial(display_name or email)

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO users (
                user_id,
                email,
                password_hash,
                display_name,
                avatar_initial,
                plan,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                email,
                password_hash,
                display_name,
                avatar_initial,
                "free",
                now,
                now,
            ),
        )

    return User(
        user_id=user_id,
        email=email,
        display_name=display_name,
        avatar_initial=avatar_initial,
        plan="free",
        created_at=now,
        updated_at=now,
    )


def get_user_by_email(email: str) -> dict | None:
    init_database()
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,),
        ).fetchone()

    return dict(row) if row is not None else None


def get_user_by_id(user_id: str) -> User | None:
    init_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT user_id, email, display_name, avatar_initial, plan, created_at, updated_at
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

    return _row_to_user(row) if row is not None else None


def create_user_session(
    user_id: str,
    token_hash: str,
    expires_at: str,
) -> str:
    init_database()
    session_id = uuid4().hex
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO user_sessions (
                session_id,
                user_id,
                token_hash,
                expires_at,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, user_id, token_hash, expires_at, _now()),
        )

    return session_id


def get_user_by_session_hash(token_hash: str) -> User | None:
    init_database()
    now = _now()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT u.user_id, u.email, u.display_name, u.avatar_initial, u.plan, u.created_at, u.updated_at
            FROM user_sessions s
            JOIN users u ON u.user_id = s.user_id
            WHERE s.token_hash = ?
              AND s.expires_at > ?
            """,
            (token_hash, now),
        ).fetchone()

    return _row_to_user(row) if row is not None else None


def delete_user_session(token_hash: str) -> None:
    init_database()
    with _connect() as connection:
        connection.execute(
            "DELETE FROM user_sessions WHERE token_hash = ?",
            (token_hash,),
        )


def get_or_create_project_conversation(
    project_id: str,
    user_id: str,
    title: str | None = None,
) -> Conversation:
    init_database()
    now = _now()

    with _connect() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM conversations
            WHERE project_id = ?
              AND user_id = ?
              AND status = 'active'
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (project_id, user_id),
        ).fetchone()
        if row is not None:
            return _row_to_conversation(row)

        conversation_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO conversations (
                conversation_id,
                user_id,
                project_id,
                title,
                status,
                short_summary,
                summary_updated_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                user_id,
                project_id,
                title,
                "active",
                None,
                None,
                now,
                now,
            ),
        )

        return Conversation(
            conversation_id=conversation_id,
            user_id=user_id,
            project_id=project_id,
            title=title,
            status="active",
            created_at=now,
            updated_at=now,
        )


def get_conversation(conversation_id: str, user_id: str) -> Conversation | None:
    init_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM conversations
            WHERE conversation_id = ?
              AND user_id = ?
            """,
            (conversation_id, user_id),
        ).fetchone()

    return _row_to_conversation(row) if row is not None else None


def list_conversation_messages(
    conversation_id: str,
    user_id: str,
    limit: int = 200,
) -> list[ConversationMessage]:
    init_database()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM conversation_messages
            WHERE conversation_id = ?
              AND user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, user_id, limit),
        ).fetchall()

    return [_row_to_conversation_message(row) for row in reversed(rows)]


def list_recent_conversation_messages(
    conversation_id: str,
    user_id: str,
    limit: int = 12,
) -> list[ConversationMessage]:
    init_database()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM conversation_messages
            WHERE conversation_id = ?
              AND user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, user_id, limit),
        ).fetchall()

    return [_row_to_conversation_message(row) for row in reversed(rows)]


def save_conversation_message(
    conversation_id: str,
    user_id: str,
    project_id: str | None,
    role: str,
    content: str,
    content_type: str = "text",
    metadata: dict | None = None,
) -> ConversationMessage:
    init_database()
    now = _now()
    message = ConversationMessage(
        message_id=uuid4().hex,
        conversation_id=conversation_id,
        user_id=user_id,
        project_id=project_id,
        role=role,
        content=content,
        content_type=content_type,
        metadata=metadata,
        token_count=_estimate_token_count(content),
        created_at=now,
    )

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO conversation_messages (
                message_id,
                conversation_id,
                user_id,
                project_id,
                role,
                content,
                content_type,
                metadata,
                token_count,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.message_id,
                message.conversation_id,
                message.user_id,
                message.project_id,
                message.role,
                message.content,
                message.content_type,
                json.dumps(message.metadata, ensure_ascii=False) if message.metadata else None,
                message.token_count,
                message.created_at,
            ),
        )
        connection.execute(
            """
            UPDATE conversations
            SET updated_at = ?
            WHERE conversation_id = ?
              AND user_id = ?
            """,
            (now, conversation_id, user_id),
        )

    return message


def update_conversation_summary(
    conversation_id: str,
    user_id: str,
    short_summary: str,
) -> None:
    init_database()
    now = _now()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE conversations
            SET short_summary = ?,
                summary_updated_at = ?,
                updated_at = ?
            WHERE conversation_id = ?
              AND user_id = ?
            """,
            (short_summary, now, now, conversation_id, user_id),
        )


def upsert_project_memory(
    project_id: str,
    user_id: str,
    memory_type: str,
    content: str,
    normalized_key: str | None = None,
    importance: float = 0.5,
    confidence: float = 0.7,
    source_type: str = "system",
    source_id: str | None = None,
    evidence: dict | None = None,
) -> MemoryItem:
    init_database()
    now = _now()
    clean_key = normalized_key.strip().lower() if normalized_key else None

    with _connect() as connection:
        existing = None
        if clean_key:
            existing = connection.execute(
                """
                SELECT *
                FROM memory_items
                WHERE user_id = ?
                  AND scope = 'project'
                  AND scope_id = ?
                  AND memory_type = ?
                  AND normalized_key = ?
                LIMIT 1
                """,
                (user_id, project_id, memory_type, clean_key),
            ).fetchone()

        if existing is not None:
            connection.execute(
                """
                UPDATE memory_items
                SET content = ?,
                    importance = ?,
                    confidence = ?,
                    status = 'active',
                    source_type = ?,
                    source_id = ?,
                    evidence = ?,
                    updated_at = ?
                WHERE memory_id = ?
                """,
                (
                    content,
                    importance,
                    confidence,
                    source_type,
                    source_id,
                    json.dumps(evidence, ensure_ascii=False) if evidence else None,
                    now,
                    existing["memory_id"],
                ),
            )
            row = connection.execute(
                "SELECT * FROM memory_items WHERE memory_id = ?",
                (existing["memory_id"],),
            ).fetchone()
            return _row_to_memory_item(row)

        memory_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO memory_items (
                memory_id,
                user_id,
                scope,
                scope_id,
                memory_type,
                content,
                normalized_key,
                importance,
                confidence,
                status,
                source_type,
                source_id,
                evidence,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                user_id,
                "project",
                project_id,
                memory_type,
                content,
                clean_key,
                importance,
                confidence,
                "active",
                source_type,
                source_id,
                json.dumps(evidence, ensure_ascii=False) if evidence else None,
                now,
                now,
            ),
        )

        return MemoryItem(
            memory_id=memory_id,
            user_id=user_id,
            scope="project",
            scope_id=project_id,
            memory_type=memory_type,
            content=content,
            normalized_key=clean_key,
            importance=importance,
            confidence=confidence,
            status="active",
            source_type=source_type,
            source_id=source_id,
            evidence=evidence,
            created_at=now,
            updated_at=now,
        )


def list_project_memories(
    project_id: str,
    user_id: str,
    status: str = "active",
    limit: int = 50,
) -> list[MemoryItem]:
    init_database()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM memory_items
            WHERE user_id = ?
              AND scope = 'project'
              AND scope_id = ?
              AND status = ?
            ORDER BY importance DESC, updated_at DESC
            LIMIT ?
            """,
            (user_id, project_id, status, limit),
        ).fetchall()

    return [_row_to_memory_item(row) for row in rows]


def upsert_user_memory(
    user_id: str,
    memory_type: str,
    content: str,
    normalized_key: str | None = None,
    importance: float = 0.5,
    confidence: float = 0.7,
    source_type: str = "system",
    source_id: str | None = None,
    evidence: dict | None = None,
) -> MemoryItem:
    init_database()
    now = _now()
    clean_key = normalized_key.strip().lower() if normalized_key else None

    with _connect() as connection:
        existing = None
        if clean_key:
            existing = connection.execute(
                """
                SELECT *
                FROM memory_items
                WHERE user_id = ?
                  AND scope = 'user'
                  AND scope_id IS NULL
                  AND memory_type = ?
                  AND normalized_key = ?
                LIMIT 1
                """,
                (user_id, memory_type, clean_key),
            ).fetchone()

        if existing is not None:
            connection.execute(
                """
                UPDATE memory_items
                SET content = ?,
                    importance = ?,
                    confidence = ?,
                    status = 'active',
                    source_type = ?,
                    source_id = ?,
                    evidence = ?,
                    updated_at = ?
                WHERE memory_id = ?
                """,
                (
                    content,
                    importance,
                    confidence,
                    source_type,
                    source_id,
                    json.dumps(evidence, ensure_ascii=False) if evidence else None,
                    now,
                    existing["memory_id"],
                ),
            )
            row = connection.execute(
                "SELECT * FROM memory_items WHERE memory_id = ?",
                (existing["memory_id"],),
            ).fetchone()
            return _row_to_memory_item(row)

        memory_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO memory_items (
                memory_id,
                user_id,
                scope,
                scope_id,
                memory_type,
                content,
                normalized_key,
                importance,
                confidence,
                status,
                source_type,
                source_id,
                evidence,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                user_id,
                "user",
                None,
                memory_type,
                content,
                clean_key,
                importance,
                confidence,
                "active",
                source_type,
                source_id,
                json.dumps(evidence, ensure_ascii=False) if evidence else None,
                now,
                now,
            ),
        )

        return MemoryItem(
            memory_id=memory_id,
            user_id=user_id,
            scope="user",
            scope_id=None,
            memory_type=memory_type,
            content=content,
            normalized_key=clean_key,
            importance=importance,
            confidence=confidence,
            status="active",
            source_type=source_type,
            source_id=source_id,
            evidence=evidence,
            created_at=now,
            updated_at=now,
        )


def list_user_memories(
    user_id: str,
    status: str = "active",
    limit: int = 50,
    memory_type: str | None = None,
) -> list[MemoryItem]:
    init_database()
    params: list[object] = [user_id, status]
    type_filter = ""
    if memory_type:
        type_filter = "AND memory_type = ?"
        params.append(memory_type)
    params.append(limit)

    with _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM memory_items
            WHERE user_id = ?
              AND scope = 'user'
              AND scope_id IS NULL
              AND status = ?
              {type_filter}
            ORDER BY importance DESC, updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()

    return [_row_to_memory_item(row) for row in rows]


def get_memory_item(memory_id: str, user_id: str) -> MemoryItem | None:
    init_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM memory_items
            WHERE memory_id = ?
              AND user_id = ?
            """,
            (memory_id, user_id),
        ).fetchone()

    return _row_to_memory_item(row) if row is not None else None


def update_memory_item_content(
    memory_id: str,
    user_id: str,
    content: str,
    memory_type: str | None = None,
    importance: float | None = None,
    confidence: float | None = None,
) -> MemoryItem | None:
    init_database()
    existing = get_memory_item(memory_id, user_id)
    if existing is None or existing.scope != "user":
        return None

    updated_type = memory_type or existing.memory_type
    updated_importance = existing.importance if importance is None else importance
    updated_confidence = existing.confidence if confidence is None else confidence
    now = _now()

    with _connect() as connection:
        connection.execute(
            """
            UPDATE memory_items
            SET content = ?,
                memory_type = ?,
                importance = ?,
                confidence = ?,
                updated_at = ?
            WHERE memory_id = ?
              AND user_id = ?
              AND scope = 'user'
            """,
            (
                content,
                updated_type,
                updated_importance,
                updated_confidence,
                now,
                memory_id,
                user_id,
            ),
        )
        row = connection.execute(
            "SELECT * FROM memory_items WHERE memory_id = ? AND user_id = ?",
            (memory_id, user_id),
        ).fetchone()

    return _row_to_memory_item(row) if row is not None else None


def update_memory_item_status(
    memory_id: str,
    user_id: str,
    status: str,
) -> MemoryItem | None:
    init_database()
    existing = get_memory_item(memory_id, user_id)
    if existing is None or existing.scope != "user":
        return None

    now = _now()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE memory_items
            SET status = ?,
                updated_at = ?
            WHERE memory_id = ?
              AND user_id = ?
              AND scope = 'user'
            """,
            (status, now, memory_id, user_id),
        )
        row = connection.execute(
            "SELECT * FROM memory_items WHERE memory_id = ? AND user_id = ?",
            (memory_id, user_id),
        ).fetchone()

    return _row_to_memory_item(row) if row is not None else None


def save_project_graph(project_id: str, user_id: str, graph: dict) -> dict:
    init_database()
    now = _now()
    entities = graph.get("entities") if isinstance(graph.get("entities"), list) else []
    relations = graph.get("relations") if isinstance(graph.get("relations"), list) else []

    with _connect() as connection:
        project_row = connection.execute(
            """
            SELECT paper_id, paper_version_id
            FROM projects
            WHERE project_id = ?
              AND user_id = ?
            """,
            (project_id, user_id),
        ).fetchone()
        if project_row is None:
            return {"entity_count": 0, "relation_count": 0}

        paper_id = project_row["paper_id"]
        paper_version_id = project_row["paper_version_id"]

        _delete_project_graph(connection, project_id, user_id)

        entity_id_by_key: dict[str, str] = {}
        entity_rows = []
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            name = _clean_text(entity.get("name"))
            entity_type = _clean_text(entity.get("entity_type"))
            normalized_name = _clean_text(entity.get("normalized_name")) or _normalize_graph_name(name)
            if not name or not entity_type or not normalized_name:
                continue

            key = _graph_entity_key(entity_type, normalized_name)
            if key in entity_id_by_key:
                continue

            entity_id = uuid4().hex
            entity_id_by_key[key] = entity_id
            entity_rows.append(
                (
                    entity_id,
                    user_id,
                    project_id,
                    paper_id,
                    paper_version_id,
                    entity_type,
                    name,
                    normalized_name,
                    _clean_text(entity.get("description")) or None,
                    _safe_float(entity.get("importance"), 0.5),
                    _safe_float(entity.get("confidence"), 0.7),
                    json.dumps(_string_list(entity.get("source_chunk_ids")), ensure_ascii=False),
                    _clean_text(entity.get("evidence")) or None,
                    now,
                    now,
                )
            )

        if entity_rows:
            connection.executemany(
                """
                INSERT INTO graph_entities (
                    entity_id,
                    user_id,
                    project_id,
                    paper_id,
                    paper_version_id,
                    entity_type,
                    name,
                    normalized_name,
                    description,
                    importance,
                    confidence,
                    source_chunk_ids,
                    evidence,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                entity_rows,
            )

        relation_keys: set[str] = set()
        relation_rows = []
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            source_key = _resolve_relation_entity_key(relation.get("source"), relation.get("source_entity_type"), entity_id_by_key)
            target_key = _resolve_relation_entity_key(relation.get("target"), relation.get("target_entity_type"), entity_id_by_key)
            source_entity_id = entity_id_by_key.get(source_key)
            target_entity_id = entity_id_by_key.get(target_key)
            relation_type = _clean_text(relation.get("relation_type"))
            if not source_entity_id or not target_entity_id or not relation_type:
                continue

            relation_key = f"{source_entity_id}:{relation_type}:{target_entity_id}"
            if relation_key in relation_keys:
                continue
            relation_keys.add(relation_key)

            relation_rows.append(
                (
                    uuid4().hex,
                    user_id,
                    project_id,
                    paper_id,
                    paper_version_id,
                    source_entity_id,
                    target_entity_id,
                    relation_type,
                    _clean_text(relation.get("description")) or None,
                    _safe_float(relation.get("confidence"), 0.7),
                    json.dumps(_string_list(relation.get("source_chunk_ids")), ensure_ascii=False),
                    _clean_text(relation.get("evidence")) or None,
                    now,
                    now,
                )
            )

        if relation_rows:
            connection.executemany(
                """
                INSERT INTO graph_relations (
                    relation_id,
                    user_id,
                    project_id,
                    paper_id,
                    paper_version_id,
                    source_entity_id,
                    target_entity_id,
                    relation_type,
                    description,
                    confidence,
                    source_chunk_ids,
                    evidence,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                relation_rows,
            )

    return {"entity_count": len(entity_rows), "relation_count": len(relation_rows)}


def delete_project_graph(project_id: str, user_id: str) -> None:
    init_database()
    with _connect() as connection:
        _delete_project_graph(connection, project_id, user_id)


def list_project_graph_entities(project_id: str, user_id: str) -> list[GraphEntity]:
    init_database()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM graph_entities
            WHERE project_id = ?
              AND user_id = ?
            ORDER BY importance DESC, confidence DESC, name ASC
            """,
            (project_id, user_id),
        ).fetchall()

    return [_row_to_graph_entity(row) for row in rows]


def list_project_graph_relations(project_id: str, user_id: str) -> list[GraphRelation]:
    init_database()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM graph_relations
            WHERE project_id = ?
              AND user_id = ?
            ORDER BY confidence DESC, relation_type ASC
            """,
            (project_id, user_id),
        ).fetchall()

    return [_row_to_graph_relation(row) for row in rows]


def get_graph_entity(entity_id: str, user_id: str) -> GraphEntity | None:
    init_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM graph_entities
            WHERE entity_id = ?
              AND user_id = ?
            """,
            (entity_id, user_id),
        ).fetchone()

    return _row_to_graph_entity(row) if row is not None else None


def list_entity_relations(entity_id: str, user_id: str) -> list[GraphRelation]:
    init_database()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM graph_relations
            WHERE user_id = ?
              AND (source_entity_id = ? OR target_entity_id = ?)
            ORDER BY confidence DESC, relation_type ASC
            """,
            (user_id, entity_id, entity_id),
        ).fetchall()

    return [_row_to_graph_relation(row) for row in rows]


def record_graph_extraction_run(
    project_id: str,
    user_id: str,
    status: str,
    entity_count: int = 0,
    relation_count: int = 0,
    error_message: str | None = None,
) -> GraphExtractionRun:
    init_database()
    now = _now()

    with _connect() as connection:
        _, paper_id, paper_version_id = _get_project_paper_identity(connection, project_id)
        run_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO graph_extraction_runs (
                run_id,
                user_id,
                project_id,
                paper_id,
                paper_version_id,
                status,
                entity_count,
                relation_count,
                error_message,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                user_id,
                project_id,
                paper_id,
                paper_version_id,
                status,
                entity_count,
                relation_count,
                error_message,
                now,
                now,
            ),
        )

    return GraphExtractionRun(
        run_id=run_id,
        user_id=user_id,
        project_id=project_id,
        paper_id=paper_id,
        paper_version_id=paper_version_id,
        status=status,
        entity_count=entity_count,
        relation_count=relation_count,
        error_message=error_message,
        created_at=now,
        updated_at=now,
    )


def create_chunks_table() -> None:
    with _connect() as connection:
        connection.execute(CHUNKS_TABLE_SQL)
        _ensure_document_chunks_identity_columns(connection)


def create_project_events_table() -> None:
    with _connect() as connection:
        connection.execute(PROJECT_EVENTS_TABLE_SQL)
        _ensure_project_events_details_column(connection)


def create_project(
    project_id: str,
    original_filename: str,
    pdf_path: Path,
    user_id: str = DEFAULT_USER_ID,
    paper_id: str | None = None,
    paper_version_id: str | None = None,
    file_sha256: str | None = None,
) -> Project:
    init_database()
    now = _now()
    project = Project(
        project_id=project_id,
        status=ProjectStatus.UPLOADED,
        current_step="论文已上传",
        progress=5,
        original_filename=original_filename,
        pdf_path=str(pdf_path),
        user_id=user_id,
        paper_id=paper_id,
        paper_version_id=paper_version_id,
        file_sha256=file_sha256,
        created_at=now,
        updated_at=now,
    )

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO projects (
                project_id,
                user_id,
                paper_id,
                paper_version_id,
                file_sha256,
                status,
                current_step,
                progress,
                original_filename,
                pdf_path,
                error_message,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project.project_id,
                project.user_id,
                project.paper_id,
                project.paper_version_id,
                project.file_sha256,
                project.status,
                project.current_step,
                project.progress,
                project.original_filename,
                project.pdf_path,
                project.error_message,
                project.created_at,
                project.updated_at,
            ),
        )

    return project


def find_or_create_paper_identity(
    file_sha256: str,
    user_id: str = DEFAULT_USER_ID,
) -> str:
    init_database()
    now = _now()

    with _connect() as connection:
        existing = connection.execute(
            """
            SELECT paper_id
            FROM paper_versions
            WHERE user_id = ? AND file_sha256 = ?
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (user_id, file_sha256),
        ).fetchone()

        if existing is not None:
            return existing["paper_id"]

        paper_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO papers (
                paper_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?)
            """,
            (paper_id, now, now),
        )
        return paper_id


def create_paper_version(
    paper_id: str,
    project_id: str,
    file_sha256: str,
    original_filename: str,
    pdf_path: Path,
    user_id: str = DEFAULT_USER_ID,
    parser_version: str | None = None,
    chunker_version: str | None = None,
    embedding_model: str | None = None,
) -> str:
    init_database()
    paper_version_id = uuid4().hex
    now = _now()

    with _connect() as connection:
        version_number = _next_paper_version_number(connection, paper_id, user_id)
        connection.execute(
            """
            INSERT INTO paper_versions (
                paper_version_id,
                paper_id,
                user_id,
                project_id,
                file_sha256,
                original_filename,
                pdf_path,
                parser_version,
                chunker_version,
                embedding_model,
                version_number,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_version_id,
                paper_id,
                user_id,
                project_id,
                file_sha256,
                original_filename,
                str(pdf_path),
                parser_version,
                chunker_version,
                embedding_model,
                version_number,
                now,
            ),
        )

    return paper_version_id


def update_project_paper_version(
    project_id: str,
    paper_version_id: str,
) -> None:
    init_database()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE projects
            SET paper_version_id = ?,
                updated_at = ?
            WHERE project_id = ?
            """,
            (paper_version_id, _now(), project_id),
        )


def get_project(project_id: str) -> Project | None:
    init_database()
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()

    if row is None:
        return None

    return Project(
        project_id=row["project_id"],
        status=ProjectStatus(row["status"]),
        current_step=row["current_step"],
        progress=row["progress"],
        original_filename=row["original_filename"],
        pdf_path=row["pdf_path"],
        user_id=row["user_id"],
        paper_id=row["paper_id"],
        paper_version_id=row["paper_version_id"],
        file_sha256=row["file_sha256"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def list_projects_by_user(user_id: str, limit: int = 100) -> list[Project]:
    init_database()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM projects
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()

    return [
        Project(
            project_id=row["project_id"],
            status=ProjectStatus(row["status"]),
            current_step=row["current_step"],
            progress=row["progress"],
            original_filename=row["original_filename"],
            pdf_path=row["pdf_path"],
            user_id=row["user_id"],
            paper_id=row["paper_id"],
            paper_version_id=row["paper_version_id"],
            file_sha256=row["file_sha256"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def update_project_status(
    project_id: str,
    status: ProjectStatus,
    current_step: str,
    progress: int,
    error_message: str | None = None,
) -> None:
    init_database()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE projects
            SET status = ?,
                current_step = ?,
                progress = ?,
                error_message = ?,
                updated_at = ?
            WHERE project_id = ?
            """,
            (
                status,
                current_step,
                progress,
                error_message,
                _now(),
                project_id,
            ),
        )


def add_project_event(
    project_id: str,
    step: str,
    message: str,
    level: str = "info",
    duration_ms: int | None = None,
    details: dict | None = None,
) -> None:
    create_project_events_table()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO project_events (
                project_id,
                step,
                level,
                message,
                duration_ms,
                details,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                step,
                level,
                message,
                duration_ms,
                json.dumps(details, ensure_ascii=False) if details else None,
                _now(),
            ),
        )


def list_project_events(project_id: str, limit: int = 50) -> list[ProjectEvent]:
    create_project_events_table()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT step, level, message, duration_ms, details, created_at
            FROM project_events
            WHERE project_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()

    events = [
        ProjectEvent(
            step=row["step"],
            level=row["level"],
            message=row["message"],
            duration_ms=row["duration_ms"],
            details=_decode_details(row["details"]),
            created_at=row["created_at"],
        )
        for row in rows
    ]
    return list(reversed(events))


def save_document_chunks(project_id: str, chunks: list[dict]) -> None:
    init_database()
    now = _now()

    with _connect() as connection:
        user_id, paper_id, paper_version_id = _get_project_paper_identity(connection, project_id)
        connection.execute(
            "DELETE FROM document_chunks WHERE project_id = ?",
            (project_id,),
        )
        connection.executemany(
            """
            INSERT INTO document_chunks (
                chunk_id,
                project_id,
                user_id,
                paper_id,
                paper_version_id,
                content,
                content_hash,
                document_title,
                section_title,
                hierarchy_path,
                page_start,
                page_end,
                element_type,
                chunk_size_tokens,
                is_special_element,
                is_cross_page,
                is_split_sentence,
                is_forced_split,
                needs_review,
                source_file_type,
                order_index,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                _chunk_to_row(project_id, user_id, paper_id, paper_version_id, chunk, now)
                for chunk in chunks
            ],
        )


def list_document_chunks(project_id: str) -> list[dict]:
    create_chunks_table()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM document_chunks
            WHERE project_id = ?
            ORDER BY order_index ASC
            """,
            (project_id,),
        ).fetchall()

    return [_row_to_chunk(row) for row in rows]


def list_document_chunks_by_ids(project_id: str, chunk_ids: list[str]) -> list[dict]:
    create_chunks_table()
    if not chunk_ids:
        return []

    placeholders = ",".join("?" for _ in chunk_ids)
    with _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM document_chunks
            WHERE project_id = ?
              AND chunk_id IN ({placeholders})
            """,
            (project_id, *chunk_ids),
        ).fetchall()

    chunks_by_id = {row["chunk_id"]: _row_to_chunk(row) for row in rows}
    return [chunks_by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in chunks_by_id]


def delete_document_chunks(project_id: str) -> None:
    create_chunks_table()
    with _connect() as connection:
        connection.execute(
            "DELETE FROM document_chunks WHERE project_id = ?",
            (project_id,),
        )


def save_vector_index_records(records: list[dict]) -> None:
    init_database()
    if not records:
        return

    with _connect() as connection:
        connection.executemany(
            """
            INSERT OR REPLACE INTO vector_index_records (
                chunk_id,
                project_id,
                paper_id,
                paper_version_id,
                vector_id,
                content_hash,
                embedding_model,
                vector_store,
                indexed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [_vector_index_record_to_row(record) for record in records],
        )


def delete_vector_index_records(project_id: str) -> None:
    init_database()
    with _connect() as connection:
        connection.execute(
            "DELETE FROM vector_index_records WHERE project_id = ?",
            (project_id,),
        )


def _chunk_to_row(
    project_id: str,
    user_id: str | None,
    paper_id: str | None,
    paper_version_id: str | None,
    chunk: dict,
    created_at: str,
) -> tuple:
    metadata = chunk.get("metadata", {})
    content = chunk.get("content", "")
    return (
        chunk.get("chunk_id", ""),
        project_id,
        user_id or DEFAULT_USER_ID,
        paper_id,
        paper_version_id,
        content,
        _calculate_content_hash(content),
        metadata.get("document_title", ""),
        metadata.get("section_title", ""),
        metadata.get("hierarchy_path", ""),
        metadata.get("page_start"),
        metadata.get("page_end"),
        metadata.get("element_type", "unknown"),
        int(metadata.get("chunk_size_tokens", 0)),
        _bool_to_int(metadata.get("is_special_element", False)),
        _bool_to_int(metadata.get("is_cross_page", False)),
        _bool_to_int(metadata.get("is_split_sentence", False)),
        _bool_to_int(metadata.get("is_forced_split", False)),
        _bool_to_int(metadata.get("needs_review", False)),
        metadata.get("source_file_type", ""),
        int(metadata.get("order_index", 0)),
        created_at,
    )


def _row_to_chunk(row: sqlite3.Row) -> dict:
    metadata = {
        "document_id": row["project_id"],
        "project_id": row["project_id"],
        "user_id": row["user_id"],
        "paper_id": row["paper_id"],
        "paper_version_id": row["paper_version_id"],
        "content_hash": row["content_hash"],
        "document_title": row["document_title"] or "",
        "section_title": row["section_title"] or "",
        "hierarchy_path": row["hierarchy_path"] or "",
        "page_start": row["page_start"],
        "page_end": row["page_end"],
        "element_type": row["element_type"],
        "chunk_size_tokens": row["chunk_size_tokens"],
        "is_special_element": bool(row["is_special_element"]),
        "is_cross_page": bool(row["is_cross_page"]),
        "is_split_sentence": bool(row["is_split_sentence"]),
        "is_forced_split": bool(row["is_forced_split"]),
        "needs_review": bool(row["needs_review"]),
        "source_file_type": row["source_file_type"],
        "order_index": row["order_index"],
    }
    return {
        "chunk_id": row["chunk_id"],
        "content": row["content"],
        "title": metadata["section_title"],
        "page_start": metadata["page_start"],
        "page_end": metadata["page_end"],
        "metadata": metadata,
    }


def _bool_to_int(value: object) -> int:
    return 1 if bool(value) else 0


def _calculate_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _get_project_paper_identity(
    connection: sqlite3.Connection,
    project_id: str,
) -> tuple[str | None, str | None, str | None]:
    row = connection.execute(
        """
        SELECT user_id, paper_id, paper_version_id
        FROM projects
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    if row is None:
        return None, None, None
    return row["user_id"], row["paper_id"], row["paper_version_id"]


def _vector_index_record_to_row(record: dict) -> tuple:
    return (
        record["chunk_id"],
        record["project_id"],
        record["paper_id"],
        record["paper_version_id"],
        record["vector_id"],
        record["content_hash"],
        record["embedding_model"],
        record["vector_store"],
        record["indexed_at"],
    )


def _delete_project_graph(
    connection: sqlite3.Connection,
    project_id: str,
    user_id: str,
) -> None:
    connection.execute(
        "DELETE FROM graph_relations WHERE project_id = ? AND user_id = ?",
        (project_id, user_id),
    )
    connection.execute(
        "DELETE FROM graph_entities WHERE project_id = ? AND user_id = ?",
        (project_id, user_id),
    )


def _row_to_graph_entity(row: sqlite3.Row) -> GraphEntity:
    return GraphEntity(
        entity_id=row["entity_id"],
        user_id=row["user_id"],
        project_id=row["project_id"],
        paper_id=row["paper_id"],
        paper_version_id=row["paper_version_id"],
        entity_type=row["entity_type"],
        name=row["name"],
        normalized_name=row["normalized_name"],
        description=row["description"],
        importance=float(row["importance"]),
        confidence=float(row["confidence"]),
        source_chunk_ids=_decode_string_list(row["source_chunk_ids"]),
        evidence=row["evidence"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_graph_relation(row: sqlite3.Row) -> GraphRelation:
    return GraphRelation(
        relation_id=row["relation_id"],
        user_id=row["user_id"],
        project_id=row["project_id"],
        paper_id=row["paper_id"],
        paper_version_id=row["paper_version_id"],
        source_entity_id=row["source_entity_id"],
        target_entity_id=row["target_entity_id"],
        relation_type=row["relation_type"],
        description=row["description"],
        confidence=float(row["confidence"]),
        source_chunk_ids=_decode_string_list(row["source_chunk_ids"]),
        evidence=row["evidence"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _graph_entity_key(entity_type: str, normalized_name: str) -> str:
    return f"{entity_type.strip().lower()}::{normalized_name.strip().lower()}"


def _resolve_relation_entity_key(
    name: object,
    entity_type: object,
    entity_id_by_key: dict[str, str],
) -> str:
    normalized_name = _normalize_graph_name(_clean_text(name))
    clean_type = _clean_text(entity_type)
    if clean_type:
        return _graph_entity_key(clean_type, normalized_name)

    matches = [
        key
        for key in entity_id_by_key
        if key.endswith(f"::{normalized_name}")
    ]
    return matches[0] if len(matches) == 1 else ""


def _normalize_graph_name(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _clean_text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _safe_float(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(parsed, 1.0))


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = [value]
    else:
        return []

    result = []
    for item in raw_items:
        text = _clean_text(item)
        if text and text not in result:
            result.append(text)
    return result


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        user_id=row["user_id"],
        email=row["email"],
        display_name=row["display_name"],
        avatar_initial=row["avatar_initial"],
        plan=row["plan"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_conversation(row: sqlite3.Row) -> Conversation:
    return Conversation(
        conversation_id=row["conversation_id"],
        user_id=row["user_id"],
        project_id=row["project_id"],
        title=row["title"],
        status=row["status"],
        short_summary=row["short_summary"],
        summary_updated_at=row["summary_updated_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_conversation_message(row: sqlite3.Row) -> ConversationMessage:
    return ConversationMessage(
        message_id=row["message_id"],
        conversation_id=row["conversation_id"],
        user_id=row["user_id"],
        project_id=row["project_id"],
        role=row["role"],
        content=row["content"],
        content_type=row["content_type"],
        metadata=_decode_details(row["metadata"]),
        token_count=row["token_count"],
        created_at=row["created_at"],
    )


def _row_to_memory_item(row: sqlite3.Row) -> MemoryItem:
    return MemoryItem(
        memory_id=row["memory_id"],
        user_id=row["user_id"],
        scope=row["scope"],
        scope_id=row["scope_id"],
        memory_type=row["memory_type"],
        content=row["content"],
        normalized_key=row["normalized_key"],
        importance=float(row["importance"]),
        confidence=float(row["confidence"]),
        status=row["status"],
        source_type=row["source_type"],
        source_id=row["source_id"],
        evidence=_decode_details(row["evidence"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _build_avatar_initial(value: str) -> str:
    stripped = value.strip()
    return stripped[:1].upper() if stripped else "U"


def _next_paper_version_number(
    connection: sqlite3.Connection,
    paper_id: str,
    user_id: str,
) -> int:
    row = connection.execute(
        """
        SELECT COALESCE(MAX(version_number), 0) AS max_version_number
        FROM paper_versions
        WHERE paper_id = ? AND user_id = ?
        """,
        (paper_id, user_id),
    ).fetchone()
    return int(row["max_version_number"]) + 1


def _ensure_projects_identity_columns(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        "projects",
        {
            "user_id": "TEXT NOT NULL DEFAULT 'local'",
            "paper_id": "TEXT",
            "paper_version_id": "TEXT",
            "file_sha256": "TEXT",
        },
    )


def _ensure_document_chunks_identity_columns(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        "document_chunks",
        {
            "user_id": "TEXT NOT NULL DEFAULT 'local'",
            "paper_id": "TEXT",
            "paper_version_id": "TEXT",
            "content_hash": "TEXT",
        },
    )


def _ensure_project_events_details_column(connection: sqlite3.Connection) -> None:
    _ensure_columns(connection, "project_events", {"details": "TEXT"})


def _ensure_columns(
    connection: sqlite3.Connection,
    table_name: str,
    columns: dict[str, str],
) -> None:
    existing_columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing_column_names = {column["name"] for column in existing_columns}
    for column_name, column_type in columns.items():
        if column_name not in existing_column_names:
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
            )


def _ensure_indexes(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users (email)")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_sessions_token_hash ON user_sessions (token_hash)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions (user_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_project_user ON conversations (project_id, user_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation ON conversation_messages (conversation_id, created_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversation_messages_user ON conversation_messages (user_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_items_project ON memory_items (user_id, scope, scope_id, status)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_items_user ON memory_items (user_id, scope, status)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_items_key ON memory_items (user_id, scope, scope_id, memory_type, normalized_key)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_versions_paper_id ON paper_versions (paper_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_versions_project_id ON paper_versions (project_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects (user_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_projects_paper_id ON projects (paper_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_project_id ON document_chunks (project_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_user_id ON document_chunks (user_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_paper_version_id ON document_chunks (paper_version_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_vectors_project_id ON vector_index_records (project_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_vectors_paper_version_id ON vector_index_records (paper_version_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_entities_project ON graph_entities (user_id, project_id, entity_type)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_entities_name ON graph_entities (project_id, normalized_name)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_relations_project ON graph_relations (user_id, project_id, relation_type)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_relations_source ON graph_relations (source_entity_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_relations_target ON graph_relations (target_entity_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_runs_project ON graph_extraction_runs (user_id, project_id, created_at)"
    )


def _decode_details(value: str | None) -> dict | None:
    if not value:
        return None

    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return None

    return decoded if isinstance(decoded, dict) else None


def _decode_string_list(value: str | None) -> list[str]:
    if not value:
        return []

    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []

    if not isinstance(decoded, list):
        return []
    return [_clean_text(item) for item in decoded if _clean_text(item)]


def _estimate_token_count(content: str) -> int:
    stripped = content.strip()
    if not stripped:
        return 0
    return max(1, len(stripped) // 4)
