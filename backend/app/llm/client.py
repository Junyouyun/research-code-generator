import os

from typing import Any

from openai import APITimeoutError, OpenAI

from app.config import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL, DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS


def chat_completion(
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 2000,
    response_format: dict[str, Any] | None = None,
) -> str:
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 LLM_API_KEY，无法调用模型接口。")

    timeout_seconds = _request_timeout_seconds()
    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL).rstrip("/"),
    )

    try:
        request = {
            "model": os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "timeout": timeout_seconds,
        }
        if response_format is not None:
            request["response_format"] = response_format

        response = client.chat.completions.create(**request)
    except APITimeoutError as exc:
        raise RuntimeError(f"模型请求超时（>{timeout_seconds}s）") from exc

    choices = response.choices or []
    if not choices:
        raise RuntimeError("模型接口返回为空，缺少 choices。")

    choice = choices[0]
    content = choice.message.content
    if not content:
        finish_reason = getattr(choice, "finish_reason", "")
        refusal = getattr(choice.message, "refusal", None)
        raise RuntimeError(
            "模型接口返回为空，缺少 message.content。"
            f" finish_reason={finish_reason or 'unknown'}"
            f" refusal={refusal or 'none'}"
        )

    return content


def _request_timeout_seconds() -> int:
    value = os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", str(DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS))
    try:
        parsed = int(value)
    except ValueError:
        return DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS
    return max(30, min(parsed, 600))
