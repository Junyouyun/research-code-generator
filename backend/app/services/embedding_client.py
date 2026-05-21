import os
from collections.abc import Iterable

from openai import APITimeoutError, OpenAI

from app.config import (
    DEFAULT_EMBEDDING_BASE_URL,
    DEFAULT_EMBEDDING_BATCH_SIZE,
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_TIMEOUT_SECONDS,
    get_int_env,
)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    if any(not text.strip() for text in texts):
        raise ValueError("embedding 输入文本不能为空。")

    api_key = _api_key()
    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("EMBEDDING_BASE_URL", DEFAULT_EMBEDDING_BASE_URL).rstrip("/"),
    )

    model = get_embedding_model()
    timeout_seconds = _timeout_seconds()
    vectors: list[list[float]] = []

    for batch in _batched(texts, _batch_size()):
        try:
            request = {
                "model": model,
                "input": batch,
                "timeout": timeout_seconds,
            }
            dimensions = get_embedding_dimensions()
            if dimensions is not None:
                request["dimensions"] = dimensions

            response = client.embeddings.create(
                **request,
            )
        except APITimeoutError as exc:
            raise RuntimeError(f"embedding 请求超时（>{timeout_seconds}s）。") from exc

        batch_vectors = [item.embedding for item in response.data]
        if len(batch_vectors) != len(batch):
            raise RuntimeError(
                "embedding 接口返回数量和输入数量不一致。"
                f" input={len(batch)} output={len(batch_vectors)}"
            )
        vectors.extend(batch_vectors)

    return vectors


def get_embedding_model() -> str:
    return os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)


def get_embedding_dimensions() -> int | None:
    raw_value = os.getenv("EMBEDDING_DIMENSIONS")
    if raw_value is not None and raw_value.strip() == "":
        return None

    value = get_int_env("EMBEDDING_DIMENSIONS", DEFAULT_EMBEDDING_DIMENSIONS)
    if value <= 0:
        return None
    return value


def _api_key() -> str:
    api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 EMBEDDING_API_KEY 或 LLM_API_KEY，无法调用 embedding 接口。")
    return api_key


def _batch_size() -> int:
    value = get_int_env("EMBEDDING_BATCH_SIZE", DEFAULT_EMBEDDING_BATCH_SIZE)
    return max(1, min(value, 256))


def _timeout_seconds() -> int:
    value = get_int_env("EMBEDDING_TIMEOUT_SECONDS", DEFAULT_EMBEDDING_TIMEOUT_SECONDS)
    return max(10, min(value, 600))


def _batched(items: list[str], batch_size: int) -> Iterable[list[str]]:
    for index in range(0, len(items), batch_size):
        yield items[index : index + batch_size]
