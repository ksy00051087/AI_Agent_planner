"""F3001 — 등록 · Agent 용 명세 · 예외를 밖으로 던지지 않음."""

from app.tools import TOOLS, catalog, run_tool


def test_외부API툴_3개와_로컬서버API툴_구분():
    assert {n for n, t in TOOLS.items() if t.kind == "external"} == {"search_qualifications", "get_exam_schedule", "search_books"}
    assert {n for n, t in TOOLS.items() if t.kind == "local"} == {"search_documents", "list_schedule", "register_plan"}


def test_catalog는_이름_설명_입력규격만():
    for c in catalog():
        assert set(c) == {"name", "description", "parameters"}
        assert c["parameters"]["type"] == "object"
        assert c["description"]


def test_출력구조도_정의되어_있다():
    assert all(t.returns for t in TOOLS.values())


def test_모르는_Tool_모르는_인자는_BAD_ARGUMENT():
    assert run_tool("nope")["error"]["code"] == "BAD_ARGUMENT"
    assert run_tool("search_books", qualification_name="x", foo=1)["error"]["code"] == "BAD_ARGUMENT"


def test_함수_안에서_예외가_나도_실패응답으로(monkeypatch):
    t = TOOLS["search_books"]
    monkeypatch.setattr(t, "func", lambda **kw: 1 / 0)
    assert t.run(qualification_name="x") == {
        "ok": False, "error": {"code": "UPSTREAM_ERROR", "message": "Tool 실행 중 오류입니다."}}
