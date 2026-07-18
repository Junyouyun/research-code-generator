import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR.parent / "data"

load_dotenv(BACKEND_DIR / ".env")

UPLOAD_DIR = DATA_DIR / "uploads"
PARSED_DIR = DATA_DIR / "parsed"
GENERATED_DIR = DATA_DIR / "generated"
ARTIFACT_DIR = DATA_DIR / "artifacts"
VALIDATION_DIR = DATA_DIR / "validation_runs"
TRACE_DIR = DATA_DIR / "traces"
EVAL_REPORT_DIR = DATA_DIR / "eval_reports"
DATABASE_PATH = DATA_DIR / "db.sqlite3"
QDRANT_PATH = DATA_DIR / "qdrant"

DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_LLM_MAX_WORKERS = 3
DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS = 90
DEFAULT_EMBEDDING_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_EMBEDDING_MODEL = "embedding-3"
DEFAULT_EMBEDDING_DIMENSIONS = 1024
DEFAULT_EMBEDDING_BATCH_SIZE = 64
DEFAULT_EMBEDDING_TIMEOUT_SECONDS = 60
DEFAULT_QDRANT_COLLECTION = "paper_chunks"
DEFAULT_AGENT_DIALOGUE_ROUNDS = 2
DEFAULT_AGENT_MAX_WORKERS = 4
DEFAULT_CODE_GEN_MAX_WORKERS = 3
DEFAULT_CODE_VALIDATION_TIMEOUT_SECONDS = 90
DEFAULT_CODE_VALIDATION_INSTALL_TIMEOUT_SECONDS = 180
DEFAULT_CODE_VALIDATION_KEEP_FAILED_RUNS = False
DEFAULT_CODE_REPAIR_MAX_ATTEMPTS = 3
DEFAULT_CODE_REPAIR_MAX_TOKENS = 6000


def get_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default
