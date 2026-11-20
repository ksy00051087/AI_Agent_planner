"""계획 판정 — 준비 기간 역산 · 접수 가능 여부 · 같은 날짜 시간 겹침 (F3008 · F3015).

공부 기간은 외부 API 로 확인할 수 없는 값이다. 그래서 '서비스 기준값'으로 두고,
사용자가 말하면 그 값을 쓴다. 어느 쪽인지 항상 basis 에 남긴다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

# 등급별 기본 준비 기간(주) — 사실이 아니라 '서비스 기준'. 화면에 그렇게 표시한다.
DEFAULT_PREP_WEEKS = {
    "기능사": 6,
    "산업기사": 8,
    "기사": 10,
    "기능장": 12,
    "기술사": 24,
    "전문자격": 24,
}
FALLBACK_PREP_WEEKS = 10


def prep_weeks_for(grade: str | None, user_weeks: int | None = None) -> tuple[int, str]:
    """(주 수, 근거). 사용자가 준 값이 우선."""
    if user_weeks is not None and user_weeks > 0:
        return user_weeks, "사용자 입력"
    if grade:
        for key, weeks in DEFAULT_PREP_WEEKS.items():
            if key in grade:
                return weeks, f"서비스 기준값({key} {weeks}주, 조정 가능)"
    return FALLBACK_PREP_WEEKS, f"서비스 기준값(등급 미상 {FALLBACK_PREP_WEEKS}주, 조정 가능)"


def latest_start(exam_date: date, prep_weeks: int) -> date:
    """늦어도 이 날 공부를 시작해야 시험일까지 prep_weeks 를 채운다 (역산)."""
    return exam_date - timedelta(weeks=prep_weeks)


def judge_round(round_: dict, today: date, prep_weeks: int) -> dict:
    """회차 하나가 계획에 들어갈 수 있는지 판정한다.

    반환 {"ok": bool, "reason": str|None, "latest_start": date|None}
    reason: REGISTRATION_CLOSED · NOT_ENOUGH_TIME · UNJUDGEABLE
    """
    if not round_.get("judgeable"):
        return {"ok": False, "reason": "UNJUDGEABLE", "latest_start": None,
                "detail": f"판단에 필요한 날짜가 비어 있음: {', '.join(round_.get('missing', []))}"}
    d = round_["dates"]
    if d["written_reg_end"] < today:
        return {"ok": False, "reason": "REGISTRATION_CLOSED", "latest_start": None,
                "detail": f"필기 접수 마감 {d['written_reg_end']:%Y-%m-%d} 이 지났음"}
    start_by = latest_start(d["written_exam_start"], prep_weeks)
    if start_by < today:
        short = (today - start_by).days
        return {"ok": False, "reason": "NOT_ENOUGH_TIME", "latest_start": start_by,
                "detail": f"준비 {prep_weeks}주를 채우려면 {start_by:%Y-%m-%d} 에 시작했어야 함 ({short}일 부족)"}
    return {"ok": True, "reason": None, "latest_start": start_by, "detail": None}


# ── F3015: 같은 날짜에 시간이 겹치는 계획 ─────────────────────────
def _parse_hm(value: str | None) -> time | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError:
        return None


def find_overlaps(new_plan: dict, plans: list[dict]) -> list[dict]:
    """new_plan 과 같은 날짜에 시간이 겹치는 기존 계획 목록.

    계획: {"plan_id", "plan_date": date, "start_time": "HH:MM"|None, "end_time": "HH:MM"|None}
    - 둘 다 시각이 있으면: [시작, 종료) 구간이 겹칠 때만
    - 한쪽이라도 시각이 없으면: 하루 전체로 보고 같은 날짜면 겹침 (확인 못 한 걸 '안 겹친다'고 하지 않는다)
    - 자기 자신(plan_id 같음)은 제외 → 수정할 때도 쓸 수 있다
    """
    out = []
    ns, ne = _parse_hm(new_plan.get("start_time")), _parse_hm(new_plan.get("end_time"))
    for p in plans:
        if p.get("plan_id") is not None and p.get("plan_id") == new_plan.get("plan_id"):
            continue
        if p.get("plan_date") != new_plan.get("plan_date"):
            continue
        ps, pe = _parse_hm(p.get("start_time")), _parse_hm(p.get("end_time"))
        if None in (ns, ne, ps, pe):
            out.append(p)
        elif ns < pe and ps < ne:
            out.append(p)
    return out
