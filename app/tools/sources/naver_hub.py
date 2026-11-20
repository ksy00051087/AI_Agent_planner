"""NAVER API HUB 검색 (네이버 클라우드) — 백과사전 · 블로그.

호출 한도가 있어 수집 스크립트(scripts/collect_naver.py)에서만 부른다. 대화 요청 중에는 부르지 않는다.
  · 같은 질의는 디스크 캐시(30일)에서 돌려준다
  · 하루 호출 수 상한 NAVER_HUB_DAILY_CAP (기본 2000, 상품 한도 25,000/일보다 훨씬 낮게)
인증: X-NCP-APIGW-API-KEY-ID = NAVER_HUB_CLIENT_ID, X-NCP-APIGW-API-KEY = NAVER_HUB_CLIENT_SECRET (.env)
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
BASE = "https://naverapihub.apigw.ntruss.com/search/v1"
CACHE_DIR = ROOT / "data" / "rag" / "naver_cache"
USAGE = ROOT / "data" / "rag" / "naver_usage.json"
CACHE_TTL_SEC = 30 * 24 * 3600
KINDS = ("encyc", "blog", "webkr")
# 웹문서(시험 일정 조각)는 자주 바뀌므로 짧게
TTL_BY_KIND = {"webkr": 3 * 24 * 3600}
load_dotenv(ROOT / ".env")


class HubError(Exception):
    """code: NO_KEY · DAILY_CAP · INVALID_KEY · QUOTA_EXCEEDED · UPSTREAM_ERROR"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def daily_cap() -> int:
    try:
        return int(os.getenv("NAVER_HUB_DAILY_CAP") or 2000)
    except ValueError:
        return 2000


def _usage() -> dict:
    try:
        return json.loads(USAGE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def used_today() -> int:
    return int(_usage().get(date.today().isoformat(), 0))


def _count_call() -> None:
    u = _usage()
    today = date.today().isoformat()
    u = {today: int(u.get(today, 0)) + 1}          # 오늘 것만 남긴다
    USAGE.parent.mkdir(parents=True, exist_ok=True)
    USAGE.write_text(json.dumps(u), encoding="utf-8")


def _cache_path(kind: str, query: str, display: int) -> Path:
    h = hashlib.sha1(f"{kind}|{query}|{display}".encode("utf-8")).hexdigest()[:20]
    return CACHE_DIR / f"{kind}-{h}.json"


def search(kind: str, query: str, display: int = 10, *, session: requests.Session | None = None) -> dict:
    """{"total", "items": [...], "cached": bool}. 캐시에 있으면 호출하지 않는다."""
    if kind not in KINDS:
        raise ValueError(kind)
    path = _cache_path(kind, query, display)
    if path.exists() and time.time() - path.stat().st_mtime < TTL_BY_KIND.get(kind, CACHE_TTL_SEC):
        return {**json.loads(path.read_text(encoding="utf-8")), "cached": True}
    cid, secret = (os.getenv("NAVER_HUB_CLIENT_ID") or "").strip(), (os.getenv("NAVER_HUB_CLIENT_SECRET") or "").strip()
    if not (cid and secret):
        raise HubError("NO_KEY", "NAVER_HUB_CLIENT_ID / NAVER_HUB_CLIENT_SECRET (NAVER API HUB 키) 가 없습니다.")
    if used_today() >= daily_cap():
        raise HubError("DAILY_CAP", f"오늘 호출 상한 {daily_cap()}회에 닿았습니다 (NAVER_HUB_DAILY_CAP). 내일 이어서 하세요.")
    http = session or requests
    try:
        res = http.get(f"{BASE}/{kind}", params={"query": query, "display": display}, timeout=10,
                       headers={"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": secret})
    except requests.RequestException as e:
        raise HubError("UPSTREAM_ERROR", "NAVER API HUB 를 부르지 못했습니다.") from e
    _count_call()
    if res.status_code in (401, 403):
        raise HubError("INVALID_KEY", "NAVER API HUB 키가 틀렸거나 이 API 권한이 없습니다.")
    if res.status_code == 429:
        raise HubError("QUOTA_EXCEEDED", "NAVER API HUB 호출 한도를 넘었습니다.")
    if res.status_code != 200:
        raise HubError("UPSTREAM_ERROR", f"NAVER API HUB 오류 (HTTP {res.status_code}).")
    body = res.json()
    out = {"total": body.get("total"), "items": body.get("items") or []}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return {**out, "cached": False}
