"""Coordinator 与 Analyst 共用的模型配置。"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel


def create_structured_model(schema: type[BaseModel], *, label: str):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model_name = os.getenv("LLM_MODEL", "").strip()
    if not api_key or not model_name:
        raise RuntimeError(f"{label} 调用模型需要 OPENAI_API_KEY 和 LLM_MODEL；离线测试请注入 mock 模型")

    api = os.getenv("LLM_API", "chat_completions").strip().lower()
    if api not in {"chat_completions", "responses"}:
        raise ValueError("LLM_API 必须是 chat_completions 或 responses")
    base_url = os.getenv("OPENAI_BASE_URL", "").strip().rstrip("/")
    if base_url:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("OPENAI_BASE_URL 必须是有效的 HTTP(S) API 根地址")
        if parsed.path.endswith(("/responses", "/chat/completions")):
            raise ValueError("OPENAI_BASE_URL 应填写 API 根地址（如 https://host/v1），不要包含 /responses 或 /chat/completions")

    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": model_name,
        "api_key": api_key,
        "use_responses_api": api == "responses",
        "timeout": 120,
        "max_retries": 2,
    }
    if base_url:
        kwargs["base_url"] = base_url
    # 使用模型默认采样参数，兼容不接受 temperature 的推理模型。
    if api == "responses":
        kwargs["store"] = False
    return ChatOpenAI(**kwargs).with_structured_output(schema, method="json_schema", strict=True)
