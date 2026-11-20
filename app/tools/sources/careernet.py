"""커리어넷 직업정보 Open API (한국직업능력개발원) — 직업 목록 · 직업 상세(하는 일 · 관련 자격 · 학과 · 훈련 · 채용).

  · 목록(552개 직업, 10개씩 56쪽)은 한 번 받아 디스크에 30일 캐시
  · 상세는 직업마다 30일 캐시
  · 인증: CAREERNET_API_KEY (.env). 화면에는 출처 '커리어넷' 과 원문 링크를 함께 보여 준다
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
BASE = "https://www.career.go.kr/cnet/front/openapi"
CACHE = ROOT / "data" / "rag" / "careernet"
TTL = 30 * 24 * 3600
VIEW_URL = "https://www.career.go.kr/cnet/front/base/job/jobView.do?SEQ={seq}"
load_dotenv(ROOT / ".env")


class CareerNetError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _key() -> str:
    k = (os.getenv("CAREERNET_API_KEY") or "").strip()
    if not k:
        raise CareerNetError("NO_KEY", "CAREERNET_API_KEY 가 없습니다.")
    return k


def _get(path: str, **params) -> dict:
    try:
        res = requests.get(f"{BASE}/{path}", params={"apiKey": _key(), **params}, timeout=15)
    except requests.RequestException as e:
        raise CareerNetError("UPSTREAM_ERROR", "커리어넷을 부르지 못했습니다.") from e
    if res.status_code != 200:
        raise CareerNetError("UPSTREAM_ERROR", f"커리어넷 오류 (HTTP {res.status_code}).")
    body = res.json()
    err = (body.get("hashMap") or {}) if isinstance(body, dict) else {}
    if err.get("code") and str(err["code"]).startswith("-"):
        raise CareerNetError("INVALID_KEY", err.get("message") or "커리어넷 인증 실패")
    return body


def _cached(name: str, fetch) -> dict | list:
    path = CACHE / name
    if path.exists() and time.time() - path.stat().st_mtime < TTL:
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def list_jobs() -> list[dict]:
    """[{seq(=상세 번호 job_cd), job_nm, rel_job_nm, work, top_nm}]"""
    def fetch():
        out, page = [], 1
        while True:
            body = _get("jobs.json", pageIndex=page)
            jobs = body.get("jobs") or []
            # 상세(job.json?seq=) 의 번호는 목록의 job_cd 다 (목록의 seq 는 다른 번호 — 넣으면 엉뚱한 직업이 온다)
            out += [{"seq": j.get("job_cd"), **{k: j.get(k) for k in ("job_nm", "rel_job_nm", "work", "top_nm")}} for j in jobs]
            if not jobs or len(out) >= int(body.get("count") or 0):
                return out
            page += 1
    return _cached("jobs-v2.json", fetch)


def job_detail(seq: int) -> dict:
    return _cached(f"job-{int(seq)}.json", lambda: _get("job.json", seq=int(seq)))


def _norm(s: str | None) -> str:
    return re.sub(r"[\sㆍ·,()\-/]", "", s or "").lower()


def _bigrams(s: str) -> set[str]:
    s = _norm(s)
    return {s[i:i + 2] for i in range(len(s) - 1)} or ({s} if s else set())


# 직업 이름의 꼬리말 — '전기 엔지니어' 에서 '엔지니어' 만 겹치는 직업이 위로 오지 않게, 꼬리말을 뗀 핵심 낱말로 먼저 찾는다
_TAILS = ("엔지니어", "기술자", "전문가", "관리자", "개발자", "분석가", "설계사", "디자이너", "연구원", "매니저", "담당자", "종사자")


def _core_words(name: str) -> list[str]:
    out = []
    for w in re.split(r"[\s·,/]+", name or ""):
        for t in _TAILS:
            if w.endswith(t) and len(w) > len(t):
                w = w[: -len(t)]
                break
        if len(_norm(w)) >= 2 and w not in _TAILS:
            out.append(_norm(w))
    return out


def candidates(name: str, limit: int = 20) -> list[dict]:
    """같은 직업일 수 있는 커리어넷 직업 — LLM 이 이 중에서만 고른다.
    ① 핵심 낱말(꼬리말 뗀 것)이 직업명 · 관련 직업명에 들어간 직업  ② 글자(2글자 단위)가 많이 겹치는 직업"""
    q = _bigrams(name)
    if not q:
        return []
    core = _core_words(name)
    scored = []
    for j in list_jobs():
        names = [n for n in [j["job_nm"], *re.split(r"[,ㆍ]", j.get("rel_job_nm") or "")] if n.strip()]
        overlap = max(len(q & _bigrams(n)) / len(q) for n in names)
        hit = any(w in _norm(n) for w in core for n in names)
        if hit or overlap > 0:
            scored.append((1 + overlap if hit else overlap, j))
    scored.sort(key=lambda x: -x[0])
    return [{"seq": j["seq"], "job_nm": j["job_nm"], "rel_job_nm": j.get("rel_job_nm") or ""} for _, j in scored[:limit]]


def _texts(rows, key: str) -> list[str]:
    return [re.sub(r"\s+", " ", (r.get(key) or "")).strip() for r in rows or [] if (r.get(key) or "").strip()]


def _other_job(text: str, names: list[str]) -> str | None:
    """'소믈리에가 되기 위해 …' 처럼 다른 직업 이야기면 그 직업 이름 (커리어넷 원문의 입력 오류를 거른다)"""
    m = re.search(r"([가-힣A-Za-z ·ㆍ()]+?)(?:이|가)\s*되기\s*위해", text)
    if not m:
        return None
    said = m.group(1).strip().split()[-1] if m.group(1).strip() else ""
    if len(_norm(said)) < 2:
        return None
    ok = any(len(_bigrams(said) & _bigrams(n)) / max(1, len(_bigrams(said))) >= 0.5 for n in names if n.strip())
    return None if ok else said


def profile(seq: int) -> dict:
    """직업 상세를 화면에 쓸 모양으로 — 원문 그대로 (요약 · 바꿔 쓰기 없음)"""
    d = job_detail(seq)
    base, ready = d.get("baseInfo") or {}, d.get("jobReadyList") or {}
    names = [base.get("job_nm") or "", *re.split(r"[,ㆍ]", base.get("rel_job_nm") or "")]
    certs = _texts(ready.get("certificate"), "certificate")
    other = next((o for o in (_other_job(t, names) for t in certs) if o), None)
    return {"seq": int(seq), "name": base.get("job_nm") or "", "url": VIEW_URL.format(seq=int(seq)),
            "related": base.get("rel_job_nm") or "",
            "work": _texts(d.get("workList"), "work"),
            "certificate": [] if other else certs,
            "certificate_issue": (f"커리어넷 원문의 관련 자격 설명이 다른 직업('{other}') 내용이라 쓰지 않았습니다."
                                  if other else None),
            "curriculum": _texts(ready.get("curriculum"), "curriculum"),
            "training": _texts(ready.get("training"), "training"),
            "recruit": _texts(ready.get("recruit"), "recruit"),
            "source": "커리어넷 직업정보 (한국직업능력개발원)"}
