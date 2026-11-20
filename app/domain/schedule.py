"""시험 회차 정규화 · 미공고 연도 추정 · 응시료 파싱.

외부 API 응답의 '모양'은 모른다. tools/ 가 꺼내 준 문자열만 받아 판정한다.
비어 있는 값은 채우지 않는다 — None 으로 두고 missing 에 이름을 남긴다.
"""

from __future__ import annotations

import re
from datetime import date

# 회차에서 계획 판단에 쓰는 날짜. 필기 접수 마감과 필기 시험 시작일이 없으면 그 회차는 판단하지 않는다.
REQUIRED_FIELDS = ("written_reg_end", "written_exam_start")

# tools 가 넘겨주는 이름 → 정규화된 이름
FIELD_NAMES = (
    "written_reg_start", "written_reg_end",
    "written_exam_start", "written_exam_end",
    "written_pass",
    "practical_reg_start", "practical_reg_end",
    "practical_exam_start", "practical_exam_end",
    "practical_pass",
)


def parse_ymd(value: str | None) -> date | None:
    """'20260130' → date. 빈 값 · 'XXXXXXXX' · 잘못된 날짜는 None (임의로 채우지 않는다)."""
    if not value:
        return None
    s = value.strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def shift_year(d: date, years: int) -> date:
    """같은 월·일로 연도만 옮긴다. 2월 29일은 28일로."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def normalize_round(name: str, raw_dates: dict[str, str | None]) -> dict:
    """회차 하나를 정규화한다.

    raw_dates: FIELD_NAMES 를 키로 하는 'YYYYMMDD' 문자열 (없으면 None/빈 값)
    반환: {"name", "dates": {필드: date|None}, "missing": [...], "judgeable": bool, "estimated": False}
    """
    dates = {f: parse_ymd(raw_dates.get(f)) for f in FIELD_NAMES}
    # 필기만 하루 치르면 종료일이 없다 → 시작일과 같다고 '추정'하지 않고 그대로 비워 둔다
    missing = [f for f in REQUIRED_FIELDS if dates[f] is None]
    return {
        "name": name,
        "dates": dates,
        "missing": missing,
        "judgeable": not missing,
        "estimated": False,
        "basis": None,
    }


def upcoming_rounds(rounds: list[dict], from_date: date, max_years_ahead: int = 2) -> list[dict]:
    """from_date 이후에 '접수할 수 있는' 회차를 돌려준다.

    1) 실제 공고된 회차 중 필기 접수 마감이 from_date 이후인 것 → estimated=False
    2) 하나도 없으면, 가장 최근 연도의 회차를 1년씩 옮겨 추정한다 → estimated=True, basis 에 근거
       (예: 2027년 일정이 미공고면 2026년 같은 회차 +1년)
    판단할 수 없는 회차(missing 이 있는 것)는 옮기지 않는다.
    """
    judgeable = [r for r in rounds if r["judgeable"]]
    if not judgeable:
        return []
    actual = [r for r in judgeable if r["dates"]["written_reg_end"] >= from_date]
    last_actual = max((r["dates"]["written_exam_start"] for r in actual), default=None)

    # 공고된 회차 뒤로는 다음 해들을 추정으로 이어 붙인다 (올해 남은 회차만으로는 준비 기간이 모자랄 수 있다)
    latest_year = max(r["dates"]["written_exam_start"].year for r in judgeable)
    base = [r for r in judgeable if r["dates"]["written_exam_start"].year == latest_year]
    projected = []
    for years in range(1, max_years_ahead + 1):
        for r in base:
            moved = {k: (shift_year(v, years) if v else None) for k, v in r["dates"].items()}
            if moved["written_reg_end"] < from_date:
                continue
            if last_actual and moved["written_exam_start"] <= last_actual:
                continue  # 실제 공고가 있는 기간은 추정하지 않는다
            projected.append({
                **r,
                "name": f"{latest_year + years}년 추정 ({r['name']}와 같은 시기)",
                "dates": moved,
                "estimated": True,
                "basis": f"{latest_year + years}년 일정 미공고 — {latest_year}년 같은 회차 날짜에 {years}년을 더한 추정치",
            })
    return sorted(actual + projected, key=lambda r: (r["dates"]["written_exam_start"], r["estimated"]))


_FEE_RE = re.compile(r"(필기|실기|1차|2차|3차|면접)?\s*[:：]?\s*([\d,]{3,})")


def parse_fee(text: str | None) -> dict[str, int] | None:
    """'1차 : 19400, 2차 : 22600' → {'1차': 19400, '2차': 22600}. 못 읽으면 None."""
    if not text:
        return None
    fees: dict[str, int] = {}
    for i, (label, amount) in enumerate(_FEE_RE.findall(text)):
        digits = amount.replace(",", "")
        if digits.isdigit():
            fees[label or f"항목{i + 1}"] = int(digits)
    return fees or None
