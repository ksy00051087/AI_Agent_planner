"""테스트 공통 — 외부 API 는 가짜 응답으로 바꾼다 (쿼터 · 네트워크와 무관하게 돈다).

큐넷 가짜 응답은 scripts/check_apis.py 가 저장한 '실제 응답'(docs/api_samples)을 그대로 쓴다.
실제 API 를 부르는 테스트는 `pytest -m live` 로만 돈다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("PLANNER_NO_AUTOAPP", "1")  # app.main import 때 실제 DB · Agent 를 만들지 않는다
os.environ["CALENDAR_BACKEND"] = "local"         # .env 가 google 이어도 테스트는 실제 Google Calendar 를 건드리지 않는다

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "docs" / "api_samples"

API_KEY_ENVS = ("QNET_SERVICE_KEY", "DATA_GO_KR_KEY", "NAVER_HUB_CLIENT_ID", "NAVER_HUB_CLIENT_SECRET",
                "CAREERNET_API_KEY", "KAKAO_REST_API_KEY")


class FakeResponse:
    def __init__(self, status_code=200, text="", body=None):
        self.status_code = status_code
        self.text = text if body is None else json.dumps(body, ensure_ascii=False)
        self.content = self.text.encode("utf-8")
        self._body = body

    def json(self):
        return self._body if self._body is not None else json.loads(self.text)


def sample(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


EMPTY_XML = ('<?xml version="1.0" encoding="UTF-8"?><response><header><resultCode>00</resultCode>'
             '<resultMsg>NORMAL SERVICE.</resultMsg></header><body><items/></body></response>')
FEE_XML = ('<?xml version="1.0" encoding="UTF-8"?><response><header><resultCode>00</resultCode></header><body>'
           '<items><item><contents>1차 : 19400, 2차 : 22600</contents><infogb>응시수수료</infogb>'
           '<jmfldnm>정보처리기사</jmfldnm></item></items></body></response>')
KEY_ERROR_XML = ('<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>'
                 '<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>'
                 '<returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>')


@pytest.fixture(autouse=True)
def isolate(monkeypatch, request):
    """모든 테스트: 키를 비우고, 큐넷 캐시를 지우고, 실제 네트워크를 막는다 (live 표시 테스트 제외)."""
    from app.tools import sources
    from app.tools.sources import manual, table

    sources.clear_caches()
    if "live" in request.keywords:
        yield
        return
    for k in API_KEY_ENVS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(manual, "FILE", Path("__no_such_manual_file__.json"))
    monkeypatch.setattr(table, "CONFIG_FILE", Path("__no_such_sources_file__.json"))

    def blocked(*a, **kw):
        raise AssertionError("테스트에서 실제 네트워크를 불렀습니다. fake_http 를 쓰세요.")

    monkeypatch.setattr(requests, "get", blocked)
    yield


@pytest.fixture
def fake_http(monkeypatch):
    """routes: [(URL 에 들어 있는 문자열, FakeResponse 또는 예외)] — 앞에서부터 처음 맞는 것을 돌려준다."""
    calls: list[dict] = []

    def install(routes):
        def fake_get(url, params=None, headers=None, timeout=None):
            calls.append({"url": url, "params": params or {}, "headers": headers or {}})
            for needle, resp in routes:
                if needle in url:
                    if isinstance(resp, Exception):
                        raise resp
                    return resp
            raise AssertionError(f"준비하지 않은 URL: {url}")

        monkeypatch.setattr(requests, "get", fake_get)
        return calls

    return install


def qnet_routes(schedule_xml: str | None = None, fee_xml: str = FEE_XML):
    return [
        ("InquiryListNationalQualifcationSVC/getList", FakeResponse(text=sample("qnet_getList.xml"))),
        ("getJMList", FakeResponse(text=schedule_xml or sample("qnet_getJMList_1320.xml"))),
        ("getFeeList", FakeResponse(text=fee_xml)),
        ("InquiryInformationTradeNTQSVC", FakeResponse(text=sample("qnet_infoTrade_1320.xml"))),
        # 합격률: 올해(집계 없음) → 작년 순으로 부른다. 연도와 무관하게 2025년 기사 실제 응답을 돌려준다
        ("InquiryQualPassRateSVC", FakeResponse(text=sample("qnet_passRate_2025_30.xml"))),
    ]
