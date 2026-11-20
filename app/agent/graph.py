"""메인 Agent 그래프 (LangGraph) — analyze → (screen) → plan → execute → judge → (replan → execute)* → enrich → respond.

run_agent() 가 요청 1건을 실행한다. 대화 맥락은 체크포인터(세션 = thread_id)에 남는다 (F3010).
"""

from __future__ import annotations

from datetime import date

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.domain.names import target_found
from app.events import Emitter, EventBus

from .analyze import make_analyze
from .deps import AgentDeps
from .nodes import PLAN_INTENTS, make_enrich, make_execute, make_judge, make_plan, make_replan
from .respond import make_respond
from .external import make_external, needs_external
from .screen import make_screen, needs_screen
from .state import PlannerState

# 요청마다 새로 시작하는 값 (대화 맥락으로 남기지 않는다)
PER_TURN_RESET = {
    "missing": [], "warnings": [], "interpretations": [], "steps": [], "tool_results": {}, "failures": [],
    "candidates": [], "arrangement": None, "documents": [], "busy_dates": [], "route_meta": {}, "lookup": None, "books": {}, "replan_count": 0, "replan_log": [],
    "needs_replan": None, "ignore_deadline": False, "fatal": None, "error": None, "batch_end": 0,
    "held_panel": None, "selection": None, "screen": None, "degree_panel": None, "degree_lookup": None,
}


def _after_analyze(s: PlannerState) -> str:
    if s.get("error") or s.get("missing") or s.get("degree_panel") or s.get("intent") not in (*PLAN_INTENTS, "fact_lookup", "qual_info"):
        return "respond"
    return "plan"


def _after_screen(s: PlannerState) -> str:
    return "respond" if s.get("screen") or s.get("intent") == "chat" else "plan"


def _after_execute(s: PlannerState) -> str:
    return "respond" if s.get("fatal") or s.get("held_panel") or s.get("intent") == "qual_info" else "judge"


def _after_judge(s: PlannerState) -> str:
    if s.get("needs_replan") in ("NEXT_CANDIDATES", "RELAX_DEADLINE"):
        return "replan"
    if s.get("intent") == "fact_lookup" or not ((s.get("arrangement") or {}).get("placed")):
        return "respond"
    return "enrich"


def _unplannable(state: PlannerState, deps: AgentDeps) -> list[dict]:
    """같이 준비하기로 골랐지만 출처에 일정이 없어 계획에 못 넣은 기본 자격 {name, note}"""
    c = state.get("conditions") or {}
    placed = {p["name"] for p in (state.get("arrangement") or {}).get("placed") or []}
    names = [q["name"] for q in state.get("candidates") or []]
    basics = {b["name"]: b for b in deps.relations().get("basics") or []}
    return [{"name": n, "note": (basics.get(n) or {}).get("note")} for n in c.get("include") or []
            if not target_found(n, names) and n not in placed]


class PlannerAgent:
    def __init__(self, deps: AgentDeps, bus: EventBus | None = None):
        self.deps = deps
        self.bus = bus
        self._emitters: dict[str, Emitter] = {}
        emitter_of = lambda s: self._emitters[s["run_id"]]  # noqa: E731
        g = StateGraph(PlannerState)
        g.add_node("analyze", make_analyze(deps, emitter_of))
        g.add_node("screen", make_screen(deps, emitter_of))
        g.add_node("plan", make_plan(deps, emitter_of))
        g.add_node("execute", make_execute(deps, emitter_of))
        g.add_node("judge", make_judge(deps, emitter_of))
        g.add_node("replan", make_replan(deps, emitter_of))
        g.add_node("enrich", make_enrich(deps, emitter_of))
        g.add_node("external", make_external(deps, emitter_of))
        g.add_node("respond", make_respond(deps, emitter_of))
        g.add_edge(START, "analyze")
        def after_analyze(s: PlannerState) -> str:
            nxt = _after_analyze(s)
            # 목표 점검은 실제로 할 때만 거친다 (자격을 직접 지정했거나 LLM 이 없으면 건너뛴다)
            return "screen" if nxt == "plan" and deps.screen_llm is not None and needs_screen(s) else nxt

        g.add_conditional_edges("analyze", after_analyze, ["screen", "plan", "respond"])
        g.add_conditional_edges("screen", _after_screen, ["plan", "respond"])
        g.add_edge("plan", "execute")
        g.add_conditional_edges("execute", _after_execute, ["judge", "respond"])
        def ext_or_respond(s: PlannerState) -> str:
            # 큐넷 밖 자격 탐색은 직업 목표이고 탐색 도구가 있을 때만
            on = deps.extract_llm is not None and deps.web_snippets is not None and needs_external(s)
            return "external" if on else "respond"

        def after_judge(s: PlannerState) -> str:
            nxt = _after_judge(s)
            return ext_or_respond(s) if nxt == "respond" and s.get("intent") != "fact_lookup" else nxt

        g.add_conditional_edges("judge", after_judge, ["replan", "enrich", "external", "respond"])
        g.add_edge("replan", "execute")
        g.add_conditional_edges("enrich", ext_or_respond, ["external", "respond"])
        g.add_edge("external", "respond")
        g.add_edge("respond", END)
        self.graph = g.compile(checkpointer=MemorySaver())

    def run(self, session_id: str, message: str, today: str | None = None, selection: dict | None = None) -> dict:
        """selection: 화면 선택지로 고른 값 {"held": [보유 자격], "include": [같이 준비할 기본 자격]}"""
        em = Emitter(self.bus, session_id)
        self._emitters[em.run_id] = em
        try:
            prev = self.deps.last_inspection(session_id)
        except Exception:  # 판정을 못 읽어도 대화는 계속한다
            prev = None
        if prev:
            em.emit("inspection_seen", None, run=prev.get("run_id"), verdict=prev.get("verdict"),
                    warnings=[w["type"] for w in prev.get("warnings") or []])
        try:
            state = self.graph.invoke(
                {**PER_TURN_RESET, "session_id": session_id, "run_id": em.run_id, "message": message,
                 "today": today or date.today().isoformat(), "prev_inspection": prev,
                 **({"selection": selection} if selection is not None else {})},
                config={"configurable": {"thread_id": session_id}, "recursion_limit": 40},
            )
        finally:
            self._emitters.pop(em.run_id, None)
        a = state.get("arrangement") or {}
        return {
            "session_id": session_id, "run_id": em.run_id, "answer": state.get("answer", ""),
            "intent": state.get("intent"), "conditions": state.get("conditions"),
            "draft_plan": a.get("placed") or [], "excluded": a.get("excluded") or [],
            "lookup": state.get("lookup"), "books": state.get("books") or {}, "documents": state.get("documents") or [],
            "replans": state.get("replan_log") or [], "needs_replan": state.get("needs_replan"),
            "failures": [{k: f.get(k) for k in ("tool", "code", "name")} for f in state.get("failures") or []],
            "events": em.events, "prev_inspection": prev,
            # 화면이 카드로 그릴 수 있게 구조화된 요약 (answer 는 같은 내용의 글 버전)
            "view": {
                "missing": state.get("missing") or [],
                "interpretations": state.get("interpretations") or [],
                "deferred": a.get("deferred") or [],
                "fee_total": a.get("fee_total"), "fee_unknown": a.get("fee_unknown") or [],
                "deadline_ignored": bool(a.get("deadline_ignored")),
                "busy_days": len(state.get("busy_dates") or []),
                "unmatched": [t for t in (state.get("conditions") or {}).get("targets") or []
                              if not target_found(t, [q["name"] for q in state.get("candidates") or []],
                                                  (state.get("conditions") or {}).get("keywords"))],
                "error": state.get("error"), "fatal": state.get("fatal"),
                "relations": state.get("route_meta") or {},
                "held_panel": state.get("held_panel"),
                "degree_panel": state.get("degree_panel"),
                "screen": state.get("screen"),
                "held": (state.get("conditions") or {}).get("held") or [],
                "include": (state.get("conditions") or {}).get("include") or [],
                "tracks": (state.get("route_meta") or {}).get("tracks_used") or [],
                "basics_unplannable": _unplannable(state, self.deps),
            },
        }
