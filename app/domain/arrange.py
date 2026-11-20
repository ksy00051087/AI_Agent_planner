"""여러 자격을 하나의 장기 계획으로 배치한다 (F3008) — 순수 함수.

입력은 Tool 결과에서 뽑은 '후보'와 사용자 조건이고, 출력은 배치된 항목과 제외 사유다.
판단 근거가 비어 있으면 채우지 않고 제외 사유로 남긴다. 외부 API 로 확인할 수 없는 공부 기간은
'서비스 기준값'으로 두고, 시험일에서 역산한 '늦어도 이 날 시작'을 제시한다.

후보(candidate) 모양
    {"qual_id", "name", "grade", "source", "fee": {라벨: 원}|None,
     "pass_rate": {"by_stage": {"필기": {"rate": ..}}}|None,
     "rounds": [{"name", "stage", "estimated", "basis", "exam_time",
                 "written_reg_start", "written_reg_end", "written_exam_start", "practical_exam_start", ...}]}  ← ISO 날짜 문자열
"""

from __future__ import annotations

from datetime import date, timedelta

from .names import name_matches
from .planning import prep_weeks_for

GRADE_ORDER = {"기능사": 1, "산업기사": 2, "기사": 3, "기능장": 4, "기술사": 5}
HARD_PASS_RATE = 35.0     # 필기 합격률이 이보다 낮으면 준비 기간을 늘린다
HARD_EXTRA_WEEKS = 2

# 공부 부담 — 큰 시험은 그 기간에 그것만, 나머지는 병행, 기본 자격(토익 · 한국사 …)은 무엇과도 병행
HEAVY_GRADES = ("기사", "기능장", "기술사", "전문자격")
HEAVY_WEEKS = 10          # 등급을 몰라도 준비 기간이 이만큼이면 큰 시험으로 본다
LIGHT_PARALLEL = 2        # 큰 시험이 아닌 자격은 동시에 2개까지
LOAD_TEXT = {"heavy": "큰 시험 — 이 기간엔 이것만 공부", "light": f"다른 자격과 최대 {LIGHT_PARALLEL}개 병행",
             "basic": "기본 자격 — 다른 공부와 병행"}

# 제외 사유 — 숫자가 클수록 '더 결정적인' 사유 (회차가 여러 개일 때 대표 사유를 고른다)
REASONS = {
    "PREREQ_NOT_PLACED": (0, "같은 계열의 앞 단계를 배치하지 못해 이 단계도 넣지 않음"),
    "UNJUDGEABLE": (1, "판단에 필요한 날짜(접수 마감 · 시험일)가 비어 있음"),
    "REGISTRATION_CLOSED": (2, "접수가 이미 끝남"),
    "BLOCKED_DATE": (3, "시험을 볼 수 없다고 한 날과 겹침"),
    "CALENDAR_BUSY": (3, "캘린더에 이미 일정이 있는 날과 시험일이 겹침"),
    "STUDY_OVERLAP": (4, "공부 기간이 다른 자격과 겹침 (큰 시험은 혼자, 나머지는 2개까지 병행)"),
    "DATE_CONFLICT": (4, "앞서 배치한 자격과 시험 날짜 · 시각이 겹침"),
    "NOT_ENOUGH_TIME": (5, "준비 기간을 채울 수 있는 회차가 없음"),
    "DEADLINE_EXCEEDED": (6, "기한 안에 끝나는 회차가 없음"),
}


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def order_candidates(cands: list[dict], targets: list[str] | None = None,
                     precedes: dict[str, set[str]] | None = None) -> list[dict]:
    """순서: ① 사용자가 이름을 댄 순서 ② 선수 관계(precedes[A] = A 보다 먼저 따면 좋은 자격들)
    ③ 낮은 등급 먼저 ④ 가장 빠른 시험일."""
    targets = targets or []
    precedes = precedes or {}

    def first_exam(c: dict) -> str:
        days = [r.get("written_exam_start") for r in c.get("rounds", []) if r.get("written_exam_start")]
        return min(days) if days else "9999-12-31"

    def key(c: dict):
        tpos = next((i for i, t in enumerate(targets) if name_matches(t, c["name"])), len(targets))
        rank = c.get("path_rank")  # Agent 가 정한 흐름 순서 (많이 따는 계열 → 낮은 등급)
        return (tpos, rank if rank is not None else 10**6, GRADE_ORDER.get(c.get("grade") or "", 3), first_exam(c), c["name"])

    ordered = sorted(cands, key=key)
    # 선수 관계는 안정 정렬 뒤 한 번 더: B 의 선수 A 가 뒤에 있으면 A 를 B 앞으로 옮긴다
    names = [c["name"] for c in ordered]
    for c in list(ordered):
        for pre in precedes.get(c["name"], set()):
            if pre in names and names.index(pre) > names.index(c["name"]):
                moved = ordered.pop(names.index(pre))
                ordered.insert(names.index(c["name"]), moved)
                names = [x["name"] for x in ordered]
    return ordered


def prep_weeks(cand: dict, user_weeks: int | None) -> tuple[int, str]:
    weeks, basis = prep_weeks_for(cand.get("grade"), user_weeks)
    if user_weeks:
        return weeks, basis
    if cand.get("prep_hint"):
        weeks, basis = int(cand["prep_hint"]), f"서비스 기준값(종목별 {int(cand['prep_hint'])}주, 조정 가능)"
    rate = (((cand.get("pass_rate") or {}).get("by_stage") or {}).get("필기") or {}).get("rate")
    if rate is not None and rate < HARD_PASS_RATE:
        weeks += HARD_EXTRA_WEEKS
        basis += f" + 필기 합격률 {rate}% 로 {HARD_EXTRA_WEEKS}주 추가"
    return weeks, basis


def study_load(cand: dict, weeks: int) -> str:
    """heavy | light | basic"""
    if cand.get("basic"):
        return "basic"
    grade = cand.get("grade") or ""
    if any(g == grade for g in HEAVY_GRADES) or weeks >= HEAVY_WEEKS:
        return "heavy"
    return "light"


def _overlaps(a: tuple[date, date], b: tuple[date, date]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def _study_fits(window: tuple[date, date], load: str, placed: list[dict], user_parallel: int | None) -> bool:
    """공부 기간이 앞서 배치한 자격들과 겹쳐도 되는가.
    사용자가 동시 공부 수를 말했으면 그 수(기본 자격 제외)만 본다. 아니면 큰 시험은 혼자, 나머지는 2개까지."""
    if load == "basic":
        return True
    others = [p for p in placed if p["load"] != "basic" and _overlaps(window, p["_window"])]
    if user_parallel:
        return len(others) < user_parallel
    if load == "heavy":
        return not others
    return not any(p["load"] == "heavy" for p in others) and len(others) < LIGHT_PARALLEL


def _exam_days(r: dict) -> list[tuple[date, str | None]]:
    out = []
    for f in ("written_exam_start", "practical_exam_start"):
        d = _d(r.get(f))
        if d:
            out.append((d, r.get("exam_time")))
    return out


def _conflicts(r: dict, placed: list[dict]) -> bool:
    """같은 날 시험이 있으면 충돌. 둘 다 시각을 알고 시각이 다를 때만 같은 날도 허용한다."""
    for d, t in _exam_days(r):
        for p in placed:
            for pd, pt in p["_days"]:
                if d == pd and (t is None or pt is None or t == pt):
                    return True
    return False


def evaluate_round(r: dict, available_from: date, today: date, weeks: int, deadline: date | None,
                   blocked: set[date], placed: list[dict], busy: set[date] | None = None,
                   load: str = "light", user_parallel: int | None = 1) -> tuple[str | None, date | None]:
    """(실패 사유 코드 | None, 늦어도 공부를 시작할 날)"""
    reg_end, exam = _d(r.get("written_reg_end")), _d(r.get("written_exam_start"))
    if not (reg_end and exam):
        return "UNJUDGEABLE", None
    if reg_end < today:
        return "REGISTRATION_CLOSED", None
    final = _d(r.get("practical_exam_start")) or exam
    if deadline and final > deadline:
        return "DEADLINE_EXCEEDED", None
    start_by = exam - timedelta(weeks=weeks)
    if start_by < available_from:
        return "NOT_ENOUGH_TIME", start_by
    if any(d in blocked for d, _ in _exam_days(r)):
        return "BLOCKED_DATE", start_by
    if busy and any(d in busy for d, _ in _exam_days(r)):
        return "CALENDAR_BUSY", start_by
    if _conflicts(r, placed):
        return "DATE_CONFLICT", start_by
    if not _study_fits((start_by, final), load, placed, user_parallel):
        return "STUDY_OVERLAP", start_by
    return None, start_by


def arrange(cands: list[dict], conditions: dict, today: date, ignore_deadline: bool = False,
            precedes: dict[str, set[str]] | None = None, max_items: int | None = None,
            busy_dates: set[str] | None = None) -> dict:
    """후보를 순서대로 배치한다.

    반환 {"placed": [...], "excluded": [{"qual_id", "name", "reason_code", "detail"}],
          "fee_total": int, "fee_unknown": [이름], "deadline_ignored": bool}
    """
    start = _d(conditions.get("start_date")) or today
    start = max(start, today)
    deadline = None if ignore_deadline else _d(conditions.get("deadline"))
    blocked = {d for d in (_d(x) for x in conditions.get("blocked_dates") or []) if d}
    user_parallel = conditions.get("max_parallel") or None   # 말하지 않았으면 부담별 기본 규칙
    busy = {d for d in (_d(x) for x in busy_dates or []) if d}

    placed: list[dict] = []
    excluded: list[dict] = []
    deferred: list[str] = []
    for cand in order_candidates(cands, conditions.get("targets"), precedes):
        if max_items and len(placed) >= max_items:
            deferred.append(cand["name"])  # 계획 크기 제한 — 제외가 아니라 '다음 계획 후보'
            continue
        chain = cand.get("chain")
        if chain and any(e.get("chain") == chain and GRADE_ORDER.get(e.get("grade") or "", 0)
                         < GRADE_ORDER.get(cand.get("grade") or "", 0) for e in excluded):
            excluded.append({"qual_id": cand["qual_id"], "name": cand["name"], "reason_code": "PREREQ_NOT_PLACED",
                             "detail": REASONS["PREREQ_NOT_PLACED"][1], "chain": chain, "grade": cand.get("grade")})
            continue
        weeks, basis = prep_weeks(cand, conditions.get("prep_weeks"))
        load = study_load(cand, weeks)
        # 먼저 따야 하는 자격(같은 계열 아래 단계 · 시험 면제 선수)이 끝난 뒤에 시작한다. 그 밖의 겹침은 부담 규칙으로 본다
        before = [p["_final"] for p in placed
                  if p["name"] in (precedes or {}).get(cand["name"], set())
                  or (chain and p.get("_chain") == chain
                      and GRADE_ORDER.get(p.get("grade") or "", 0) < GRADE_ORDER.get(cand.get("grade") or "", 0))]
        available_from = max([start, *[d + timedelta(days=1) for d in before]])

        best_reason, chosen, start_by = None, None, None
        rounds = sorted(cand.get("rounds", []), key=lambda r: r.get("written_exam_start") or "9999")
        for r in rounds:
            reason, sb = evaluate_round(r, available_from, today, weeks, deadline, blocked, placed, busy,
                                        load, user_parallel)
            if reason is None:
                chosen, start_by = r, sb
                break
            if best_reason is None or REASONS[reason][0] > REASONS[best_reason][0]:
                best_reason = reason
        if chosen is None:
            code = best_reason or "UNJUDGEABLE"
            excluded.append({"qual_id": cand["qual_id"], "name": cand["name"], "reason_code": code,
                             "detail": REASONS[code][1], "prep_weeks": weeks,
                             "chain": cand.get("chain"), "grade": cand.get("grade")})
            continue

        exam = _d(chosen["written_exam_start"])
        final = _d(chosen.get("practical_exam_start")) or exam
        fee = cand.get("fee")
        placed.append({
            "qual_id": cand["qual_id"], "name": cand["name"], "grade": cand.get("grade"), "source": cand.get("source"),
            "round_name": chosen.get("name"), "stage": chosen.get("stage"),
            "registration_start": chosen.get("written_reg_start"), "registration_end": chosen.get("written_reg_end"),
            "exam_date": chosen["written_exam_start"], "exam_time": chosen.get("exam_time"),
            "practical_exam_date": chosen.get("practical_exam_start"),
            "practical_registration_end": chosen.get("practical_reg_end"),
            "study_start_by": start_by.isoformat(), "prep_weeks": weeks, "prep_basis": basis,
            "estimated": bool(chosen.get("estimated")), "basis": chosen.get("basis"),
            "fee": fee, "fee_total": sum(fee.values()) if fee else None,
            "path_reason": cand.get("path_reason"), "ladder": cand.get("ladder"),
            "precedes_link": sorted(p_["name"] for p_ in placed if p_["name"] in (precedes or {}).get(cand["name"], set())),
            "load": load, "load_text": LOAD_TEXT[load] if not user_parallel else f"동시에 {user_parallel}개까지 (요청)",
            "_days": _exam_days(chosen), "_final": final, "_window": (start_by, final), "_chain": chain,
        })

    # 예산: 넘으면 마지막에 배치한 것부터 뺀다. 응시료를 모르는 자격은 합에 넣지 않고 따로 알린다
    budget = conditions.get("budget")
    while budget and sum(p["fee_total"] or 0 for p in placed) > budget and placed:
        p = placed.pop()
        excluded.append({"qual_id": p["qual_id"], "name": p["name"], "reason_code": "BUDGET_EXCEEDED",
                         "detail": f"응시료 합계가 예산 {budget:,}원을 넘음", "prep_weeks": p["prep_weeks"]})

    # 공부를 시작하는 날 순서로 보여 준다 (병행하면 루트 순서와 날짜 순서가 다를 수 있다)
    placed.sort(key=lambda p: (p["_window"][0], p["exam_date"]))
    for p in placed:
        p["parallel_with"] = [o["name"] for o in placed if o is not p and _overlaps(p["_window"], o["_window"])]
    for p in placed:
        for k in ("_days", "_final", "_window", "_chain"):
            p.pop(k)
    return {
        "placed": placed,
        "excluded": excluded,
        "fee_total": sum(p["fee_total"] or 0 for p in placed),
        "fee_unknown": [p["name"] for p in placed if p["fee_total"] is None],
        "deadline_ignored": ignore_deadline and bool(conditions.get("deadline")),
        "deferred": deferred,
    }
