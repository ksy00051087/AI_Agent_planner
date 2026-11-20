"""대화 라우터 (F3017). 메인 Agent 는 app.state.agent (PlannerAgent)."""

import uuid

from fastapi import APIRouter, HTTPException, Request

from ..schemas import ChatIn, ChatOut

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatOut)
def chat(body: ChatIn, request: Request):
    """사용자 발화 1건을 메인 Agent 로 처리한다. 응답 · 계획 초안 · 제외 사유 · 실행 이벤트를 돌려준다."""
    session_id = body.session_id or uuid.uuid4().hex[:12]
    try:
        extra = {"selection": body.selection.model_dump()} if body.selection else {}
        result = request.app.state.agent.run(session_id, body.message, **extra)
    except Exception:
        # 오류 상세(키가 섞일 수 있는 원문)는 화면에 보내지 않는다 (NF3002)
        raise HTTPException(status_code=500, detail="요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.")
    return result
