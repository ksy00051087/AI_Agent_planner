"""1일차 기획 검증 — 자격증 플래너의 외부 API 를 한 번씩 실제로 호출해 본다.

    python scripts/check_apis.py              # 전부
    python scripts/check_apis.py qnet_list    # 하나만 (qnet_list | qnet_schedule | book | kdata | gms)

확인하는 것
    ① 큐넷 종목 목록     (F3002 후보)  InquiryListNationalQualifcationSVC/getList — 613종목, 직무분야 코드
    ② 큐넷 종목별 일정   (F3003 상세)  InquiryTestInformationNTQSVC/getJMList — 접수·시험·발표일
    ③ 책 검색           (F3004 보조)  네이버 책 검색 또는 카카오 책 검색 (키가 있는 쪽)
    ④ 데이터진흥원 CSV   (F3002 보충, 선택) data/kdata_exam_schedule.csv — SQLD·ADsP 등
    ⑤ GMS               (LLM, 선택)

상태 코드
    OK / NO_KEY / INVALID_KEY / DISABLED / QUOTA / NO_DATA / UPSTREAM / SKIP

응답 원본은 docs/api_samples/ 에 저장한다 (키는 들어가지 않는다). Tool 출력 구조 대조와 제출용 근거로 쓴다.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "docs" / "api_samples"
KDATA_CSV = ROOT / "data" / "kdata_exam_schedule.csv"
load_dotenv(ROOT / ".env")

if hasattr(sys.stdout, "reconfigure"):  # Windows 콘솔 한글
    sys.stdout.reconfigure(encoding="utf-8")

TIMEOUT = 10
QNET_BASE = os.getenv("QNET_BASE") or "http://openapi.q-net.or.kr/api/service/rest"  # 큐넷은 HTTPS 미지원
SAMPLE_JMCD = ("1320", "정보처리기사")


class Result:
    def __init__(self, status: str, message: str = ""):
        self.status, self.message = status, message


def head(title: str) -> None:
    print(f"\n━━ {title} " + "━" * max(0, 60 - len(title)))


def line(label: str, value) -> None:
    print(f"   {label:<14} {value if value not in (None, '') else '∅ (비어 있음)'}")


def save(name: str, body, ext: str = "json") -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    path = SAMPLES / f"{name}.{ext}"
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    print(f"   (원본 저장: {path.relative_to(ROOT).as_posix()})")


def get_key(name: str) -> str | None:
    return (os.getenv(name) or "").strip() or None


def ymd(s: str | None) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if s and len(s) == 8 and s.isdigit() else "∅"


# ── 큐넷 공통 ─────────────────────────────────────────────────────
def _qnet(path: str, **params):
    """(Result | None, items) — 큐넷 레거시 엔드포인트는 현재 키 없이 응답한다.
    큐넷은 HTTP 만 받으므로 키는 보내지 않는다 (HTTPS 주소일 때만 보낸다 — 평문 노출 방지)."""
    key = get_key("QNET_SERVICE_KEY")
    if key and QNET_BASE.lower().startswith("https://"):
        params["serviceKey"] = key
    try:
        res = requests.get(f"{QNET_BASE}/{path}", params=params, timeout=TIMEOUT)
    except requests.RequestException as e:
        return Result("UPSTREAM", f"{path} 호출 실패 ({type(e).__name__})"), None
    text = res.text
    if "SERVICE_KEY" in text or res.status_code in (401, 403):
        return Result("INVALID_KEY", f"{path}: 서비스키 오류 (HTTP {res.status_code}) — 키 없이 쓰던 엔드포인트가 막혔다면 data.go.kr 활용신청 키를 QNET_SERVICE_KEY 에 넣는다"), None
    try:
        root = ET.fromstring(res.content)
    except ET.ParseError:
        return Result("UPSTREAM", f"{path}: XML 이 아닌 응답 (HTTP {res.status_code}) {text[:100]!r}"), None
    code = root.findtext(".//resultCode")
    if code not in ("00", "0000"):
        return Result("UPSTREAM", f"{path}: resultCode={code} {root.findtext('.//resultMsg')}"), None
    items = [{c.tag: (c.text or "").strip() for c in it} for it in root.findall(".//item")]
    return None, (items, text)


# ── ① 큐넷 종목 목록 ─────────────────────────────────────────────
def check_qnet_list() -> Result:
    head("① 큐넷 국가자격 종목 목록 (F3002 후보)")
    err, out = _qnet("InquiryListNationalQualifcationSVC/getList")
    if err:
        return err
    rows, raw = out
    save("qnet_getList", raw, "xml")
    if not rows:
        return Result("NO_DATA", "종목 목록이 비었습니다.")
    by_type: dict[str, int] = {}
    by_field: dict[str, int] = {}
    for r in rows:
        by_type[r.get("qualgbnm", "?")] = by_type.get(r.get("qualgbnm", "?"), 0) + 1
        f = r.get("obligfldnm") or "(분야 없음: 전문자격)"
        by_field[f] = by_field.get(f, 0) + 1
    line("총 종목", len(rows))
    line("자격 구분", by_type)
    line("직무분야 상위", sorted(by_field.items(), key=lambda kv: -kv[1])[:6])
    print("   예시 (직무분야 '경영.회계.사무'):")
    for r in [r for r in rows if r.get("obligfldcd") == "02"][:5]:
        print(f"     - {r['jmcd']}  {r['jmfldnm']}  [{r.get('seriesnm')} / {r.get('mdobligfldnm')}]")
    return Result("OK", f"{len(rows)}종목 ({', '.join(f'{k} {v}' for k, v in by_type.items())})")


# ── ② 큐넷 종목별 시험일정 ───────────────────────────────────────
def check_qnet_schedule() -> Result:
    head("② 큐넷 종목별 시험일정 (F3003 상세)")
    jmcd, name = SAMPLE_JMCD
    err, out = _qnet("InquiryTestInformationNTQSVC/getJMList", jmCd=jmcd)
    if err:
        return err
    rows, raw = out
    save(f"qnet_getJMList_{jmcd}", raw, "xml")
    if not rows:
        return Result("NO_DATA", f"{name}({jmcd}) 일정이 비었습니다.")
    years = sorted({r.get("implplannm", "")[:4] for r in rows})
    print(f"   [{name} {jmcd}] {len(rows)}개 회차, 수록 연도 {years}")
    for r in rows:
        print(f"     · {r.get('implplannm')}")
        print(f"         필기 접수 {ymd(r.get('docregstartdt'))}~{ymd(r.get('docregenddt'))}  시험 {ymd(r.get('docexamstartdt'))}~{ymd(r.get('docexamenddt'))}  발표 {ymd(r.get('docpassdt'))}")
        print(f"         실기 접수 {ymd(r.get('pracregstartdt'))}~{ymd(r.get('pracregenddt'))}  시험 {ymd(r.get('pracexamstartdt'))}~{ymd(r.get('pracexamenddt'))}")

    # 값이 비어 오는 실제 사례 (F3003 NO_DATA 설계 근거): 사회복지사 1급
    err, out = _qnet("InquiryTestInformationNTQSVC/getJMList", jmCd="9738")
    if not err:
        empty_rows, raw2 = out
        save("qnet_getJMList_9738_empty_dates", raw2, "xml")
        for r in empty_rows[:1]:
            line("빈 값 사례", f"{r.get('implplannm')} — 필기 시험일 {ymd(r.get('docexamstartdt'))}")
    next_year = str(date.today().year + 1)
    note = "" if next_year in years else f" · {next_year}년 일정 미공고 → 추정 처리 필요"
    return Result("OK", f"{name} {len(rows)}개 회차{note}")


# ── ③ 책 검색 (네이버 또는 카카오) ───────────────────────────────
def _kakao_book(query: str) -> Result:
    key = get_key("KAKAO_REST_API_KEY")
    try:
        res = requests.get("https://dapi.kakao.com/v3/search/book", timeout=TIMEOUT,
                           headers={"Authorization": f"KakaoAK {key}"}, params={"query": query, "size": 5})
    except requests.RequestException as e:
        return Result("UPSTREAM", f"카카오 호출 실패 ({type(e).__name__})")
    if res.status_code == 401:
        return Result("INVALID_KEY", "카카오 REST API 키가 틀렸습니다 (JavaScript 키가 아닌 REST API 키)")
    if res.status_code == 403:
        return Result("DISABLED", "카카오 앱에서 이 API 사용이 허용되지 않았습니다")
    if res.status_code == 429:
        return Result("QUOTA", "카카오 호출 한도 초과")
    if res.status_code != 200:
        return Result("UPSTREAM", f"HTTP {res.status_code} {res.text[:100]}")
    body = res.json()
    save("kakao_book", body)
    docs = body.get("documents", [])
    line("검색어", f"{query!r} (총 {body.get('meta', {}).get('total_count')}건)")
    for b in docs:
        print(f"     - {b.get('datetime', '')[:4]}  {b.get('title')[:45]}  / {', '.join(b.get('authors', []))} / {b.get('publisher')}  {b.get('sale_price')}원")
    return Result("OK", f"카카오 {len(docs)}건") if docs else Result("NO_DATA", "결과 없음")


def check_book() -> Result:
    head("③ 책 검색 (F3004 보조)")
    query = f"{SAMPLE_JMCD[1]} 필기"
    if get_key("KAKAO_REST_API_KEY"):
        return _kakao_book(query)
    return Result("NO_KEY", "KAKAO_REST_API_KEY 가 필요합니다.")


# ── ④ 데이터진흥원 CSV (선택) ────────────────────────────────────
def check_kdata() -> Result:
    head("④ 한국데이터산업진흥원 자격검정 시험정보 CSV (선택)")
    if not KDATA_CSV.exists():
        return Result("SKIP", f"{KDATA_CSV.relative_to(ROOT).as_posix()} 없음 — data.go.kr/data/15062838 에서 CSV 를 받아 이 이름으로 둔다")
    for enc in ("utf-8-sig", "cp949"):
        try:
            with KDATA_CSV.open(encoding=enc, newline="") as f:
                rows = list(csv.DictReader(f))
            break
        except UnicodeDecodeError:
            continue
    else:
        return Result("UPSTREAM", "CSV 인코딩을 읽지 못했습니다 (utf-8 / cp949 아님)")
    if not rows:
        return Result("NO_DATA", "CSV 가 비었습니다.")
    line("컬럼", list(rows[0].keys()))
    line("행 수", len(rows))
    for r in rows[:5]:
        print("     -", {k: v for k, v in r.items() if v})
    years = sorted({(r.get("시험일") or "")[:4] for r in rows if r.get("시험일")})
    return Result("OK", f"{len(rows)}행, 시험일 연도 {years}")


# ── ⑤ GMS (선택) ─────────────────────────────────────────────────
def check_gms() -> Result:
    head("⑤ SSAFY GMS (LLM, 선택)")
    key = get_key("GMS_API_KEY")
    if not key:
        return Result("NO_KEY", "GMS_API_KEY 가 .env 에 없습니다. (16시 게이트 대상은 아님)")
    base = (os.getenv("GMS_BASE_URL") or "https://gms.ssafy.io/gmsapi/api.openai.com/v1").rstrip("/")
    model = os.getenv("GMS_MODEL") or "gpt-4.1-mini"
    try:
        res = requests.post(f"{base}/chat/completions", timeout=30,
                            headers={"Authorization": f"Bearer {key}"},
                            json={"model": model, "messages": [{"role": "user", "content": "한 단어로 대답해: 안녕?"}]})
    except requests.RequestException as e:
        return Result("UPSTREAM", f"GMS 호출 실패 ({type(e).__name__})")
    if res.status_code in (401, 403):
        return Result("INVALID_KEY", f"HTTP {res.status_code} — GMS 키 확인")
    if res.status_code != 200:
        return Result("UPSTREAM", f"HTTP {res.status_code} {res.text[:150]}")
    line("모델", model)
    line("응답", res.json()["choices"][0]["message"]["content"].strip()[:60])
    return Result("OK", f"{model} 응답 수신")


CHECKS = {"qnet_list": check_qnet_list, "qnet_schedule": check_qnet_schedule, "book": check_book,
          "kdata": check_kdata, "gms": check_gms}
REQUIRED = ("qnet_list", "qnet_schedule", "book")


def main(argv: list[str]) -> int:
    names = argv or list(CHECKS)
    results: dict[str, Result] = {}
    for n in names:
        try:
            results[n] = CHECKS[n]()
        except Exception as e:  # 스크립트가 죽지 않게. 상세 메시지는 키가 섞일 수 있어 종류만
            results[n] = Result("UPSTREAM", f"예상 밖 오류 ({type(e).__name__})")

    print("\n━━ 요약 " + "━" * 54)
    for n, r in results.items():
        mark = {"OK": "✅", "NO_KEY": "⏭️ ", "SKIP": "⏭️ "}.get(r.status, "❌")
        print(f" {mark} {n:<14} {r.status:<12} {r.message}")
    req = [n for n in REQUIRED if n in results]
    passed = [n for n in req if results[n].status == "OK"]
    if len(req) == len(REQUIRED):
        print(f"\n 도메인 게이트(필수 3종): {len(passed)}/3 통과 — {datetime.now():%H:%M} 기준")
    return 0 if len(passed) == len(req) else 1


if __name__ == "__main__":
    unknown = [a for a in sys.argv[1:] if a not in CHECKS]
    if unknown:
        print(f"모르는 대상: {unknown}. 가능한 값: {list(CHECKS)}")
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
