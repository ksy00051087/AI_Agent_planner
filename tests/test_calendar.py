"""F3023 캘린더 — 로컬 구현체 먼저 · Google 로 바꿔도 Tool 입출력 동일 · 계획 ID 만 받는 등록 (검증 4.6)."""

import pytest
from fastapi.testclient import TestClient

from app.calendar import GoogleCalendar, LocalCalendar
from app.storage import Database, PlanStore
from app.tools import TOOLS, run_tool
from app.tools import calendar as cal


@pytest.fixture
def plans(tmp_path):
    store = PlanStore(Database(tmp_path / "c.sqlite3"))
    store.create({"qual_name": "전기기능사", "plan_date": "2027-01-20", "start_time": "09:00", "end_time": None,
                  "stage": "필기+실기", "round_name": "2027년 추정", "study_start": "2026-12-09", "estimated": True,
                  "source": "큐넷", "registration_end": "2027-01-09"})
    store.create({"qual_name": "한국사능력검정시험", "plan_date": "2027-02-07"})
    return store


class FakeGoogleService:
    """googleapiclient 의 events().insert/list(...).execute() 모양만 흉내 낸다."""

    def __init__(self):
        self.inserted = []

    def events(self):
        return self

    def insert(self, calendarId, body):
        self.inserted.append(body)
        self._result = {"id": f"g{len(self.inserted)}", "htmlLink": "https://calendar.google.com/e"}
        return self

    def list(self, **kw):
        self._result = {"items": [
            {"id": "x", "summary": "가족 여행", "start": {"date": "2027-01-20"}, "end": {"date": "2027-01-21"},
             "htmlLink": "https://calendar.google.com/x"},
            {"id": "y", "summary": "회의", "start": {"dateTime": "2027-02-01T14:00:00+09:00"},
             "end": {"dateTime": "2027-02-01T15:00:00+09:00"}}]}
        return self

    def execute(self):
        return self._result


def google_backend():
    g = GoogleCalendar()
    g._svc = FakeGoogleService()
    return g


def test_로컬_서버_API_툴로_정의():
    assert TOOLS["register_plan"].kind == "local" and TOOLS["list_schedule"].kind == "local"
    assert TOOLS["register_plan"].parameters["required"] == ["plan_id"]
    assert set(TOOLS["register_plan"].parameters["properties"]) == {"plan_id"}   # 제목 · 시각을 받지 않는다


def test_연결전에는_NOT_CONFIGURED():
    cal.configure(None, None)
    assert run_tool("list_schedule")["error"]["code"] == "NOT_CONFIGURED"


def test_로컬_구현체로_등록과_조회(plans, tmp_path):
    cal.configure(plans, LocalCalendar(tmp_path / "c.sqlite3"))
    r = run_tool("register_plan", plan_id=1)["data"]
    assert r["backend"] == "local" and r["title"] == "[시험] 전기기능사 필기+실기" and r["start_time"] == "09:00"
    run_tool("register_plan", plan_id=2)
    d = run_tool("list_schedule", date_from="2027-01-01", date_to="2027-12-31")["data"]
    assert d["busy_dates"] == ["2027-01-20", "2027-02-07"]
    assert [e["all_day"] for e in d["events"]] == [False, True]


def test_등록은_계획ID만_제목_날짜는_저장소에서(plans, tmp_path):
    cal.configure(plans, LocalCalendar(tmp_path / "c.sqlite3"))
    assert run_tool("register_plan", plan_id=99)["error"]["code"] == "NOT_FOUND"
    assert run_tool("register_plan", plan_id=0)["error"]["code"] == "BAD_ARGUMENT"
    assert run_tool("register_plan", plan_id=1, title="지어낸 제목")["error"]["code"] == "BAD_ARGUMENT"


def test_Google_구현체로_바꿔도_Tool_입출력이_같다(plans, tmp_path):
    cal.configure(plans, LocalCalendar(tmp_path / "c.sqlite3"))
    local_reg = run_tool("register_plan", plan_id=1)["data"]
    local_list = run_tool("list_schedule", date_from="2027-01-01", date_to="2027-12-31")["data"]

    g = google_backend()
    cal.configure(plans, g)
    google_reg = run_tool("register_plan", plan_id=1)["data"]
    google_list = run_tool("list_schedule", date_from="2027-01-01", date_to="2027-12-31")["data"]

    assert set(local_reg) == set(google_reg) and google_reg["backend"] == "google" and google_reg["link"]
    assert set(local_list) == set(google_list)
    assert set(local_list["events"][0]) == set(google_list["events"][0])
    # 시각이 있으면 시간 일정(+2시간), 없으면 하루 종일
    body = g._svc.inserted[0]
    assert body["start"]["dateTime"] == "2027-01-20T09:00:00" and body["end"]["dateTime"] == "2027-01-20T11:00:00"
    assert "추정 일정" in body["description"]
    run_tool("register_plan", plan_id=2)
    assert g._svc.inserted[1]["start"] == {"date": "2027-02-07"}
    assert google_list["busy_dates"] == ["2027-01-20", "2027-02-01"]


def test_Google_로그인이_없으면_안내(plans, monkeypatch, tmp_path):
    from app.calendar import backends

    monkeypatch.setattr(backends, "GOOGLE_DIR", tmp_path / "nogoogle")
    cal.configure(plans, GoogleCalendar())
    r = run_tool("list_schedule")
    assert r["error"]["code"] == "INVALID_KEY" and "로그인" in r["error"]["message"]


def test_API(tmp_path):
    from app.events import EventBus
    from app.main import create_app
    from tests.test_api import FakeAgent

    bus = EventBus()
    c = TestClient(create_app(db_path=str(tmp_path / "a.sqlite3"), agent=FakeAgent(bus), bus=bus))
    pid = c.post("/api/plans", json={"qual_name": "전기기사", "plan_date": "2027-05-09"}).json()["plan"]["plan_id"]
    r = c.post(f"/api/plans/{pid}/calendar")
    assert r.status_code == 201 and r.json()["backend"] == "local"
    assert c.get("/api/calendar?date_from=2027-05-01&date_to=2027-05-31").json()["busy_dates"] == ["2027-05-09"]
    assert c.post("/api/plans/999/calendar").status_code == 404
    assert c.get("/api/health").json()["calendar"] == "local"
