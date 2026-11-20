"""캘린더 툴 (F3023) — 로컬 서버 API 툴 2종. 구현체(로컬 · Google)를 바꿔도 입출력은 그대로다.

    list_schedule(date_from, date_to)   이미 잡힌 일정 조회 → 제약 판단(시험일과 겹치는 날)에 쓴다
    register_plan(plan_id)              저장한 계획을 캘린더에 등록. 계획 ID 만 받고, 제목 · 날짜 · 시각은
                                        서버가 계획 저장소에서 읽는다 (모델이 값을 지어내지 못한다)

app/main.py 가 configure(plan_store, backend) 로 연결한다. 연결 전에는 NOT_CONFIGURED.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.calendar import CalendarUnavailable

from .base import BAD_ARGUMENT, INVALID_KEY, NOT_FOUND, UPSTREAM_ERROR, fail, ok

NOT_CONFIGURED = "NOT_CONFIGURED"
MAX_RANGE_DAYS = 800
_ctx: dict = {"plans": None, "backend": None}


def configure(plan_store, backend) -> None:
    _ctx.update(plans=plan_store, backend=backend)


def backend_name() -> str | None:
    return getattr(_ctx["backend"], "name", None)


def _range(date_from, date_to):
    try:
        a = date.fromisoformat(str(date_from)) if date_from else date.today()
        b = date.fromisoformat(str(date_to)) if date_to else a + timedelta(days=365)
    except ValueError:
        return fail(BAD_ARGUMENT, "date_from · date_to 는 YYYY-MM-DD 형식이어야 합니다."), None, None
    if b < a or (b - a).days > MAX_RANGE_DAYS:
        return fail(BAD_ARGUMENT, f"조회 기간은 0~{MAX_RANGE_DAYS}일이어야 합니다."), None, None
    return None, a.isoformat(), b.isoformat()


def list_schedule(date_from: str | None = None, date_to: str | None = None):
    backend = _ctx["backend"]
    if backend is None:
        return fail(NOT_CONFIGURED, "캘린더가 연결되지 않았습니다.")
    err, a, b = _range(date_from, date_to)
    if err:
        return err
    try:
        events = backend.list_events(a, b)
    except CalendarUnavailable as e:
        return fail(INVALID_KEY, str(e))
    except Exception:
        return fail(UPSTREAM_ERROR, "캘린더를 조회하지 못했습니다.")
    return ok({"backend": backend.name, "date_from": a, "date_to": b, "events": events,
               "busy_dates": sorted({e["date"] for e in events})})


def register_plan(plan_id: int):
    backend, plans = _ctx["backend"], _ctx["plans"]
    if backend is None or plans is None:
        return fail(NOT_CONFIGURED, "캘린더가 연결되지 않았습니다.")
    if not isinstance(plan_id, int) or plan_id < 1:
        return fail(BAD_ARGUMENT, "plan_id 는 저장한 계획의 번호(양의 정수)여야 합니다.")
    p = plans.get(plan_id)
    if p is None:
        return fail(NOT_FOUND, f"계획 {plan_id} 이 없습니다.")
    title = f"[시험] {p['qual_name']}" + (f" {p['stage']}" if p.get("stage") else "")
    lines = [f"자격: {p['qual_name']}", f"회차: {p.get('round_name') or '-'}",
             f"늦어도 공부 시작: {p.get('study_start') or '-'}", f"접수 마감: {p.get('registration_end') or '-'}",
             f"출처: {p.get('source') or '-'}", "※ 추정 일정 — 공고 후 다시 확인" if p.get("estimated") else "",
             "자격증 장기 플래너에서 등록"]
    try:
        made = backend.create_event(title, p["plan_date"], p.get("start_time"), p.get("end_time"),
                                    "\n".join(x for x in lines if x))
    except CalendarUnavailable as e:
        return fail(INVALID_KEY, str(e))
    except Exception:
        return fail(UPSTREAM_ERROR, "캘린더에 등록하지 못했습니다.")
    return ok({"backend": backend.name, "plan_id": plan_id, "title": title, "date": p["plan_date"],
               "start_time": p.get("start_time"), **made})
