"""커리어넷 직업정보 — 목록 · 상세 번호 · 후보 추리기 · 원문 그대로."""

import pytest

from app.tools.sources import careernet
from tests.conftest import FakeResponse

LIST = {"count": 3, "jobs": [
    {"job_nm": "산업안전관리원", "seq": 167, "job_cd": 84, "rel_job_nm": "안전관리자", "work": "", "top_nm": ""},
    {"job_nm": "전기공학기술자", "seq": 40, "job_cd": 31, "rel_job_nm": "전기설계기술자", "work": "", "top_nm": ""},
    {"job_nm": "통신엔지니어", "seq": 41, "job_cd": 32, "rel_job_nm": "", "work": "", "top_nm": ""},
]}
DETAIL = {"baseInfo": {"job_nm": "산업안전관리원", "rel_job_nm": "안전관리자"},
          "workList": [{"work": "작업장의 안전을 점검한다."}],
          "jobReadyList": {"certificate": [{"certificate": "국가자격증으로는 산업안전기사가 있습니다."}],
                           "curriculum": [{"curriculum": "안전공학과"}], "training": [], "recruit": []}}


@pytest.fixture
def cn(monkeypatch, tmp_path, fake_http):
    monkeypatch.setenv("CAREERNET_API_KEY", "k")
    monkeypatch.setattr(careernet, "CACHE", tmp_path)
    return fake_http([("jobs.json", FakeResponse(body=LIST)), ("job.json", FakeResponse(body=DETAIL))])


def test_상세_번호는_목록의_job_cd다(cn):
    js = careernet.list_jobs()
    assert {j["job_nm"]: j["seq"] for j in js}["산업안전관리원"] == 84      # 목록의 seq(167) 가 아니다
    careernet.job_detail(84)
    assert cn[-1]["params"]["seq"] == 84


def test_꼬리말을_뗀_핵심_낱말로_먼저_찾는다(cn):
    names = [x["job_nm"] for x in careernet.candidates("전기 엔지니어")]
    assert names[0] == "전기공학기술자"          # '엔지니어' 만 겹치는 통신엔지니어보다 먼저


def test_상세는_원문_그대로(cn):
    p = careernet.profile(84)
    assert p["name"] == "산업안전관리원" and p["certificate"] == ["국가자격증으로는 산업안전기사가 있습니다."]
    assert p["certificate_issue"] is None and p["url"].endswith("SEQ=84")


def test_관련자격_원문이_다른_직업_이야기면_쓰지_않는다(monkeypatch, tmp_path, fake_http):
    monkeypatch.setenv("CAREERNET_API_KEY", "k")
    monkeypatch.setattr(careernet, "CACHE", tmp_path)
    wrong = {**DETAIL, "jobReadyList": {"certificate": [{"certificate": "소믈리에가 되기 위해 요구되는 자격증은 없습니다."}]}}
    fake_http([("job.json", FakeResponse(body=wrong))])
    p = careernet.profile(84)
    assert p["certificate"] == [] and "소믈리에" in p["certificate_issue"]


def test_키가_없으면_NO_KEY(monkeypatch, tmp_path):
    monkeypatch.delenv("CAREERNET_API_KEY", raising=False)
    monkeypatch.setattr(careernet, "CACHE", tmp_path)
    with pytest.raises(careernet.CareerNetError) as e:
        careernet.list_jobs()
    assert e.value.code == "NO_KEY"
