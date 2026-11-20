"""출처 확장 — 설정 한 줄로 붙는 표 출처(CSV · 자동변환 API), 보충 공고문, 출처 실패 격리."""

import json

import pytest

from app.tools import run_tool
from app.tools.sources import manual, table
from tests.conftest import FakeResponse, qnet_routes

COLUMNS = {"qual_name": "시험명", "round": "회차", "written_reg_start": "접수시작일",
           "written_reg_end": "접수마감일", "written_exam_start": "시험일", "written_pass": "합격자발표일"}


@pytest.fixture
def csv_source(tmp_path, monkeypatch):
    """CSV 출처 하나를 설정한다. 반환: CSV 파일 경로 (내용은 테스트가 쓴다)"""
    data = tmp_path / "kdata.csv"
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"sources": [{
        "id": "kdata", "label": "데이터자격검정", "organization": "한국데이터산업진흥원",
        "source_url": "https://www.data.go.kr/data/15062838/fileData.do", "kind": "csv",
        "path": str(data), "field": "데이터", "columns": COLUMNS}]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(table, "CONFIG_FILE", cfg)
    monkeypatch.setattr(table, "ROOT", tmp_path)  # path 를 절대경로로 줬으므로 영향 없음
    return data


def write_csv(path, rows, encoding="utf-8-sig"):
    head = ",".join(COLUMNS.values())
    path.write_text("\n".join([head, *rows]) + "\n", encoding=encoding)


def test_to_ymd_여러_표기():
    for v in ("2027-03-07", "2027.03.07", "2027/3/7", "20270307", "2027-03-07 09:00"):
        assert table.to_ymd(v) == "20270307", v
    assert table.to_ymd("미정") is None and table.to_ymd(None) is None


def test_CSV_출처가_후보와_일정에_합쳐진다(csv_source, fake_http):
    write_csv(csv_source, [
        "SQLD,제64회,2027-02-02,2027-02-06,2027-03-07,2027-03-27",
        "SQLD,제65회,2027-04-27,2027-05-01,2027-05-31,2027-06-19",
        "ADsP,제52회,2027-01-20,2027-01-24,,2027-03-20",  # 시험일 비어 있음
    ])
    fake_http(qnet_routes())
    d = run_tool("search_qualifications", keyword="SQLD")["data"]
    assert [(i["qual_id"], i["organization"]) for i in d["items"]] == [("kdata:SQLD", "한국데이터산업진흥원")]

    s = run_tool("get_exam_schedule", qual_id="kdata:SQLD", from_date="2026-11-18")["data"]
    assert [r["written_exam_start"] for r in s["rounds"]][:2] == ["2027-03-07", "2027-05-31"]
    assert s["estimated"] is False and "15062838" in s["source"]

    a = run_tool("get_exam_schedule", qual_id="kdata:ADsP")
    assert a["error"]["code"] == "NO_EXAM_DATE"  # 비어 있는 시험일을 채우지 않는다


def test_CSV_cp949도_읽는다(csv_source, fake_http):
    write_csv(csv_source, ["SQLD,제64회,2027-02-02,2027-02-06,2027-03-07,2027-03-27"], encoding="cp949")
    fake_http(qnet_routes())
    assert run_tool("get_exam_schedule", qual_id="kdata:SQLD")["ok"]


def test_분야로도_찾는다(csv_source, fake_http):
    write_csv(csv_source, ["SQLD,제64회,2027-02-02,2027-02-06,2027-03-07,2027-03-27"])
    fake_http(qnet_routes())
    names = [i["name"] for i in run_tool("search_qualifications", field="데이터")["data"]["items"]]
    assert names == ["SQLD"]


def test_보충출처_파일이_없으면_건너뛰고_알린다(csv_source, fake_http):
    fake_http(qnet_routes())  # CSV 파일을 만들지 않았다
    d = run_tool("search_qualifications", keyword="정보처리기사")["data"]
    assert d["items"][0]["qual_id"] == "1320"
    assert d["source_errors"] == [{"source": "kdata", "code": "NO_DATA", "message": d["source_errors"][0]["message"]}]


def test_odcloud_자동변환API(tmp_path, monkeypatch, fake_http):
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"sources": [{
        "id": "history", "label": "한국사능력검정시험 일정", "kind": "odcloud",
        "endpoint": "https://api.odcloud.kr/api/15155201/v1/uddi:test", "key_env": "DATA_GO_KR_KEY",
        "columns": {"qual_name": "시험명", "round": "회차", "written_reg_end": "원서접수마감",
                    "written_exam_start": "시험일"}}]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(table, "CONFIG_FILE", cfg)
    body = {"data": [{"시험명": "한국사능력검정시험", "회차": "제77회", "원서접수마감": "2027.01.13", "시험일": "2027.02.07"}]}

    # 키가 없으면 그 출처만 실패하고 큐넷 결과는 그대로
    fake_http(qnet_routes())
    d = run_tool("search_qualifications", keyword="한국사")
    assert d["error"]["code"] == "NO_DATA"

    monkeypatch.setenv("DATA_GO_KR_KEY", "k")
    table.clear_cache()
    calls = fake_http([("odcloud", FakeResponse(body=body)), *qnet_routes()])
    s = run_tool("get_exam_schedule", qual_id="history:한국사능력검정시험", from_date="2026-11-18")["data"]
    assert s["rounds"][0]["written_exam_start"] == "2027-02-07"
    assert any(c["params"].get("serviceKey") == "k" for c in calls)


def test_공고문_보충데이터(tmp_path, monkeypatch, fake_http):
    f = tmp_path / "manual.json"
    f.write_text(json.dumps({"items": [{
        "name": "투자자산운용사", "organization": "금융투자협회", "field": "금융",
        "source_url": "https://example.org/notice", "checked_at": "2026-11-18",
        "rounds": [{"name": "2027년 제1회", "dates": {"written_reg_end": "20270210", "written_exam_start": "20270315"}}],
    }]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(manual, "FILE", f)
    fake_http(qnet_routes())
    s = run_tool("get_exam_schedule", qual_id="manual:투자자산운용사", from_date="2026-11-18")["data"]
    assert s["rounds"][0]["written_exam_start"] == "2027-03-15"
    assert "공고문 기준 수동 입력" in s["source"] and "2026-11-18 확인" in s["source"]


def test_모르는_식별자_형식(fake_http):
    fake_http(qnet_routes())
    assert run_tool("get_exam_schedule", qual_id="foo:bar")["error"]["code"] == "BAD_ARGUMENT"


def test_이름통일_행필터_단계_시각_페이지넘김(tmp_path, monkeypatch, fake_http):
    """실제 데이터진흥원 응답 모양: 해마다 바뀐 이름, 필기/실기 별도 행, 특별검정 섞임, 1000행 단위 페이지."""
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"sources": [{
        "id": "kdata", "kind": "odcloud", "endpoint": "https://api.odcloud.kr/api/15062838/v1/uddi:x",
        "row_filter": {"시험구분": ["일반검정"]},
        "columns": {"qual_name": "시험명", "round": "회차", "stage": "시험유형", "exam_time": "시험시작시간",
                    "written_reg_end": "접수마감일", "written_exam_start": "시험일"},
        "name_map": {"빅데이터분석기사-필기": "빅데이터분석기사", "빅데이터분석기사-실기": "빅데이터분석기사"},
    }]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(table, "CONFIG_FILE", cfg)
    monkeypatch.setenv("DATA_GO_KR_KEY", "k")
    page1 = {"totalCount": 3, "data": [
        {"시험구분": "일반검정", "시험명": "빅데이터분석기사-필기", "회차": 12, "시험유형": "필기",
         "시험시작시간": "10:00:00", "접수마감일": "2026-03-09", "시험일": "2026-04-04"},
        {"시험구분": "특별검정", "시험명": "빅데이터분석기사-필기", "회차": 99, "시험유형": "필기",
         "시험시작시간": "10:00:00", "접수마감일": "2026-03-01", "시험일": "2026-03-20"},
    ]}
    page2 = {"totalCount": 3, "data": [
        {"시험구분": "일반검정", "시험명": "빅데이터분석기사-실기", "회차": 12, "시험유형": "실기",
         "시험시작시간": "10:00:00", "접수마감일": "2026-05-22", "시험일": "2026-06-20"},
    ]}
    pages = iter([FakeResponse(body=page1), FakeResponse(body=page2)])

    class Pager:
        def __init__(self):
            self.status_code = 200

    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(params)
        if "odcloud" in url:
            return next(pages)
        for needle, resp in qnet_routes():
            if needle in url:
                return resp
        raise AssertionError(url)

    monkeypatch.setattr(table.requests, "get", fake_get)
    names = [i["qual_id"] for i in run_tool("search_qualifications", keyword="빅데이터")["data"]["items"]]
    assert names == ["kdata:빅데이터분석기사"]  # 두 이름이 하나로
    d = run_tool("get_exam_schedule", qual_id="kdata:빅데이터분석기사", from_date="2026-01-01")["data"]
    assert [(r["stage"], r["exam_time"], r["written_exam_start"]) for r in d["rounds"]][:2] == [
        ("필기", "10:00", "2026-04-04"), ("실기", "10:00", "2026-06-20")]  # 특별검정 제외
    assert [c["page"] for c in calls if "perPage" in c] == [1, 2]


def test_자동변환API가_실패하면_CSV로_대체(tmp_path, monkeypatch, fake_http):
    data = tmp_path / "backup.csv"
    write_csv(data, ["SQLD,제64회,2027-02-02,2027-02-06,2027-03-07,2027-03-27"])
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"sources": [{
        "id": "kdata", "kind": "odcloud", "endpoint": "https://api.odcloud.kr/api/x", "fallback_path": str(data),
        "columns": COLUMNS}]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(table, "CONFIG_FILE", cfg)
    fake_http(qnet_routes())  # DATA_GO_KR_KEY 가 없어 API 는 INVALID_KEY
    s = run_tool("get_exam_schedule", qual_id="kdata:SQLD", from_date="2026-11-18")["data"]
    assert s["rounds"][0]["written_exam_start"] == "2027-03-07"


# ── 1일차 이후 추가한 표 형식: 고정 이름 · 범위 칸 · 이름 속 단계 · 중복 제거 · XML 오픈API ──
def _config(tmp_path, monkeypatch, src):
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"sources": [src]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(table, "CONFIG_FILE", cfg)


def test_split_range():
    assert table.split_range("2025-09-24 ~ 2025-10-02") == ("20250924", "20251002")
    assert table.split_range("2026-03-10~2026-03-16") == ("20260310", "20260316")
    assert table.split_range("2026-04-10") == ("20260410", None)
    assert table.split_range(None) == (None, None)


def test_고정이름_범위칸_이름속_단계(tmp_path, monkeypatch, fake_http):
    data = tmp_path / "k.csv"
    data.write_text("직종,회차,온라인접수기간,시험일\n"
                    "의사(실기),91,2026-01-12 ~ 2026-01-16,2026-03-04\n"
                    "의사,91,2026-09-01 ~ 2026-09-05,2027-01-08\n", encoding="utf-8-sig")
    _config(tmp_path, monkeypatch, {
        "id": "kuksiwon", "kind": "csv", "path": str(data), "field": "보건.의료",
        "columns": {"qual_name": "직종", "round": "회차", "written_exam_start": "시험일"},
        "ranges": {"온라인접수기간": ["written_reg_start", "written_reg_end"]},
        "name_stage_pattern": r"^(?P<name>.+?)\s*\((?P<stage>실기|필기)\)$"})
    fake_http(qnet_routes())
    ids = [i["qual_id"] for i in run_tool("search_qualifications", field="보건.의료")["data"]["items"]]
    assert [i for i in ids if i.startswith("kuksiwon:")] == ["kuksiwon:의사"]  # '의사(실기)' 와 '의사' 가 하나로
    assert any(not i.startswith("kuksiwon:") for i in ids)  # 같은 분야의 큐넷 종목과 함께 나온다
    rounds = run_tool("get_exam_schedule", qual_id="kuksiwon:의사", from_date="2026-01-01")["data"]["rounds"]
    assert [(r["stage"], r["written_reg_end"], r["written_exam_start"]) for r in rounds][:2] == [
        ("실기", "2026-01-16", "2026-03-04"), (None, "2026-09-05", "2027-01-08")]


def test_자격명_컬럼이_없으면_고정이름_시험장별_중복은_합침(tmp_path, monkeypatch, fake_http):
    data = tmp_path / "h.csv"
    data.write_text("회차,접수마감,시험일,시험장\n81,2026-11-10,2026-11-28,서울\n81,2026-11-10,2026-11-28,부산\n",
                    encoding="utf-8-sig")
    _config(tmp_path, monkeypatch, {
        "id": "history", "kind": "csv", "path": str(data), "qual_name_fixed": "한국사능력검정시험",
        "columns": {"round": "회차", "written_reg_end": "접수마감", "written_exam_start": "시험일"}})
    fake_http(qnet_routes())
    d = run_tool("get_exam_schedule", qual_id="history:한국사능력검정시험", from_date="2026-11-01")["data"]
    assert [r["name"] for r in d["rounds"] if not r["estimated"]] == ["한국사능력검정시험 제81회"]


def test_XML_오픈API는_작년_올해_내년을_부른다(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, {
        "id": "livestock", "kind": "xml_api", "endpoint": "https://apis.data.go.kr/x/getList",
        "year_param": "srchTestYear", "qual_name_fixed": "가축인공수정사", "stage_fixed": "필기 → 실기",
        "columns": {"round": "testTmrd", "written_reg_end": "rceptEnd", "written_exam_start": "testBegin",
                    "practical_exam_start": "prcttqTestBegin"}})
    monkeypatch.setenv("DATA_GO_KR_KEY", "k")
    from datetime import date
    y = date.today().year

    def xml(year, has):
        item = (f"<item><testYear>{year}</testYear><testTmrd>1</testTmrd><rceptEnd>{year}-05-22 00:00</rceptEnd>"
                f"<testBegin>{year}-07-11 00:00</testBegin><prcttqTestBegin>{year}-08-29 00:00</prcttqTestBegin></item>")
        code = "200" if has else "03"
        return FakeResponse(text=f"<response><header><resultCode>{code}</resultCode></header>"
                                 f"<body><items>{item if has else ''}</items></body></response>")

    asked = []

    def fake_get(url, params=None, headers=None, timeout=None):
        asked.append(params["srchTestYear"])
        return xml(params["srchTestYear"], has=params["srchTestYear"] != str(y + 1))

    monkeypatch.setattr(table.requests, "get", fake_get)
    err, rounds, meta = table.TableSource(table.configs()[0]).get_schedule("livestock:가축인공수정사")
    assert err is None and asked == [str(y - 1), str(y), str(y + 1)]
    assert [r["dates"]["practical_exam_start"] for r in rounds] == [f"{y - 1}0829", f"{y}0829"]
    assert rounds[0]["stage"] == "필기 → 실기"
