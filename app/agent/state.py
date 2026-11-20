"""Agent 상태와 LLM 구조화 출력 형식 (설계 문서 3 · 4장)."""

from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, Field

Intent = Literal["plan_create", "fact_lookup", "qual_info", "plan_modify", "plan_save", "chat"]
Education = Literal["고졸이하", "전문대재학", "전문대졸", "대학재학", "대졸이상", "기타"]
Grade = Literal["기능사", "산업기사", "기사", "기능장", "기술사", "전문자격"]
GRADES = ("기능사", "산업기사", "기사", "기능장", "기술사", "전문자격")


class Conditions(BaseModel):
    """요청에서 뽑는 조건. 말하지 않은 값은 비워 둔다 (임의로 채우지 않는다)."""

    # 기준
    start_date: str | None = Field(None, description="공부를 시작할 수 있는 날 YYYY-MM-DD. 말하지 않았으면 null")
    deadline: str | None = Field(None, description="목표 기한 YYYY-MM-DD. '6월까지' 같은 표현은 날짜로 바꾸고 interpretations 에 남긴다")
    # 목표 직업 — 이 앱의 출발점. 사용자가 되고 싶다 · 일하고 싶다고 한 직업 · 직무 이름 그대로
    job: str | None = Field(None, description="되고 싶은 직업 · 직무 (예: '전기 엔지니어가 되고 싶어' → '전기 엔지니어'). 말하지 않았으면 null")
    # 선호
    field: str | None = Field(None, description="분야. 반드시 제공된 분야 목록 중 하나. 맞는 것이 없으면 null 로 두고 keywords 에")
    keywords: list[str] = Field(default_factory=list, description="자격명 일부나 분야를 나타내는 낱말 (예: 정보처리, 전기, 데이터)")
    targets: list[str] = Field(default_factory=list, description="사용자가 직접 이름을 댄 자격 (예: 정보처리기사, SQLD)")
    grades: list[Grade] = Field(default_factory=list, description="등급만 말했을 때 (예: '기사만' → ['기사']). 자격명은 targets 에")
    exclude: list[str] = Field(default_factory=list, description="빼 달라고 한 자격이나 등급")
    held: list[str] = Field(default_factory=list, description="이미 가지고 있다고 말한 자격 (예: 'SQLD 있어' → ['SQLD'])")
    education: Education | None = Field(None, description="학력. 말하지 않았으면 null")
    # 제약
    budget: int | None = Field(None, description="응시료 총액 상한(원)")
    prep_weeks: int | None = Field(None, description="자격 하나당 공부할 주 수를 직접 말했을 때만")
    max_parallel: int | None = Field(None, description="동시에 공부할 자격 수를 말했을 때만")
    blocked_dates: list[str] = Field(default_factory=list, description="시험을 볼 수 없는 날 YYYY-MM-DD")
    clear: list[Literal["deadline", "start_date", "budget", "prep_weeks", "max_parallel", "exclude", "grades",
                        "targets", "keywords", "field", "job", "blocked_dates"]] = Field(
        default_factory=list, description="직전 조건 중 없애 달라고 한 것 (예: '기한 없이' → ['deadline'])")


class Interpretation(BaseModel):
    text: str = Field(description="사용자가 쓴 표현 그대로 (예: 내년 6월까지)")
    as_value: str = Field(description="바꾼 값 (예: 2027-06-30)")


class AnalyzeOutput(BaseModel):
    """analyze 노드에서 LLM 이 채우는 형식"""

    intent: Intent
    intent_reason: str = Field(description="그 의도로 분류한 이유 한 문장")
    new_topic: bool = Field(description="이전 대화와 상관없는 새 목표면 true (이전 조건을 버린다)")
    conditions: Conditions
    interpretations: list[Interpretation] = Field(default_factory=list)


class RelevanceItem(BaseModel):
    name: str = Field(description="판정한 자격 이름 (입력 목록의 이름 그대로)")
    relevant: bool = Field(description="시험과목이 목표 분야의 직무와 직접 이어지면 true. 판단하기 어려우면 true")
    basis: str = Field(description="판단 근거 — 입력에 있는 시험과목 이름 하나를 그대로 옮긴다")
    reason: str = Field(description="한 문장 이유")


class RelevanceOutput(BaseModel):
    items: list[RelevanceItem] = Field(default_factory=list)


class CareerOutput(BaseModel):
    """직무 풀이 — 직무를 아는 만큼만. 모르는 직무면 known=false 로 두고 지어내지 않는다"""

    known: bool = Field(description="이 직무(또는 약어)가 무엇인지 확실히 알면 true. 짐작이면 false")
    job: str = Field(description="직무의 한국어 풀이 한 문장 (known=false 면 빈 문자열)")
    search_words: list[str] = Field(default_factory=list,
                                    description="이 직무에 실제로 쓰이는 국가자격 · 공인 자격의 정확한 이름 또는 핵심 낱말 (최대 8개). 확실한 것만")
    careernet_seq: int | None = Field(None, description="커리어넷 직업 후보 중 같은 직업의 번호. 같은 직업이 없으면 null")


class PlannerState(TypedDict, total=False):
    session_id: str
    message: str
    today: str                   # 기준일 (테스트에서 고정할 수 있게 상태로 둔다)
    intent: str
    intent_reason: str
    conditions: dict             # 이전 턴과 병합된 Conditions
    missing: list[str]           # 되물어야 할 것
    interpretations: list[dict]
    warnings: list[str]
    steps: list[dict]
    tool_results: dict
    failures: list[dict]
    draft_plan: list[dict]
    excluded: list[dict]
    replan_count: int
    error: str | None            # LLM_UNAVAILABLE 같은 진행 불가 사유
    answer: str
    # 실행 중 값
    run_id: str
    batch_end: int               # 일정을 조회할 후보 수 (재계획 때 늘린다)
    candidates: list[dict]       # 후보 (search_qualifications 결과, 순위순)
    arrangement: dict | None     # domain.arrange 결과
    lookup: list[dict] | None    # fact_lookup 결과
    documents: list[dict]        # qual_info — RAG 검색 결과 (F3022)
    busy_dates: list[str]        # 캘린더에 일정이 있는 날 (F3023)
    route_meta: dict             # 관계 분석 요약: 상위에 포함된 자격 · 다음 단계 · 인기 낮아 뺀 것 · 넘친 것
    books: dict
    replan_log: list[dict]
    needs_replan: str | None     # NEXT_CANDIDATES · RELAX_DEADLINE · LIMIT_REACHED
    ignore_deadline: bool
    fatal: str | None            # 재시도해도 같은 Tool 실패 코드
    # 대화 맥락 (F3010)
    last_plan: list[dict]
    prev_inspection: dict | None  # 직전 실행의 이상 징후 판정 (F3020)
    # 보유 자격 확인 — 분야로 계획을 처음 짤 때 한 번 묻는다 (선택지는 화면이 그린다)
    selection: dict | None       # 화면에서 고른 값 {"held", "include", "tracks"} — 있으면 LLM 없이 조건에 반영
    held_checked: bool           # 이 주제에서 보유 자격을 이미 물었는가
    screen: dict | None          # 목표 점검에서 걸러진 경우 {verdict, reason, suggestions}
    degree_panel: dict | None    # 학과가 필요한 직업 — 그 학과에 다니는지 묻는다 {"job", "major"} (화면이 예 · 아니오를 그린다)
    degree_pending: str | None   # 학과 질문을 보낸 직업 (답을 받으면 비운다)
    degree_lookup: str | None    # 학과 재학 '예' 로 시험 일정을 찾는 직업 (이번 요청만)
    held_panel: dict | None      # 물을 선택지 {"tracks": [{name, examples}], "field": [{chain, items}], "basics": [...]}
