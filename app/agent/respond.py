"""respond 노드 (F3011) — 구조화된 결과를 사람이 읽을 문장으로. 값은 상태에 있는 것만 쓴다 (LLM 미사용).

추천 항목 · 판단 기준 · 근거(출처) · 제외 사유 · 추정 표시 · 재계획 이력을 함께 보여 준다.
"""

from __future__ import annotations

from app.domain.names import target_found

from .state import PlannerState

USAGE = ("직업 준비 플래너입니다. 되고 싶은 직업(또는 분야 · 자격)과 기한을 말씀해 주시면 시험 일정을 확인해 "
         "따는 순서와 '늦어도 이 날 공부 시작'을 계산해 드립니다.\n"
         "예) \"전기 엔지니어가 되고 싶어. 내년 6월까지\", \"간호사 국가시험 언제야?\", \"9급 공무원이랑 한국사 같이 준비할래\"")

REASON_TEXT = {
    "SUPERSEDED": "같은 계열 상위 자격이 계획에 있어 따로 딸 필요 없음",
    "NO_EXAM_DATE": "공식 데이터에 시험일이 비어 있어 판단하지 않음",
    "NOT_FOUND": "등록된 출처에 없음",
    "NO_DATA": "접수 가능한 회차를 찾지 못함",
    "STUDY_OVERLAP": "공부 기간이 다른 자격과 겹침 (큰 시험은 혼자, 나머지는 2개까지 병행)",
}
FATAL_TEXT = {
    "INVALID_KEY": "외부 API 키가 없거나 올바르지 않아 일정을 확인하지 못했습니다. 관리자에게 키 설정(.env)을 확인해 달라고 해 주세요.",
    "QUOTA_EXCEEDED": "외부 API 의 하루 호출 한도를 넘어 지금은 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.",
    "UPSTREAM_ERROR": "외부 API 가 응답하지 않아 일정을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.",
}


def _date(iso: str | None, time: str | None = None) -> str:
    if not iso:
        return "–"
    return f"{iso} {time}" if time else iso


def _won(n: int | None) -> str:
    return f"{n:,}원" if n else "미확인"


def _conditions_line(state: PlannerState) -> list[str]:
    c = state.get("conditions") or {}
    parts = []
    if c.get("job"):
        parts.append(f"목표 직업 {c['job']}")
    if c.get("field"):
        parts.append(f"분야 {c['field']}")
    if c.get("targets"):
        parts.append(f"지정 자격 {', '.join(c['targets'])}")
    if c.get("keywords"):
        parts.append(f"검색어 {', '.join(c['keywords'])}")
    if (state.get("route_meta") or {}).get("tracks_used"):
        parts.append(f"진로 {', '.join(state['route_meta']['tracks_used'])}")
    if c.get("grades"):
        parts.append(f"등급 {', '.join(c['grades'])}")
    if c.get("exclude"):
        parts.append(f"제외 {', '.join(c['exclude'])}")
    parts.append(f"기한 {c['deadline']}" if c.get("deadline") else "기한 없음")
    parts.append(f"시작 {c.get('start_date') or state.get('today')}" + ("" if c.get("start_date") else "(오늘)"))
    parts.append(f"동시에 공부 {c['max_parallel']}개" if c.get("max_parallel")
                 else "큰 시험(기사 · 전문자격 등)은 혼자 · 나머지 2개까지 병행 · 기본 자격은 병행(기본)")
    if state.get("busy_dates"):
        parts.append(f"캘린더 일정 {len(state['busy_dates'])}일 피함")
    if c.get("budget"):
        parts.append(f"예산 {c['budget']:,}원")
    lines = ["**적용한 조건**: " + " · ".join(parts)]
    for it in state.get("interpretations") or []:
        lines.append(f"- '{it['text']}' → {it['as']} 로 해석했습니다.")
    return lines


def _official_lines(off: dict) -> list[str]:
    """커리어넷 직업정보 원문 — 요약하지 않고 옮긴다 (출처 링크 포함)"""
    out = [f"**{off['name']}** — [커리어넷 직업정보]({off['url']})"]
    if off.get("work"):
        out.append(f"- 하는 일: {off['work'][0]}")
    for label, key in (("관련 자격", "certificate"), ("학과", "curriculum"), ("교육 · 훈련", "training"), ("채용", "recruit")):
        for t in (off.get(key) or [])[:2]:
            out.append(f"- {label}: {t}")
    if off.get("certificate_issue"):
        out.append(f"- 관련 자격: {off['certificate_issue']}")
    return out


def _external_lines(ext: list[dict]) -> list[str]:
    """큐넷 밖 자격 — 웹문서 조각에서 찾은 일정 (비공식, 출처 링크)"""
    if not ext:
        return []
    out = ["", "**큐넷 밖 관련 자격** (웹 검색 · 비공식 — 시행기관 공지로 꼭 확인하세요)"]
    for x in ext:
        src = f"[{x['title']}]({x['link']})" if x.get("link") else "출처 없음"
        if x.get("exam_date"):
            yr = " (조각에 연도가 없어 오늘 이후 같은 날짜로 추정)" if x.get("year_estimated") else ""
            reg = f" · 접수 '{x['reg_text']}'" if x.get("reg_text") else ""
            out.append(f"- {x['name']}: 다음 시험 {x['exam_date']}{yr} — 조각 원문 '{x['date_text']}'{reg} · "
                       f"늦어도 {x['study_start_by']} 공부 시작(8주 가정) · {src} · {x['from']}")
        else:
            out.append(f"- {x['name']}: 웹 검색에서 시험일을 확인하지 못했습니다 · {src} · {x['from']}")
    return out


def _unmatched(state: PlannerState) -> list[str]:
    """사용자가 이름을 댄 자격 중 등록된 출처에서 후보로도 찾지 못한 것"""
    names = [q["name"] for q in state.get("candidates") or []]
    c = state.get("conditions") or {}
    return [t for t in c.get("targets") or [] if not target_found(t, names, c.get("keywords"))]


NOT_IN_SOURCES = ("등록된 출처(큐넷 국가자격 · 공공데이터)에 없어 일정을 확인할 수 없습니다. "
                  "금융 · 어학 · 상공회의소처럼 공식 일정 데이터가 없는 민간 · 협회 자격일 수 있으니 시행기관 공지를 확인해 주세요.")


def _plan_text(state: PlannerState) -> str:
    a = state.get("arrangement") or {}
    placed, excluded = a.get("placed") or [], a.get("excluded") or []
    books = state.get("books") or {}
    out = _conditions_line(state) + [""]
    if (state.get("conditions") or {}).get("job"):
        out.insert(0, f"### {state['conditions']['job']} 준비 계획\n")

    if a.get("deadline_ignored") and placed:
        out.append(f"⚠️ 기한 {state['conditions'].get('deadline')} 안에는 가능한 계획이 없어, **기한을 넘기는 가장 빠른 대안**입니다.\n")
    if placed:
        out.append("| 순서 | 자격 | 회차 | 접수 마감 | 시험일 | 실기 · 2차 | 늦어도 공부 시작 | 응시료 |")
        out.append("|---|---|---|---|---|---|---|---|")
        for i, p in enumerate(placed, 1):
            est = " (추정*)" if p["estimated"] else ""
            out.append(f"| {i} | {p['name']} | {p['round_name']}{est} | {_date(p['registration_end'])} | "
                       f"{_date(p['exam_date'], p['exam_time'])} | {_date(p['practical_exam_date'])} | "
                       f"**{p['study_start_by']}** ({p['prep_weeks']}주) | {_won(p['fee_total'])} |")
        out.append("")
        out.append("**이 순서인 이유 (흐름)**")
        for i, p in enumerate(placed, 1):
            why = p.get("path_reason") or "조건에 맞는 후보"
            if p.get("precedes_link"):
                why += f" · 먼저 딴 {', '.join(p['precedes_link'])} 로 일부 과목 면제 (공식 시험면제과목 기준)"
            if p.get("load_text"):
                why += f" · 공부 방식: {p['load_text']}" + (f" (같은 기간: {', '.join(p['parallel_with'])})"
                                                         if p.get("parallel_with") else "")
            out.append(f"{i}. {p['name']} — {why}")
            it = p.get("intro") or {}
            if it.get("study"):
                out.append(f"   - 무엇을 공부: {it['study']} ({it['study_source']})")
            if it.get("good_for"):
                out.append(f"   - 이럴 때 유리: {it['good_for']} ({it['good_for_source']})")
        for p in placed:
            lad = p.get("ladder") or []
            if lad and p["name"] in lad and lad.index(p["name"]) > 0 and not any(x in [q["name"] for q in placed] for x in lad[:lad.index(p["name"])]):
                out.append(f"- {p['name']} 응시자격(학력 · 경력)이 아직 안 되면 앞 단계부터: {' → '.join(lad[:lad.index(p['name']) + 1])}. "
                           "응시자격은 Q-Net 에서 확인하세요.")
        if a.get("deferred"):
            out.append(f"- 다음 계획 후보(한 번에 {len(placed)}개까지만 배치): {', '.join(a['deferred'][:6])}")
        out.append("")
        out.append("**판단 기준**")
        for p in placed:
            line = f"- {p['name']}: 준비 {p['prep_weeks']}주 = {p['prep_basis']}. 출처: {p['source']}"
            if p["estimated"]:
                line += f"\n  - *추정: {p['basis']}. 공고가 나오면 다시 확인하세요."
            if not p["practical_exam_date"] and p.get("stage") and "필기" in p["stage"]:
                line += "\n  - 실기 · 다음 단계 일정은 필기 합격 후 따로 접수합니다 (데이터에 날짜가 없어 계산하지 않음)."
            out.append(line)
        out.append(f"- 응시료 합계(확인된 것만): {_won(a.get('fee_total'))}"
                   + (f" · 응시료 미확인: {', '.join(a['fee_unknown'])}" if a.get("fee_unknown") else ""))
        out.append("- 공부 기간은 외부 데이터로 확인할 수 없는 값이라 서비스 기준값입니다. 원하시면 '자격마다 8주'처럼 말씀해 주세요.")
    else:
        out.append("조건을 모두 충족하는 계획을 만들지 못했습니다."
                   + (" 기한을 넘기는 대안도 계산했지만 배치할 수 있는 회차가 없었습니다." if a.get("deadline_ignored") else ""))

    for t in _unmatched(state):
        out.append(f"\n- {t}: {NOT_IN_SOURCES}")
    rel = state.get("route_meta") or {}
    cr = rel.get("career")
    web = (cr or {}).get("web") or {}
    if web.get("names"):
        out.append(f"\n**네이버 글 {web['docs']}건 중 이 직무와 함께 언급된 자격(비공식)**: "
                   + ", ".join(f"{n} {web['counts'].get(n, 0)}건" for n in web["names"]))
    if cr and cr.get("official"):
        out += [""] + _official_lines(cr["official"])
        if cr["official"].get("cert_names") and cr.get("missing"):
            out.append("- 커리어넷에 나온 관련 자격 중 연결된 출처에 일정이 없는 것: " + ", ".join(cr["missing"]))
    elif cr and cr.get("known") and cr.get("job"):
        out.append(f"\n**직무 풀이(AI 해석)**: {cr['job']}")
    out += _external_lines(rel.get("external") or [])
    if rel.get("irrelevant"):
        out.append("\n**목표와 이어지지 않아 뺀 자격** (공식 시험과목 기준):")
        for x in rel["irrelevant"][:6]:
            out.append(f"- {x['name']}: 시험과목 '{x['basis']}' — {x['reason']}")
    if rel.get("sector_note"):
        out.append(f"\n**안내**: {rel['sector_note']}")
    low = [x for x in rel.get("low_popular") or [] if x["name"] not in {p["name"] for p in placed}]
    if low and (rel.get("tracks_used") or len(placed) < 3):
        out.append("\n**이 진로의 다른 국가자격** — 최근 합격자가 매우 적어 기본 계획에는 넣지 않았습니다. 원하면 넣어 드립니다.")
        for x in low:
            out.append(f"- {x['name']}: {x['basis']}")
    for x in (rel.get("co_mentions") or [])[:3]:
        out.append(f"- 후기에서 함께 언급: {x['a']} · {x['b']} — '{x['a']} 다음 자격증' 블로그 후기 {x['posts']}건 중 {x['count']}건 (비공식)")
    if rel.get("held"):
        out.append("\n**보유 자격 반영**: " + ", ".join(
            h["name"] if h["name"] == h["by"] else f"{h['name']}({h['by']} 보유로 불필요)" for h in rel["held"])
            + " — 계획에서 뺐습니다.")
    placed_names = {p["name"] for p in placed}
    names = [q["name"] for q in state.get("candidates") or []]
    for n in (state.get("conditions") or {}).get("include") or []:
        if n not in placed_names and not target_found(n, names):
            out.append(f"- {n}: 같이 준비하기로 고르셨지만 등록된 출처에 일정이 없어 계획에 넣지 못했습니다. 시행기관 일정을 확인하세요.")

    shelf = [(p["name"], books.get(p["qual_id"])) for p in placed if books.get(p["qual_id"])]
    if shelf:
        out.append("\n**교재** (제목에 자격명이 들어간 실제 책 · 최근 출간순, 판매 순위 아님)")
        for name, items in shelf:
            for b in items[:2]:
                out.append(f"- {name}: [{b['title']}]({b['link']}) · {b.get('publisher') or ''} · {b.get('pub_date') or ''}")

    if excluded:
        out.append("\n**제외한 후보와 사유**")
        for e in excluded[:12]:
            out.append(f"- {e['name']}: {REASON_TEXT.get(e['reason_code'], e['detail'])} ({e['reason_code']})")
        if len(excluded) > 12:
            out.append(f"- 외 {len(excluded) - 12}개")

    if state.get("replan_log"):
        out.append("\n**재계획**")
        for r in state["replan_log"]:
            out.append(f"- {r['count']}회차: {r['change']}")
    if state.get("needs_replan") == "EXHAUSTED":
        out.append("\n재계획으로 바꿀 수 있는 대안(기한 완화 · 루트 밖 자격)을 모두 써 봤지만 배치할 수 있는 회차가 없습니다. "
                   "기한을 늘리거나 자격마다 공부 기간을 줄여 다시 요청해 주세요.")
    if state.get("needs_replan") == "LIMIT_REACHED":
        out.append("\n재계획 상한에 도달해 멈췄습니다. 기한을 늘리거나, 자격마다 공부 기간을 줄이거나, "
                   "동시에 공부할 자격 수를 늘리면 다시 계산할 수 있습니다. 어떻게 바꿀까요?")
    return "\n".join(out)


def _held_text(state: PlannerState) -> str:
    """계획 전에 '지금 가진 자격' 을 묻는다 — 화면은 view.held_panel 로 선택지를 그린다"""
    panel = state.get("held_panel") or {}
    job = (state.get("conditions") or {}).get("job")
    out = [f"{job} 준비 계획을 짜기 전에 확인할게요." if job else "계획을 짜기 전에 확인할게요.", ""]
    if panel.get("tracks"):
        out.append("**어느 쪽으로 가고 싶으세요?** (여러 개 골라도 되고, 모르면 비워 두세요)")
        for t in panel["tracks"]:
            out.append(f"- {t['name']}: {' · '.join(t['examples'])}" + (f" ({t['note']})" if t.get("note") else ""))
        out.append("")
    out += ["**이미 가지고 있는 자격** — 가진 자격과 그 아래 단계는 계획에서 빼고, 다음 단계부터 짭니다.", ""]
    for g in panel.get("field") or []:
        out.append("- " + " → ".join(i["name"] for i in g["items"]))
    if panel.get("basics"):
        out += ["", "**기본 자격** (분야와 상관없이 쓰이는 자격) — 가지고 있는지, 같이 준비할지 골라 주세요."]
        for b in panel["basics"]:
            out.append(f"- {b['name']}" + (f" — {b['note']}" if b.get("note") else ""))
    return "\n".join(out)


def _docs_text(state: PlannerState) -> str:
    """RAG 결과 (F3022) — 원문 조각과 출처를 그대로. 요약 · 생성하지 않는다."""
    out = []
    for group in state.get("documents") or []:
        for it in group["items"]:
            title = " · ".join(x for x in (it.get("qual_name"), it.get("kind")) if x)
            body = it["text"].strip()
            if len(body) > 700:
                body = body[:700] + " …"
            quoted = "\n".join(f"> {ln}" for ln in body.split("\n"))
            src = f"[{it['source']}]({it['url']})" if it.get("url") else it["source"]
            out += [f"**{title}** (질문과의 거리 {it['distance']})", quoted, f"출처: {src}", ""]
    for f in state.get("failures") or []:
        if f["code"] == "NO_INDEX":
            out.append("자격 정보 문서를 아직 모으지 못했습니다 (색인 없음). 관리자가 색인을 만들면 답할 수 있습니다.")
        elif f["code"] == "NO_DATA":
            out.append(f"'{f['args'].get('qualification_name') or f['args'].get('query')}' 와 관련된 문서를 찾지 못했습니다.")
    if out:
        out.insert(0, "자격 정보 문서에서 찾은 **원문**입니다. 시험 일정 · 응시자격의 최신 여부는 시행기관 공지로 확인하세요.\n")
    return "\n".join(out).strip() or "관련 문서를 찾지 못했습니다."


def _lookup_text(state: PlannerState) -> str:
    items = state.get("lookup") or []
    out = []
    for q in items:
        out.append(f"**{q['name']}** ({q.get('organization') or q.get('source')})")
        for r in q["rounds"][:3]:
            est = " · 추정*" if r.get("estimated") else ""
            out.append(f"- {r['name']}{est}: 접수 {_date(r.get('written_reg_start'))} ~ {_date(r.get('written_reg_end'))}, "
                       f"시험 {_date(r.get('written_exam_start'), r.get('exam_time'))}"
                       + (f", 실기 · 2차 {r['practical_exam_start']}" if r.get("practical_exam_start") else ""))
        if q.get("fee"):
            out.append(f"- 응시료: {', '.join(f'{k} {v:,}원' for k, v in q['fee'].items())}")
        rate = (q.get("pass_rate") or {}).get("by_stage")
        if rate:
            out.append(f"- {q['pass_rate']['year']}년 합격률: " + ", ".join(f"{k} {v['rate']}%" for k, v in rate.items()))
        if any(r.get("estimated") for r in q["rounds"][:3]):
            out.append(f"- *{q['rounds'][0].get('basis') or '추정치'}")
        out.append(f"- 출처: {q.get('source')}")
        out.append("")
    for t in _unmatched(state):
        out.append(f"- {t}: {NOT_IN_SOURCES}")
    for f in state.get("failures") or []:
        if f["tool"] == "get_exam_schedule":
            out.append(f"- {f.get('name') or f['args'].get('qual_id')}: {REASON_TEXT.get(f['code'], f['message'])}")
    if not items and not state.get("failures"):
        out.append("말씀하신 자격을 등록된 출처에서 찾지 못했습니다. 공식 일정 데이터가 없는 민간 · 협회 자격일 수 있습니다.")
    return "\n".join(out).strip()


def make_respond(deps, emitter_of):
    def respond(state: PlannerState) -> dict:
        em = emitter_of(state)
        em.node_enter("respond")
        intent = state.get("intent")
        if state.get("error") == "LLM_UNAVAILABLE":
            answer = "요청을 해석할 LLM 키(GMS_API_KEY)가 설정되지 않았습니다. .env 를 확인해 주세요."
        elif state.get("error") == "BLOCKED_REQUEST":
            answer = "이 요청은 도와드릴 수 없습니다. 취업하려는 분야나 따고 싶은 자격을 알려 주시면 계획을 짜 드릴게요."
        elif state.get("error"):
            answer = "요청을 해석하는 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요."
        elif state.get("missing"):
            answer = "계획을 세우려면 다음을 알려 주세요: " + ", ".join(state["missing"])
        elif intent == "chat":
            answer = USAGE
        elif intent == "plan_save":
            answer = ("직전 계획은 화면의 [계획 저장] 버튼으로 저장할 수 있습니다." if state.get("last_plan")
                      else "저장할 계획이 아직 없습니다. 먼저 계획을 만들어 주세요.")
        elif state.get("fatal"):
            answer = FATAL_TEXT.get(state["fatal"], FATAL_TEXT["UPSTREAM_ERROR"])
        elif intent == "qual_info":
            answer = _docs_text(state)
        elif intent == "fact_lookup":
            answer = _lookup_text(state)
        elif state.get("screen"):
            sc = state["screen"]
            answer = sc.get("reason") or "자격 준비 계획으로 이어지는 직업을 알려 주세요."
            if sc.get("suggestions"):
                answer += ("\n\n**이런 직업으로 준비해 볼까요?** (누르면 공식 직업정보 · 시험 일정으로 다시 확인합니다)\n"
                           + "\n".join(f"- {x}" for x in sc["suggestions"]))
        elif state.get("held_panel"):
            answer = _held_text(state)
        elif not (state.get("candidates") or []) and (state.get("route_meta") or {}).get("held"):
            answer = ("말씀하신 분야의 루트 자격을 이미 모두 가지고 계십니다: "
                      + ", ".join(h["name"] for h in state["route_meta"]["held"])
                      + ". 상위 단계(기능장 · 기술사 · 전문가급)나 다른 분야를 원하시면 말씀해 주세요.")
        elif not (state.get("candidates") or []) and (state.get("route_meta") or {}).get("career") is not None:
            cr = state["route_meta"]["career"]
            web = cr.get("web") or {}
            if cr.get("official"):
                answer = "\n".join([*_official_lines(cr["official"]), "",
                                    "큐넷 · 공공데이터에서 공식 시험 일정을 확인할 수 있는 관련 자격이 없어 공식 일정 계획은 만들지 않았습니다. "
                                    + ("학과 · 훈련 · 채용 경로와 아래 큐넷 밖 자격을 참고해 준비해 주세요."
                                       if (state.get("route_meta") or {}).get("external") else
                                       "학과 · 훈련 · 채용 경로를 기준으로 준비해 주세요.")])
            elif not cr["known"] and web.get("refs"):
                answer = ("말씀하신 직무에 맞는 자격을 연결된 출처(큐넷 · 공공데이터)와 네이버 글에서 확인하지 못했습니다. 참고할 글: "
                          + " · ".join(f"[{r['title']}]({r['link']})" for r in web["refs"])
                          + "\n직무에 맞는 자격 이름을 아시면 알려 주세요.")
            elif not cr["known"]:
                answer = ("말씀하신 직무가 정확히 무엇인지 확실히 알 수 없습니다. 풀어서 다시 말씀해 주시거나 "
                          "(예: 약어 대신 정식 직무명) 따고 싶은 자격 이름을 알려 주세요.")
            else:
                answer = (f"'{cr['job']}' 직무로 이해했지만(AI 풀이), 연결된 출처(큐넷 국가자격 · 공공데이터)에서 "
                          "일정을 확인할 수 있는 관련 자격이 없습니다. 이 직무는 자격보다 경력 · 포트폴리오가 중요할 수 있습니다.")
        elif not (state.get("candidates") or []):
            missing = _unmatched(state)
            answer = ("\n".join(f"- {t}: {NOT_IN_SOURCES}" for t in missing) if missing else
                      "말씀하신 조건에 맞는 자격을 등록된 출처(큐넷 국가자격 · 공공데이터)에서 찾지 못했습니다. "
                      "금융 · 어학 · 상공회의소 자격처럼 공식 일정 데이터가 없는 자격일 수 있습니다.")
        else:
            answer = _plan_text(state)
        ext = (state.get("route_meta") or {}).get("external") or []
        if ext and not ((state.get("arrangement") or {}).get("placed")) and not state.get("held_panel"):
            answer += "\n" + "\n".join(_external_lines(ext))
        prev = state.get("prev_inspection") or {}
        if prev.get("verdict") == "이상" and intent not in ("chat",):
            kinds = ", ".join(sorted({w["type"] for w in prev.get("warnings") or []}))
            answer += (f"\n\n> 참고: 직전 요청의 실행 점검에서 이상 징후({kinds})가 있었습니다. "
                       "결과가 이상하면 조건을 바꿔 다시 요청해 주세요. 자세한 내용은 [실행 로그] 화면.")
        placed = ((state.get("arrangement") or {}).get("placed")) or []
        em.node_exit("respond", length=len(answer))
        update = {"answer": answer}
        if placed:  # 대화 맥락: 계획 요약만 남긴다 (F3010)
            update["last_plan"] = [{k: p[k] for k in ("qual_id", "name", "exam_date", "study_start_by")} for p in placed]
        return update

    return respond
