"""직무 → 자격 근거 찾기 — 네이버(API HUB) 블로그 · 백과사전에서 그 직무 글에 함께 나온 자격을 센다.

LLM 이 자격을 만들어 내지 않는다: 글에 나온 표기가 등록된 출처(큐넷 · 공공데이터)의 자격명과 글자 그대로 같을 때만 센다.
같은 질의는 30일 디스크 캐시, 하루 호출 상한은 naver_hub 가 지킨다 (직무 하나에 최대 2회).
"""

from __future__ import annotations

import html
import re

from . import sources
from .sources import naver_hub

MIN_DOCS = 3          # 서로 다른 글 3건 이상에서 함께 나온 자격만 (2건은 우연히 겹치는 경우가 있었다 — 스페이스X 대표 → 세무사)
TOP = 6
_names: list[str] | None = None


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(s or ""))).strip()


def _norm(s: str) -> str:
    return re.sub(r"[\s·()\-]", "", s).lower()


def _catalog() -> list[tuple[str, str]]:
    """(정규화한 표기, 자격명) — 긴 표기부터. 'SQL 개발자(SQLD)' 는 SQLD 로도 찾는다"""
    global _names
    if _names is None:
        seen = []
        for src in sources.all_sources():
            err, qs = src.list_quals()
            seen += [q["name"] for q in qs or [] if "특례" not in q["name"]]
        _names = sorted(set(seen))
    out = []
    for n in _names:
        out.append((_norm(n), n))
        m = re.search(r"\(([A-Za-z]{3,6})\)", n)
        if m:
            out.append((_norm(m.group(1)), n))
    return sorted((x for x in out if len(x[0]) >= 3), key=lambda x: -len(x[0]))


def _mentions(text: str) -> set[str]:
    t, found = _norm(text), set()
    for alias, name in _catalog():
        if alias in t:
            found.add(name)
            t = t.replace(alias, "#")          # '건축전기설비기술사' 안의 다른 이름을 또 세지 않는다
    return found


def job_evidence(goal: str) -> dict:
    """{"mentions": [{name, docs}], "docs": 훑은 글 수, "refs": [{title, link, kind}], "error": 코드|None}"""
    counts: dict[str, int] = {}
    refs, scanned, error = [], 0, None
    for kind, query, size in (("encyc", goal, 3), ("blog", f"{goal} 자격증", 30)):
        try:
            res = naver_hub.search(kind, query, size)
        except naver_hub.HubError as e:
            error = e.code
            continue
        for it in res["items"]:
            title, desc = _clean(it.get("title")), _clean(it.get("description"))
            scanned += 1
            for name in _mentions(f"{title} {desc}"):
                counts[name] = counts.get(name, 0) + 1
            if _norm(goal) in _norm(title) and len(refs) < 3:
                refs.append({"title": title, "link": it.get("link"), "kind": "백과사전" if kind == "encyc" else "블로그"})
    top = sorted(((n, c) for n, c in counts.items() if c >= MIN_DOCS), key=lambda x: -x[1])[:TOP]
    return {"mentions": [{"name": n, "docs": c} for n, c in top], "docs": scanned, "refs": refs, "error": error}


# ── 커리어넷 직업정보 (공식) ─────────────────────────────────────
def job_candidates(goal: str) -> list[dict]:
    """직업 이름과 글자가 겹치는 커리어넷 직업 후보 (키가 없거나 실패하면 빈 목록)"""
    from .sources import careernet
    try:
        return careernet.candidates(goal)
    except careernet.CareerNetError:
        return []


def job_profile(seq: int) -> dict | None:
    """커리어넷 직업 상세 + '관련 자격' 원문에 나온 등록 자격명(cert_names). 실패하면 None"""
    from .sources import careernet
    try:
        p = careernet.profile(seq)
    except careernet.CareerNetError:
        return None
    found = set()
    for t in p["certificate"]:
        found |= _mentions(t)
    p["cert_names"] = sorted(found)
    return p


# ── 큐넷 밖 자격 — 웹문서 검색 (비공식) ──────────────────────────
def web_snippets(query: str, size: int = 10) -> dict:
    """네이버 웹문서 검색 조각 {"items": [{i, title, text, link}], "error"} — 태그를 지운 원문 그대로"""
    try:
        res = naver_hub.search("webkr", query, size)
    except naver_hub.HubError as e:
        return {"items": [], "error": e.code}
    items = [{"i": i, "title": _clean(it.get("title")), "text": _clean(it.get("description")), "link": it.get("link")}
             for i, it in enumerate(res["items"])]
    return {"items": items, "error": None}


def registered(names: list[str]) -> set[str]:
    """출처(큐넷 · 공공데이터)에 등록된 자격으로 볼 수 있는 이름 — 글자 그대로 또는 약칭(SQLD 등)이 같을 때"""
    table = _catalog()
    out = set()
    for n in names:
        k = _norm(n)
        if any(k == a or (len(k) >= 3 and k in a and len(a) - len(k) <= 2) for a, _ in table):
            out.add(n)
    return out
