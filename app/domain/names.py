"""자격명 맞추기 — 사용자가 말한 이름과 출처의 종목명이 같은 자격인지 (순수 함수)."""

from __future__ import annotations

import re

# 자격명 뒤에 붙여 말하는 낱말 — 종목명에는 없다 ("간호사 국가시험" → "간호사")
SUFFIXES = ("국가고시", "국가시험", "자격시험", "자격증", "시험", "자격", "면허")


def strip_suffix(name: str) -> str:
    n = name.strip()
    changed = True
    while changed:
        changed = False
        for s in SUFFIXES:
            if n.endswith(s) and len(n) > len(s) + 1:
                n = n[: -len(s)].strip()
                changed = True
    return n


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def name_matches(target: str | None, name: str | None) -> bool:
    """한쪽이 다른 쪽에 들어 있으면 같은 자격으로 본다 (두 글자 이상). '전기기사' ↔ '전기기사', '간호사 국가시험' ↔ '간호사'."""
    t, n = _norm(target), _norm(name)
    if len(t) < 2 or len(n) < 2:
        return False
    return t in n or n in t


def target_found(target: str, names: list[str], keywords: list[str] | None = None) -> bool:
    """지정한 자격을 후보에서 찾았는가. 이름이 맞거나, 그 이름 안에 든 검색어로 찾은 후보가 있으면 찾은 것으로 본다
    ('9급 공무원' → 검색어 '9급' 으로 '9급공개경쟁채용시험' 을 찾았다)."""
    if any(name_matches(target, n) for n in names):
        return True
    words = [k for k in keywords or [] if len(k) >= 2 and _norm(k) in _norm(target)]
    return any(_norm(k) in _norm(n) for k in words for n in names)
