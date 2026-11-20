"""메인 Agent 그래프 — 대표 시나리오 (설계 문서 11장, 검증 4.2 · 4.3 · 4.7). Tool · LLM 은 가짜."""

from collections import Counter

import pytest

from app.agent.deps import AgentDeps
from app.agent.graph import PlannerAgent
from app.agent.state import AnalyzeOutput, Conditions
from app.events import EventBus

TODAY = "2026-11-18"


def R(reg_end, exam, practical=None, est=True, stage="필기+실기"):
    return {"name": f"{exam} 회차", "stage": stage, "exam_time": None, "estimated": est,
            "basis": "2027년 일정 미공고 — 추정" if est else None, "written_reg_start": None,
            "written_reg_end": reg_end, "written_exam_start": exam, "practical_exam_start": practical}


QUALS = {  # 분야 '전기' — 인기: 기능사 > 기사 > 산업기사
    "E1": {"name": "전기기능사", "grade": "기능사", "pop": 27015,
           "rounds": [R("2027-01-09", "2027-01-20", "2027-03-14"), R("2027-06-01", "2027-06-20", "2027-08-01")]},
    "E2": {"name": "전기산업기사", "grade": "산업기사", "pop": 5694,
           "rounds": [R("2027-04-23", "2027-05-09", "2027-07-18"), R("2027-07-23", "2027-08-07", "2027-10-24")]},
    "E3": {"name": "전기기사", "grade": "기사", "pop": 13918,
           "rounds": [R("2027-07-23", "2027-08-07", "2027-10-24"), R("2028-01-15", "2028-01-30", "2028-04-18")]},
    "N1": {"name": "사회복지사 1급", "grade": "전문자격", "pop": None, "rounds": None},  # 시험일 없음
    "H1": {"name": "한국사능력검정시험", "grade": None, "pop": None,
           "rounds": [R("2027-01-20", "2027-02-21", est=False, stage="필기"), R("2027-12-20", "2028-01-15", stage="필기")]},
}
TRACKS = [{"fields": ["전기"], "items": [{"name": "전기 설비 · 공사", "match": ["전기기능", "전기산업기사", "전기기사"]},
                                          {"name": "전자 · 반도체", "match": ["전자", "반도체"]}]}]
BASICS = [{"name": "토익(TOEIC)", "search": None, "note": "일정 출처 없음"},
          {"name": "한국사능력검정시험", "search": "한국사능력검정시험", "note": "공기업 가산"}]


class FakeTools:
    def __init__(self, fail_code=None):
        self.calls = []
        self.fail_code = fail_code

    def __call__(self, name, **args):
        self.calls.append((name, tuple(sorted(args.items()))))
        if self.fail_code:
            return {"ok": False, "error": {"code": self.fail_code, "message": "키 없음"}}
        if name == "search_qualifications":
            kw, field = args.get("keyword"), args.get("field")
            items = [{"qual_id": k, "name": q["name"], "grade": q["grade"], "source": "qnet", "field": "전기",
                      "popularity": {"year": 2025, "acquired": q["pop"], "basis": f"합격자 {q['pop']}명"} if q["pop"] else None}
                     for k, q in QUALS.items()
                     if (field and k.startswith("E")) or (kw and kw in q["name"])]
            if not items:
                return {"ok": False, "error": {"code": "NO_DATA", "message": "없음"}}
            return {"ok": True, "data": {"items": items, "total": len(items)}}
        if name == "get_exam_schedule":
            q = QUALS[args["qual_id"]]
            if q["rounds"] is None:
                return {"ok": False, "error": {"code": "NO_EXAM_DATE", "message": "시험일이 비어 있음"}}
            return {"ok": True, "data": {"name": q["name"], "grade": q["grade"], "rounds": q["rounds"], "source": "큐넷",
                                         "fee": {"1차": 20000, "2차": 20000}, "pass_rate": None}}
        if name == "list_schedule":
            busy = getattr(self, "busy", None)
            if busy is None:
                return {"ok": False, "error": {"code": "NOT_CONFIGURED", "message": "캘린더 미연결"}}
            return {"ok": True, "data": {"backend": "local", "busy_dates": busy, "events": []}}
        if name == "search_books":
            return {"ok": True, "data": {"items": [{"title": f"{args['qualification_name']} 기본서", "link": "https://b",
                                                     "publisher": "p", "pub_date": "2026-10-01"}]}}
        raise AssertionError(name)


def analyzer(table):
    """메시지 → AnalyzeOutput 를 돌려주는 가짜 LLM"""
    def llm(messages):
        return table[messages[-1]["content"]]
    return llm


def out(intent, new_topic=True, **cond):
    return AnalyzeOutput(intent=intent, intent_reason=f"{intent} 로 분류", new_topic=new_topic, conditions=Conditions(**cond))


def agent(table, tools=None, limit=2, bus=None, ask_held=False):
    """ask_held=False — 보유 자격 패널을 건너뛰는 기존 시나리오. 패널 흐름은 아래 전용 테스트에서 본다"""
    tools = tools or FakeTools()
    rel = {"field_groups": {}, "ladders": [], "expert": [], "prep_weeks": {}, "basics": BASICS, "tracks": TRACKS,
           "keyword_rules": {"blocked": ["폭탄", "테러"], "generic": ["제조", "관리"]}}
    deps = AgentDeps(run_tool=tools, tool_catalog=lambda: [], field_options=lambda: ["전기"],
                     analyze_llm=analyzer(table), replan_limit=limit, relations=lambda: rel, ask_held=ask_held)
    return PlannerAgent(deps, bus), tools


def nodes(res):
    return [e["node"] for e in res["events"] if e["type"] == "node_enter"]


# S1 — 한 번에 충족: 분야만 말하면 많이 따는 루트 → 같은 계열은 상위만 (기능사 · 산업기사는 기사에 포함)
def test_S1_분야만_말하면_많이따는_루트_상위만():
    a, tools = agent({"전기 쪽 취업": out("plan_create", field="전기")})
    res = a.run("s1", "전기 쪽 취업", today=TODAY)
    assert [p["name"] for p in res["draft_plan"]] == ["전기기사"]
    sup = {e["name"]: e for e in res["excluded"] if e["reason_code"] == "SUPERSEDED"}
    assert set(sup) == {"전기기능사", "전기산업기사"} and "전기기사" in sup["전기기능사"]["detail"]
    assert nodes(res) == ["analyze", "plan", "execute", "judge", "enrich", "respond"]
    assert "따로 딸 필요 없음" in res["draft_plan"][0]["path_reason"]
    assert res["draft_plan"][0]["ladder"] == ["전기기능사", "전기산업기사", "전기기사"]   # 응시자격 안내용 사다리
    assert "추정" in res["answer"] and "늦어도 공부 시작" in res["answer"]
    assert res["books"]  # 배치된 자격마다 교재


# S2 — 재계획: 기한 안에 불가 → 기한을 넘는 가장 빠른 대안 (이미 받은 일정은 다시 부르지 않음)
def test_S2_기한_안에_불가하면_재계획하고_Tool_결과를_재사용():
    a, tools = agent({"전기기사 3월까지": out("plan_create", targets=["전기기사"], deadline="2027-03-31")})
    res = a.run("s2", "전기기사 3월까지", today=TODAY)
    assert [r["reason_code"] for r in res["replans"]] == ["DEADLINE_INFEASIBLE"]
    assert res["draft_plan"][0]["name"] == "전기기사" and "기한을 넘기는 가장 빠른 대안" in res["answer"]
    calls = Counter(tools.calls)
    assert all(n == 1 for n in calls.values())  # 같은 인자로 두 번 부르지 않는다
    assert nodes(res).count("replan") == 1


# S3 — 상한 도달: 재계획해도 안 되면 멈추고 조건 조정을 되묻는다
def test_S3_재계획_상한에_도달하면_멈추고_묻는다():
    a, _ = agent({"사회복지사 1급 다음달까지": out("plan_create", targets=["사회복지사 1급"], deadline="2026-12-31")},
                 limit=0)
    res = a.run("s3", "사회복지사 1급 다음달까지", today=TODAY)
    assert res["needs_replan"] == "LIMIT_REACHED"
    assert "재계획 상한" in res["answer"]


# S4 — Tool 하나 실패: 지어내지 않고 사유를 남기고 나머지는 진행
def test_S4_시험일이_없는_자격은_사유와_함께_제외하고_진행():
    a, _ = agent({"전기 + 사회복지사": out("plan_create", field="전기", keywords=["사회복지사"])})
    res = a.run("s4", "전기 + 사회복지사", today=TODAY)
    assert {"name": "사회복지사 1급", "code": "NO_EXAM_DATE"}.items() <= next(
        f for f in res["failures"] if f["name"] == "사회복지사 1급").items()
    assert any(e["reason_code"] == "NO_EXAM_DATE" for e in res["excluded"])
    assert res["draft_plan"]  # 전기 계열은 계획됨


def test_S4_치명적_실패는_재계획하지_않고_안내():
    a, _ = agent({"전기": out("plan_create", field="전기")}, tools=FakeTools(fail_code="INVALID_KEY"))
    res = a.run("s4b", "전기", today=TODAY)
    assert "API 키" in res["answer"] and res["replans"] == []
    assert "judge" not in nodes(res)


# S5 — Tool 불필요
def test_S5_인사는_Tool_없이():
    a, tools = agent({"안녕": out("chat")})
    res = a.run("s5", "안녕", today=TODAY)
    assert tools.calls == [] and nodes(res) == ["analyze", "respond"] and "직업 준비 플래너" in res["answer"]


# S6 — 되묻기
def test_S6_조건이_모자라면_Tool_부르기_전에_되묻기():
    a, tools = agent({"자격증 따고 싶어": out("plan_create")})
    res = a.run("s6", "자격증 따고 싶어", today=TODAY)
    assert tools.calls == [] and "알려 주세요" in res["answer"]


# S7 — 후속 요청: 바뀐 조건만 갱신
def test_S7_후속요청은_이전_조건을_유지():
    a, _ = agent({"전기 쪽 취업": out("plan_create", field="전기"),
                  "기능사는 빼줘": out("plan_modify", new_topic=False, exclude=["기능사"])})
    a.run("s7", "전기 쪽 취업", today=TODAY)
    res = a.run("s7", "기능사는 빼줘", today=TODAY)
    assert res["conditions"]["field"] == "전기" and res["conditions"]["exclude"] == ["기능사"]
    assert [p["name"] for p in res["draft_plan"]] == ["전기기사"]


# 이벤트 · 로깅 분리 (F3012 · 4.3)
def test_이벤트_공통필드와_Tool_소요시간_LLM판단():
    a, _ = agent({"전기 쪽 취업": out("plan_create", field="전기")})
    res = a.run("e1", "전기 쪽 취업", today=TODAY)
    ev = res["events"]
    assert [e["seq"] for e in ev] == list(range(1, len(ev) + 1))
    assert all(e["session_id"] == "e1" and e["run_id"] == res["run_id"] for e in ev)
    assert all("duration_ms" in e for e in ev if e["type"] == "tool_result")
    decision = next(e for e in ev if e["type"] == "llm_decision")
    assert decision["kind"] == "intent" and decision["reason"]


def test_구독자가_고장나도_메인_Agent는_정상응답():
    bus = EventBus()
    bus.subscribe(lambda e: (_ for _ in ()).throw(RuntimeError("로깅 고장")))
    a, _ = agent({"전기 쪽 취업": out("plan_create", field="전기")}, bus=bus)
    assert a.run("e2", "전기 쪽 취업", today=TODAY)["draft_plan"]


def test_LLM_키가_없으면_설정_안내():
    deps = AgentDeps(run_tool=FakeTools(), tool_catalog=lambda: [], field_options=lambda: [], analyze_llm=None)
    res = PlannerAgent(deps).run("e3", "전기", today=TODAY)
    assert "GMS_API_KEY" in res["answer"]


@pytest.mark.live
def test_live_전기_흐름():
    from app.container import build_deps
    a = PlannerAgent(build_deps())
    first = a.run("live", "전기 쪽으로 취업하고 싶어. 자격증 계획 짜줘", today=TODAY)
    assert first["view"]["held_panel"]
    res = a.run("live", "보유 자격 없음", today=TODAY, selection={"held": [], "include": []})
    assert res["draft_plan"][0]["name"] == "전기기사"


def test_지정했지만_출처에_없는_자격은_그렇다고_말한다():
    a, _ = agent({"투자자산운용사 일정": out("fact_lookup", targets=["투자자산운용사"])})
    res = a.run("u1", "투자자산운용사 일정", today=TODAY)
    assert "투자자산운용사: 등록된 출처" in res["answer"] and "2027" not in res["answer"]


# F3023 — 조회한 캘린더 일정을 제약 판단에 반영
def test_캘린더에_일정이_있는_날은_시험일로_잡지_않는다():
    tools = FakeTools()
    tools.busy = ["2027-08-07"]          # 전기기사 첫 가능 회차의 필기일
    a, _ = agent({"전기 쪽 취업": out("plan_create", field="전기")}, tools=tools)
    res = a.run("cal1", "전기 쪽 취업", today=TODAY)
    first = res["draft_plan"][0]
    assert first["name"] == "전기기사" and first["exam_date"] == "2028-01-30"   # 다음 회차로
    assert "캘린더 일정 1일 피함" in res["answer"]
    assert ("list_schedule", ()) in tools.calls


# 보유 자격 패널 — 분야로 처음 계획을 짤 때 선택지로 먼저 묻는다 (대화로 쓰지 않는다)
def test_분야로_처음_계획하면_일정_조회_전에_보유_자격을_묻는다():
    a, tools = agent({"전기 쪽 취업": out("plan_create", field="전기")}, ask_held=True)
    res = a.run("h1", "전기 쪽 취업", today=TODAY)
    panel = res["view"]["held_panel"]
    assert nodes(res) == ["analyze", "plan", "execute", "respond"] and res["draft_plan"] == []
    assert not any(n == "get_exam_schedule" for n, _ in tools.calls)          # 고르기 전엔 일정을 부르지 않는다
    assert panel["field"][0]["items"] == [{"name": "전기기능사", "grade": "기능사"},
                                          {"name": "전기산업기사", "grade": "산업기사"},
                                          {"name": "전기기사", "grade": "기사"}]   # 같은 계열은 낮은 단계부터
    assert [b["name"] for b in panel["basics"]] == ["토익(TOEIC)", "한국사능력검정시험"]
    assert [b["plannable"] for b in panel["basics"]] == [False, True]
    assert "이미 가지고 있는 자격" in res["answer"]


def test_고른_보유_자격은_LLM_없이_반영하고_아래_단계까지_뺀다():
    a, tools = agent({"전기 쪽 취업": out("plan_create", field="전기")}, ask_held=True)
    a.run("h2", "전기 쪽 취업", today=TODAY)
    res = a.run("h2", "보유: 전기산업기사", today=TODAY, selection={"held": ["전기산업기사"], "include": []})
    assert [p["name"] for p in res["draft_plan"]] == ["전기기사"]       # LLM 표에 없는 메시지 → LLM 을 안 불렀다
    held = {h["name"]: h["by"] for h in res["view"]["relations"]["held"]}
    assert held == {"전기기능사": "전기산업기사", "전기산업기사": "전기산업기사"}
    assert not any(e["reason_code"] == "SUPERSEDED" for e in res["excluded"])
    assert "보유 자격 반영" in res["answer"] and res["view"]["held_panel"] is None
    assert any(e["type"] == "user_selection" for e in res["events"])


def test_같이_준비할_기본_자격은_루트_뒤에_붙이고_출처가_없으면_안내():
    a, _ = agent({"전기 쪽 취업": out("plan_create", field="전기")}, ask_held=True)
    a.run("h3", "전기 쪽 취업", today=TODAY)
    res = a.run("h3", "같이 준비: 한국사 · 토익", today=TODAY,
                selection={"held": [], "include": ["한국사능력검정시험", "토익(TOEIC)"]})
    names = [p["name"] for p in res["draft_plan"]]
    assert set(names) == {"전기기사", "한국사능력검정시험"}
    hist = next(p for p in res["draft_plan"] if p["name"] == "한국사능력검정시험")
    assert hist["load"] == "basic"                       # 기본 자격은 다른 공부와 병행
    assert next(p for p in res["draft_plan"] if p["name"] == "한국사능력검정시험")["path_reason"].startswith("직접 골라 넣은")
    assert [b["name"] for b in res["view"]["basics_unplannable"]] == ["토익(TOEIC)"]
    assert "토익(TOEIC): 같이 준비하기로 고르셨지만" in res["answer"]


def test_루트를_모두_가졌으면_그렇다고_말한다():
    a, _ = agent({"전기 쪽 취업": out("plan_create", field="전기")}, ask_held=True)
    a.run("h4", "전기 쪽 취업", today=TODAY)
    res = a.run("h4", "보유: 전기기사", today=TODAY, selection={"held": ["전기기사"], "include": []})
    assert res["draft_plan"] == [] and "이미 모두 가지고 계십니다" in res["answer"]


def test_자격을_직접_지정하면_묻지_않는다():
    a, _ = agent({"전기기사 3월까지": out("plan_create", targets=["전기기사"], deadline="2027-03-31")}, ask_held=True)
    res = a.run("h5", "전기기사 3월까지", today=TODAY)
    assert res["view"]["held_panel"] is None and res["draft_plan"]


def test_후속_요청에서는_다시_묻지_않는다():
    a, _ = agent({"전기 쪽 취업": out("plan_create", field="전기"),
                  "기한 없이 다시": out("plan_create", new_topic=False)}, ask_held=True)
    a.run("h6", "전기 쪽 취업", today=TODAY)
    a.run("h6", "없음", today=TODAY, selection={"held": [], "include": []})
    res = a.run("h6", "기한 없이 다시", today=TODAY)
    assert res["view"]["held_panel"] is None and res["draft_plan"]


class FlakySchedule(FakeTools):
    """일정 조회만 일시적으로 실패 (큐넷 응답 지연 등)"""
    def __init__(self, bad):
        super().__init__()
        self.bad = bad

    def __call__(self, name, **args):
        if name == "get_exam_schedule" and args["qual_id"] in self.bad:
            self.calls.append((name, tuple(sorted(args.items()))))
            return {"ok": False, "error": {"code": "UPSTREAM_ERROR", "message": "응답 없음"}}
        return super().__call__(name, **args)


def test_한_자격의_일시적_실패는_그_자격만_빼고_계획한다():
    a, _ = agent({"전기 + 한국사": out("plan_create", field="전기", keywords=["한국사"])}, tools=FlakySchedule({"H1"}))
    res = a.run("f1", "전기 + 한국사", today=TODAY)
    assert [p["name"] for p in res["draft_plan"]] == ["전기기사"]
    assert any(e["name"] == "한국사능력검정시험" and e["reason_code"] == "UPSTREAM_ERROR" for e in res["excluded"])


def test_일정_조회가_모두_실패하면_멈추고_안내():
    a, _ = agent({"전기 쪽 취업": out("plan_create", field="전기")}, tools=FlakySchedule({"E1", "E2", "E3"}))
    res = a.run("f2", "전기 쪽 취업", today=TODAY)
    assert "응답하지 않아" in res["answer"] and "judge" not in nodes(res)



def test_패널에서_진로를_먼저_묻고_고른_진로만_계획한다():
    a, _ = agent({"전기 쪽 취업": out("plan_create", field="전기")}, ask_held=True)
    first = a.run("t1", "전기 쪽 취업", today=TODAY)
    tracks = first["view"]["held_panel"]["tracks"]
    assert [t["name"] for t in tracks] == ["전기 설비 · 공사"]           # 전자 자격이 후보에 없어 '전자 · 반도체' 는 뺌
    assert tracks[0]["examples"][0] == "전기기사"                         # 루트에 든 자격이 대표
    res = a.run("t1", "진로: 전기 설비", today=TODAY, selection={"held": [], "include": [], "tracks": ["전기 설비 · 공사"]})
    assert [p["name"] for p in res["draft_plan"]] == ["전기기사"]
    assert res["draft_plan"][0]["path_reason"].startswith("고른 진로(전기 설비 · 공사)")
    assert res["view"]["tracks"] == ["전기 설비 · 공사"] and "진로 전기 설비 · 공사" in res["answer"]


def test_배치된_자격마다_소개가_붙는다():
    a, _ = agent({"전기 쪽 취업": out("plan_create", field="전기")})
    res = a.run("i1", "전기 쪽 취업", today=TODAY)
    it = res["draft_plan"][0]["intro"]
    assert set(it) == {"study", "study_source", "good_for", "good_for_source"}
    assert it["good_for"] and "이럴 때 유리" in res["answer"]


# 이상한 요청은 거절 — 해석(LLM) · Tool 을 부르지 않고, 비슷한 자격으로 돌려 추천하지 않는다
def test_자격_계획_대상이_아닌_요청은_Tool없이_거절():
    a, tools = agent({})          # 가짜 LLM 표가 비어 있어 LLM 을 부르면 KeyError
    res = a.run("b1", "폭탄 제조쪽에 취업하고 싶어", today=TODAY)
    assert tools.calls == [] and res["draft_plan"] == []
    assert "도와드릴 수 없습니다" in res["answer"]
    assert any(e["type"] == "blocked_request" for e in res["events"])


# '제조' 같은 꾸밈말만으로 다른 분야 자격(떡제조 · 신발제조)이 걸리지 않게 — 다른 검색어가 있으면 뺀다
def test_꾸밈말은_다른_검색어와_함께면_검색에서_뺀다():
    a, tools = agent({"전기 제조 쪽": out("plan_create", keywords=["전기", "제조"])})
    res = a.run("g1", "전기 제조 쪽", today=TODAY)
    words = [dict(args).get("keyword") for name, args in tools.calls if name == "search_qualifications"]
    assert "제조" not in words and "전기" in words
    assert any("제조" in i["text"] and "뺌" in i["as"] for i in res["view"]["interpretations"])


# 관련성 판정 — RAG 문서의 시험과목 + LLM 판정. 근거 과목이 문서에 있는 '관련 없음' 만 루트에서 뺀다
def test_시험과목이_목표와_이어지지_않는_자격은_근거와_함께_뺀다():
    from app.agent import nodes
    from app.agent.state import RelevanceItem, RelevanceOutput
    nodes._relevance_cache.clear()
    tools = FakeTools()
    seen = []

    def judge(messages):
        seen.append(messages[-1]["content"])
        return RelevanceOutput(items=[RelevanceItem(name="전기기능사", relevant=False, basis="전기이론", reason="테스트")])

    rel = {"field_groups": {}, "ladders": [], "expert": [], "prep_weeks": {}, "basics": [], "tracks": []}
    deps = AgentDeps(run_tool=tools, tool_catalog=lambda: [], field_options=lambda: ["전기"],
                     analyze_llm=analyzer({"전기 쪽 취업": out("plan_create", field="전기")}), relations=lambda: rel,
                     ask_held=False, subjects_of=lambda names: {n: "필기: 전기이론, 전기기기" for n in names if n == "전기기능사"},
                     relevance_llm=judge)
    res = PlannerAgent(deps).run("r1", "전기 쪽 취업", today=TODAY)
    assert "전기기능사" in seen[0] and "전기이론" in seen[0]          # 문서의 시험과목을 LLM 에 준다
    gone = res["view"]["relations"]["irrelevant"]
    assert [x["name"] for x in gone] == ["전기기능사"] and gone[0]["basis"] == "전기이론"
    assert all(e["name"] != "전기기능사" for e in res["excluded"] if e["reason_code"] == "SUPERSEDED")
    assert any(e["type"] == "llm_decision" and e.get("kind") == "relevance" for e in res["events"])
    # 같은 목표 · 같은 자격은 다시 묻지 않는다 (판정 고정)
    PlannerAgent(deps).run("r2", "전기 쪽 취업", today=TODAY)
    assert len(seen) == 1


# 특이한 직무(약어 · 신생 직업) — LLM 이 직무를 풀어 검색어만 내고, 출처에 있는 자격만 후보가 된다
def _career_agent(output):
    from app.agent import nodes
    nodes._career_cache.clear()
    tools = FakeTools()
    rel = {"field_groups": {}, "ladders": [], "expert": [], "prep_weeks": {}, "basics": [], "tracks": []}
    deps = AgentDeps(run_tool=tools, tool_catalog=lambda: [], field_options=lambda: ["전기"],
                     analyze_llm=analyzer({"브이씨피엠 쪽": out("plan_create", keywords=["브이씨피엠"])}),
                     relations=lambda: rel, ask_held=False, career_llm=lambda m: output)
    return PlannerAgent(deps), tools


def test_모르는_직무는_짐작해_추천하지_않고_되묻는다():
    from app.agent.state import CareerOutput
    a, tools = _career_agent(CareerOutput(known=False, job="", search_words=["전기"]))   # 모르면 검색어도 버린다
    res = a.run("c1", "브이씨피엠 쪽", today=TODAY)
    assert res["draft_plan"] == [] and "확실히 알 수 없습니다" in res["answer"]
    assert "전기" not in [dict(args).get("keyword") for n, args in tools.calls]


def test_직무를_풀어_출처에_있는_자격만_후보로_쓴다():
    from app.agent.state import CareerOutput
    a, tools = _career_agent(CareerOutput(known=True, job="벤처 사업 총괄", search_words=["전기기사", "없는자격"]))
    res = a.run("c2", "브이씨피엠 쪽", today=TODAY)
    assert "벤처 사업 총괄" in res["answer"] and "없는자격" not in res["answer"]  # 풀이는 AI 해석으로, 확인 안 된 추측은 보이지 않는다
    assert any(e["type"] == "llm_decision" and e.get("kind") == "career" for e in res["events"])


def test_LLM이_모르는_직무도_네이버_글에_함께_나온_자격은_출처로_확인해_쓴다():
    from app.agent import nodes
    from app.agent.state import CareerOutput
    nodes._career_cache.clear()
    nodes._evidence_cache.clear()
    tools = FakeTools()
    rel = {"field_groups": {}, "ladders": [], "expert": [], "prep_weeks": {}, "basics": [], "tracks": []}
    ev = {"mentions": [{"name": "전기기사", "docs": 5}, {"name": "없는자격", "docs": 3}], "docs": 33, "refs": [], "error": None}
    deps = AgentDeps(run_tool=tools, tool_catalog=lambda: [], field_options=lambda: ["전기"],
                     analyze_llm=analyzer({"브이씨피엠 쪽": out("plan_create", keywords=["브이씨피엠"])}),
                     relations=lambda: rel, ask_held=False,
                     career_llm=lambda m: CareerOutput(known=False, job="", search_words=[]), job_evidence=lambda g: ev)
    res = PlannerAgent(deps).run("w1", "브이씨피엠 쪽", today=TODAY)
    assert "네이버 글 33건" in res["answer"] and "전기기사 5건" in res["answer"]
    assert [p["name"] for p in res["draft_plan"]] == ["전기기사"]            # 출처에 없는 '없는자격' 은 계획에 안 들어간다


def test_직업을_말하면_분야가_있어도_직업으로_자격을_찾고_계획_제목이_직업이다():
    from app.agent import nodes
    from app.agent.state import CareerOutput
    nodes._career_cache.clear()
    nodes._evidence_cache.clear()
    tools = FakeTools()
    asked = []

    def career(m):
        asked.append(m[-1]["content"])
        return CareerOutput(known=True, job="전기 설비를 설계 · 시공 · 관리", search_words=["전기기사"])

    rel = {"field_groups": {}, "ladders": [], "expert": [], "prep_weeks": {}, "basics": [], "tracks": []}
    deps = AgentDeps(run_tool=tools, tool_catalog=lambda: [], field_options=lambda: ["전기"],
                     analyze_llm=analyzer({"전기 엔지니어가 되고 싶어": out("plan_create", job="전기 엔지니어", field="전기")}),
                     relations=lambda: rel, ask_held=False, career_llm=career)
    res = PlannerAgent(deps).run("j1", "전기 엔지니어가 되고 싶어", today=TODAY)
    assert "전기 엔지니어" in asked[0]
    assert res["answer"].startswith("### 전기 엔지니어 준비 계획") and "목표 직업 전기 엔지니어" in res["answer"]
    assert res["view"]["relations"]["career"]["name"] == "전기 엔지니어"


# 커리어넷(공식) — LLM 은 후보 목록 안에서 같은 직업만 고르고, 관련 자격은 커리어넷 원문에서 나온 이름만 쓴다
def _careernet_agent(seq, cert_names, web_calls):
    from app.agent import nodes
    from app.agent.state import CareerOutput
    for cache in (nodes._career_cache, nodes._evidence_cache, nodes._profile_cache):
        cache.clear()
    prof = {"seq": 7, "name": "전기공학기술자", "url": "https://career.example/7", "work": ["전기 설비를 설계한다."],
            "certificate": ["전기기사, 전기공사기사 등이 있습니다."], "curriculum": ["전기공학과"], "training": [], "recruit": [],
            "cert_names": cert_names}
    rel = {"field_groups": {}, "ladders": [], "expert": [], "prep_weeks": {}, "basics": [], "tracks": []}
    deps = AgentDeps(run_tool=FakeTools(), tool_catalog=lambda: [], field_options=lambda: ["전기"],
                     analyze_llm=analyzer({"전기 엔지니어가 되고 싶어": out("plan_create", job="전기 엔지니어")}),
                     relations=lambda: rel, ask_held=False,
                     career_llm=lambda m: CareerOutput(known=True, job="AI 풀이", search_words=["없는자격"], careernet_seq=seq),
                     job_candidates=lambda g: [{"seq": 7, "job_nm": "전기공학기술자", "rel_job_nm": ""}],
                     job_profile=lambda s: prof, job_evidence=lambda g: web_calls.append(g) or {})
    return PlannerAgent(deps)


def test_커리어넷_직업이_있으면_공식_관련_자격만_쓰고_네이버는_부르지_않는다():
    web = []
    res = _careernet_agent(7, ["전기기사"], web).run("cn1", "전기 엔지니어가 되고 싶어", today=TODAY)
    assert [p["name"] for p in res["draft_plan"]] == ["전기기사"]           # LLM 검색어 '없는자격' 은 쓰지 않는다
    assert "전기공학기술자" in res["answer"] and "커리어넷 직업정보" in res["answer"] and "관련 자격: 전기기사" in res["answer"]
    assert web == []
    assert res["view"]["relations"]["career"]["official"]["name"] == "전기공학기술자"


def test_후보_목록_밖의_번호는_버리고_비공식_경로로():
    web = []
    res = _careernet_agent(999, ["전기기사"], web).run("cn2", "전기 엔지니어가 되고 싶어", today=TODAY)
    assert res["view"]["relations"]["career"]["official"] is None and web == ["전기 엔지니어"]


# 목표 점검 — 문장 전체 맥락으로 직위 · 모호 · 직업 아님을 거르고, 실제 직업을 선택지로 제안한다
def _screen_agent(verdict, core=None, suggestions=()):
    from app.agent.screen import ScreenOutput
    tools = FakeTools()
    seen = []

    def screen(m):
        seen.append(m[-1]["content"])
        return ScreenOutput(verdict=verdict, core_job=core, reason="특정 회사의 대표는 자격으로 준비하는 직업이 아닙니다.",
                            suggestions=list(suggestions))

    rel = {"field_groups": {}, "ladders": [], "expert": [], "prep_weeks": {}, "basics": [], "tracks": []}
    table = {"스페이스x 대표": out("plan_create", job="스페이스x 대표"),
             "스페이스x 로켓 엔지니어": out("plan_create", job="스페이스x 로켓 엔지니어"),
             "전기기사 따고 싶어": out("plan_create", targets=["전기기사"])}
    deps = AgentDeps(run_tool=tools, tool_catalog=lambda: [], field_options=lambda: ["전기"], analyze_llm=analyzer(table),
                     relations=lambda: rel, ask_held=False, screen_llm=screen)
    return PlannerAgent(deps), tools, seen


def test_직위는_Tool_없이_걸러_내고_맥락에_맞는_직업을_제안한다():
    a, tools, seen = _screen_agent("position", suggestions=["항공우주 엔지니어", "경영 컨설턴트"])
    res = a.run("s1", "스페이스x 대표", today=TODAY)
    assert tools.calls == [] and res["draft_plan"] == []
    assert "스페이스x 대표" in seen[0]                                   # 낱말이 아니라 문장 전체를 넘긴다
    assert res["view"]["screen"]["suggestions"] == ["항공우주 엔지니어", "경영 컨설턴트"]
    assert "항공우주 엔지니어" in res["answer"] and nodes(res) == ["analyze", "screen", "respond"]


def test_통과하면_맥락_속_실제_직무로_고쳐서_진행():
    a, tools, _ = _screen_agent("ok", core="항공우주 엔지니어")
    res = a.run("s2", "스페이스x 로켓 엔지니어", today=TODAY)
    assert res["conditions"]["job"] == "항공우주 엔지니어" and res["view"]["screen"] is None
    assert any("항공우주 엔지니어" in i["as"] for i in res["view"]["interpretations"])


def test_자격을_직접_말하면_점검하지_않는다():
    a, tools, seen = _screen_agent("vague")
    res = a.run("s3", "전기기사 따고 싶어", today=TODAY)
    assert seen == [] and "screen" not in nodes(res)


# 외부 자격 탐색 — 커리어넷 원문의 큐넷 밖 자격을 웹 조각에서 찾되, 조각에 있는 날짜만 쓴다
def _external_agent(exam_items, cert_text="민간자격으로 투자자산운용사가 있습니다."):
    from app.agent import nodes
    from app.agent.external import CertNames, ExamFind, ExamItem
    from app.agent.state import CareerOutput
    for cache in (nodes._career_cache, nodes._evidence_cache, nodes._profile_cache):
        cache.clear()
    prof = {"seq": 9, "name": "투자분석가", "url": "https://career.example/9", "work": ["투자 정보를 분석한다."],
            "certificate": [cert_text], "curriculum": [], "training": [], "recruit": [], "cert_names": []}

    def extract(messages, schema):
        if schema is CertNames:
            return CertNames(names=["투자자산운용사", "지어낸자격"])           # 원문에 없는 이름은 버려져야 한다
        return ExamFind(items=[ExamItem(**x) for x in exam_items])

    snippets = {"items": [{"i": 0, "title": "투자자산운용사 시험일정 - 금융투자협회", "text": "시험 : 12.20(일), 접수 11.23~11.27",
                           "link": "https://license.example/exam"}], "error": None}
    rel = {"field_groups": {}, "ladders": [], "expert": [], "prep_weeks": {}, "basics": [], "tracks": []}
    deps = AgentDeps(run_tool=FakeTools(), tool_catalog=lambda: [], field_options=lambda: ["전기"],
                     analyze_llm=analyzer({"투자분석가가 되고 싶어": out("plan_create", job="투자분석가")}),
                     relations=lambda: rel, ask_held=False,
                     career_llm=lambda m: CareerOutput(known=True, job="", search_words=[], careernet_seq=9),
                     job_candidates=lambda g: [{"seq": 9, "job_nm": "투자분석가", "rel_job_nm": ""}], job_profile=lambda s: prof,
                     web_snippets=lambda q: snippets, extract_llm=extract)
    return PlannerAgent(deps)


def test_큐넷_밖_자격은_조각에_적힌_날짜만_비공식으로_보여준다():
    res = _external_agent([{"source": 0, "date_text": "12.20(일)", "exam_date": "2026-12-20", "reg_text": "11.23~11.27"}]
                          ).run("x1", "투자분석가가 되고 싶어", today=TODAY)
    ext = res["view"]["relations"]["external"]
    assert [x["name"] for x in ext] == ["투자자산운용사"]                  # '지어낸자격' 은 원문에 없어 버림
    assert ext[0]["exam_date"] == "2026-12-20" and ext[0]["year_estimated"] and ext[0]["link"] == "https://license.example/exam"
    assert "큐넷 밖 관련 자격" in res["answer"] and "비공식" in res["answer"] and res["draft_plan"] == []
    assert "external" in nodes(res)


def test_조각에_없는_날짜는_버린다():
    res = _external_agent([{"source": 0, "date_text": "3월 14일", "exam_date": "2027-03-14"}]).run("x2", "투자분석가가 되고 싶어", today=TODAY)
    x = res["view"]["relations"]["external"][0]
    assert x["exam_date"] is None and "확인하지 못했습니다" in res["answer"]


def test_조각_날짜의_연도는_코드가_정한다():
    from datetime import date
    from app.agent.external import _date_of, _web_names
    t = date(2026, 11, 20)
    assert _date_of("02.28 (토)", t) == (date(2027, 2, 28), False)        # 지난 날짜면 다음 해로 (추정)
    assert _date_of("12.20(일)", t) == (date(2026, 12, 20), False)
    assert _date_of("2027년 3월 14일", t) == (date(2027, 3, 14), True)
    assert _date_of("상시", t) == (None, False)
    assert _web_names(["투자분석사", "금융투자분석사", "없는자격"], ["금융투자분석사 증권분석사"]) == ["금융투자분석사"]
