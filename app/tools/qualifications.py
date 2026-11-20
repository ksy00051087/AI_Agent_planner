"""시험일정 외부 API 툴 — F3002 후보 조회 · F3003 시험일정 상세.

여러 출처(sources/)를 한 모양으로 합친다. 기준 출처는 큐넷이고, 나머지는 보충이다.
보충 출처 하나가 실패해도 결과는 돌려주고 source_errors 로 알린다.
"""

from __future__ import annotations

import re
from datetime import date

from app.domain.schedule import normalize_round, upcoming_rounds

from . import sources
from .base import BAD_ARGUMENT, NO_DATA, NO_EXAM_DATE, fail, ok

MAX_ROUNDS = 30  # 공고된 회차 + 다음 해 추정 회차. 상시시험은 달마다 첫 회차만 남겨 2년을 덮는다
_QUAL_KEYS = ("qual_id", "name", "grade", "qual_type", "field", "sub_field", "organization", "source")


def _norm(s: str | None) -> str:
    return re.sub(r"[\s.·]", "", s or "").lower()


def _parse_date_arg(value, name: str):
    if value in (None, ""):
        return None, None
    try:
        return None, date.fromisoformat(str(value))
    except ValueError:
        return fail(BAD_ARGUMENT, f"{name} 는 YYYY-MM-DD 형식이어야 합니다."), None


# ── F3002 후보 조회 ───────────────────────────────────────────────
def search_qualifications(field: str | None = None, keyword: str | None = None, grade: str | None = None,
                          base_date: str | None = None, limit: int = 20):
    if not (field or keyword):
        return fail(BAD_ARGUMENT, "field(직무분야) 또는 keyword(자격명 일부) 중 하나는 필요합니다.")
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        return fail(BAD_ARGUMENT, "limit 는 1~100 사이 정수여야 합니다.")
    err, requested = _parse_date_arg(base_date, "base_date")
    if err:
        return err
    today = date.today()
    base = requested or today  # 기준 날짜 기본값: 오늘

    pool, source_errors, first_error = [], [], None
    for src in sources.all_sources():
        serr, quals = src.list_quals()
        if serr:
            first_error = first_error or serr
            source_errors.append({"source": src.NAME, **serr["error"]})
            continue
        pool.extend(quals)
    if not pool and first_error:
        return first_error  # 모든 출처가 실패 — 키 오류 등은 그대로 알린다

    f, k, g = _norm(field), _norm(keyword), _norm(grade)
    matched = [
        q for q in pool
        if (not f or f in _norm(q.get("field")) or f in _norm(q.get("sub_field")))
        and (not k or k in _norm(q.get("name")))
        and (not g or g == _norm(q.get("grade")))
    ]
    if not matched:
        return fail(NO_DATA, "조건에 맞는 자격 종목이 없습니다. 등록된 출처에 없는 자격은 일정을 확인할 수 없습니다.")

    estimated = base.year != today.year  # 요청 기준과 실제 조회 기준이 다르면 밝힌다
    basis = f"종목 목록은 {today:%Y-%m-%d} 조회 기준"
    if estimated:
        basis += f" — 요청한 {base.year}년의 신설 · 폐지 종목은 반영되지 않은 추정입니다"

    items = [{key: q.get(key) for key in _QUAL_KEYS} for q in matched]
    # 인기순 — 큐넷 종목은 최근 연도 최종 합격자 수. 근거가 없는 출처는 뒤로 (값을 지어내지 않는다)
    for it in items:
        it["popularity"] = sources.qnet.popularity(it["qual_id"], it["name"]) if it["source"] == "qnet" else None
    items.sort(key=lambda it: -((it["popularity"] or {}).get("acquired") or -1))
    return ok({
        "base_date": base.isoformat(),
        "base_date_defaulted": requested is None,
        "estimated": estimated,
        "basis": basis,
        "total": len(items),
        "truncated": len(items) > limit,
        "items": items[:limit],
        "source_errors": source_errors,
    })


# ── F3003 시험일정 상세 ───────────────────────────────────────────
def _serialize(r: dict) -> dict:
    return {"name": r["name"], "stage": r.get("stage"), "exam_time": r.get("exam_time"),
            "estimated": r["estimated"], "basis": r["basis"],
            **{k: (v.isoformat() if v else None) for k, v in r["dates"].items()}}


def _thin(rounds: list[dict]) -> list[dict]:
    """상시시험처럼 회차가 많으면 (단계, 연-월)마다 첫 회차만 남긴다. 계획에는 '그 달에 볼 수 있다'면 충분하다."""
    if len(rounds) <= MAX_ROUNDS:
        return rounds
    seen, out = set(), []
    for r in rounds:
        key = (r.get("stage"), r["dates"]["written_exam_start"].strftime("%Y-%m"))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def get_exam_schedule(qual_id: str, from_date: str | None = None):
    if not qual_id or not isinstance(qual_id, str):
        return fail(BAD_ARGUMENT, "qual_id 는 필수입니다. search_qualifications 결과의 qual_id 를 넘기세요.")
    err, requested = _parse_date_arg(from_date, "from_date")
    if err:
        return err
    start = requested or date.today()

    src = sources.source_for(qual_id)
    if src is None:
        return fail(BAD_ARGUMENT, "qual_id 형식을 알 수 없습니다. search_qualifications 결과의 qual_id 를 그대로 넘기세요.")
    serr, rounds_raw, meta = src.get_schedule(qual_id)
    if serr:
        return serr

    rounds = [{**normalize_round(r["name"], r["dates"]), "stage": r.get("stage"), "exam_time": r.get("exam_time")}
              for r in rounds_raw]
    unjudged = [{"name": r["name"], "missing": r["missing"]} for r in rounds if not r["judgeable"]]
    if not any(r["judgeable"] for r in rounds):
        return fail(NO_EXAM_DATE, f"{meta['name']}: 모든 회차에서 접수 마감 · 시험일이 비어 있어 판단할 수 없습니다.")

    upcoming = _thin(upcoming_rounds(rounds, start, max_years_ahead=3))  # 루트 전체를 배치하면 2년을 넘는다
    if not upcoming:
        return fail(NO_DATA, f"{meta['name']}: {start:%Y-%m-%d} 이후 접수할 수 있는 회차를 찾지 못했습니다.")

    return ok({
        "qual_id": qual_id,
        "name": meta["name"],
        "grade": meta.get("grade"),
        "organization": meta.get("organization"),
        "from_date": start.isoformat(),
        "from_date_defaulted": requested is None,
        "estimated": upcoming[0]["estimated"],  # 다음 시험(첫 회차)이 추정인가. 회차마다 estimated 도 따로 있다
        "rounds": [_serialize(r) for r in upcoming[:MAX_ROUNDS]],
        "more_rounds": max(0, len(upcoming) - MAX_ROUNDS),
        "unjudged": unjudged,
        "fee": meta.get("fee"),
        "fee_text": meta.get("fee_text"),
        "exam_info": meta.get("exam_info"),
        "pass_rate": meta.get("pass_rate"),
        "source": meta["source"],
    })


# ── Agent 조건 추출용: 출처에 실제로 있는 분야 이름 (Tool 아님) ──────────
def field_options() -> list[str]:
    names: set[str] = set()
    for src in sources.all_sources():
        err, quals = src.list_quals()
        for q in quals or []:
            for key in ("field", "sub_field"):
                if q.get(key):
                    names.add(q[key])
    return sorted(names)


# ── Agent 순서 판정용: 공식 시험면제과목 연계 (Tool 아님) ─────────────
_EXEMPT_FILE = sources.table.ROOT / "data" / "raw" / "15120651.csv"   # scripts/download_datasets.py 로 받은 파일
_exempt_pairs: set[tuple[str, str]] | None = None


def exemption_precedes(names: list[str]) -> dict[str, set[str]]:
    """{응시종목: {먼저 따면 과목이 면제되는 취득종목}} — 두 자격이 모두 후보일 때만. 파일이 없으면 빈 dict."""
    global _exempt_pairs
    if _exempt_pairs is None:
        try:
            rows = sources.table._read_csv(_EXEMPT_FILE)
            pairs = {(r["취득종목명"], r["응시종목명"]) for r in rows if r.get("취득종목명") != r.get("응시종목명")}
            # 서로 면제(A↔B)는 순서 근거가 아니다 — 한 방향만 남긴다
            _exempt_pairs = {(a, b) for a, b in pairs if (b, a) not in pairs}
        except (OSError, ValueError, KeyError):
            _exempt_pairs = set()
    wanted = set(names)
    out: dict[str, set[str]] = {}
    for before, after in _exempt_pairs:
        if before in wanted and after in wanted:
            out.setdefault(after, set()).add(before)
    return out


# ── Agent 관계 분석용: data/qual_relations.json (Tool 아님) ───────────
_REL_FILE = sources.table.ROOT / "data" / "qual_relations.json"


def relations_config() -> dict:
    """{"field_groups": {분야: [가까운 분야]}, "ladders": [[낮은, 높은]], "expert": [이름], "prep_weeks": {이름: 주},
        "basics": [{name, search, note}] (계획 전에 보유 여부를 묻는 기본 자격),
        "tracks": [{fields, items: [{name, match, note?}]}] (계획 전에 묻는 진로 방향 · 직업군)}"""
    import json

    try:
        raw = json.loads(_REL_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"field_groups": {}, "ladders": [], "expert": [], "prep_weeks": {}, "basics": [], "tracks": []}
    strip = lambda d: {k: v for k, v in (d or {}).items() if not k.startswith("_")}  # noqa: E731
    return {"field_groups": strip(raw.get("field_groups")), "ladders": (raw.get("ladders") or {}).get("items", []),
            "expert": raw.get("expert") or [], "prep_weeks": strip(raw.get("prep_weeks")),
            "basics": (raw.get("basics") or {}).get("items", []),
            "tracks": (raw.get("tracks") or {}).get("groups", []), "intros": _intros(), "co_mention": _co_mention(),
            "keyword_rules": strip(raw.get("keyword_rules")), "sectors": strip(raw.get("sectors"))}


_subjects_cache: dict = {"mtime": None, "map": {}}


def official_subjects(names: list[str]) -> dict[str, str]:
    """{자격명: '필기: … / 실기: …'} — RAG 문서(data/rag/docs.json, 큐넷 취득방법)의 공식 시험과목. 없으면 빈 dict"""
    import json

    from app.domain.qualinfo import parse_acquisition

    path = sources.table.ROOT / "data" / "rag" / "docs.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _subjects_cache["mtime"] != mtime:
        out = {}
        for d in json.loads(path.read_text(encoding="utf-8")):
            if d.get("kind") != "취득방법" or d["qual_name"] in out:
                continue
            info = parse_acquisition(d["text"]) or {}
            parts = [f"{st}: {', '.join(v)}" for st, v in (info.get("subjects") or {}).items() if v]
            if parts:
                out[d["qual_name"]] = " / ".join(parts)
        _subjects_cache.update(mtime=mtime, map=out)
    return {n: _subjects_cache["map"][n] for n in names if n in _subjects_cache["map"]}


def _co_mention() -> dict:
    """블로그 후기 함께 언급 (data/rag/co_mention.json — scripts/collect_naver.py). 없으면 빈 dict"""
    import json

    try:
        raw = json.loads((_REL_FILE.parent / "rag" / "co_mention.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _intros() -> dict:
    """자격 소개 한 줄 (data/qual_intros.json — 서비스 안내). 없으면 빈 dict"""
    import json

    try:
        return json.loads((_REL_FILE.parent / "qual_intros.json").read_text(encoding="utf-8")).get("items") or {}
    except (OSError, ValueError):
        return {}
