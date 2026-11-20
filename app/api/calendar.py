"""캘린더 라우터 (F3023) — Tool 을 그대로 부른다. 구현체(로컬 · Google)는 CALENDAR_BACKEND 로 고른다."""

from fastapi import APIRouter, HTTPException

from ..tools import run_tool

router = APIRouter(tags=["calendar"])
STATUS = {"BAD_ARGUMENT": 422, "NOT_FOUND": 404, "NOT_CONFIGURED": 503, "INVALID_KEY": 503, "UPSTREAM_ERROR": 502}


def _unwrap(r: dict) -> dict:
    if r["ok"]:
        return r["data"]
    # 오류 원문 대신 Tool 이 정한 안내 문구만 (NF3002)
    raise HTTPException(status_code=STATUS.get(r["error"]["code"], 500), detail=r["error"]["message"])


@router.get("/api/calendar")
def list_calendar(date_from: str | None = None, date_to: str | None = None):
    """캘린더 일정 조회 (list_schedule Tool). 기본: 오늘부터 1년."""
    return _unwrap(run_tool("list_schedule", **{k: v for k, v in {"date_from": date_from, "date_to": date_to}.items() if v}))


@router.post("/api/plans/{plan_id}/calendar", status_code=201)
def register_plan_to_calendar(plan_id: int):
    """저장한 계획을 캘린더에 등록 (register_plan Tool). 계획 번호만 받고 제목 · 날짜 · 시각은 저장소에서 읽는다."""
    return _unwrap(run_tool("register_plan", plan_id=plan_id))
