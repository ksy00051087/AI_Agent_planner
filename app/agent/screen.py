"""목표 점검 Agent (screen) — 요청 전체 맥락을 읽고 '자격 준비 계획으로 이어질 수 있는 목표인가' 를 판정한다.

analyze 가 뽑은 낱말(job · keywords)만 보지 않는다. 문장 전체를 보고
  · 특정 회사의 대표 · 임원 · 창업자 같은 '직위' (스페이스X 대표) — 자격으로 가는 길이 아니다
  · 뜻을 알 수 없거나 너무 모호한 말
  · 직업이 아닌 것 (부자 되기, 유명해지기)
을 걸러 내고, 대신 맥락에 맞는 실제 직업을 화면 선택지로 제안한다. 제안은 '다시 물어볼 후보' 일 뿐이고,
누르면 일반 흐름(커리어넷 · 큐넷 확인)을 그대로 거친다 — 여기서 자격이나 일정을 말하지 않는다.

통과한 경우 맥락 속 실제 직업으로 고쳐 준다 (예: '스페이스X 로켓 엔지니어' → '항공우주공학기술자 · 로켓 엔지니어' 쪽).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.events import Emitter

from .deps import AgentDeps
from .state import PlannerState

NODE = "screen"
Verdict = Literal["ok", "position", "vague", "not_job"]

SCREEN_SYSTEM = """너는 자격증 기반 직업 준비 플래너의 '목표 점검' 단계다. 사용자 문장 '전체' 를 읽고 판정한다.
낱말 하나(예: '대표', '매니저')에 끌려가지 말고, 회사 · 맥락 · 수식어까지 함께 보고 사용자가 실제로 원하는 것을 파악한다.

verdict
- ok       : 사람들이 자격 · 교육 · 훈련으로 준비해 들어가는 직업 · 직무다 (전기 엔지니어, 조리사, 데이터 분석가, 9급 공무원,
             '삼성전자 반도체 엔지니어' 처럼 회사가 붙어도 직무가 분명하면 ok).
- position : 특정 회사 · 조직의 대표 · CEO · 회장 · 임원 · 창업자처럼 자격 준비로 오르는 자리가 아닌 '직위' 다 (스페이스X 대표, 삼성 회장).
- vague    : 무엇을 하고 싶은지 알 수 없을 만큼 모호하거나, 뜻을 알 수 없는 말이다.
- not_job  : 직업이 아니다 (부자 되기, 유명해지기, 행복하게 살기).

core_job : ok 일 때 맥락 속 실제 직무 이름 (회사명 · 꾸밈말을 뗀다). 예) '스페이스X 로켓 엔지니어' → '항공우주 엔지니어'. 아니면 null.
reason   : 사용자에게 보여 줄 한두 문장. 판정 이유를 담담하게. 사과 · 훈계 · 과장 없이.
suggestions : ok 가 아닐 때, 문장의 맥락과 이어지는 '실제 직업' 2~4개 (예: 스페이스X 대표 → 항공우주 엔지니어, 기업 경영 컨설턴트 …).
              짐작이 어려우면 빈 목록. 자격 이름 · 일정 · 합격률은 말하지 않는다."""


class ScreenOutput(BaseModel):
    verdict: Verdict = Field(description="ok | position | vague | not_job")
    core_job: str | None = Field(None, description="ok 일 때 맥락 속 실제 직무 이름. 아니면 null")
    reason: str = Field(description="사용자에게 보여 줄 판정 이유 한두 문장")
    suggestions: list[str] = Field(default_factory=list, description="ok 가 아닐 때 맥락에 맞는 실제 직업 2~4개")


def needs_screen(state: PlannerState) -> bool:
    """새로 계획을 짜는 요청에서 직업 · 낱말로만 목표를 말했을 때만 (자격을 직접 지정했거나 화면 선택 후속이면 건너뛴다)"""
    c = state.get("conditions") or {}
    if state.get("intent") != "plan_create" or state.get("selection") is not None or c.get("targets"):
        return False
    return bool(c.get("job") or (c.get("keywords") and not c.get("field")))


def make_screen(deps: AgentDeps, emitter_of):
    cache: dict[str, dict] = {}

    def screen(state: PlannerState) -> dict:
        em: Emitter = emitter_of(state)
        em.node_enter(NODE)
        c = dict(state.get("conditions") or {})
        if deps.screen_llm is None or not needs_screen(state):
            em.node_exit(NODE, skipped=True)
            return {"screen": None}
        msg = state["message"]
        if msg not in cache:
            goal = c.get("job") or " ".join(c.get("keywords") or [])
            messages = [{"role": "system", "content": SCREEN_SYSTEM},
                        {"role": "user", "content": f"사용자 문장: {msg}\n(앞 단계가 뽑은 목표 낱말: {goal})"}]
            try:
                cache[msg] = deps.screen_llm(messages).model_dump()
            except Exception:
                em.error(NODE, "LLM_ERROR", where="screen")
                em.node_exit(NODE, verdict=None)
                return {"screen": None}        # 점검을 못 하면 막지 않고 원래 흐름으로
        out = dict(cache[msg])
        out["suggestions"] = [s.strip() for s in out.get("suggestions") or [] if s and s.strip()][:4]
        em.llm_decision(NODE, "screen", {"verdict": out["verdict"], "core_job": out.get("core_job"),
                                         "suggestions": out["suggestions"]}, out.get("reason") or "")
        update: dict = {"screen": out if out["verdict"] != "ok" else None}
        core = (out.get("core_job") or "").strip()
        if out["verdict"] == "ok" and core and core != c.get("job"):
            before = c.get("job") or " ".join(c.get("keywords") or [])
            c["job"] = core
            update["conditions"] = c
            update["interpretations"] = [*(state.get("interpretations") or []),
                                         {"text": before, "as": f"직무 '{core}' (문장 전체 맥락으로 판단)"}]
        em.node_exit(NODE, verdict=out["verdict"])
        return update

    return screen
