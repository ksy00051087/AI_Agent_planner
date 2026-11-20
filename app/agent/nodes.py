"""plan · execute · judge · replan · enrich 노드 (F3006 ~ F3009).

LLM 을 쓰지 않는다. analyze 가 정한 의도 · 조건으로 Tool 순서를 정하고, Tool 결과를 domain 함수로 판정한다.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from app.domain.arrange import GRADE_ORDER, arrange
from app.domain.intro import build_intro
from app.domain.names import name_matches
from app.domain.relevance import apply_relevance
from app.domain.relations import co_mentions, filter_by_tracks, held_options, in_track, select_route, track_group, track_options

from .deps import AgentDeps
from .state import PlannerState

PLAN_INTENTS = ("plan_create", "plan_modify")
FATAL = {"INVALID_KEY", "QUOTA_EXCEEDED", "UPSTREAM_ERROR"}
BATCH = 8                 # 한 번에 일정을 조회할 후보 수 (루트 전체)
LOOKUP_BATCH = 3
BOOKS_FOR = 4             # 교재를 붙일 배치 항목 수
PLAN_SIZE = 4             # 사용자가 자격을 지정하지 않았을 때 한 계획에 넣는 자격 수
REPLANNABLE = {"NOT_ENOUGH_TIME", "DEADLINE_EXCEEDED", "DATE_CONFLICT", "REGISTRATION_CLOSED", "BUDGET_EXCEEDED", "STUDY_OVERLAP"}


def _call(deps: AgentDeps, em, node: str, cache: dict, tool: str, **args) -> dict:
    """Tool 호출 + 이벤트. 같은 인자는 다시 부르지 않는다 (재계획 때 재사용, F3009)."""
    key = f"{tool}:{sorted(args.items())}"
    if key in cache:
        return cache[key]
    em.tool_call(node, tool, args)
    t0 = time.perf_counter()
    result = deps.run_tool(tool, **args)
    data = result.get("data") or {}
    count = len(data.get("items") or data.get("rounds") or []) if result.get("ok") else None
    em.tool_result(node, tool, result, int((time.perf_counter() - t0) * 1000), count)
    cache[key] = result
    return result


def _prefetch(deps: AgentDeps, em, node: str, cache: dict, tool: str, arg_list: list[dict]) -> None:
    """캐시에 없는 호출을 동시에 보낸다. 이벤트는 호출 순서대로, 각자 실제 소요 시간으로 남긴다."""
    todo = [a for a in arg_list if f"{tool}:{sorted(a.items())}" not in cache]
    if len(todo) < 2:
        return
    for a in todo:
        em.tool_call(node, tool, a)

    def run(a):
        t0 = time.perf_counter()
        try:
            r = deps.run_tool(tool, **a)
        except Exception:
            r = {"ok": False, "error": {"code": "UPSTREAM_ERROR", "message": "Tool 실행 중 오류입니다."}}
        return a, r, int((time.perf_counter() - t0) * 1000)

    with ThreadPoolExecutor(max_workers=min(6, len(todo))) as pool:
        for a, r, ms in pool.map(run, todo):
            data = r.get("data") or {}
            count = len(data.get("items") or data.get("rounds") or []) if r.get("ok") else None
            em.tool_result(node, tool, r, ms, count)
            cache[f"{tool}:{sorted(a.items())}"] = r


# ── plan (F3006) ─────────────────────────────────────────────────
def make_plan(deps: AgentDeps, emitter_of):
    def plan(state: PlannerState) -> dict:
        em = emitter_of(state)
        em.node_enter("plan", intent=state.get("intent"))
        c = state.get("conditions") or {}
        if state.get("intent") == "qual_info":
            # 문서로만 있는 자격 정보 → RAG 검색 (F3022). 자격명을 알면 자격마다, 모르면 질문 그대로
            names = c.get("targets") or [None]
            steps = [{"tool": "search_documents",
                      "args": {"query": state["message"], **({"qualification_name": n} if n else {}), "limit": 3},
                      "why": f"자격 정보 문서 검색{f' — {n}' if n else ''}"} for n in names[:3]]
            em.node_exit("plan", steps=[{"tool": s["tool"], "why": s["why"]} for s in steps])
            return {"steps": steps, "batch_end": 0}
        searches = []
        for t in c.get("targets") or []:
            searches.append({"tool": "search_qualifications", "args": {"keyword": t, "limit": 20}, "why": f"지정한 자격 '{t}'"})
        sector = (deps.relations().get("sectors") or {}).get(c.get("field") or "")
        if sector:
            for f in sector.get("fields") or []:
                searches.append({"tool": "search_qualifications", "args": {"field": f, "limit": 100},
                                 "why": f"{c['field']} — 분야 '{f}'"})
        elif c.get("field"):
            searches.append({"tool": "search_qualifications", "args": {"field": c["field"], "limit": 100},
                             "why": f"분야 '{c['field']}'"})
            for f in (deps.relations().get("field_groups") or {}).get(c["field"], []):
                searches.append({"tool": "search_qualifications", "args": {"field": f, "limit": 100},
                                 "why": f"가까운 분야 '{f}' (보완 자격)"})
        for k in c.get("keywords") or []:
            searches.append({"tool": "search_qualifications", "args": {"keyword": k, "limit": 50}, "why": f"검색어 '{k}'"})
        basics = {b["name"]: b for b in deps.relations().get("basics") or []}
        for name in c.get("include") or []:
            word = (basics.get(name) or {}).get("search", name)
            if word:   # 출처에 일정이 없는 기본 자격(search null)은 조회하지 않고 안내만 한다
                searches.append({"tool": "search_qualifications", "args": {"keyword": word, "limit": 5},
                                 "why": f"같이 준비할 기본 자격 '{name}'"})
        lookup = state.get("intent") == "fact_lookup"
        steps = [*searches,
                 {"tool": "get_exam_schedule", "for_each": "후보", "limit": LOOKUP_BATCH if lookup else BATCH,
                  "why": "접수 · 시험일 · 응시료 · 합격률 확인"}]
        if not lookup:
            steps.append({"tool": "list_schedule", "args": {}, "why": "캘린더에 이미 잡힌 일정 확인 (시험일 충돌)"})
            steps.append({"tool": "search_books", "for_each": "배치된 자격", "limit": BOOKS_FOR, "why": "교재"})
        em.node_exit("plan", steps=[{"tool": s["tool"], "why": s["why"]} for s in steps])
        return {"steps": steps, "batch_end": LOOKUP_BATCH if lookup else BATCH}

    return plan


# ── execute (F3007) ──────────────────────────────────────────────
def _keep(q: dict, c: dict) -> bool:
    name, grade = q.get("name") or "", q.get("grade") or ""
    targets = c.get("targets") or []
    if any(name_matches(t, name) for t in targets):
        return True
    if any(x and (x in name or x == grade) for x in c.get("exclude") or []):
        return False
    grades = c.get("grades") or []
    # 등급 체계가 없는 자격(공무원 · 한국사 · 면허 등)은 등급 조건으로 빼지 않는다
    return not grades or grade in grades or grade not in (*LADDER, *EXPERT)


LADDER = ("기능사", "산업기사", "기사")       # 자동으로 짜는 흐름에 넣는 등급
EXPERT = ("기능장", "기술사")                # 실무 경력이 필요 — 사용자가 원할 때만


def stem_of(name: str, grade: str | None) -> str:
    """같은 계열 묶기: 이름에서 등급을 뗀다 (전기기능사 · 전기산업기사 · 전기기사 → 전기)."""
    if grade and grade in (*LADDER, *EXPERT) and name.endswith(grade):
        return name[: -len(grade)]
    return name


def _acquired(q: dict) -> int:
    return ((q.get("popularity") or {}).get("acquired")) or 0


def _rank(cands: list[dict], c: dict, rel: dict) -> tuple[list[dict], dict]:
    """루트 선정과 관계 분석 (domain/relations.py). 반환 (순서대로 정렬한 후보, 관계 분석 요약)."""
    related = {c.get("field"), *(rel.get("field_groups", {}).get(c.get("field") or "", []))} - {None}
    group = track_group(rel.get("tracks") or [], c.get("field"), cands)
    all_cands = cands
    basics = [b["name"] for b in rel.get("basics") or []]
    keep_always = lambda q: (any(name_matches(t, q["name"]) for t in c.get("targets") or [])  # noqa: E731
                             or any(name_matches(i, q["name"]) for i in c.get("include") or []))
    sector = (rel.get("sectors") or {}).get(c.get("field") or "")
    if sector and group:
        # 묶음(공기업)은 직렬에 걸리는 자격만 — 분야 전체 인기순이면 지게차 · 굴착기 운전이 기계직 1위가 된다
        cands = [q for q in cands if keep_always(q) or any(in_track(i, q["name"]) for i in group.get("items", []))]
        all_cands = cands
    picked, tracks_used = filter_by_tracks([q for q in cands if not keep_always(q)], group, c.get("tracks") or [])
    if tracks_used:   # 고른 진로(직업군)의 자격만 루트로. 지정 · 같이 준비하기로 고른 자격은 그대로
        cands = picked + [q for q in cands if keep_always(q)]
    out = select_route(cands, c, ladders=rel.get("ladders"), expert=set(rel.get("expert") or []),
                       related_fields=related)
    ranked, extras = out["route"], out["extras"]
    targets, keywords = c.get("targets") or [], c.get("keywords") or []
    if targets:
        # 자격을 지정했으면 그 자격(과 말한 낱말로 찾은 것)만 계획한다. 분야 검색 결과는 계열 정보로만 쓴다
        said = lambda q: any(name_matches(t, q["name"]) for t in targets) or any(k and k in q["name"] for k in keywords)  # noqa: E731
        include = c.get("include") or []
        ranked = [q for q in ranked if said(q) or any(name_matches(i, q["name"]) for i in include)]
        extras = []
    hints = rel.get("prep_weeks") or {}
    def mine(q):
        return [i["name"] for i in (group or {}).get("items", []) if i["name"] in tracks_used and in_track(i, q["name"])]

    def reason(q):
        r = q.get("route_reason")
        return f"고른 진로({', '.join(mine(q))}) · {r}" if mine(q) and r else r

    mark = lambda q: {**q, "path_reason": reason(q), "track": ", ".join(mine(q)) or None, "prep_hint": hints.get(q["name"]),  # noqa: E731
                      "basic": any(name_matches(b, q["name"]) for b in basics)}   # 기본 자격 — 다른 공부와 병행
    meta = {k: out[k] for k in ("superseded", "next_steps", "not_popular", "overflow", "held")}
    meta["route_len"] = len(ranked)
    meta["options"] = held_options(cands, out, rel.get("ladders"))
    meta["tracks"] = track_options(group, all_cands, [q["name"] for q in out["route"]])
    meta["tracks_used"] = tracks_used
    meta["sector_note"] = (sector or {}).get("note")
    # 고른 진로 · 분야에 있지만 최근 합격자가 매우 적어 기본 계획에서 뺀 국가자격 — 숫자를 밝히고 원하면 추가
    meta["low_popular"] = [{"name": q["name"], "basis": (q.get("popularity") or {}).get("basis") or "최근 합격자 통계 없음"}
                           for q in out["extras"] if not (tracks_used and not mine(q))][:6]
    return [mark(q) for q in ranked] + [mark(q) for q in extras], meta


RELEVANCE_SYSTEM = """너는 자격증 관련성 판정기다. 사용자가 가려는 분야와, 자격 목록(각 자격의 공식 시험과목, 큐넷 취득방법)을 받는다.
자격 하나마다 항목을 정확히 하나 만든다 (과목마다 만들지 않는다). name 은 목록의 [자격] 이름을 그대로 쓴다.
그 자격의 시험과목 전체가 가려는 분야의 직무와 직접 이어지면 relevant=true, 주로 다른 분야(제조 · 기술 등)의 직무라면 false.
- basis 에는 판단의 근거가 된 시험과목 이름 하나를 입력에서 그대로 옮긴다 (지어내지 않는다).
- 판단하기 어려우면 relevant=true 로 둔다 (근거 없이 빼지 않는다).
- 합격자 수 · 인기는 판단하지 않는다. 과목 내용만 본다."""
_relevance_cache: dict[tuple[str, str], dict] = {}


def _goal(c: dict) -> str | None:
    words = [c.get("job"), c.get("field"), *(c.get("keywords") or [])]
    return " · ".join(w for w in words if w) or None


def _check_relevance(deps: AgentDeps, em, c: dict, pool: list[dict], rel: dict) -> tuple[list[dict], list[dict]]:
    """분야 · 낱말로 모은 후보 중 시험과목이 목표와 이어지지 않는 것을 뺀다 (RAG 문서 + LLM 판정, 코드 검증).
    자격을 직접 지정했거나 묶음(공기업 — 직렬로 거른다)이면 판정하지 않는다. LLM 이 없거나 실패하면 그대로."""
    goal = _goal(c)
    if (not goal or c.get("targets") or deps.relevance_llm is None
            or (rel.get("sectors") or {}).get(c.get("field") or "")):
        return pool, []
    keep_always = [*(c.get("include") or []), *(c.get("held") or [])]
    # 사용자가 직접 고른 진로(직업군)의 자격은 판정으로 빼지 않는다 — 판정은 '아무것도 안 골랐을 때의 기본 루트' 용
    group = track_group(rel.get("tracks") or [], c.get("field"), pool)
    chosen = [i for i in (group or {}).get("items", []) if i["name"] in (c.get("tracks") or [])]
    judge = [q for q in pool if not any(name_matches(k, q["name"]) for k in keep_always)
             and not any(in_track(i, q["name"]) for i in chosen)]
    subjects = deps.subjects_of([q["name"] for q in judge])
    asked = sorted(subjects)
    if not asked:
        return pool, []
    # (목표, 자격) 마다 판정을 저장 — 같은 질문에 늘 같은 답 (LLM 은 temperature 0 이어도 조금 흔들린다)
    new = [n for n in asked if (goal, n) not in _relevance_cache]
    if new:
        listing = "\n".join(f"{i}. [자격] {n} — 시험과목: {subjects[n]}" for i, n in enumerate(new, 1))
        messages = [{"role": "system", "content": RELEVANCE_SYSTEM},
                    {"role": "user", "content": f"가려는 분야: {goal}\n\n자격과 공식 시험과목:\n{listing}"}]
        try:
            items = [i.model_dump() for i in deps.relevance_llm(messages).items]
        except Exception:
            em.error("execute", "LLM_ERROR", where="relevance")
            return pool, []
        for it in items:
            if it.get("name") in new:          # 목록에 없는 이름(과목명 등)으로 온 판정은 버린다
                _relevance_cache[(goal, it["name"])] = it
    verdicts = [_relevance_cache[(goal, n)] for n in asked if (goal, n) in _relevance_cache]
    kept, dropped = apply_relevance(pool, subjects, verdicts)
    em.llm_decision("execute", "relevance", {"goal": goal, "judged": len(asked), "dropped": [d["name"] for d in dropped]},
                    "RAG 문서의 공식 시험과목으로 목표와의 관련성 판정 (근거 과목이 문서에 있을 때만 뺌)")
    return kept, dropped


CAREER_SYSTEM = """너는 직무 풀이기다. 사용자가 가고 싶은 직업 · 직무(약어일 수 있다)를 받아 무엇인지 풀고,
그 직무에서 실제로 요구되거나 흔히 따는 자격의 이름을 search_words 에 넣는다.
- 확실히 아는 직무만 known=true. 약어는 한국 취업 맥락(예: VCPM = 벤처프로젝트매니저)에서 뜻이 분명할 때만 푼다. 모르면 known=false, 지어내지 않는다.
- search_words 는 실제로 존재하는 자격의 이름이나 핵심 낱말만 (예: 정보처리, 사회조사, 컨벤션, 경영지도사). 불확실하면 넣지 않는다.
- 자격이 거의 없는 직무면 빈 목록. 일정 · 합격률 같은 사실은 말하지 않는다.
- careernet_seq: 아래 '커리어넷 직업 후보' 중 사용자의 직업과 같은 직업(같은 일을 하는 직업)이 있으면 그 번호. 
  이름이 비슷해도 하는 일이 다르면 고르지 않는다 (예: 조리사 ≠ 영양사, 건축 설계사 ≠ 토목공학기술자). 없으면 null."""
_career_cache: dict[str, dict] = {}
_evidence_cache: dict[str, dict] = {}
_profile_cache: dict[int, dict | None] = {}


def _expand_career(deps: AgentDeps, em, cache: dict, c: dict, found: dict) -> dict | None:
    """목표 직업 → 그 직업의 자격을 찾아 후보에 더한다.
    1) 커리어넷(공식): 후보 직업 중 같은 직업을 LLM 이 '목록 안에서만' 고르고, 상세의 '관련 자격' 원문에 나온 자격명을 쓴다
    2) 커리어넷에 없거나 관련 자격이 없으면: LLM 풀이의 검색어 + 네이버 글에 함께 나온 자격 (비공식)
    어느 쪽이든 실제 출처(큐넷 · 공공데이터)에서 확인된 자격만 후보가 된다."""
    words = [w for w in c.get("keywords") or [] if w]
    if deps.career_llm is None and deps.job_evidence is None and deps.job_profile is None:
        return None
    if c.get("job"):
        goal = c["job"]
    elif words and not c.get("targets") and not c.get("field"):
        goal = " ".join(words)
    else:
        return None
    if goal not in _career_cache:
        cands = []
        if deps.job_candidates is not None:
            try:
                cands = deps.job_candidates(goal) or []
            except Exception:
                em.error("execute", "UPSTREAM_ERROR", where="careernet")
        if deps.career_llm is None:
            _career_cache[goal] = {"known": False, "job": "", "words": [], "seq": None}
        else:
            listing = "\n".join(f"{x['seq']}. {x['job_nm']} (관련: {x['rel_job_nm'] or '-'})" for x in cands) or "(없음)"
            msgs = [{"role": "system", "content": CAREER_SYSTEM},
                    {"role": "user", "content": f"직업 · 직무: {goal}\n\n커리어넷 직업 후보:\n{listing}"}]
            try:
                o = deps.career_llm(msgs)
            except Exception:
                em.error("execute", "LLM_ERROR", where="career")
                return None
            seq = getattr(o, "careernet_seq", None)
            if seq not in {x["seq"] for x in cands}:          # 목록 밖 번호는 버린다
                seq = None
            _career_cache[goal] = {"known": bool(o.known) or seq is not None, "job": o.job if o.known else "",
                                   "words": [w for w in o.search_words if w and len(w) >= 2][:8] if o.known else [],
                                   "seq": seq}
    info = dict(_career_cache[goal])

    official = None
    if info.get("seq") is not None and deps.job_profile is not None:
        if info["seq"] not in _profile_cache:
            try:
                _profile_cache[info["seq"]] = deps.job_profile(info["seq"])
            except Exception:
                _profile_cache[info["seq"]] = None
                em.error("execute", "UPSTREAM_ERROR", where="careernet_profile")
        official = _profile_cache[info["seq"]]

    # 공식 관련 자격이 있으면 그것만. 없을 때만 LLM 검색어 + 네이버 글(비공식)
    ev = {}
    if official and official.get("cert_names"):
        search = list(official["cert_names"])
        from_web = []
    else:
        if deps.job_evidence is not None:
            try:
                ev = _evidence_cache.setdefault(goal, deps.job_evidence(goal))
            except Exception:
                em.error("execute", "UPSTREAM_ERROR", where="job_evidence")
        from_web = [m["name"] for m in ev.get("mentions") or []]
        search = [*info["words"], *(n for n in from_web if n not in info["words"])]
    hit, missing = [], []
    for w in search:
        r = _call(deps, em, "execute", cache, "search_qualifications", keyword=w, limit=10)
        items = r["data"]["items"] if r["ok"] else []
        for q in items:
            found.setdefault(q["qual_id"], q)
        (hit if items else missing).append(w)
    info["web"] = {"names": [m for m in from_web if m in hit], "docs": ev.get("docs", 0), "refs": ev.get("refs") or [],
                   "counts": {m["name"]: m["docs"] for m in ev.get("mentions") or []}}
    info["official"] = official
    em.llm_decision("execute", "career", {"goal": goal, "careernet": official and official["name"], "known": info["known"],
                                          "found": hit, "not_in_sources": missing, "web_names": from_web},
                    "직업 → 커리어넷 공식 직업정보(관련 자격 원문) 우선, 없으면 LLM 풀이 · 네이버 글. 출처에서 확인된 자격만 후보")
    info.update(words=hit, missing=missing, name=goal)
    return info


def _ask_held(deps: AgentDeps, state: PlannerState, c: dict, candidates: list[dict]) -> bool:
    """분야 · 낱말로 처음 계획을 짤 때만 묻는다. 자격을 직접 지정했거나 이미 물었으면 묻지 않는다."""
    return (deps.ask_held and state.get("intent") == "plan_create" and not state.get("held_checked")
            and not c.get("targets") and bool(candidates))


def make_execute(deps: AgentDeps, emitter_of):
    def execute(state: PlannerState) -> dict:
        em = emitter_of(state)
        em.node_enter("execute", batch_end=state.get("batch_end"))
        cache = dict(state.get("tool_results") or {})
        failures = list(state.get("failures") or [])
        c = state.get("conditions") or {}

        if state.get("intent") == "qual_info":
            documents = []
            for step in state.get("steps") or []:
                r = _call(deps, em, "execute", cache, step["tool"], **step["args"])
                if r["ok"]:
                    documents.append({"qualification_name": step["args"].get("qualification_name"), **r["data"]})
                else:
                    failures.append({"tool": step["tool"], "args": step["args"], **r["error"]})
            fatal = next((f["code"] for f in failures if f["code"] in FATAL), None)
            em.node_exit("execute", documents=sum(len(d["items"]) for d in documents), failures=len(failures))
            return {"tool_results": cache, "failures": failures, "documents": documents, "fatal": fatal}

        found: dict[str, dict] = {}
        for step in state.get("steps") or []:
            if step["tool"] != "search_qualifications":
                continue
            r = _call(deps, em, "execute", cache, step["tool"], **step["args"])
            if not r["ok"]:
                failures.append({"tool": step["tool"], "args": step["args"], **r["error"]})
                if r["error"]["code"] in FATAL:
                    em.node_exit("execute", fatal=r["error"]["code"])
                    return {"tool_results": cache, "failures": failures, "fatal": r["error"]["code"]}
                continue
            for q in r["data"]["items"]:
                found.setdefault(q["qual_id"], q)

        rel = deps.relations()
        career = _expand_career(deps, em, cache, c, found)
        pool = [q for q in found.values() if _keep(q, c)]
        full_pool = pool
        pool, irrelevant = _check_relevance(deps, em, c, pool, rel)
        candidates, route_meta = _rank(pool, c, rel)
        route_meta["irrelevant"] = irrelevant
        route_meta["career"] = career
        if irrelevant:
            # 진로 선택지의 예시는 판정 전 전체 후보로 — 고르면 그 갈래 자격은 되살린다 (위 _check_relevance)
            group = track_group(rel.get("tracks") or [], c.get("field"), full_pool)
            route_meta["tracks"] = track_options(group, full_pool, [q["name"] for q in candidates])
        if _ask_held(deps, state, c, candidates):
            # 계획 전에 '지금 가진 자격' 을 묻는다 — 일정은 고른 뒤에 조회한다
            panel = {"tracks": route_meta.pop("tracks"), "field": route_meta.pop("options"), "basics": [
                {"name": b["name"], "note": b.get("note"), "plannable": bool(b.get("search"))}
                for b in rel.get("basics") or []], "held": c.get("held") or []}
            em.node_exit("execute", candidates=len(candidates), ask_held=sum(len(g["items"]) for g in panel["field"]))
            return {"tool_results": cache, "failures": failures, "candidates": candidates, "fatal": None,
                    "route_meta": route_meta, "held_panel": panel, "held_checked": True}
        route_meta.pop("options", None)
        route_meta.pop("tracks", None)
        # 첫 실행은 루트만 조회한다. 재계획(NEXT_CANDIDATES)이면 루트 밖 대안까지 넓힌다
        batch_end = state.get("batch_end", BATCH)
        if not state.get("replan_count"):
            cap = BATCH + len(c.get("include") or [])     # 고른 기본 자격은 루트 크기와 따로 센다
            batch_end = min(cap, route_meta["route_len"]) or min(BATCH, len(candidates))
        batch = candidates[:batch_end]
        _prefetch(deps, em, "execute", cache, "get_exam_schedule", [{"qual_id": q["qual_id"]} for q in batch])
        for q in batch:
            r = _call(deps, em, "execute", cache, "get_exam_schedule", qual_id=q["qual_id"])
            if not r["ok"]:
                if not any(f.get("args", {}).get("qual_id") == q["qual_id"] for f in failures):
                    failures.append({"tool": "get_exam_schedule", "args": {"qual_id": q["qual_id"]},
                                     "name": q["name"], **r["error"]})
                # 키 · 한도 문제는 다른 자격도 똑같이 실패한다 → 멈춘다. 일시적 응답 실패는 그 자격만 빼고 진행
                if r["error"]["code"] in FATAL - {"UPSTREAM_ERROR"}:
                    em.node_exit("execute", fatal=r["error"]["code"])
                    return {"tool_results": cache, "failures": failures, "candidates": candidates,
                            "fatal": r["error"]["code"]}
        results = [_call(deps, em, "execute", cache, "get_exam_schedule", qual_id=q["qual_id"]) for q in batch]
        # 루트 자격이 '시험일 없음 · 회차 없음' 으로 빠지면 그 수만큼 다음 후보(루트 밖 대안)로 한 번 채운다
        missing = sum(1 for x in results if not x["ok"] and x["error"]["code"] in ("NO_EXAM_DATE", "NO_DATA"))
        if missing and not state.get("replan_count") and batch_end < len(candidates):
            extra = candidates[batch_end:batch_end + missing]
            _prefetch(deps, em, "execute", cache, "get_exam_schedule", [{"qual_id": q["qual_id"]} for q in extra])
            for q in extra:
                r = _call(deps, em, "execute", cache, "get_exam_schedule", qual_id=q["qual_id"])
                if not r["ok"] and not any(f.get("args", {}).get("qual_id") == q["qual_id"] for f in failures):
                    failures.append({"tool": "get_exam_schedule", "args": {"qual_id": q["qual_id"]},
                                     "name": q["name"], **r["error"]})
            batch_end += len(extra)
        if batch and all(not x["ok"] and x["error"]["code"] == "UPSTREAM_ERROR" for x in results):
            em.node_exit("execute", fatal="UPSTREAM_ERROR")
            return {"tool_results": cache, "failures": failures, "candidates": candidates, "fatal": "UPSTREAM_ERROR"}
        busy: list[str] = list(state.get("busy_dates") or [])
        if any(st["tool"] == "list_schedule" for st in state.get("steps") or []) and not busy:
            r = _call(deps, em, "execute", cache, "list_schedule")
            if r["ok"]:
                busy = r["data"]["busy_dates"]
            elif r["error"]["code"] != "NOT_CONFIGURED":   # 캘린더가 없으면 조용히 넘어간다
                failures.append({"tool": "list_schedule", "args": {}, **r["error"]})
        em.node_exit("execute", candidates=len(candidates), scheduled=min(len(candidates), state.get("batch_end", BATCH)),
                     failures=len(failures))
        return {"tool_results": cache, "failures": failures, "candidates": candidates, "fatal": None, "busy_dates": busy,
                "route_meta": route_meta, "batch_end": batch_end}

    return execute


# ── judge (F3008) ────────────────────────────────────────────────
def _schedules(state: PlannerState) -> list[dict]:
    cache = state.get("tool_results") or {}
    out = []
    for q in (state.get("candidates") or [])[: state.get("batch_end", BATCH)]:
        r = cache.get(f"get_exam_schedule:{sorted({'qual_id': q['qual_id']}.items())}")
        if r and r["ok"]:
            d = r["data"]
            out.append({"qual_id": q["qual_id"], "name": d["name"], "grade": d.get("grade") or q.get("grade"),
                        "path_rank": q.get("path_rank"), "path_reason": q.get("path_reason"), "chain": q.get("chain"),
                        "ladder": q.get("ladder"), "prep_hint": q.get("prep_hint"), "basic": q.get("basic"),
                        "track": q.get("track"), "popularity": q.get("popularity"),
                        "source": d.get("source"), "fee": d.get("fee"), "pass_rate": d.get("pass_rate"),
                        "rounds": d["rounds"], "organization": d.get("organization"),
                        "exam_info": d.get("exam_info")})
    return out


def make_judge(deps: AgentDeps, emitter_of):
    def judge(state: PlannerState) -> dict:
        em = emitter_of(state)
        em.node_enter("judge")
        today = date.fromisoformat(state.get("today") or date.today().isoformat())
        scheds = _schedules(state)
        if state.get("intent") == "fact_lookup":
            em.node_exit("judge", lookup=len(scheds))
            return {"lookup": scheds, "needs_replan": None}

        c = state.get("conditions") or {}
        precedes = deps.precedes([x["name"] for x in scheds])
        result = arrange(scheds, c, today, ignore_deadline=bool(state.get("ignore_deadline")),
                         precedes=precedes, max_items=None,  # 루트 크기는 select_route 가 정한다 (최대 8)
                         busy_dates=set(state.get("busy_dates") or []))
        excluded = list(result["excluded"])
        meta = state.get("route_meta") or {}
        # 자격마다 소개 한 줄 — 무엇을 공부하나 · 이럴 때 유리 (공식 시험과목 먼저, 없으면 서비스 안내)
        by_id = {x["qual_id"]: x for x in scheds}
        nexts = {n["after"]: n["name"] for n in meta.get("next_steps") or []}
        rel_cfg = deps.relations()
        intros = rel_cfg.get("intros") or {}
        meta = {**meta, "co_mentions": co_mentions([p["name"] for p in result["placed"]], rel_cfg.get("co_mention") or {})}
        for p in result["placed"]:
            src = by_id.get(p["qual_id"]) or {}
            lad = src.get("ladder") or []
            up = lad[lad.index(p["name"]) + 1] if p["name"] in lad and lad.index(p["name"]) + 1 < len(lad) else None
            p["intro"] = build_intro(p["name"], src.get("exam_info"), intros, track=src.get("track"),
                                     popularity=((src.get("popularity") or {}).get("basis")),
                                     next_step=nexts.get(p["name"]) or up)
        for sp in meta.get("superseded") or []:
            excluded.append({"qual_id": sp.get("qual_id"), "name": sp["name"], "reason_code": "SUPERSEDED",
                             "detail": f"상위 자격 {sp['by']} 를 따면 따로 딸 필요 없음 (같은 계열)"})
        for f in state.get("failures") or []:
            if f["tool"] == "get_exam_schedule":
                excluded.append({"qual_id": f["args"]["qual_id"], "name": f.get("name"), "reason_code": f["code"],
                                 "detail": f["message"]})

        # 재계획 판단 — 충족하는 배치가 없거나, 사용자가 지정한 자격이 판정으로 빠졌을 때만
        targets = c.get("targets") or []
        target_dropped = [e for e in result["excluded"]
                          if e["reason_code"] in REPLANNABLE and any(t in (e["name"] or "") for t in targets)]
        need = None
        if not result["placed"] or target_dropped:
            more = len(state.get("candidates") or []) > state.get("batch_end", BATCH)
            # 기한이 원인이면 먼저 '기한을 넘기는 가장 빠른 대안' 을 보여 준다 (후보만 늘려서는 해결되지 않는다)
            if c.get("deadline") and not state.get("ignore_deadline"):
                need = "RELAX_DEADLINE"
            elif more and not targets:
                need = "NEXT_CANDIDATES"
        stuck = not result["placed"] or bool(target_dropped)
        if stuck and state.get("replan_count", 0) >= deps.replan_limit:
            need = "LIMIT_REACHED"          # 상한 — 더 재계획하지 않고 멈춘다 (NF3004)
        elif stuck and need is None and state.get("replan_count", 0) > 0:
            need = "EXHAUSTED"              # 상한 전이지만 바꿀 수 있는 대안이 더 없다
        em.node_exit("judge", placed=[p["name"] for p in result["placed"]],
                     excluded=[(e["name"], e["reason_code"]) for e in excluded], needs_replan=need)
        return {"arrangement": {**result, "excluded": excluded}, "needs_replan": need, "route_meta": meta}

    return judge


# ── replan (F3009) ───────────────────────────────────────────────
def make_replan(deps: AgentDeps, emitter_of):
    def replan(state: PlannerState) -> dict:
        em = emitter_of(state)
        count = state.get("replan_count", 0) + 1
        em.node_enter("replan", count=count)
        need = state.get("needs_replan")
        log = list(state.get("replan_log") or [])
        update: dict = {"replan_count": count}
        if need == "NEXT_CANDIDATES":
            update["batch_end"] = state.get("batch_end", BATCH) + BATCH
            change = f"인기 루트로는 배치가 안 돼, 루트 밖 같은 분야 자격 {BATCH}개를 대안으로 추가 확인 (이미 조회한 일정은 재사용)"
            reason = "NO_FEASIBLE_PLAN"
        else:
            update["ignore_deadline"] = True
            change = f"기한 {state['conditions'].get('deadline')} 안에는 불가 — 기한을 넘기는 가장 빠른 대안을 계산"
            reason = "DEADLINE_INFEASIBLE"
        em.replan("replan", count, reason, change)
        log.append({"count": count, "reason_code": reason, "change": change})
        em.node_exit("replan", change=change)
        return {**update, "replan_log": log}

    return replan


# ── enrich: 교재 (F3004) ─────────────────────────────────────────
def make_enrich(deps: AgentDeps, emitter_of):
    def enrich(state: PlannerState) -> dict:
        em = emitter_of(state)
        em.node_enter("enrich")
        cache = dict(state.get("tool_results") or {})
        failures = list(state.get("failures") or [])
        books = {}
        for p in ((state.get("arrangement") or {}).get("placed") or [])[:BOOKS_FOR]:
            stage = p.get("stage") or ""
            exam_type = "필기" if "필기" in stage or "+" in stage else None
            r = _call(deps, em, "enrich", cache, "search_books", qualification_name=p["name"],
                      **({"exam_type": exam_type} if exam_type else {}), limit=3)
            if r["ok"]:
                books[p["qual_id"]] = r["data"]["items"]
            else:
                books[p["qual_id"]] = []
                failures.append({"tool": "search_books", "args": {"qualification_name": p["name"]}, **r["error"]})
        em.node_exit("enrich", books={k: len(v) for k, v in books.items()})
        return {"books": books, "tool_results": cache, "failures": failures}

    return enrich
