"""외부 자격 탐색 Agent (external) — 큐넷 · 공공데이터에 없는 자격을 웹에서 찾아 '비공식' 으로 보여 준다.

언제: 목표 직업의 관련 자격 중 등록된 출처에 없는 것이 있을 때 (금융 · 협회 · 민간 자격 — 투자자산운용사, CFA …)
자격 이름
  ① 커리어넷 원문의 '관련 자격' 문장에 글자 그대로 있는 이름 (LLM 이 뽑고, 코드가 원문에 있는지 확인)
  ② 원문이 없으면 웹문서 '{직업} 자격증' 조각에서 LLM 이 뽑은 이름 — 조각에 글자 그대로 있고,
     그 이름으로 다시 검색했을 때 웹문서 2건 이상에 나올 때만 (서로 다른 두 검색으로 확인)
시험 일정
  네이버 웹문서 검색 조각에서 LLM 이 시험일을 뽑는다. 뽑은 날짜 글자가 그 조각에 실제로 있어야 하고(코드 확인),
  오늘 이후 · 1년 안의 날짜만 쓴다. 조각에 연도가 없으면 오늘 기준 가장 가까운 그 날짜로 보고 '연도 추정' 이라고 밝힌다.
공식 일정 계획(큐넷)과 섞지 않는다 — 별도 칸에 출처 링크와 함께 '외부 검색 · 비공식 · 시행기관 공지 확인' 으로만.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from pydantic import BaseModel, Field

from app.events import Emitter

from .deps import AgentDeps
from .state import PlannerState

NODE = "external"
MAX_CERTS = 4
PREP_WEEKS = 8           # 큐넷 밖 자격은 준비 기간 기준값이 없어 8주로 가정하고 그렇게 밝힌다


class CertNames(BaseModel):
    names: list[str] = Field(default_factory=list, description="문장에 글자 그대로 나온 자격 이름들")


class ExamItem(BaseModel):
    source: int = Field(description="근거 조각 번호")
    date_text: str = Field(description="조각에 적힌 시험일 표현을 글자 그대로 (예: '12.20(일)', '2027년 3월 14일')")
    exam_date: str | None = Field(None, description="그 시험일을 YYYY-MM-DD 로. 연도가 없으면 오늘 이후 가장 가까운 날로")
    agency: str | None = Field(None, description="조각에 나온 시행기관 이름. 없으면 null")
    reg_text: str | None = Field(None, description="조각에 적힌 접수 기간 표현 그대로. 없으면 null")


class ExamFind(BaseModel):
    items: list[ExamItem] = Field(default_factory=list)


NAMES_SYSTEM = """문장에서 자격증 · 자격시험 이름만 뽑는다. 문장에 글자 그대로 있는 이름만, 바꾸거나 보태지 않는다.
학과 · 기관 · 직업 이름은 뽑지 않는다."""
EXAM_SYSTEM = """너는 시험 일정 추출기다. 오늘: {today}. 자격: {name}.
번호가 붙은 웹문서 조각에서 이 자격의 '시험일' 만 뽑는다. 조각에 없는 날짜는 절대 만들지 않는다.
- date_text 는 조각에 적힌 표현을 글자 그대로 옮긴다.
- 다른 자격의 날짜, 합격자 발표일, 접수일을 시험일로 착각하지 않는다.
- 찾지 못하면 빈 목록."""


def _norm(s: str | None) -> str:
    return re.sub(r"[\s·()\-]", "", s or "").lower()


def _date_of(text: str, today: date) -> tuple[date | None, bool]:
    """조각의 날짜 글자 → (날짜, 연도가 적혀 있었나). 연도가 없으면 오늘 이후 가장 가까운 그 월 · 일 (지난 회차 날짜로 추정)"""
    # '2027.03.14' · '2027년 3월 14일' · '26년 02월 02일' (두 자리 연도) — 연도가 적혀 있으면 그대로 (지났으면 지난 회차라 버려진다)
    m = re.search(r"((?:20)?\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})", text or "")
    try:
        if m and (len(m.group(1)) == 4 or "년" in m.group(0) or re.match(r"\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}", m.group(0))):
            y = int(m.group(1))
            return date(y if y > 99 else 2000 + y, int(m.group(2)), int(m.group(3))), True
        m = re.search(r"(\d{1,2})\s*[./월]\s*(\d{1,2})", text or "")
        if not m:
            return None, False
        d = date(today.year, int(m.group(1)), int(m.group(2)))
        return (d if d >= today else date(today.year + 1, d.month, d.day)), False
    except ValueError:
        return None, False


def _clean_name(n: str) -> str:
    """'CFA(Chartered Financial Analyst)' → 'CFA', '국제재무분석사 자격증' → '국제재무분석사'"""
    n = re.sub(r"\s*자격(증|시험)?$", "", n.strip())
    head = re.split(r"\s*\(", n, maxsplit=1)[0].strip()
    return head if len(_norm(head)) >= 2 else n


def _web_names(got: list[str], texts: list[str]) -> list[str]:
    """웹 조각에 글자 그대로 나온 이름만, 많이 나온 순. 다른 이름의 일부인 짧은 이름은 뺀다 (투자분석사 ⊂ 금융투자분석사)"""
    names = [n for n in dict.fromkeys(_clean_name(g) for g in got) if len(_norm(n)) >= 2]
    names = [n for n in names if any(_norm(n) in _norm(t) for t in texts)]
    names = [n for n in names if not any(o != n and _norm(n) in _norm(o) for o in names)]
    return sorted(names, key=lambda n: -sum(_norm(n) in _norm(t) for t in texts))


def needs_external(s: PlannerState) -> bool:
    cr = (s.get("route_meta") or {}).get("career") or {}
    return bool((s.get("conditions") or {}).get("job") and cr and s.get("intent") in ("plan_create", "plan_modify"))


def make_external(deps: AgentDeps, emitter_of):
    names_cache: dict[str, list[str]] = {}
    exam_cache: dict[str, dict] = {}

    def cert_names(em, cr: dict) -> list[tuple[str, str]]:
        """[(자격명, 어디서)]"""
        off = cr.get("official") or {}
        text = " ".join(off.get("certificate") or [])
        out: list[tuple[str, str]] = []
        if text:
            if text not in names_cache:
                try:
                    got = deps.extract_llm([{"role": "system", "content": NAMES_SYSTEM},
                                            {"role": "user", "content": text}], CertNames).names
                except Exception:
                    em.error(NODE, "LLM_ERROR", where="cert_names")
                    got = []
                names_cache[text] = [n.strip() for n in got if n.strip() and _norm(n) in _norm(text)]   # 원문에 있는 것만
            out = [(n, "커리어넷 원문") for n in names_cache[text]]
        if not out:
            # 원문이 없으면 웹문서 '{직업} 자격증' 조각에서 — 서로 다른 조각 2건 이상에 글자 그대로 나온 이름만
            job = re.sub(r"\(.*?\)", "", off.get("name") or cr.get("name") or "").strip()
            web = deps.web_snippets(f"{job} 자격증") if job else {"items": []}
            texts = [x["title"] + " " + x["text"] for x in web.get("items") or []]
            if texts:
                key = "web|" + job
                if key not in names_cache:
                    listing = "\n".join(f"[{i}] {t}" for i, t in enumerate(texts))
                    try:
                        got = deps.extract_llm([{"role": "system", "content": NAMES_SYSTEM},
                                                {"role": "user", "content": listing}], CertNames).names
                    except Exception:
                        em.error(NODE, "LLM_ERROR", where="web_cert_names")
                        got = []
                    got += [w for w in cr.get("missing") or []]          # 앞 단계 제안도 같은 기준으로 센다
                    names_cache[key] = _web_names(got, texts)
                out = [(n, "웹 검색") for n in names_cache[key]]
        # 직업 이름 자체는 자격이 아니다 ('투자분석가(애널리스트)' 의 '애널리스트')
        job_names = _norm(" ".join([off.get("name") or "", off.get("related") or "", cr.get("name") or ""]))
        out = [(n, src) for n, src in out if _norm(n) not in job_names]
        known = deps.registered([n for n, _ in out])
        seen, res = set(), []
        for n, src in out:
            if n not in known and _norm(n) not in seen:
                seen.add(_norm(n))
                res.append((n, src))
        return res[:MAX_CERTS]

    def find_exam(em, name: str, src: str, today: date) -> dict | None:
        key = f"{name}|{today}"
        if key in exam_cache:
            return exam_cache[key]
        web = deps.web_snippets(f"{name} 시험일정")
        items = [x for x in web.get("items") or [] if _norm(name) in _norm(x["title"] + x["text"])]
        if src != "커리어넷 원문" and len(items) < 2:     # 웹에서 실제로 쓰이는 자격명인지부터
            exam_cache[key] = None
            return None
        out = {"name": name, "from": src, "exam_date": None, "date_text": None, "agency": None, "reg_text": None,
               "link": items[0]["link"] if items else None, "title": items[0]["title"] if items else None,
               "year_estimated": False, "mentions": len(items)}
        if items:
            listing = "\n".join(f"[{x['i']}] {x['title']} — {x['text']}" for x in items)
            try:
                found = deps.extract_llm([{"role": "system", "content": EXAM_SYSTEM.format(today=today, name=name)},
                                          {"role": "user", "content": listing}], ExamFind).items
            except Exception:
                em.error(NODE, "LLM_ERROR", where="exam")
                found = []
            by_i = {x["i"]: x for x in items}
            ok = []
            for it in found:
                snip = by_i.get(it.source)
                if not snip or not it.date_text or _norm(it.date_text) not in _norm(snip["title"] + snip["text"]):
                    continue                                 # 조각에 없는 날짜는 버린다
                d, has_year = _date_of(it.date_text, today)    # 연도는 LLM 이 아니라 조각 글자로 정한다
                if d is None or not (today <= d <= today + timedelta(days=400)):
                    continue
                ok.append((d, it, snip, has_year))
            if ok:
                d, it, snip, has_year = min(ok, key=lambda x: x[0])
                out.update(exam_date=d.isoformat(), date_text=it.date_text, agency=it.agency, reg_text=it.reg_text,
                           link=snip["link"], title=snip["title"],
                           year_estimated=not has_year,
                           study_start_by=(d - timedelta(weeks=PREP_WEEKS)).isoformat())
        exam_cache[key] = out
        return out

    def external(state: PlannerState) -> dict:
        em: Emitter = emitter_of(state)
        em.node_enter(NODE)
        cr = (state.get("route_meta") or {}).get("career") or {}
        today = date.fromisoformat(state.get("today") or date.today().isoformat())
        names = cert_names(em, cr)
        found = []
        for n, src in names:
            r = find_exam(em, n, src, today)
            if r:
                found.append(r)
        em.llm_decision(NODE, "external", {"names": [n for n, _ in names],
                                           "dated": [f["name"] for f in found if f["exam_date"]]},
                        "큐넷 · 공공데이터에 없는 자격 — 웹문서 조각에서 시험일 (조각에 있는 날짜만, 비공식)")
        em.node_exit(NODE, found=len(found))
        meta = dict(state.get("route_meta") or {})
        meta["external"] = found
        return {"route_meta": meta}

    return external
