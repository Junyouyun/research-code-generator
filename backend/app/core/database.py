import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from app.config import DATABASE_PATH
from app.core.models import Project, ProjectEvent, ProjectStatus, User

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
        connection.execute(PAPERS_TABLE_SQL)
        connection.execute(PAPER_VERSIONS_TABLE_SQL)
        connection.execute(CHUNKS_TABLE_SQL)
        connection.execute(VECTOR_INDEX_RECORDS_TABLE_SQL)
        connection.execute(PROJECT_EVENTS_TABLE_SQL)
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


def _decode_details(value: str | None) -> dict | None:
    if not value:
        return None

    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return None

    return decoded if isinstance(decoded, dict) else None
