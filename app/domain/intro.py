"""자격 소개 한 줄 — 무엇을 공부하나 · 이럴 때 유리 (순수 함수).

공부 내용은 공식 시험과목(큐넷 취득방법)을 먼저 쓰고, 없을 때만 서비스 안내 문구를 쓴다.
'이럴 때 유리' 는 공식 데이터가 없어 서비스 안내 문구를 쓰고, 그것도 없으면 데이터로 확인되는 사실만 적는다.
어느 쪽인지 항상 source 로 남긴다.
"""

from __future__ import annotations

from .names import name_matches

MAX_SUBJECTS = 5
MAX_SUBJECT_LEN = 28


def _subjects_text(exam_info: dict | None) -> str | None:
    subjects = (exam_info or {}).get("subjects") or {}
    parts = []
    for stage, names in subjects.items():
        names = [n if len(n) <= MAX_SUBJECT_LEN else n[:MAX_SUBJECT_LEN] + "…" for n in names or []]
        if names:
            more = f" 외 {len(names) - MAX_SUBJECTS}과목" if len(names) > MAX_SUBJECTS else ""
            parts.append(f"{stage}: {', '.join(names[:MAX_SUBJECTS])}{more}")
    return " / ".join(parts) or None


def _curated(name: str, intros: dict[str, dict]) -> dict:
    if name in intros:
        return intros[name]
    # 이름이 조금 다른 경우 (공백 · 괄호) — 한쪽이 다른 쪽에 들어 있으면 같은 자격
    return next((v for k, v in intros.items() if name_matches(k, name) and abs(len(k) - len(name)) <= 2), {})


def build_intro(name: str, exam_info: dict | None, intros: dict[str, dict], *,
                track: str | None = None, popularity: str | None = None, next_step: str | None = None) -> dict:
    """{"study", "study_source", "good_for", "good_for_source"} — 값을 모르면 None"""
    cur = _curated(name, intros)
    official = _subjects_text(exam_info)
    study, study_src = (official, "큐넷 시험과목") if official else (cur.get("study"), "서비스 안내" if cur.get("study") else None)
    if cur.get("good_for"):
        good, good_src = cur["good_for"], "서비스 안내"
    else:
        facts = []
        if track:
            facts.append(f"{track} 쪽으로 갈 때 이어지는 자격")
        if popularity:
            facts.append(popularity)
        if next_step:
            facts.append(f"다음 단계 {next_step} 로 이어짐")
        good, good_src = (" · ".join(facts), "데이터") if facts else (None, None)
    return {"study": study, "study_source": study_src, "good_for": good, "good_for_source": good_src}
