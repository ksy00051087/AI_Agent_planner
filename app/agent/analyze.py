"""analyze 노드 (F3005 · F3010) — 의도 분류, 조건 추출, 이전 조건과 병합, 되묻기 판단.

LLM 은 AnalyzeOutput 을 채우기만 한다. 검증 · 병합 · 되묻기 판단은 코드가 한다.
"""

from __future__ import annotations

import json
from datetime import date

from app.events import Emitter

from app.domain.names import strip_suffix

from .deps import AgentDeps
from .prompts import ANALYZE_SYSTEM
from .state import GRADES, AnalyzeOutput, Conditions, PlannerState

NODE = "analyze"
LIST_FIELDS = ("keywords", "targets", "grades", "blocked_dates")


def _valid_date(value: str | None) -> bool:
    if not value:
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _clamp_month_end(value: str | None) -> str | None:
    """'2027-02-29' 처럼 그 달에 없는 날 → 그 달 마지막 날 ('~월까지' 해석에서 자주 생긴다)."""
    import calendar
    import re as _re

    m = _re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value or "")
    if not m:
        return value
    y, mo, d = map(int, m.groups())
    if not 1 <= mo <= 12:
        return value
    last = calendar.monthrange(y, mo)[1]
    return f"{y:04d}-{mo:02d}-{min(d, last):02d}" if d > last else value


def clean_conditions(raw: Conditions, field_options: list[str], message: str | None = None) -> tuple[dict, list[str]]:
    """LLM 이 낸 조건을 검증한다. (조건 dict, 경고 목록)"""
    c = raw.model_dump()
    warnings: list[str] = []
    if message is not None:
        # 등급은 사용자가 그 낱말을 실제로 말했을 때만 (LLM 이 지어낸 등급으로 후보를 거르지 않는다)
        invented = [g for g in c["grades"] if g not in message]
        if invented:
            c["grades"] = [g for g in c["grades"] if g in message]
            warnings.append(f"사용자가 말하지 않은 등급 {invented} 를 뺌")
    for key in ("start_date", "deadline"):
        fixed = _clamp_month_end(c[key])
        if fixed and fixed != c[key]:
            warnings.append(f"{key} {c[key]} 은 없는 날짜라 그 달 마지막 날 {fixed} 로 맞춤")
            c[key] = fixed
        if c[key] and not _valid_date(c[key]):
            warnings.append(f"{key} '{c[key]}' 를 날짜로 읽지 못해 비워 둠")
            c[key] = None
    bad = [d for d in c["blocked_dates"] if not _valid_date(d)]
    if bad:
        warnings.append(f"시험 불가 날짜 {bad} 를 읽지 못해 뺌")
        c["blocked_dates"] = [d for d in c["blocked_dates"] if _valid_date(d)]
    if c["field"] and c["field"] not in field_options:
        # 목록에 없는 분야는 검색어로 돌린다 (LLM 이 만든 분야명으로 검색하지 않는다)
        warnings.append(f"분야 '{c['field']}' 는 출처의 분야 목록에 없어 검색어로 바꿈")
        c["keywords"] = [*c["keywords"], c["field"]]
        c["field"] = None
    # "간호사 국가시험" 처럼 붙여 말한 낱말은 떼어 낸다 (종목명은 "간호사")
    stripped = [strip_suffix(t) for t in c["targets"]]
    if stripped != c["targets"]:
        warnings.append(f"자격명 {c['targets']} → {stripped}")
        c["targets"] = stripped
    # 등급 이름은 자격명이 아니다 ('기사만' → targets ['기사'] 를 grades 로)
    grade_like = [t for t in c["targets"] if t in GRADES]
    if grade_like:
        c["targets"] = [t for t in c["targets"] if t not in GRADES]
        c["grades"] = sorted({*c["grades"], *grade_like}, key=GRADES.index)
        warnings.append(f"자격명 자리에 있던 등급 {grade_like} 를 등급 조건으로 옮김")
    dropped = [k for k in c["keywords"] if k in STOPWORDS]
    if dropped:
        c["keywords"] = [k for k in c["keywords"] if k not in STOPWORDS]
        warnings.append(f"검색어로 쓸 수 없는 낱말 {dropped} 를 뺌")
    for key in ("budget", "prep_weeks", "max_parallel"):
        if c[key] is not None and c[key] <= 0:
            warnings.append(f"{key}={c[key]} 은 쓸 수 없는 값이라 비워 둠")
            c[key] = None
    return c, warnings


def merge_conditions(previous: dict | None, new: dict, new_topic: bool) -> dict:
    """후속 요청은 '바뀐 조건만' 갱신한다 (F3010). 새 주제면 이전 조건을 버린다."""
    if new_topic or not previous:
        return new
    merged = dict(previous)
    for key, value in new.items():
        if key == "clear":
            continue
        if key in ("exclude", "held"):
            merged[key] = sorted({*previous.get(key, []), *value})
        elif key in LIST_FIELDS:
            if value:
                merged[key] = value
        elif value is not None:
            merged[key] = value
    # "기한 없이", "예산 상관없어" — 사용자가 없애 달라고 한 조건만 비운다
    for key in new.get("clear") or []:
        if key in merged:
            merged[key] = [] if isinstance(merged[key], list) else None
    merged["clear"] = []
    return merged


STOPWORDS = {"취업", "자격증", "자격", "계획", "공부", "시험", "플랜", "준비"}


def apply_sector(c: dict, message: str, sectors: dict | None) -> str | None:
    """'공기업 취업' — 분야 목록에 없는 묶음 말이면 분야를 그 묶음으로 둔다. 반환: 적용한 묶음 이름"""
    text = (message or "").replace(" ", "")
    for name, cfg in (sectors or {}).items():
        words = cfg.get("words") or [name]
        if any(w in text for w in words):
            c["field"] = name
            c["keywords"] = [k for k in c.get("keywords") or [] if not any(w in k or k in w for w in words)]
            return name
    return None


def blocked_word(message: str, rules: dict | None) -> str | None:
    """자격 계획 대상이 아닌 요청 (설정 keyword_rules.blocked) — 들어 있으면 그 낱말"""
    text = (message or "").replace(" ", "")
    return next((w for w in (rules or {}).get("blocked") or [] if w in text), None)


def degree_job(message: str, rules: dict | None) -> str | None:
    """정해진 학과를 나와야 하는 직업(의사 · 약사 …, 설정 keyword_rules.degree_required) — 들어 있으면 그 낱말.
    '의사소통' · '제약사' 처럼 직업이 아닌 말(degree_exceptions)은 먼저 지우고 본다."""
    text = (message or "").replace(" ", "")
    for ex in (rules or {}).get("degree_exceptions") or []:
        text = text.replace(ex, "")
    # '치과의사' 가 '의사' 로, '한약사' 가 '약사' 로 잡히지 않게 긴 낱말부터
    jobs = sorted((rules or {}).get("degree_required") or {}, key=len, reverse=True)
    return next((w for w in jobs if w in text), None)


def refine_keywords(keywords: list[str], rules: dict | None) -> tuple[list[str], list[dict]]:
    """검색어 정리 — (새 검색어, 화면에 보여 줄 해석 [{text, as}]).

    꾸밈말('제조' · '관리' …)은 다른 검색어와 함께 오면 뺀다. 혼자 찾으면 다른 분야 자격까지 걸린다
    ('OO 제조' 에서 OO 이 없는 말이면 '제조' 만으로 떡제조기능사 · 신발제조기능사가 나오던 문제).
    꾸밈말만 있으면 그대로 둔다. 붙여 쓴 '식품제조' 는 '식품' 으로 (앞말이 두 글자 이상일 때만 — '떡제조' 는 그대로).
    """
    generic = set((rules or {}).get("generic") or [])
    split = []
    for k in keywords:
        g = next((g for g in generic if k.endswith(g) and len(k) - len(g) >= 2), None)
        split += [k[: -len(g)], g] if g else [k]
    notes = []
    specific = [k for k in split if k not in generic]
    if specific and len(specific) < len(split):
        dropped = list(dict.fromkeys(k for k in split if k in generic))
        notes.append({"text": ", ".join(dropped), "as": "검색어에서 뺌 (혼자 찾으면 다른 분야 자격까지 걸리는 말)"})
        split = specific
    return list(dict.fromkeys(split)), notes


def find_missing(intent: str, c: dict, today: str | None = None) -> list[str]:
    """Tool 을 부르기 전에 되물어야 할 것 (설계 4장)."""
    if today and c.get("deadline") and c["deadline"] < today:
        # 지난 날짜를 다음 해로 고쳐 쓰지 않는다 — 사용자에게 확인한다
        return [f"기한 {c['deadline']} 이 오늘({today})보다 이전입니다. 언제까지인지 다시 알려 주세요"]
    if intent == "plan_create" and not (c.get("job") or c.get("field") or c.get("keywords") or c.get("targets")):
        return ["목표 분야 또는 따고 싶은 자격"]
    if intent == "qual_info" and not (c.get("targets") or c.get("keywords")):
        return ["알고 싶은 자격 이름"]
    if intent == "fact_lookup" and not (c.get("targets") or c.get("keywords")):
        return ["알고 싶은 자격 이름"]
    return []


def make_analyze(deps: AgentDeps, emitter_of):
    """emitter_of(state) -> Emitter. 그래프가 요청마다 Emitter 를 만들어 넘긴다."""

    def analyze(state: PlannerState) -> dict:
        em: Emitter = emitter_of(state)
        em.node_enter(NODE, message=state["message"][:200])
        sel = state.get("selection")
        if sel is not None and sel.get("enrolled") is not None:
            # 학과 질문 패널의 답 — 해석할 것이 없어 LLM 을 부르지 않는다
            job = state.get("degree_pending")
            em.emit("user_selection", NODE, degree_job=job, enrolled=sel["enrolled"])
            if not (sel["enrolled"] and job):
                em.node_exit(NODE, error="DEGREE_REQUIRED")
                return {"error": "DEGREE_REQUIRED", "intent": "chat", "degree_pending": None}
            # 그 학과에 다니면 계획 대신 그 직업의 국가시험 일정을 보여 준다
            c = {**(state.get("conditions") or {}), "targets": [job], "keywords": []}
            em.node_exit(NODE, intent="fact_lookup", conditions={"targets": [job]})
            return {"intent": "fact_lookup", "intent_reason": f"{job} 학과 재학 — 국가시험 일정 조회",
                    "conditions": c, "missing": [], "interpretations": [], "degree_pending": None, "error": None}
        if sel is not None and state.get("conditions"):
            # 화면 선택지로 고른 보유 자격 · 같이 준비할 기본 자격 — 해석할 것이 없어 LLM 을 부르지 않는다
            c = dict(state["conditions"])
            c["held"] = sorted({*c.get("held", []), *(sel.get("held") or [])})
            c["include"] = [x for x in sel.get("include") or [] if x not in c["held"]]
            c["tracks"] = list(sel.get("tracks") or [])
            em.emit("user_selection", NODE, held=c["held"], include=c["include"], tracks=c["tracks"])
            em.node_exit(NODE, intent="plan_create", conditions={k: v for k, v in c.items() if v})
            return {"intent": "plan_create", "intent_reason": "화면에서 보유 자격을 골라 계획 요청",
                    "conditions": c, "missing": find_missing("plan_create", c, state.get("today")),
                    "interpretations": [], "held_checked": True, "error": None}
        word = blocked_word(state["message"], deps.relations().get("keyword_rules"))
        if word:
            # 자격 계획 대상이 아닌 요청 — 해석 · 검색을 하지 않고 거절한다 (비슷한 자격으로 돌려 추천하지 않음)
            em.emit("blocked_request", NODE, word=word)
            em.node_exit(NODE, error="BLOCKED_REQUEST")
            return {"error": "BLOCKED_REQUEST", "intent": "chat"}
        if deps.analyze_llm is None:
            em.error(NODE, "LLM_UNAVAILABLE", where="analyze")
            em.node_exit(NODE, error="LLM_UNAVAILABLE")
            return {"error": "LLM_UNAVAILABLE", "intent": "chat"}

        options = deps.field_options()
        previous = state.get("conditions") or {}
        today = state.get("today") or date.today().isoformat()
        messages = [
            {"role": "system", "content": ANALYZE_SYSTEM.format(
                today=today, field_options=", ".join(options),
                previous=json.dumps(previous, ensure_ascii=False) if previous else "없음")},
            {"role": "user", "content": state["message"]},
        ]
        try:
            out: AnalyzeOutput = deps.analyze_llm(messages)
        except Exception:
            em.error(NODE, "LLM_ERROR", where="analyze")
            em.node_exit(NODE, error="LLM_ERROR")
            return {"error": "LLM_ERROR", "intent": "chat"}

        em.llm_decision(NODE, "intent", out.intent, out.intent_reason)
        rules = deps.relations().get("keyword_rules") or {}
        job = degree_job(state["message"], rules)
        if job and out.intent in ("plan_create", "plan_modify"):
            # 학과를 나와야만 갈 수 있는 직업의 계획 요청 — 검색하지 않고 그 학과에 다니는지 먼저 묻는다.
            # 일정 · 자격 정보만 묻는 요청(fact_lookup · qual_info)은 평소대로 답한다
            major = rules["degree_required"][job]
            em.emit("degree_required", NODE, word=job, major=major)
            em.node_exit(NODE, intent=out.intent, degree_panel=job)
            return {"intent": out.intent, "intent_reason": out.intent_reason, "missing": [], "error": None,
                    "degree_panel": {"job": job, "major": major}, "degree_pending": job}
        for it in out.interpretations:
            em.llm_decision(NODE, "interpretation", {"text": it.text, "as": it.as_value}, "상대 표현을 날짜 · 값으로 해석")

        cleaned, warnings = clean_conditions(out.conditions, options, state["message"])
        interps = [{"text": i.text, "as": i.as_value} for i in out.interpretations]
        cleaned["keywords"], kw_notes = refine_keywords(cleaned.get("keywords") or [], deps.relations().get("keyword_rules"))
        for n in kw_notes:
            em.llm_decision(NODE, "keyword", n, "검색어 정리 (설정 keyword_rules)")
        interps += kw_notes
        sector = apply_sector(cleaned, state["message"], deps.relations().get("sectors"))
        if sector:
            em.llm_decision(NODE, "sector", sector, "설정 sectors 의 낱말이 요청에 있음 — 여러 분야를 묶어 검색")
        for it in interps:   # 말일을 맞춘 경우 화면에도 실제로 쓴 날짜를 보여 준다
            for key in ("deadline", "start_date"):
                if it["as"] == getattr(out.conditions, key) and cleaned.get(key) and cleaned[key] != it["as"]:
                    it["as"] = cleaned[key]
        conditions = merge_conditions(previous, cleaned, out.new_topic)
        missing = find_missing(out.intent, conditions, today)
        em.node_exit(NODE, intent=out.intent, conditions={k: v for k, v in conditions.items() if v},
                     missing=missing, warnings=warnings or None)
        topic = {"held_checked": False} if out.new_topic or not previous else {}
        return {
            **topic,
            "intent": out.intent,
            "intent_reason": out.intent_reason,
            "conditions": conditions,
            "missing": missing,
            "interpretations": interps,
            "warnings": [*state.get("warnings", []), *warnings],
            "error": None,
        }

    return analyze
