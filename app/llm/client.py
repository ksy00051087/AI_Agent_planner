"""LLM 어댑터 — SSAFY GMS (OpenAI 호환). 키가 없으면 None 을 돌려 Agent 가 설정 안내를 하게 한다 (F3019)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DEFAULT_BASE_URL = "https://gms.ssafy.io/gmsapi/api.openai.com/v1"
DEFAULT_MODEL = "gpt-4.1-mini"


def llm_configured() -> bool:
    return bool((os.getenv("GMS_API_KEY") or "").strip())


def get_chat_model(temperature: float = 0.0):
    """ChatOpenAI 를 만든다. 키가 없으면 None."""
    if not llm_configured():
        return None
    from langchain_openai import ChatOpenAI  # 키가 없을 때는 import 비용도 들이지 않는다

    return ChatOpenAI(
        model=os.getenv("GMS_MODEL") or DEFAULT_MODEL,
        base_url=(os.getenv("GMS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        api_key=os.getenv("GMS_API_KEY"),
        temperature=temperature,
        timeout=60,
        max_retries=1,
    )
