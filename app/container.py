"""조립 지점 (Frameworks & Drivers) — 실제 Tool · LLM · 이벤트 버스를 Agent 에 넣는다.

agent/ 는 이 파일을 모른다. API 라우터와 스크립트가 이 파일에서 만든 것을 쓴다.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from app.agent.deps import AgentDeps
from app.agent.screen import ScreenOutput
from app.agent.state import AnalyzeOutput, CareerOutput, RelevanceOutput
from app.llm import get_chat_model
from app.logging_agent.inspector import DIAGNOSE_PROMPT, summarize_for_diagnosis
from app.tools import catalog, run_tool
from app.tools.jobsearch import job_candidates, job_evidence, job_profile, registered, web_snippets
from app.tools.qualifications import exemption_precedes, field_options, official_subjects, relations_config


def replan_limit() -> int:
    return int(os.getenv("REPLAN_LIMIT") or 2)


def build_deps(last_inspection: Callable[[str], dict | None] | None = None) -> AgentDeps:
    llm = get_chat_model()
    analyze_llm = relevance_llm = career_llm = screen_llm = extract_llm = None
    if llm is not None:
        structured = llm.with_structured_output(AnalyzeOutput)

        def analyze_llm(messages: list[dict]) -> AnalyzeOutput:
            return structured.invoke(messages)

        judge = llm.with_structured_output(RelevanceOutput)

        def relevance_llm(messages: list[dict]) -> RelevanceOutput:
            return judge.invoke(messages)

        explain = llm.with_structured_output(CareerOutput)
        screener = llm.with_structured_output(ScreenOutput)

        def screen_llm(messages: list[dict]) -> ScreenOutput:
            return screener.invoke(messages)

        extractors: dict = {}

        def extract_llm(messages: list[dict], schema: type):
            if schema not in extractors:
                extractors[schema] = llm.with_structured_output(schema)
            return extractors[schema].invoke(messages)

        def career_llm(messages: list[dict]) -> CareerOutput:
            return explain.invoke(messages)

    return AgentDeps(
        run_tool=run_tool,
        tool_catalog=catalog,
        field_options=field_options,
        analyze_llm=analyze_llm,
        replan_limit=replan_limit(),
        precedes=exemption_precedes,
        last_inspection=last_inspection or (lambda session_id: None),
        relations=relations_config,
        subjects_of=official_subjects,
        relevance_llm=relevance_llm,
        career_llm=career_llm,
        screen_llm=screen_llm,
        web_snippets=web_snippets,
        registered=registered,
        extract_llm=extract_llm,
        job_evidence=job_evidence,
        job_candidates=job_candidates,
        job_profile=job_profile,
    )


def build_diagnose() -> Callable[[dict, list[dict]], str] | None:
    """로깅 Agent 의 진단 함수 (F3020) — '이상' 판정에만 불린다. LLM 키가 없으면 None (진단 생략)."""
    llm = get_chat_model()
    if llm is None:
        return None

    def diagnose(result: dict, events: list[dict]) -> str:
        warnings = "; ".join(w["detail"] for w in result["warnings"])
        msg = DIAGNOSE_PROMPT.format(warnings=warnings, events=summarize_for_diagnosis(events))
        text = llm.invoke(msg).content.strip()
        return text[:600]

    return diagnose
