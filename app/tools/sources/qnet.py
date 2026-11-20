"""출처 어댑터: 큐넷(한국산업인력공단) 국가자격 오픈 API.

출처: openapi.q-net.or.kr — 종목 목록 · 종목별 시험일정 · 응시료
이용 조건: 공공데이터포털 이용허락범위 '제한 없음'. 레거시 엔드포인트는 2026-11-18 현재 키 없이 응답한다.
           키 정책이 바뀌면 data.go.kr 활용신청 키를 QNET_SERVICE_KEY 에 넣는다.
식별자: 네 자리 종목코드 (예: 1320)
"""

from __future__ import annotations

import os
import re
import time as _time
import xml.etree.ElementTree as ET

import requests

from app.domain.qualinfo import parse_acquisition, summarize_pass_rates
from app.domain.schedule import parse_fee

from ..base import INVALID_KEY, NO_DATA, NOT_FOUND, UPSTREAM_ERROR, fail

NAME = "qnet"
LABEL = "큐넷 국가자격 오픈 API (한국산업인력공단)"
# 큐넷 원본 API 는 HTTP 만 받는다 (2026-11-19 확인: https 는 연결 시간 초과, 공공데이터포털 https 게이트웨이에는
# 이 서비스가 없음 NO_OPENAPI_SERVICE_ERROR). 키 없이도 5개 API 가 모두 응답하므로 HTTP 로는 키를 보내지 않는다.
QNET_BASE = os.getenv("QNET_BASE") or "http://openapi.q-net.or.kr/api/service/rest"
TIMEOUT = 25              # 상시 시험 종목(미용사 등)은 회차가 많아 응답이 10초를 넘기도 한다
CATALOG_TTL_SEC = 3600

_JM_FIELDS = {
    "written_reg_start": "docregstartdt", "written_reg_end": "docregenddt",
    "written_exam_start": "docexamstartdt", "written_exam_end": "docexamenddt",
    "written_pass": "docpassdt",
    "practical_reg_start": "pracregstartdt", "practical_reg_end": "pracregenddt",
    "practical_exam_start": "pracexamstartdt", "practical_exam_end": "pracexamenddt",
    "practical_pass": "pracpassstartdt",
}
_GRADE_SUFFIX = ("기술사", "기능장", "산업기사", "기사", "기능사")


def owns(qual_id: str) -> bool:
    return bool(re.fullmatch(r"\d{4}", qual_id or ""))


_resp_cache: dict[tuple, tuple[float, list[dict]]] = {}
RESP_TTL_SEC = 3600


def _call(path: str, **params):
    """(실패 dict | None, items) — 성공한 응답은 1시간 캐시한다 (큐넷 응답이 느리다, NF3005)."""
    ck = (path, tuple(sorted(params.items())))
    hit = _resp_cache.get(ck)
    if hit and _time.time() - hit[0] < RESP_TTL_SEC:
        return None, hit[1]
    err, items = _call_uncached(path, **params)
    if err is None:
        _resp_cache[ck] = (_time.time(), items)
    return err, items


def _call_uncached(path: str, **params):
    """(실패 dict | None, items) — 키 · 원문 오류는 밖으로 내보내지 않는다."""
    key = (os.getenv("QNET_SERVICE_KEY") or "").strip()
    secure = QNET_BASE.lower().startswith("https://")
    if key and secure:            # 키는 암호화된 연결(HTTPS)로만 보낸다 — HTTP 면 평문으로 노출된다
        params["serviceKey"] = key
    res = None
    for _attempt in range(2):     # 일시적 끊김 · 시간 초과는 한 번 더
        try:
            res = requests.get(f"{QNET_BASE}/{path}", params=params, timeout=TIMEOUT)
            break
        except requests.RequestException:
            continue
    if res is None:
        return fail(UPSTREAM_ERROR, "큐넷 API 를 부르지 못했습니다."), None
    if res.status_code in (401, 403) or "SERVICE_KEY" in res.text:
        if not secure:
            return fail(INVALID_KEY, "큐넷이 서비스키를 요구합니다. 키는 HTTPS 로만 보내므로 HTTPS 주소(QNET_BASE)가 필요합니다."), None
        return fail(INVALID_KEY, "큐넷 서비스키가 없거나 틀렸습니다. QNET_SERVICE_KEY 를 확인하세요."), None
    if res.status_code != 200:
        return fail(UPSTREAM_ERROR, f"큐넷 API 오류 (HTTP {res.status_code})."), None
    try:
        root = ET.fromstring(res.content)
    except ET.ParseError:
        return fail(UPSTREAM_ERROR, "큐넷 API 가 예상 밖의 형식으로 응답했습니다."), None
    if root.findtext(".//resultCode") not in ("00", "0000"):
        return fail(UPSTREAM_ERROR, "큐넷 API 가 오류 코드를 돌려주었습니다."), None
    return None, [{c.tag: (c.text or "").strip() for c in it} for it in root.findall(".//item")]


_catalog: dict = {"at": 0.0, "rows": None}


def clear_cache() -> None:
    _catalog.update(at=0.0, rows=None)
    _pass_cache.clear()
    _resp_cache.clear()


def _grade_of(row: dict) -> str:
    if row.get("qualgbcd") == "S":
        return "전문자격"
    name = row.get("jmfldnm", "")
    # '사회조사분석사2급' · '컨벤션기획사1급' — 종목 목록의 계열(seriesnm)은 '기사' 로 오지만 합격률 통계 · 사다리는 1급 · 2급
    for suffix in ("1급", "2급"):
        if name.endswith(suffix):
            return suffix
    for suffix in _GRADE_SUFFIX:
        if name.endswith(suffix):
            return suffix
    return row.get("seriesnm") or "기타"


def list_quals():
    if _catalog["rows"] is not None and _time.time() - _catalog["at"] < CATALOG_TTL_SEC:
        return None, _catalog["rows"]
    err, rows = _call("InquiryListNationalQualifcationSVC/getList")
    if err:
        return err, None
    items = [{
        "qual_id": r.get("jmcd"),
        "name": r.get("jmfldnm"),
        "grade": _grade_of(r),
        "qual_type": r.get("qualgbnm") or None,
        "field": r.get("obligfldnm") or None,
        "sub_field": r.get("mdobligfldnm") or None,
        "organization": "한국산업인력공단",
        "source": NAME,
    } for r in rows if r.get("jmcd") and r.get("jmfldnm")]
    _catalog.update(at=_time.time(), rows=items)
    return None, items


def get_schedule(qual_id: str):
    """(실패 | None, rounds_raw, meta) — 형식은 sources/__init__.py 참고"""
    _, catalog = list_quals()
    info = next((q for q in catalog or [] if q["qual_id"] == qual_id), None)
    if catalog is not None and info is None:
        return fail(NOT_FOUND, f"종목코드 {qual_id} 는 큐넷 종목 목록에 없습니다."), None, None
    err, rows = _call("InquiryTestInformationNTQSVC/getJMList", jmCd=qual_id)
    if err:
        return err, None, None
    if not rows:
        return fail(NO_DATA, f"종목코드 {qual_id} 의 시험일정이 비어 있습니다."), None, None
    rounds = [{"name": r.get("implplannm", ""), "dates": {k: r.get(v) for k, v in _JM_FIELDS.items()},
               "stage": "필기+실기", "exam_time": None} for r in rows]
    # 응시료 · 시험정보 · 합격률은 부가 정보 — 실패해도 일정은 돌려준다 (값을 0 으로 채우지 않는다)
    _, frows = _call("InquiryTestInformationNTQSVC/getFeeList", jmCd=qual_id)
    fee_text = next((f.get("contents") for f in frows or [] if f.get("contents")), None)
    name = (info or {}).get("name") or rows[0].get("jmfldnm")
    return None, rounds, {
        "name": name,
        "grade": (info or {}).get("grade"),
        "organization": "한국산업인력공단",
        "source": LABEL,
        "fee": parse_fee(fee_text),
        "fee_text": fee_text,
        "exam_info": exam_info(qual_id),
        "pass_rate": pass_rate(qual_id, name),
    }


# ── 시험정보 (시험과목 · 검정방법 · 합격기준) ─────────────────────
def exam_info(qual_id: str) -> dict | None:
    _, rows = _call("InquiryInformationTradeNTQSVC/getList", jmCd=qual_id)
    text = next((r.get("contents") for r in rows or [] if r.get("infogb") == "취득방법"), None)
    parsed = parse_acquisition(text)
    return {**parsed, "source": f"{LABEL} — 종목별 취득방법"} if parsed else None


# ── 합격률 ────────────────────────────────────────────────────────
# 합격률 API 의 등급 코드 (2026-11-18 실제 호출로 확인)
GRADE_CODES = {"기술사": "10", "기능장": "20", "기사": "30", "산업기사": "31", "1급": "32", "2급": "33", "기능사": "40"}
PASS_RATE_YEARS_BACK = 2
_pass_cache: dict[tuple[str, str], list[dict]] = {}


def _grade_code(name: str, qual_id: str | None = None) -> str | None:
    """종목 목록의 등급이 먼저 — '미용사(일반)' 처럼 이름이 등급으로 끝나지 않는 종목도 있다"""
    if qual_id:
        _, catalog = list_quals()
        grade = next((q.get("grade") for q in catalog or [] if q["qual_id"] == qual_id), None)
        if grade in GRADE_CODES:
            return GRADE_CODES[grade]
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
    for suffix in ("산업기사", "기술사", "기능장", "기능사", "기사", "1급", "2급"):  # 산업기사를 기사보다 먼저
        if name.endswith(suffix):
            return GRADE_CODES[suffix]
    return None


def _int(s: str | None) -> int | None:
    return int(s) if s and s.isdigit() else None


def pass_rate(qual_id: str, name: str | None) -> dict | None:
    """가장 최근 집계 연도의 단계별 합격률. 올해 집계가 없으면 작년 → 재작년 순으로 (연도를 밝힌다)."""
    code = _grade_code(name or "", qual_id)
    if not code:
        return None
    this_year = _time.localtime().tm_year
    for year in range(this_year, this_year - PASS_RATE_YEARS_BACK - 1, -1):
        key = (str(year), code)
        if key not in _pass_cache:
            err, rows = _call("InquiryQualPassRateSVC/getList", baseYY=str(year), grdCd=code, numOfRows=3000, pageNo=1)
            if err:
                return None
            _pass_cache[key] = rows
        mine = [{"stage": r.get("examTypCcd"), "takers": _int(r.get("recptNoCnt")), "passed": _int(r.get("examPassCnt"))}
                for r in _pass_cache[key] if r.get("jmCd") == qual_id]
        summary = summarize_pass_rates(mine)
        if summary:
            return {"year": year, "by_stage": summary,
                    "basis": f"{year}년 회차별 합격자 합 ÷ 응시자 합 ({LABEL} — 합격률 통계)"}
    return None


# ── 인기: 최근 집계 연도의 최종 합격자 수 (≈ 그 해 취득자 수) ─────────
def popularity(qual_id: str, name: str | None) -> dict | None:
    """'사람들이 많이 따는 자격' 의 근거. 실기가 있으면 실기 합격자, 없으면 필기 합격자 합."""
    pr = pass_rate(qual_id, name)
    if not pr:
        return None
    stages = pr["by_stage"]
    final = stages.get("실기") or stages.get("면접") or stages.get("필기")
    if not final:
        return None
    stage = next(k for k in ("실기", "면접", "필기") if k in stages)
    return {"year": pr["year"], "acquired": final["passed"],
            "basis": f"{pr['year']}년 {stage} 합격자 {final['passed']:,}명 (큐넷 합격률 통계)"}
