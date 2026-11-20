"""API 요청 · 응답 형식 (F3017). 라우터가 가져다 쓴다."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


# ── 대화 ─────────────────────────────────────────────────────────
class HeldSelection(BaseModel):
    """'지금 가진 자격' 패널에서 고른 값 — 대화로 쓰지 않고 선택지로 보낸다"""
    held: list[str] = Field(default=[], max_length=40, description="이미 가진 자격 이름")
    enrolled: bool | None = Field(None, description="학과 질문 패널의 답 — 그 학과에 다니고 있으면 true (예), 아니면 false (아니오)")
    include: list[str] = Field(default=[], max_length=10, description="같이 준비할 기본 자격 이름")
    tracks: list[str] = Field(default=[], max_length=10, description="가고 싶은 진로 방향(직업군). 비우면 분야 전체")


class ChatIn(BaseModel):
    session_id: str | None = Field(None, max_length=64, description="없으면 새 세션을 만든다")
    message: str = Field(min_length=1, max_length=1000)
    selection: HeldSelection | None = Field(None, description="패널 선택 결과. 있으면 message 는 기록용 요약")


class ChatOut(BaseModel):
    session_id: str
    run_id: str
    answer: str
    intent: str | None = None
    conditions: dict[str, Any] | None = None
    draft_plan: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    books: dict[str, Any] = {}
    documents: list[dict[str, Any]] = Field(default=[], description="자격 정보 문서 검색 결과 (F3022, 근거 원문 · 출처)")
    replans: list[dict[str, Any]] = []
    needs_replan: str | None = None
    failures: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = Field(default=[], description="실행 단계 · Tool 호출 이력 (실행 순서)")
    prev_inspection: dict[str, Any] | None = Field(None, description="직전 요청의 이상 징후 판정 (F3020)")
    lookup: list[dict[str, Any]] | None = Field(None, description="사실 조회 결과 (자격별 회차 · 응시료 · 합격률)")
    view: dict[str, Any] = Field(default={}, description="화면용 구조화 요약 (해석 · 다음 후보 · 응시료 합계 · 해당 없음 자격 등)")


# ── 계획 ─────────────────────────────────────────────────────────
class PlanIn(BaseModel):
    qual_name: str = Field(min_length=1, max_length=100)
    plan_date: date = Field(description="시험일")
    start_time: str | None = Field(None, pattern=HHMM)
    end_time: str | None = Field(None, pattern=HHMM)
    qual_id: str | None = None
    stage: str | None = None
    round_name: str | None = None
    practical_date: date | None = None
    registration_end: date | None = None
    study_start: date | None = None
    estimated: bool = False
    source: str | None = None
    memo: str | None = Field(None, max_length=500)
    group_id: str | None = None


class PlanUpdate(BaseModel):
    qual_name: str | None = Field(None, min_length=1, max_length=100)
    plan_date: date | None = None
    start_time: str | None = Field(None, pattern=HHMM)
    end_time: str | None = Field(None, pattern=HHMM)
    stage: str | None = None
    round_name: str | None = None
    practical_date: date | None = None
    registration_end: date | None = None
    study_start: date | None = None
    memo: str | None = Field(None, max_length=500)


class PlanOut(PlanIn):
    plan_id: int
    created_at: str
    updated_at: str


class PlanSaved(BaseModel):
    plan: PlanOut
    overlaps: list[PlanOut] = Field(description="같은 날짜에 시간이 겹치는 기존 계획 (저장은 막지 않는다)")
    message: str


class PlanBatchIn(BaseModel):
    items: list[PlanIn] = Field(min_length=1, max_length=20)


# ── 실행 로그 ─────────────────────────────────────────────────────
class LogSession(BaseModel):
    session_id: str
    runs: int
    events: int
    started_at: str
    last_at: str
    replans: int
    errors: int
    tool_failures: int


class LogEvent(BaseModel):
    session_id: str
    run_id: str
    seq: int
    ts: str
    type: str
    node: str | None = None

    model_config = {"extra": "allow"}


class LogWarning(BaseModel):
    type: str = Field(description="REPEATED_CALL · EXCESSIVE_REPLAN · UNPLANNED_CALL")
    detail: str
    evidence: list[int] = Field(description="근거 이벤트 seq")


class LogInspection(BaseModel):
    run_id: str
    session_id: str
    verdict: str = Field(description="정상 · 이상 · 판정 불가 (규칙 판정, LLM 미사용)")
    warnings: list[LogWarning]
    reason: str | None = Field(None, description="판정 불가일 때 이유")
    counts: dict[str, int]
    diagnosis: str | None = Field(None, description="이상일 때만 LLM 이 쓴 원인 진단 (판정과 별도)")
    diagnosis_status: str | None = Field(None, description="null(대상 아님) · pending · ok · failed")
    created_at: str
