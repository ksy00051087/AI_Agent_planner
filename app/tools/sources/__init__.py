"""시험일정 출처 레지스트리 — 출처마다 어댑터 하나.

어댑터가 지킬 모양 (모듈이든 객체든)
    NAME: str
    owns(qual_id) -> bool                         이 식별자가 내 것인가
    list_quals() -> (실패|None, [qual])          qual = {qual_id, name, grade, qual_type, field, sub_field, organization, source}
    get_schedule(qual_id) -> (실패|None, rounds_raw, meta)
        rounds_raw = [{"name": 회차명, "dates": {written_reg_end: 'YYYYMMDD', ...},   ← app.domain.schedule.FIELD_NAMES
                       "stage": "필기" | "실기" | "필기+실기" | None, "exam_time": "HH:MM" | None}]
        dates 의 written_* 는 '이 회차의 첫 단계(접수→시험)'다. 실기만 따로 접수하는 행은 stage="실기" 로 표시한다.
        meta = {name, grade, organization, source(출처 문구), fee, fee_text}

새 출처 붙이기
    · 공공데이터포털 CSV / 자동변환 API → data/sources.json 에 한 줄 (table.py 설명 참고). 코드 수정 없음
    · 모양이 다른 API → 이 폴더에 어댑터 파일 하나 + all_sources() 에 추가
    · API 가 없는 기관 → data/manual_schedules.json 에 공고문을 옮겨 적는다
"""

from __future__ import annotations

from . import manual, qnet, table


def all_sources() -> list:
    """앞에 있는 출처가 우선. 큐넷이 기준 출처다."""
    return [qnet, *[table.TableSource(c) for c in table.configs()], manual]


def source_for(qual_id: str):
    return next((s for s in all_sources() if s.owns(qual_id)), None)


def clear_caches() -> None:
    qnet.clear_cache()
    table.clear_cache()
