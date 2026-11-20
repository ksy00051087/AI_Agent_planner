"""NAVER API HUB — 한도가 있어 캐시 · 하루 상한을 지킨다 (실제 호출 없음)."""

import pytest

from app.tools.sources import naver_hub


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setattr(naver_hub, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(naver_hub, "USAGE", tmp_path / "usage.json")
    monkeypatch.setenv("NAVER_HUB_CLIENT_ID", "id")
    monkeypatch.setenv("NAVER_HUB_CLIENT_SECRET", "secret")
    return naver_hub


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))

        class R:
            status_code = 200

            def json(self):
                return {"total": 1, "items": [{"title": "전기기사", "description": "설명"}]}
        return R()


def test_같은_질의는_캐시에서_돌려주고_다시_부르지_않는다(hub):
    s = FakeSession()
    first = hub.search("encyc", "전기기사", 5, session=s)
    again = hub.search("encyc", "전기기사", 5, session=s)
    assert len(s.calls) == 1 and first["cached"] is False and again["cached"] is True
    assert s.calls[0][2] == {"X-NCP-APIGW-API-KEY-ID": "id", "X-NCP-APIGW-API-KEY": "secret"}   # API HUB 인증 헤더
    assert "naverapihub.apigw.ntruss.com/search/v1/encyc" in s.calls[0][0]
    assert hub.used_today() == 1


def test_하루_상한에_닿으면_부르지_않는다(hub, monkeypatch):
    monkeypatch.setenv("NAVER_HUB_DAILY_CAP", "1")
    s = FakeSession()
    hub.search("blog", "a", 5, session=s)
    with pytest.raises(hub.HubError) as e:
        hub.search("blog", "b", 5, session=s)
    assert e.value.code == "DAILY_CAP" and len(s.calls) == 1


def test_키가_없으면_부르지_않는다(hub, monkeypatch):
    monkeypatch.delenv("NAVER_HUB_CLIENT_ID")
    with pytest.raises(hub.HubError) as e:
        hub.search("encyc", "x", 5, session=FakeSession())
    assert e.value.code == "NO_KEY"
