"""출처 어댑터: 공식 공고문을 사람이 옮겨 적은 로컬 데이터 (data/manual_schedules.json).

API 가 없는 기관(대한상공회의소 · 금융투자협회 등)용. source_url 과 checked_at 이 없는 항목은 쓰지 않는다.
식별자: manual:<자격명>
"""

from __future__ import annotations

import json
from pathlib import Path

from ..base import NOT_FOUND, fail

NAME = "manual"
PREFIX = "manual:"
FILE = Path(__file__).resolve().parents[3] / "data" / "manual_schedules.json"


def owns(qual_id: str) -> bool:
    return (qual_id or "").startswith(PREFIX)


def _items() -> list[dict]:
    """파일이 없거나 깨져도 다른 출처는 그대로 동작한다."""
    try:
        body = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [it for it in body.get("items", [])
            if it.get("name") and it.get("source_url") and it.get("checked_at")]


def list_quals():
    return None, [{
        "qual_id": f"{PREFIX}{it['name']}",
        "name": it["name"],
        "grade": it.get("grade"),
        "qual_type": it.get("qual_type", "민간 · 협회"),
        "field": it.get("field"),
        "sub_field": it.get("sub_field"),
        "organization": it.get("organization"),
        "source": NAME,
    } for it in _items()]


def get_schedule(qual_id: str):
    name = qual_id[len(PREFIX):]
    item = next((it for it in _items() if it["name"] == name), None)
    if not item:
        return fail(NOT_FOUND, f"'{name}' 는 보충 데이터에 없습니다."), None, None
    rounds = [{"name": r.get("name", ""), "dates": r.get("dates", {}), "stage": r.get("stage"),
               "exam_time": r.get("exam_time")} for r in item.get("rounds", [])]
    return None, rounds, {
        "name": name,
        "grade": item.get("grade"),
        "organization": item.get("organization"),
        "source": f"공고문 기준 수동 입력 ({item['source_url']}, {item['checked_at']} 확인)",
        "fee": item.get("fee"),
        "fee_text": None,
    }
