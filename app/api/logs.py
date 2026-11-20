"""실행 로그 라우터 (F3014) — 목록 · 상세 · 삭제만. 수정 API 는 두지 않는다 (기록을 고칠 수 있으면 관찰의 의미가 없다)."""

from fastapi import APIRouter, HTTPException, Request

from ..schemas import LogEvent, LogInspection, LogSession

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("", response_model=list[LogSession])
def list_sessions(request: Request):
    """세션 단위 실행 로그 목록 (요청 수 · 이벤트 수 · 재계획 · Tool 실패 수)."""
    return request.app.state.logs.sessions()


@router.get("/{session_id}", response_model=list[LogEvent])
def session_events(session_id: str, request: Request):
    """특정 세션의 실행 로그를 실행 순서대로."""
    events = request.app.state.logs.events(session_id)
    if not events:
        raise HTTPException(status_code=404, detail="그런 세션의 실행 로그가 없습니다.")
    return events


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: str, request: Request):
    """특정 세션의 실행 로그 삭제."""
    if not request.app.state.logs.delete(session_id):
        raise HTTPException(status_code=404, detail="그런 세션의 실행 로그가 없습니다.")


@router.get("/{session_id}/inspections", response_model=list[LogInspection])
def session_inspections(session_id: str, request: Request):
    """세션의 요청별 이상 징후 판정(F3020, 규칙) 과 진단(LLM, 이상일 때만). 판정과 진단은 칸이 따로다."""
    return request.app.state.logs.inspections(session_id)
