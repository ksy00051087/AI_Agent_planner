"""F3022 RAG 검색 Tool — 색인 없음(NO_INDEX) · 근거 문서와 출처 · 자격명 범위 · Agent 가 고르는지 (검증 4.6)."""

import pytest

from app.rag import store
from app.tools import TOOLS, run_tool

# 3차원 가짜 임베딩 — 낱말이 들어 있으면 그 축이 1
AXES = ("과목", "시행", "합격")


def fake_embed(texts):
    return [[1.0 if a in t else 0.0 for a in AXES] or [0.0] for t in texts]


def _vec(t):
    """앞 3축은 낱말, 4번째 축은 '어느 낱말과도 맞지 않음' — 무관한 질문은 문서와 직교한다."""
    v = [1.0 if a in t else 0.0 for a in AXES]
    return [*v, 0.0] if any(v) else [0.0, 0.0, 0.0, 1.0]


def fake_embed_safe(texts):
    return [_vec(t) for t in texts]


DOCS = [
    {"id": "1", "text": "정보처리기사 시험과목: 소프트웨어설계 …", "qual_id": "1320", "qual_name": "정보처리기사",
     "kind": "취득방법", "source": "큐넷", "url": "https://q-net/1320"},
    {"id": "2", "text": "전기기사 시험과목: 전기자기학 …", "qual_id": "1150", "qual_name": "전기기사",
     "kind": "취득방법", "source": "큐넷", "url": "https://q-net/1150"},
    {"id": "3", "text": "공인회계사 — 시행기관 금융감독원", "qual_id": "", "qual_name": "공인회계사",
     "kind": "시행기관", "source": "한국직업능력연구원", "url": "https://cpa.fss.or.kr"},
]


@pytest.fixture
def index(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(store, "embed", fake_embed_safe)
    store.rebuild(DOCS, embedder=fake_embed_safe)
    return tmp_path


def test_로컬_서버_API_툴로_등록():
    assert TOOLS["search_documents"].kind == "local"
    assert "문서로만 있는" in TOOLS["search_documents"].description


def test_색인이_없으면_NO_INDEX(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CHROMA_DIR", tmp_path / "empty")
    r = run_tool("search_documents", query="시험과목")
    assert r["ok"] is False and r["error"]["code"] == "NO_INDEX"


def test_근거_원문과_출처를_돌려준다(index):
    d = run_tool("search_documents", query="시행기관이 어디야", limit=1)["data"]
    it = d["items"][0]
    assert it["qual_name"] == "공인회계사" and "금융감독원" in it["text"]
    assert it["source"] and it["url"] == "https://cpa.fss.or.kr"
    assert "원문" in d["basis"]


def test_자격명을_알면_그_자격_문서로_좁힌다(index):
    d = run_tool("search_documents", query="시험과목", qualification_name="전기기사", limit=3)["data"]
    assert d["scoped_to_qualification"] and {i["qual_name"] for i in d["items"]} == {"전기기사"}


def test_관련_없는_문서는_거른다(index):
    r = run_tool("search_documents", query="날씨 어때")   # 어느 축과도 맞지 않음 → 거리가 멀다
    assert r["ok"] is False and r["error"]["code"] == "NO_DATA"


def test_빈_질문():
    assert run_tool("search_documents", query="")["error"]["code"] == "BAD_ARGUMENT"


def test_Agent는_자격정보_질문에_RAG를_고르고_원문을_그대로_보여준다():
    from app.agent.deps import AgentDeps
    from app.agent.graph import PlannerAgent
    from app.agent.state import AnalyzeOutput, Conditions

    calls = []

    def fake_tool(name, **args):
        calls.append(name)
        return {"ok": True, "data": {"query": args["query"], "qualification_name": args.get("qualification_name"),
                                     "scoped_to_qualification": True, "basis": "원문",
                                     "items": [{"text": "전기기사 시험과목: 전기자기학", "qual_name": "전기기사",
                                                "kind": "취득방법", "source": "큐넷", "url": "https://q", "distance": 0.3}]}}

    deps = AgentDeps(run_tool=fake_tool, tool_catalog=lambda: [], field_options=lambda: [],
                     analyze_llm=lambda m: AnalyzeOutput(intent="qual_info", intent_reason="과목 질문", new_topic=True,
                                                         conditions=Conditions(targets=["전기기사"])))
    res = PlannerAgent(deps).run("r1", "전기기사 시험과목이 뭐야?", today="2026-11-18")
    assert calls == ["search_documents"]
    assert "전기자기학" in res["answer"] and "출처" in res["answer"] and res["documents"]
    assert [e["node"] for e in res["events"] if e["type"] == "node_enter"] == ["analyze", "plan", "execute", "respond"]


@pytest.mark.live
def test_live_실제_색인_검색():
    if store.collection() is None:
        pytest.skip("색인 없음 — scripts/build_index.py")
    d = run_tool("search_documents", query="시험과목", qualification_name="전기기사")["data"]
    assert "전기자기학" in d["items"][0]["text"]
