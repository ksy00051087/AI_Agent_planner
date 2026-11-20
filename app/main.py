"""FastAPI 앱 조립 (F3017).

실행 (프로젝트 폴더에서):
    ./venv/Scripts/python -m uvicorn app.main:app --reload
화면:
    http://localhost:8000/        (web/ 폴더를 같은 서버가 내려준다)
API 문서:
    http://localhost:8000/docs
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import calendar as calendar_api
from .api import chat, logs, plans
from .events import default_bus
from .logging_agent import LoggingAgent
from .storage import Database, LogStore, PlanStore

ROOT = Path(__file__).resolve().parents[1]


class NoStalePage:
    """text/html 응답에 Cache-Control: no-cache 를 붙이는 순수 ASGI 미들웨어 (요청 · 본문은 건드리지 않는다)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                ctype = next((v for k, v in headers if k.lower() == b"content-type"), b"")
                if ctype.startswith(b"text/html"):
                    message = {**message, "headers": headers + [(b"cache-control", b"no-cache")]}
            await send(message)

        await self.app(scope, receive, send_wrapper)


def create_app(db_path: str | None = None, agent=None, bus=None) -> FastAPI:
    app = FastAPI(title="직업 준비 플래너", description="직업을 말하면 그 직업에 이어지는 자격을 시험 일정으로 계획하는 Agent")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5500", "http://127.0.0.1:5500"],
                       allow_methods=["*"], allow_headers=["*"])

    bus = bus or default_bus
    db = Database(db_path or os.getenv("DB_PATH") or ROOT / "data" / "app.sqlite3")
    app.state.plans = PlanStore(db)
    app.state.logs = LogStore(db)
    # 캘린더 (F3023): 로컬 구현체가 기본, CALENDAR_BACKEND=google 이면 Google Calendar. Tool 입출력은 같다
    from .calendar import GoogleCalendar, LocalCalendar
    from .tools import calendar as calendar_tools
    backend = GoogleCalendar() if (os.getenv("CALENDAR_BACKEND") or "local").lower() == "google" else LocalCalendar(db.path)
    calendar_tools.configure(app.state.plans, backend)
    # 로깅 서브 Agent: 메인 Agent 는 모른다. 버스에 구독만 한다 (F3013)
    # 이상 징후(F3020): 판정은 규칙, '이상' 에만 진단 LLM. 실제 앱일 때만 진단 함수를 붙인다
    diagnose = None
    if agent is None:
        from .container import build_diagnose
        diagnose = build_diagnose()
    from .container import replan_limit
    app.state.logging_agent = LoggingAgent(app.state.logs, diagnose=diagnose, replan_limit=replan_limit()).attach(bus)
    if agent is None:
        from .agent.graph import PlannerAgent
        from .container import build_deps
        # 메인 Agent 는 저장된 판정을 읽는 함수만 받는다 (로깅 Agent 는 모른다)
        agent = PlannerAgent(build_deps(last_inspection=app.state.logs.latest_inspection), bus)
    app.state.agent = agent

    app.include_router(chat.router)
    app.include_router(plans.router)
    app.include_router(logs.router)
    app.include_router(calendar_api.router)

    @app.get("/api/health", tags=["system"])
    def health():
        """서버 상태 · LLM 키 설정 여부 · 로깅 Agent 저장 수."""
        from .llm import llm_configured
        from .tools.calendar import backend_name
        return {"ok": True, "llm_configured": llm_configured(), "calendar": backend_name(),
                "logging_agent": {"saved": app.state.logging_agent.saved, "dropped": app.state.logging_agent.dropped}}

    # 화면(HTML)은 매번 서버에 확인 — 업데이트 뒤에도 브라우저가 옛 화면을 그대로 쓰지 않게.
    # @app.middleware("http")(BaseHTTPMiddleware) 는 TestClient · 동기 엔드포인트와 함께 멈추는 사례가 있어
    # 응답 헤더만 고치는 순수 ASGI 미들웨어로 둔다
    app.add_middleware(NoStalePage)

    web = ROOT / "web"
    if web.is_dir():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")
    return app


app = create_app() if os.getenv("PLANNER_NO_AUTOAPP") != "1" else None
