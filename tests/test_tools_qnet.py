"""F3002 · F3003 — 정상 · 빈 입력 · 키 · 결과 없음 · 추정 · 빈 값."""

import json
from datetime import date

import pytest
import requests

from app.tools import run_tool
from app.tools.sources import manual
from tests.conftest import EMPTY_XML, KEY_ERROR_XML, FakeResponse, qnet_routes, sample


# ── F3002 search_qualifications ─────────────────────────────────
class TestSearchQualifications:
    def test_정상_분야로_후보와_식별자(self, fake_http):
        fake_http(qnet_routes())
        r = run_tool("search_qualifications", field="정보기술")
        assert r["ok"]
        names = [i["name"] for i in r["data"]["items"]]
        assert "정보처리기사" in names
        it = next(i for i in r["data"]["items"] if i["name"] == "정보처리기사")
        assert it["qual_id"] == "1320" and it["grade"] == "기사" and it["source"] == "qnet"

    def test_기준날짜_기본값은_오늘(self, fake_http):
        fake_http(qnet_routes())
        d = run_tool("search_qualifications", keyword="정보처리")["data"]
        assert d["base_date"] == date.today().isoformat() and d["base_date_defaulted"] is True
        assert d["estimated"] is False

    def test_요청기준과_조회기준이_다르면_추정(self, fake_http):
        fake_http(qnet_routes())
        d = run_tool("search_qualifications", keyword="정보처리", base_date=f"{date.today().year + 1}-03-01")["data"]
        assert d["estimated"] is True and "추정" in d["basis"]

    def test_등급_필터_산업기사와_기사를_구분(self, fake_http):
        fake_http(qnet_routes())
        d = run_tool("search_qualifications", keyword="정보처리", grade="기사")["data"]
        assert [i["name"] for i in d["items"]] == ["정보처리기사"]

    def test_빈입력(self, fake_http):
        fake_http(qnet_routes())
        assert run_tool("search_qualifications")["error"]["code"] == "BAD_ARGUMENT"
        assert run_tool("search_qualifications", keyword="정보", base_date="내일")["error"]["code"] == "BAD_ARGUMENT"

    def test_결과없음_큐넷밖_자격(self, fake_http):
        fake_http(qnet_routes())
        r = run_tool("search_qualifications", keyword="투자자산운용사")
        assert r["error"]["code"] == "NO_DATA"

    def test_키없이도_동작_키는_보내지_않음(self, fake_http):
        calls = fake_http(qnet_routes())
        assert run_tool("search_qualifications", keyword="정보처리")["ok"]
        assert "serviceKey" not in calls[0]["params"]

    def test_키가_있어도_HTTP로는_보내지_않음(self, fake_http, monkeypatch):
        # 큐넷은 HTTPS 를 받지 않는다 — 평문 HTTP 로 서비스키가 새지 않게
        monkeypatch.setenv("QNET_SERVICE_KEY", "secret-key")
        calls = fake_http(qnet_routes())
        assert run_tool("search_qualifications", keyword="정보처리")["ok"]
        assert calls and all("serviceKey" not in c["params"] for c in calls)

    def test_HTTPS_주소면_키를_보냄(self, fake_http, monkeypatch):
        from app.tools.sources import qnet
        monkeypatch.setenv("QNET_SERVICE_KEY", "secret-key")
        monkeypatch.setattr(qnet, "QNET_BASE", "https://example.test/rest")
        calls = fake_http(qnet_routes())
        assert run_tool("search_qualifications", keyword="정보처리")["ok"]
        assert calls[0]["params"].get("serviceKey") == "secret-key"

    def test_키가_틀리면_INVALID_KEY(self, fake_http, monkeypatch):
        monkeypatch.setenv("QNET_SERVICE_KEY", "wrong")
        fake_http([("getList", FakeResponse(status_code=401, text=KEY_ERROR_XML))])
        assert run_tool("search_qualifications", keyword="정보")["error"]["code"] == "INVALID_KEY"

    def test_네트워크_오류는_예외가_아니라_UPSTREAM_ERROR(self, fake_http):
        fake_http([("getList", requests.ConnectionError("down"))])
        assert run_tool("search_qualifications", keyword="정보")["error"]["code"] == "UPSTREAM_ERROR"

    def test_보충데이터는_출처와_확인일이_있을때만(self, fake_http, monkeypatch, tmp_path):
        f = tmp_path / "manual.json"
        f.write_text(json.dumps({"items": [
            {"name": "투자자산운용사", "field": "금융", "source_url": "https://example.org/notice", "checked_at": "2026-11-18"},
            {"name": "출처없는자격", "field": "금융"},
        ]}, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(manual, "FILE", f)
        fake_http(qnet_routes())
        d = run_tool("search_qualifications", field="금융")["data"]
        assert [(i["qual_id"], i["source"]) for i in d["items"]] == [("manual:투자자산운용사", "manual")]


# ── F3003 get_exam_schedule ─────────────────────────────────────
class TestGetExamSchedule:
    def test_정상_공고된_회차와_응시료(self, fake_http):
        fake_http(qnet_routes())
        d = run_tool("get_exam_schedule", qual_id="1320", from_date="2026-04-01")["data"]
        assert d["name"] == "정보처리기사" and d["estimated"] is False
        assert [r["written_exam_start"] for r in d["rounds"]][:3] == ["2026-05-09", "2026-08-07", "2027-01-30"]
        assert [r["estimated"] for r in d["rounds"]][:3] == [False, False, True]
        assert d["fee"] == {"1차": 19400, "2차": 22600}

    def test_F3002_식별자를_그대로_넘겨_이어진다(self, fake_http):
        fake_http(qnet_routes())
        qid = run_tool("search_qualifications", keyword="정보처리기사")["data"]["items"][0]["qual_id"]
        assert run_tool("get_exam_schedule", qual_id=qid)["ok"]

    def test_다음해_미공고면_추정과_근거(self, fake_http):
        fake_http(qnet_routes())
        d = run_tool("get_exam_schedule", qual_id="1320", from_date="2026-11-18")["data"]
        assert d["estimated"] is True
        assert d["rounds"][0]["written_exam_start"] == "2027-01-30"
        assert "미공고" in d["rounds"][0]["basis"]

    def test_시험일이_비면_채우지_않고_전용코드(self, fake_http):
        fake_http(qnet_routes(schedule_xml=sample("qnet_getJMList_9738_empty_dates.xml")))
        r = run_tool("get_exam_schedule", qual_id="9738")
        assert r["error"]["code"] == "NO_EXAM_DATE"

    def test_빈입력_형식오류(self, fake_http):
        fake_http(qnet_routes())
        for args in ({}, {"qual_id": ""}, {"qual_id": "abc"}, {"qual_id": "1320", "from_date": "2026/01/01"}):
            assert run_tool("get_exam_schedule", **args)["error"]["code"] == "BAD_ARGUMENT", args

    def test_없는_종목코드는_NOT_FOUND(self, fake_http):
        fake_http(qnet_routes())
        assert run_tool("get_exam_schedule", qual_id="0000")["error"]["code"] == "NOT_FOUND"

    def test_종목은_있는데_일정이_비면_NO_DATA(self, fake_http):
        fake_http(qnet_routes(schedule_xml=EMPTY_XML))
        assert run_tool("get_exam_schedule", qual_id="1320")["error"]["code"] == "NO_DATA"

    def test_응시료_조회가_실패해도_일정은_돌려주고_0으로_채우지_않음(self, fake_http):
        routes = qnet_routes()
        routes[2] = ("getFeeList", requests.Timeout("slow"))
        fake_http(routes)
        d = run_tool("get_exam_schedule", qual_id="1320")["data"]
        assert d["fee"] is None and d["fee_text"] is None and d["rounds"]

    def test_키가_틀리면_INVALID_KEY(self, fake_http, monkeypatch):
        monkeypatch.setenv("QNET_SERVICE_KEY", "wrong")
        fake_http([("getList", FakeResponse(text=KEY_ERROR_XML)), ("getJMList", FakeResponse(text=KEY_ERROR_XML))])
        assert run_tool("get_exam_schedule", qual_id="1320")["error"]["code"] == "INVALID_KEY"


@pytest.mark.live
def test_live_큐넷_실제호출():
    r = run_tool("get_exam_schedule", qual_id="1320")
    assert r["ok"], r
    assert r["data"]["rounds"]


class TestExamInfoAndPassRate:
    def test_시험과목_합격기준_합격률이_붙는다(self, fake_http):
        fake_http(qnet_routes())
        d = run_tool("get_exam_schedule", qual_id="1320")["data"]
        assert d["exam_info"]["subjects"]["필기"][0] == "소프트웨어설계"
        pr = d["pass_rate"]
        assert pr["by_stage"]["필기"]["rate"] == 65.0 and pr["by_stage"]["실기"]["rate"] == 22.1
        assert str(pr["year"]) in pr["basis"]

    def test_부가정보가_실패해도_일정은_나오고_None(self, fake_http):
        routes = qnet_routes()
        routes[3] = ("InquiryInformationTradeNTQSVC", requests.Timeout("slow"))
        routes[4] = ("InquiryQualPassRateSVC", FakeResponse(status_code=500, text="err"))
        fake_http(routes)
        d = run_tool("get_exam_schedule", qual_id="1320")["data"]
        assert d["rounds"] and d["exam_info"] is None and d["pass_rate"] is None


def test_이름이_등급으로_끝나지_않아도_종목목록_등급으로_합격률_등급코드를_찾는다(monkeypatch):
    from app.tools.sources import qnet
    monkeypatch.setattr(qnet, "list_quals", lambda: (None, [{"qual_id": "7937", "name": "미용사(일반)", "grade": "기능사"}]))
    assert qnet._grade_code("미용사(일반)", "7937") == qnet.GRADE_CODES["기능사"]
    assert qnet._grade_code("전기기사") == qnet.GRADE_CODES["기사"]          # 목록 없이도 이름 끝 등급으로
