"""F3013 ~ F3017 — API 서버, 계획 저장 · 겹침 알림, 로깅 Agent 와 실행 로그."""

import pytest
from fastapi.testclient import TestClient

from app.events import Emitter, EventBus
from app.logging_agent import LoggingAgent
from app.main import create_app
from app.storage import Database, LogStore


class FakeAgent:
    """메인 Agent 대역 — 이벤트를 버스로 발행한다 (로깅 Agent 가 받는지 확인)."""

    def __init__(self, bus, explode=False):
        self.bus, self.explode = bus, explode

    def run(self, session_id, message, today=None, selection=None):
        self.last_selection = selection
        if self.explode:
            raise RuntimeError("secret-key-1234 가 섞인 내부 오류")
        em = Emitter(self.bus, session_id)
        em.node_enter("analyze")
        em.tool_call("execute", "search_qualifications", {"field": "전기"})
        em.tool_result("execute", "search_qualifications", {"ok": True, "data": {}}, 12, 3)
        em.replan("replan", 1, "DEADLINE_INFEASIBLE", "기한 완화")
        em.node_exit("respond")
        return {"session_id": session_id, "run_id": em.run_id, "answer": f"답: {message}", "intent": "plan_create",
                "conditions": {}, "draft_plan": [], "excluded": [], "books": {}, "replans": [], "needs_replan": None,
                "failures": [], "events": em.events}


@pytest.fixture
def client(tmp_path):
    bus = EventBus()
    app = create_app(db_path=str(tmp_path / "t.sqlite3"), agent=FakeAgent(bus), bus=bus)
    return TestClient(app)


def plan(name="전기기능사", day="2027-01-20", start="09:00", end="10:00", **kw):
    return {"qual_name": name, "plan_date": day, "start_time": start, "end_time": end, **kw}


# ── 대화 · 로그 ──────────────────────────────────────────────────
def test_대화하면_로깅Agent가_세션단위로_순서대로_저장(client):
    r = client.post("/api/chat", json={"message": "전기 쪽 취업"}).json()
    sid = r["session_id"]
    assert r["answer"] == "답: 전기 쪽 취업" and [e["type"] for e in r["events"]][0] == "node_enter"
    client.post("/api/chat", json={"session_id": sid, "message": "다시"})
    client.post("/api/chat", json={"message": "다른 세션"})

    sessions = {s["session_id"]: s for s in client.get("/api/logs").json()}
    assert len(sessions) == 2 and sessions[sid]["runs"] == 2 and sessions[sid]["replans"] == 2
    events = client.get(f"/api/logs/{sid}").json()
    assert len(events) == 10 and all(e["session_id"] == sid for e in events)  # 세션이 섞이지 않는다
    assert [e["seq"] for e in events[:5]] == [1, 2, 3, 4, 5]
    assert events[2]["duration_ms"] == 12  # 원본 필드가 그대로 남는다


def test_실행로그는_조회_삭제만_수정API는_없다(client):
    sid = client.post("/api/chat", json={"message": "x"}).json()["session_id"]
    assert client.put(f"/api/logs/{sid}", json={}).status_code == 405
    assert client.patch(f"/api/logs/{sid}", json={}).status_code == 405
    assert client.delete(f"/api/logs/{sid}").status_code == 204
    assert client.get(f"/api/logs/{sid}").status_code == 404


def test_대화_오류는_상세를_숨긴다(tmp_path):
    bus = EventBus()
    c = TestClient(create_app(db_path=str(tmp_path / "e.sqlite3"), agent=FakeAgent(bus, explode=True), bus=bus))
    r = c.post("/api/chat", json={"message": "x"})
    assert r.status_code == 500 and "secret" not in r.text


def test_빈_메시지는_422(client):
    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_패널_선택은_selection_으로_Agent_에_전달(client):
    r = client.post("/api/chat", json={"message": "보유: SQLD", "selection": {"held": ["SQLD"], "include": ["한국사능력검정시험"]}})
    assert r.status_code == 200
    assert client.app.state.agent.last_selection == {"held": ["SQLD"], "include": ["한국사능력검정시험"], "tracks": []}


def test_로깅Agent가_저장에_실패해도_메인은_정상(tmp_path):
    class BrokenStore:
        def append(self, e):
            raise OSError("디스크 가득")

    bus = EventBus()
    la = LoggingAgent(BrokenStore()).attach(bus)
    Emitter(bus, "s").node_enter("analyze")
    assert la.dropped == 1


def test_로깅Agent는_LLM을_쓰지_않는다():
    import inspect

    import app.logging_agent.agent as mod
    src = inspect.getsource(mod)
    assert "llm" not in src.split('"""', 2)[2].lower()  # 문서 문자열 밖 코드에서


# ── 계획 ─────────────────────────────────────────────────────────
def test_계획_저장_목록_상세_생성일시(client):
    r = client.post("/api/plans", json=plan(estimated=True, study_start="2026-12-09")).json()
    assert r["overlaps"] == [] and r["plan"]["plan_id"] == 1 and r["plan"]["created_at"]
    assert client.get("/api/plans").json()[0]["qual_name"] == "전기기능사"
    assert client.get("/api/plans/1").json()["estimated"] is True


def test_같은날_시간이_겹치면_저장하고_알린다(client):
    client.post("/api/plans", json=plan())
    r = client.post("/api/plans", json=plan("한국사능력검정시험", start="09:30", end="11:00"))
    assert r.status_code == 201 and len(r.json()["overlaps"]) == 1 and "겹치는" in r.json()["message"]
    r = client.post("/api/plans", json=plan("SQLD", start="13:00", end="14:00"))
    assert r.json()["overlaps"] == []  # 같은 날이지만 시간이 다르다
    r = client.post("/api/plans", json=plan("시각 모름", start=None, end=None))
    assert len(r.json()["overlaps"]) == 3  # 시각을 모르면 같은 날 전부와 겹침으로 본다
    assert len(client.get("/api/plans").json()) == 4


def test_묶음저장(client):
    r = client.post("/api/plans/batch", json={"items": [plan(), plan("전기산업기사", "2027-08-07")]})
    assert r.status_code == 201 and len(r.json()) == 2


def test_수정과_삭제가_반영된다(client):
    client.post("/api/plans", json=plan())
    client.post("/api/plans", json=plan("B", "2027-02-01"))
    r = client.put("/api/plans/2", json={"plan_date": "2027-01-20", "start_time": "09:30", "end_time": "10:30"})
    assert r.json()["plan"]["plan_date"] == "2027-01-20" and len(r.json()["overlaps"]) == 1
    assert client.delete("/api/plans/1").status_code == 204
    assert [p["plan_id"] for p in client.get("/api/plans").json()] == [2]
    assert client.get("/api/plans/1").status_code == 404
    assert client.put("/api/plans/9", json={"memo": "x"}).status_code == 404


def test_계획_입력_검증(client):
    assert client.post("/api/plans", json=plan(start="25:00")).status_code == 422
    assert client.post("/api/plans", json={"plan_date": "2027-01-20"}).status_code == 422


def test_로그저장소_단위(tmp_path):
    store = LogStore(Database(tmp_path / "l.sqlite3"))
    em = Emitter(None, "s1")
    for e in [em.node_enter("a"), em.llm_decision("a", "intent", "plan_create", "이유")]:
        store.append(e)
    ev = store.events("s1")
    assert ev[1]["decision"] == "plan_create" and ev[1]["reason"] == "이유"


def test_화면은_캐시하지_않고_매번_확인(client):
    r = client.get("/")
    if r.status_code == 200 and r.headers.get("content-type", "").startswith("text/html"):
        assert r.headers["cache-control"] == "no-cache"
    # API(JSON) 응답은 그대로 — 미들웨어는 화면에만 헤더를 붙인다
    assert "no-cache" not in client.get("/api/health").headers.get("cache-control", "")
