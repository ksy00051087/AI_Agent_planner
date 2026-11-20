"""F3004 search_books — 정상 · 빈 입력 · 키 없음 · 결과 없음 · 짝짓지 않음 (카카오 책 검색)."""

import os

import pytest
import requests

from app.tools import run_tool
from tests.conftest import FakeResponse


def doc(title, dt, price=-1, authors=("홍길동",)):
    return {"title": title, "authors": list(authors), "publisher": "가나출판", "datetime": f"{dt}T00:00:00.000+09:00",
            "sale_price": price, "isbn": "1234567890 9781234567890", "url": "https://kakao.example/1"}


BODY = {"meta": {"total_count": 3}, "documents": [
    doc("2026 정보처리기사 필기 기본서", "2025-10-20", 27000, ("홍길동", "김철수")),
    doc("2027 이기적 정보처리기사 필기", "2026-11-01"),
    doc("SQL 첫걸음", "2024-01-01", 18000),
]}


@pytest.fixture
def kakao(monkeypatch):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "k")


def test_정상_제목일치만_최근출간순(kakao, fake_http):
    calls = fake_http([("dapi.kakao.com", FakeResponse(body=BODY))])
    r = run_tool("search_books", qualification_name="정보처리기사", exam_type="필기")
    assert r["ok"]
    d = r["data"]
    assert d["provider"] == "kakao"
    assert [b["pub_date"] for b in d["items"]] == ["2026-11-01", "2025-10-20"]
    assert d["items"][0]["price"] is None  # 가격이 없으면(-1) 0 으로 채우지 않는다
    assert d["items"][1]["authors"] == "홍길동, 김철수"
    assert d["excluded_unmatched"] == 1  # 'SQL 첫걸음' 은 짝짓지 않고 제외
    assert calls[0]["params"]["query"] == "정보처리기사 필기"


def test_빈입력(kakao, fake_http):
    fake_http([])
    assert run_tool("search_books", qualification_name="")["error"]["code"] == "BAD_ARGUMENT"
    assert run_tool("search_books", qualification_name="x", exam_type="면접")["error"]["code"] == "BAD_ARGUMENT"
    assert run_tool("search_books")["error"]["code"] == "BAD_ARGUMENT"


def test_키없음(fake_http):
    fake_http([])
    assert run_tool("search_books", qualification_name="정보처리기사")["error"]["code"] == "INVALID_KEY"


def test_키가_틀림(kakao, fake_http):
    fake_http([("dapi.kakao.com", FakeResponse(status_code=401, body={}))])
    assert run_tool("search_books", qualification_name="정보처리기사")["error"]["code"] == "INVALID_KEY"


def test_한도초과는_전용코드(kakao, fake_http):
    fake_http([("dapi.kakao.com", FakeResponse(status_code=429, body={}))])
    assert run_tool("search_books", qualification_name="정보처리기사")["error"]["code"] == "QUOTA_EXCEEDED"


def test_결과없음_형식(kakao, fake_http):
    fake_http([("dapi.kakao.com", FakeResponse(body={"meta": {"total_count": 0}, "documents": []}))])
    r = run_tool("search_books", qualification_name="없는자격증")
    assert r == {"ok": False, "error": {"code": "NO_DATA", "message": r["error"]["message"]}}


def test_검색결과는_있지만_제목이_전부_불일치면_NO_DATA(kakao, fake_http):
    fake_http([("dapi.kakao.com", FakeResponse(body=BODY))])
    r = run_tool("search_books", qualification_name="전기기사")
    assert r["error"]["code"] == "NO_DATA" and "3건" in r["error"]["message"]


def test_네트워크_오류(kakao, fake_http):
    fake_http([("dapi.kakao.com", requests.ConnectionError("down"))])
    assert run_tool("search_books", qualification_name="정보처리기사")["error"]["code"] == "UPSTREAM_ERROR"


def test_필기를_찾으면_실기만_다룬_책은_제외_합본은_유지(kakao, fake_http):
    body = {"meta": {}, "documents": [doc("정보처리기사, 실기는 코드에서 갈린다", "2026-11-12"),
                                      doc("정보처리기사 필기+실기 합본", "2026-10-01"),
                                      doc("정보처리기사 필기 기본서", "2026-09-01")]}
    fake_http([("dapi.kakao.com", FakeResponse(body=body))])
    d = run_tool("search_books", qualification_name="정보처리기사", exam_type="필기")["data"]
    assert [b["title"] for b in d["items"]] == ["정보처리기사 필기+실기 합본", "정보처리기사 필기 기본서"]
    assert d["excluded_unmatched"] == 1


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("KAKAO_REST_API_KEY"), reason="책 검색 키 없음")
def test_live_책검색_실제호출():
    r = run_tool("search_books", qualification_name="정보처리기사", exam_type="필기")
    assert r["ok"], r
