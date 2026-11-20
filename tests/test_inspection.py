"""F3020 이상 징후 판단 — 규칙 판정 · 판정 불가 · 이상일 때만 진단 · 진단 실패 격리 · 메인 Agent 참조 (검증 4.6)."""

from fastapi.testclient import TestClient

from app.events import Emitter, EventBus
from app.logging_agent import LoggingAgent
from app.logging_agent.inspector import ANOMALY, NORMAL, UNKNOWN, inspect_run
from app.main import create_app
from app.storage import Database, LogStore


def run_events(*, plan_tools=("search_qualifications", "get_exam_schedule"), calls=(), replans=0, finish=True, plan=True):
    em = Emitter(None, "s1")
    em.node_enter("analyze")
    if plan:
        em.node_exit("plan", steps=[{"tool": t, "why": ""} for t in plan_tools])
    for tool, args in calls:
        em.tool_call("execute", tool, args)
        em.tool_result("execute", tool, {"ok": True, "data": {}}, 5)
    for i in range(replans):
        em.replan("replan", i + 1, "NO_FEASIBLE_PLAN", "다음 후보")
    if finish:
        em.node_exit("respond")
    return em.events


def types(r):
    return [w["type"] for w in r["warnings"]]


# ── 규칙 판정 ───────────────────────────────────────────────────
def test_정상():
    r = inspect_run(run_events(calls=[("search_qualifications", {"field": "전기"}),
                                      ("get_exam_schedule", {"qual_id": "1150"})]))
    assert r["verdict"] == NORMAL and r["warnings"] == []


def test_같은_Tool_같은_입력_반복호출():
    r = inspect_run(run_events(calls=[("get_exam_schedule", {"qual_id": "1150"})] * 3))
    assert r["verdict"] == ANOMALY and types(r) == ["REPEATED_CALL"]
    assert len(r["warnings"][0]["evidence"]) == 3


def test_재계획_과도():
    r = inspect_run(run_events(replans=2), replan_limit=2)
    assert types(r) == ["EXCESSIVE_REPLAN"]
    assert inspect_run(run_events(replans=1), replan_limit=2)["verdict"] == NORMAL


def test_계획에_없던_Tool_호출():
    r = inspect_run(run_events(plan_tools=("search_qualifications",), calls=[("search_books", {"qualification_name": "x"})]))
    assert types(r) == ["UNPLANNED_CALL"] and "search_books" in r["warnings"][0]["detail"]


def test_근거가_없으면_이상없음이_아니라_판정불가():
    assert inspect_run([])["verdict"] == UNKNOWN
    assert inspect_run(run_events(finish=False))["verdict"] == UNKNOWN          # 끝났는지 모름
    r = inspect_run(run_events(plan=False, calls=[("search_books", {})]))      # 계획 이벤트 없음
    assert r["verdict"] == UNKNOWN and "계획" in r["reason"]


def test_Tool_없는_대화는_정상():
    assert inspect_run(run_events(plan=False))["verdict"] == NORMAL


# ── 로깅 Agent: 판정 저장 · 이상일 때만 진단 ──────────────────────
def make_agent(tmp_path, diagnose):
    store = LogStore(Database(tmp_path / "i.sqlite3"))
    bus = EventBus()
    la = LoggingAgent(store, diagnose=diagnose, background=False).attach(bus)
    return store, bus, la


def publish(bus, events):
    for e in events:
        bus.publish(e)


def test_이상일_때만_진단을_부르고_판정과_진단을_따로_저장(tmp_path):
    called = []
    store, bus, la = make_agent(tmp_path, lambda r, ev: called.append(r["run_id"]) or "Tool 캐시 키가 인자 순서에 따라 달라짐.")
    normal = run_events(calls=[("search_qualifications", {"field": "전기"})])
    bad = run_events(calls=[("get_exam_schedule", {"qual_id": "1"})] * 2)
    publish(bus, normal)
    publish(bus, bad)
    ins = store.inspections("s1")
    assert [i["verdict"] for i in ins] == [NORMAL, ANOMALY]
    assert called == [bad[0]["run_id"]]                       # 정상에는 LLM 을 부르지 않는다
    assert ins[0]["diagnosis"] is None and ins[0]["diagnosis_status"] is None
    assert ins[1]["diagnosis_status"] == "ok" and "캐시" in ins[1]["diagnosis"]
    assert len(ins[1]["warnings"]) == 1                       # 진단이 경고 수에 섞이지 않는다


def test_진단이_실패해도_판정과_로그는_남는다(tmp_path):
    def broken(r, ev):
        raise TimeoutError("LLM 시간 초과")

    store, bus, la = make_agent(tmp_path, broken)
    publish(bus, run_events(replans=2))
    ins = store.latest_inspection("s1")
    assert ins["verdict"] == ANOMALY and ins["diagnosis_status"] == "failed" and ins["diagnosis"] is None
    assert len(store.events("s1")) > 0


# ── 메인 Agent 가 판정을 참조 ────────────────────────────────────
def test_메인Agent는_직전_판정을_참조한다():
    from app.agent.deps import AgentDeps
    from app.agent.graph import PlannerAgent
    from app.agent.state import AnalyzeOutput, Conditions

    prev = {"run_id": "r0", "verdict": ANOMALY, "warnings": [{"type": "EXCESSIVE_REPLAN", "detail": "", "evidence": []}]}
    deps = AgentDeps(run_tool=lambda *a, **k: None, tool_catalog=lambda: [], field_options=lambda: [],
                     analyze_llm=lambda m: AnalyzeOutput(intent="plan_create", intent_reason="", new_topic=True,
                                                         conditions=Conditions()),
                     last_inspection=lambda sid: prev)
    res = PlannerAgent(deps).run("s9", "자격증 따고 싶어", today="2026-11-18")
    assert res["prev_inspection"]["verdict"] == ANOMALY
    assert res["events"][0]["type"] == "inspection_seen"
    assert "이상 징후(EXCESSIVE_REPLAN)" in res["answer"]


def test_API_로_판정을_조회(tmp_path):
    from tests.test_api import FakeAgent

    bus = EventBus()
    c = TestClient(create_app(db_path=str(tmp_path / "a.sqlite3"), agent=FakeAgent(bus), bus=bus))
    sid = c.post("/api/chat", json={"message": "x"}).json()["session_id"]
    ins = c.get(f"/api/logs/{sid}/inspections").json()
    # FakeAgent 는 plan 이벤트 없이 Tool 을 불렀다 → 판정 불가
    assert len(ins) == 1 and ins[0]["verdict"] == UNKNOWN and ins[0]["reason"]
