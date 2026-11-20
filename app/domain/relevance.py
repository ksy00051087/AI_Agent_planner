"""목표 분야와 자격의 관련성 — LLM 판정을 공식 시험과목으로 검증한다 (순수 함수).

LLM 은 '이 자격의 시험과목이 목표와 이어지는가' 만 판정하고, 근거로 시험과목 이름을 그대로 댄다.
코드는 근거가 실제 시험과목(또는 자격명)에 있을 때만 판정을 받아들인다. 근거가 없거나 지어낸 과목이면
판정을 버리고 후보를 그대로 둔다 — 빼는 쪽만 근거가 필요하다 (모르면 남긴다).
"""

from __future__ import annotations

import re


def _norm(s: str | None) -> str:
    return re.sub(r"[\s·.,()\-]", "", s or "")


def grounded(basis: str | None, name: str, subjects: str) -> bool:
    b = _norm(basis)
    return len(b) >= 2 and (b in _norm(subjects) or b in _norm(name))


def apply_relevance(cands: list[dict], subjects: dict[str, str], verdicts: list[dict]) -> tuple[list[dict], list[dict]]:
    """(남길 후보, 뺀 것 [{name, qual_id, basis, subjects, reason}]).
    verdicts: [{"name", "relevant": bool, "basis": 시험과목 이름, "reason"}] — 시험과목이 있는 후보만 판정한다."""
    by_name = {v.get("name"): v for v in verdicts or []}
    keep, dropped = [], []
    for q in cands:
        v, subj = by_name.get(q["name"]), subjects.get(q["name"])
        if v and subj and v.get("relevant") is False and grounded(v.get("basis"), q["name"], subj):
            dropped.append({"name": q["name"], "qual_id": q.get("qual_id"), "basis": v["basis"],
                            "subjects": subj, "reason": v.get("reason") or ""})
        else:
            keep.append(q)
    return keep, dropped
