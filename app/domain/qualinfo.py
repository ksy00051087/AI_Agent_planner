"""자격 상세 정보 해석 — 시험과목 · 검정방법 · 합격기준 텍스트 파싱, 합격률 요약.

큐넷 '취득방법' 텍스트는 사람이 쓴 글이라 모양이 조금씩 다르다. 읽지 못한 부분은 비워 두고 원문을 함께 돌려준다.
"""

from __future__ import annotations

import html
import re

_SECTIONS = ("시험과목", "검정방법", "합격기준")
_STAGES = ("필기", "실기", "면접", "1차", "2차", "3차")
_NUMBERED = re.compile(r"\d+\s*\.\s*(.+?)(?=\s*\d+\s*\.\s*\D|$)")


def _clean_lines(text: str) -> list[str]:
    t = html.unescape(text or "").replace("\r", "\n")
    # '… 영어서신 작성) 검정방법' 처럼 줄 끝에 붙은 다음 섹션 이름은 새 줄로 (안 그러면 검정방법이 시험과목에 섞인다)
    t = re.sub(r"[ \t]+(시험과목|검정방법|합격기준)(?=[ \t]*[:：(]|[ \t]*$)", r"\n\1", t, flags=re.M)
    return [ln.strip() for ln in t.split("\n") if ln.strip()]


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current = None
    for ln in lines:
        head = next((s for s in _SECTIONS if ln.replace(" ", "").startswith(s)), None)
        if head:
            current = head
            out[current] = []
            rest = ln.replace(" ", "")[len(head):].lstrip(":：")
            if rest and not rest.startswith("("):     # "시험과목('22년부터 적용)" 의 괄호 안내는 과목이 아니다
                out[current].append(ln.split(head[-1], 1)[-1].lstrip(" :："))
            continue
        if current:
            out[current].append(ln)
    return out


def _by_stage(lines: list[str]) -> dict[str, str]:
    """'- 필기 : xxx' 줄들을 {'필기': 'xxx'} 로."""
    out: dict[str, str] = {}
    for ln in lines:
        s = ln.lstrip("-·• ").strip()
        stage = next((st for st in _STAGES if s.startswith(st)), None)
        if stage and stage not in out:          # 같은 단계가 또 나오면 처음 것 (뒤 섹션이 섞여도 덮어쓰지 않는다)
            out[stage] = s[len(stage):].lstrip(" :：").strip()
    return out


def parse_subjects(stage_text: str) -> list[str]:
    """'1. 소프트웨어설계 2. 소프트웨어개발' → ['소프트웨어설계', '소프트웨어개발']. 번호가 없으면 통째로 하나."""
    t = stage_text.strip()
    if not t:
        return []
    found = [m.strip(" ,") for m in _NUMBERED.findall(t)]
    return [f for f in found if f] or [t]


def parse_acquisition(text: str | None) -> dict | None:
    """큐넷 취득방법 텍스트 → {"subjects": {단계: [과목]}, "exam_method": {단계: 문장}, "pass_criteria": {단계: 문장}}.

    세 부분을 하나도 읽지 못하면 None.
    """
    if not text:
        return None
    sections = _split_sections(_clean_lines(text))
    subjects = {st: parse_subjects(v) for st, v in _by_stage(sections.get("시험과목", [])).items()}
    method = _by_stage(sections.get("검정방법", []))
    criteria = _by_stage(sections.get("합격기준", []))
    if not (subjects or method or criteria):
        return None
    return {"subjects": subjects or None, "exam_method": method or None, "pass_criteria": criteria or None}


def summarize_pass_rates(rows: list[dict]) -> dict | None:
    """한 종목 · 한 해의 회차별 합격률 행 → 단계별 합산 합격률.

    rows: [{"stage": "필기"|"실기", "takers": int|None, "passed": int|None}]
    합격률 = 합격자 합 / 응시자 합 (회차별 % 의 단순 평균이 아니다). 응시자가 0 이면 그 단계는 None.
    """
    totals: dict[str, list[int]] = {}
    for r in rows:
        if r.get("takers") is None or r.get("passed") is None:
            continue
        t = totals.setdefault(r["stage"], [0, 0, 0])
        t[0] += r["takers"]
        t[1] += r["passed"]
        t[2] += 1
    out = {st: {"rate": round(p / tk * 100, 1), "takers": tk, "passed": p, "rounds": n}
           for st, (tk, p, n) in totals.items() if tk > 0}
    return out or None
