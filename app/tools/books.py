"""교재 검색 외부 API 툴 — F3004 보조 정보.

출처: 카카오 책 검색 API (developers.naver.com 책 검색은 서비스 종료로 쓰지 않는다).
판단 규칙: 제목에 자격명이 들어간 책만 남기고 최근 출간순으로 정렬한다. 판매량 · 평점 정보는 없으므로 '추천 순위'라 하지 않는다.
후보와 임의로 짝짓지 않는다 — 제목에 자격명이 없는 책은 버리고 그 수를 excluded_unmatched 로 알린다.
"""

from __future__ import annotations

import html
import os
import re

import requests

from .base import BAD_ARGUMENT, INVALID_KEY, NO_DATA, QUOTA_EXCEEDED, UPSTREAM_ERROR, fail, ok

TIMEOUT = 10
FETCH_SIZE = 50  # 카카오 한 번에 최대 50 (수험서는 최신판이 중요해 최신순으로 넉넉히 받는다)
EXAM_TYPES = ("필기", "실기")


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _clean(s: str | None) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_.·()]", "", s).lower()


def _http_error(status: int):
    if status in (401, 403):
        return fail(INVALID_KEY, "책 검색 API 키가 틀렸거나 권한이 없습니다.")
    if status == 429:
        return fail(QUOTA_EXCEEDED, "책 검색 API 호출 한도를 넘었습니다.")
    return fail(UPSTREAM_ERROR, f"책 검색 API 오류 (HTTP {status}).")


def _kakao(query: str):
    res = requests.get("https://dapi.kakao.com/v3/search/book", timeout=TIMEOUT,
                       headers={"Authorization": f"KakaoAK {_env('KAKAO_REST_API_KEY')}"},
                       params={"query": query, "size": FETCH_SIZE, "target": "title", "sort": "latest"})
    if res.status_code != 200:
        return _http_error(res.status_code), None
    books = [{
        "title": _clean(b.get("title")),
        "authors": ", ".join(b.get("authors") or []) or None,
        "publisher": b.get("publisher") or None,
        "pub_date": (b.get("datetime") or "")[:10] or None,
        "price": b.get("sale_price") if isinstance(b.get("sale_price"), int) and b["sale_price"] > 0 else None,
        "isbn": b.get("isbn") or None,
        "link": b.get("url") or None,
    } for b in res.json().get("documents", [])]
    return None, books


def search_books(qualification_name: str, exam_type: str | None = None, limit: int = 5):
    if not qualification_name or not str(qualification_name).strip():
        return fail(BAD_ARGUMENT, "qualification_name(자격명)은 필수입니다.")
    if exam_type not in (None, "", *EXAM_TYPES):
        return fail(BAD_ARGUMENT, "exam_type 은 '필기' 또는 '실기' 여야 합니다.")
    if not isinstance(limit, int) or not 1 <= limit <= 20:
        return fail(BAD_ARGUMENT, "limit 는 1~20 사이 정수여야 합니다.")

    if not _env("KAKAO_REST_API_KEY"):
        return fail(INVALID_KEY, "책 검색 API 키가 없습니다. KAKAO_REST_API_KEY 를 설정하세요.")

    name = str(qualification_name).strip()
    query = f"{name} {exam_type}" if exam_type else name
    try:
        err, books = _kakao(query)
    except requests.RequestException:
        err, books = fail(UPSTREAM_ERROR, "책 검색 API 를 부르지 못했습니다."), None
    if err:
        return err

    key = _norm(name)
    other = {"필기": "실기", "실기": "필기"}.get(exam_type or "")
    matched = [b for b in books if key in _norm(b["title"])
               # 필기를 찾는데 제목에 '실기'만 있는 책은 다른 단계 교재다 (둘 다 있으면 합본이라 남긴다)
               and not (other and other in b["title"] and exam_type not in b["title"])]
    excluded = len(books) - len(matched)
    if not matched:
        return fail(NO_DATA, f"'{name}' 이 제목에 들어간 교재를 찾지 못했습니다 (검색 결과 {len(books)}건은 제목 불일치로 제외).")

    matched.sort(key=lambda b: b["pub_date"] or "", reverse=True)
    return ok({
        "query": query,
        "provider": "kakao",
        "basis": "제목에 자격명이 들어간 책만, 최근 출간순. 판매량 · 평점 순위가 아닙니다.",
        "excluded_unmatched": excluded,
        "items": matched[:limit],
    })
