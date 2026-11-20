"""F3005 · F3010 — 조건 추출 검증, 병합, 되묻기, 이벤트. LLM 은 가짜로 바꾼다."""

import pytest

from app.agent.analyze import (
    clean_conditions,
    find_missing,
    make_analyze,
    merge_conditions,
)
from app.agent.deps import AgentDeps
from app.agent.state import AnalyzeOutput, Conditions, Interpretation
from app.events import Emitter

OPTIONS = ["정보기술", "정보통신", "전기", "데이터"]


def deps_with(output=None, raises=None, llm=True):
    calls = []

    def fake_llm(messages):
        calls.append(messages)
        if raises:
            raise raises
        return output

    d = AgentDeps(
        run_tool=lambda *a, **k: None,
        tool_catalog=list,
        field_options=lambda: OPTIONS,
        analyze_llm=fake_llm if llm else None,
    )
    return d, calls


def run(deps, message, previous=None):
    em = Emitter(None, "s1")
    node = make_analyze(deps, lambda state: em)
    state = {"session_id": "s1", "message": message, "today": "2026-11-18"}
    if previous:
        state["conditions"] = previous
    return node(state), em


class TestCleanConditions:
    def test_목록에_없는_분야는_검색어로(self):
        c, w = clean_conditions(Conditions(field="IT 자격증"), OPTIONS)
        assert c["field"] is None and c["keywords"] == ["IT 자격증"] and w

    def test_목록에_있는_분야는_그대로(self):
        c, w = clean_conditions(Conditions(field="정보기술"), OPTIONS)
        assert c["field"] == "정보기술" and w == []

    def test_날짜가_아니면_비우고_경고(self):
        c, w = clean_conditions(
            Conditions(deadline="내년 6월", blocked_dates=["2027-03-07", "주말"]),
            OPTIONS,
        )
        assert (
            c["deadline"] is None
            and c["blocked_dates"] == ["2027-03-07"]
            and len(w) == 2
        )

    def test_0이하_숫자는_비움(self):
        c, _ = clean_conditions(Conditions(budget=0, prep_weeks=-1), OPTIONS)
        assert c["budget"] is None and c["prep_weeks"] is None


class TestMerge:
    prev = {
        "field": "정보기술",
        "deadline": "2027-06-30",
        "targets": ["정보처리산업기사", "정보처리기사"],
        "exclude": [],
        "keywords": [],
        "budget": None,
    }

    def test_바뀐_조건만_갱신(self):
        new = Conditions(deadline="2027-09-30").model_dump()
        m = merge_conditions(self.prev, new, new_topic=False)
        assert m["deadline"] == "2027-09-30"
        assert m["field"] == "정보기술" and m["targets"] == [
            "정보처리산업기사",
            "정보처리기사",
        ]

    def test_빼기는_누적(self):
        m = merge_conditions(
            {**self.prev, "exclude": ["SQLD"]},
            Conditions(exclude=["정보처리산업기사"]).model_dump(),
            False,
        )
        assert m["exclude"] == ["SQLD", "정보처리산업기사"]

    def test_없애달라고_한_조건만_비운다(self):
        m = merge_conditions(
            self.prev, Conditions(clear=["deadline"]).model_dump(), new_topic=False
        )
        assert m["deadline"] is None and m["field"] == "정보기술" and m["clear"] == []

    def test_새_주제면_이전_조건_버림(self):
        m = merge_conditions(
            self.prev, Conditions(field="전기").model_dump(), new_topic=True
        )
        assert m["field"] == "전기" and m["deadline"] is None and m["targets"] == []


def test_지난_기한은_고쳐쓰지_않고_되묻기():
    m = find_missing(
        "plan_modify",
        {"deadline": "2026-09-30", "field": "정보기술"},
        today="2026-11-18",
    )
    assert len(m) == 1 and "2026-09-30" in m[0]
    assert (
        find_missing(
            "plan_create",
            {"deadline": "2027-09-30", "field": "정보기술"},
            today="2026-11-18",
        )
        == []
    )


def test_자격명_자리의_등급은_등급조건으로():
    c, w = clean_conditions(Conditions(targets=["기사", "정보처리기사"]), OPTIONS)
    assert c["targets"] == ["정보처리기사"] and c["grades"] == ["기사"] and w


def test_말하지_않은_등급은_뺀다():
    c, w = clean_conditions(
        Conditions(grades=["기능사"], keywords=["9급"]),
        OPTIONS,
        "9급 공무원이랑 한국사",
    )
    assert c["grades"] == [] and w
    c, _ = clean_conditions(Conditions(grades=["기사"]), OPTIONS, "기사만 보여줘")
    assert c["grades"] == ["기사"]


def test_의미없는_검색어는_뺀다():
    c, w = clean_conditions(Conditions(keywords=["금융권", "취업", "자격증"]), OPTIONS)
    assert c["keywords"] == ["금융권"] and w


def test_되묻기_판단():
    assert find_missing("plan_create", {}) == ["목표 분야 또는 따고 싶은 자격"]
    assert find_missing("plan_create", {"keywords": ["금융"]}) == []
    assert find_missing("fact_lookup", {"field": "전기"}) == ["알고 싶은 자격 이름"]
    assert find_missing("chat", {}) == []


class TestAnalyzeNode:
    def test_정상_의도_조건_해석이_이벤트로(self):
        out = AnalyzeOutput(
            intent="plan_create",
            intent_reason="계획을 원함",
            new_topic=True,
            conditions=Conditions(field="정보기술", deadline="2027-06-30"),
            interpretations=[
                Interpretation(text="내년 6월까지", as_value="2027-06-30")
            ],
        )
        deps, calls = deps_with(out)
        res, em = run(deps, "내년 6월까지 IT 자격증 따고 싶어")
        assert (
            res["intent"] == "plan_create"
            and res["conditions"]["deadline"] == "2027-06-30"
        )
        assert res["missing"] == [] and res["error"] is None
        types = [(e["type"], e.get("kind")) for e in em.events]
        assert types == [
            ("node_enter", None),
            ("llm_decision", "intent"),
            ("llm_decision", "interpretation"),
            ("node_exit", None),
        ]
        assert em.events[1]["reason"] == "계획을 원함"
        # 프롬프트에 오늘 날짜와 분야 목록이 들어간다
        assert (
            "2026-11-18" in calls[0][0]["content"]
            and "정보기술" in calls[0][0]["content"]
        )

    def test_후속요청은_이전_조건을_유지(self):
        out = AnalyzeOutput(
            intent="plan_modify",
            intent_reason="조건 변경",
            new_topic=False,
            conditions=Conditions(exclude=["정보처리산업기사"]),
        )
        deps, _ = deps_with(out)
        res, _ = run(
            deps,
            "산업기사는 빼줘",
            previous={"field": "정보기술", "deadline": "2027-06-30"},
        )
        assert res["conditions"]["field"] == "정보기술" and res["conditions"][
            "exclude"
        ] == ["정보처리산업기사"]

    def test_조건_부족이면_되묻기(self):
        out = AnalyzeOutput(
            intent="plan_create",
            intent_reason="계획",
            new_topic=True,
            conditions=Conditions(),
        )
        deps, _ = deps_with(out)
        res, _ = run(deps, "자격증 따고 싶어")
        assert res["missing"] == ["목표 분야 또는 따고 싶은 자격"]

    def test_LLM_키가_없으면_안내용_오류(self):
        deps, _ = deps_with(llm=False)
        res, em = run(deps, "안녕")
        assert res["error"] == "LLM_UNAVAILABLE"
        assert any(
            e["type"] == "error" and e["code"] == "LLM_UNAVAILABLE" for e in em.events
        )

    def test_LLM_호출_실패도_예외가_아니라_상태로(self):
        deps, _ = deps_with(raises=TimeoutError("slow"))
        res, em = run(deps, "안녕")
        assert res["error"] == "LLM_ERROR"
        assert "slow" not in str(em.events)  # 오류 원문을 이벤트에 싣지 않는다


@pytest.mark.live
def test_live_analyze_실제_GMS():
    from app.container import build_deps

    deps = build_deps()
    res, em = run(deps, "비전공 대학생인데 내년 6월까지 IT 쪽 자격증 따고 싶어")
    assert res["intent"] == "plan_create"
    assert res["conditions"]["deadline"] == "2027-06-30"
    assert (
        res["conditions"]["field"] in ("정보기술", "정보통신")
        or res["conditions"]["keywords"]
    )


def test_없는_말일은_그_달_마지막날로():
    c, w = clean_conditions(Conditions(deadline="2027-02-29"), OPTIONS)
    assert c["deadline"] == "2027-02-28" and w
    c, _ = clean_conditions(Conditions(deadline="2027-04-31"), OPTIONS)
    assert c["deadline"] == "2027-04-30"


def test_refine_keywords_꾸밈말():
    from app.agent.analyze import refine_keywords
    rules = {"generic": ["제조", "관리"]}
    assert refine_keywords(["폭죽", "제조"], rules)[0] == ["폭죽"]          # 없는 말이어도 '제조' 로 넓혀 찾지 않는다
    assert refine_keywords(["식품제조"], rules)[0] == ["식품"]              # 붙여 쓴 꾸밈말 떼기
    assert refine_keywords(["떡제조"], rules)[0] == ["떡제조"]              # 앞말이 한 글자면 그대로
    assert refine_keywords(["제조"], rules) == (["제조"], [])              # 꾸밈말만 있으면 그대로


def test_blocked_word():
    from app.agent.analyze import blocked_word
    rules = {"blocked": ["폭탄", "테러"]}
    assert blocked_word("폭 탄 제조 쪽 취업", rules) == "폭탄"
    assert blocked_word("화약류제조기사 따고 싶어", rules) is None          # 정식 국가자격은 막지 않는다
    assert blocked_word("전기 쪽", None) is None


def test_apply_sector_공기업():
    from app.agent.analyze import apply_sector
    sectors = {"공기업": {"words": ["공기업", "공공기관"], "fields": ["전기"]}}
    c = {"field": None, "keywords": ["공기업"]}
    assert apply_sector(c, "공기업 취업하고 싶어", sectors) == "공기업"
    assert c["field"] == "공기업" and c["keywords"] == []        # '공기업' 으로 자격명을 찾지 않는다
    c2 = {"field": "전기", "keywords": []}
    assert apply_sector(c2, "전기 쪽 취업", sectors) is None and c2["field"] == "전기"
