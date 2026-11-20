"""Agent 가 바깥 세계와 닿는 지점. agent/ 는 tools · LLM SDK 를 import 하지 않고 이것을 주입받는다.

실제 연결은 app/container.py, 테스트는 가짜를 넣는다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .state import AnalyzeOutput, CareerOutput, RelevanceOutput


@dataclass
class AgentDeps:
    # Tool
    run_tool: Callable[..., dict]            # run_tool(name, **args) -> ok/fail
    tool_catalog: Callable[[], list[dict]]   # Agent 에 넘길 Tool 명세
    field_options: Callable[[], list[str]]   # 조건 추출 때 고를 수 있는 분야 이름
    # LLM — None 이면 LLM 이 필요한 단계에서 LLM_UNAVAILABLE 로 안내한다
    analyze_llm: Callable[[list[dict]], AnalyzeOutput] | None
    replan_limit: int = 2
    # 선수 관계 {B: {B 보다 먼저 따면 좋은 A}} — 공식 시험면제과목 데이터. 없으면 빈 dict
    precedes: Callable[[list[str]], dict[str, set[str]]] = lambda names: {}
    # 직전 실행의 이상 징후 판정 (F3020) — 로깅 Agent 가 저장한 것을 읽기만 한다. 없으면 None
    last_inspection: Callable[[str], dict | None] = lambda session_id: None
    # 자격 관계 설정 (분야 묶음 · 경력 사다리 · 전문가급 · 종목별 준비 기간 기준값). 없으면 빈 설정
    relations: Callable[[], dict] = lambda: {"field_groups": {}, "ladders": [], "expert": [], "prep_weeks": {}, "basics": []}
    # 목표와 자격의 관련성 판정 — RAG 문서의 공식 시험과목 {자격명: 과목 글} 과 판정 LLM. 없으면 판정 생략
    subjects_of: Callable[[list[str]], dict[str, str]] = lambda names: {}
    relevance_llm: Callable[[list[dict]], RelevanceOutput] | None = None
    # 목표 점검 LLM — 문장 전체 맥락으로 직위 · 모호 · 직업 아님을 거른다 (app/agent/screen.py). 없으면 점검 생략
    screen_llm: Callable[[list[dict]], object] | None = None
    # 직무 풀이 LLM — 특이한 직업군(약어 포함)을 자격 검색어로 바꾼다. 없으면 생략
    career_llm: Callable[[list[dict]], CareerOutput] | None = None
    # 직무 근거 — 네이버 글에서 그 직무와 함께 언급된 자격 {"mentions":[{name,docs}], "docs", "refs", "error"}. 없으면 생략
    job_evidence: Callable[[str], dict] | None = None
    # 커리어넷 직업정보 (공식) — 직업 이름 → 후보 직업 [{seq, job_nm, rel_job_nm}], seq → 상세(하는 일 · 관련 자격 원문 · 학과 · 훈련)
    job_candidates: Callable[[str], list[dict]] | None = None
    job_profile: Callable[[int], dict | None] | None = None
    # 외부 자격 탐색 (app/agent/external.py) — 큐넷 밖 자격의 웹문서 조각 · 등록 여부 · 구조화 추출 LLM. 없으면 생략
    web_snippets: Callable[[str], dict] | None = None
    registered: Callable[[list[str]], set[str]] = lambda names: set()
    extract_llm: Callable[[list[dict], type], object] | None = None
    # 분야로 처음 계획을 짤 때 '지금 가진 자격' 을 먼저 묻는다 (화면 선택지)
    ask_held: bool = True
