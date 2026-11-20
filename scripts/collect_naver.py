"""NAVER API HUB 로 자격 정보 모으기 — 한도가 있어 한 번 모아 두고 쓴다 (대화 중에는 부르지 않는다).

    ./venv/Scripts/python scripts/collect_naver.py --dry-run     # 부를 횟수만 센다
    ./venv/Scripts/python scripts/collect_naver.py               # 모으기 (캐시 30일, 하루 상한 NAVER_HUB_DAILY_CAP)
    ./venv/Scripts/python scripts/build_index.py embed           # 모은 백과사전 문서까지 RAG 색인

모으는 것
  · 백과사전(네이버 지식백과) — 자격명과 제목이 같은 항목만 → data/rag/naver_docs.json (RAG 문서, 출처 링크 포함)
  · 블로그 "{자격} 다음 자격증" — 광고성 글(학점은행 · 상담 · 수강 …)을 빼고, 한 글에 함께 나오는 다른 자격을 센다
    → data/rag/co_mention.json  (비공식 근거. 화면에는 '블로그 후기 N건 중 M건 · 비공식' 으로만 쓴다)
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.tools import sources  # noqa: E402
from app.tools.sources import naver_hub  # noqa: E402

RAG = ROOT / "data" / "rag"
DOCS = RAG / "naver_docs.json"
CO = RAG / "co_mention.json"
BLOG_SIZE = 50
BLOG_MIN_ACQ = 300        # 큐넷 종목은 최근 합격자 300명 이상만 블로그를 본다 (한도 아끼기)
AD_WORDS = ("학점은행", "평생교육", "상담", "문의", "수강", "교육원", "할인", "카톡", "이벤트", "모집", "국비", "수강료", "등록금")
# 화면의 기본 자격 — 종목 목록에 없거나 줄여 부르는 이름
EXTRA_ALIASES = {"토익(TOEIC)": ["토익", "TOEIC"], "컴퓨터활용능력": ["컴퓨터활용능력", "컴활"],
                 "한국사능력검정시험": ["한국사능력검정", "한능검"]}


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(s or ""))).strip()


def norm(s: str) -> str:
    return re.sub(r"[\s·()\-]", "", s).lower()


def all_quals() -> list[dict]:
    seen, out = set(), []
    for src in sources.all_sources():
        err, qs = src.list_quals()
        for q in qs or []:
            if q["name"] in seen or "특례" in q["name"]:
                continue
            seen.add(q["name"])
            out.append(q)
    return out


def aliases(names: list[str]) -> dict[str, list[str]]:
    """이름 → 글에서 찾을 표기들. 'SQL 개발자(SQLD)' 는 'SQLD' 로도 찾는다."""
    out = {n: [n] for n in names}
    for n in names:
        m = re.search(r"\(([A-Za-z]{3,6})\)", n)
        if m:
            out[n].append(m.group(1))
    for n, al in EXTRA_ALIASES.items():
        out.setdefault(n, []).extend(a for a in al if a not in out.get(n, []))
    return out


def mentions(text: str, table: list[tuple[str, str]]) -> set[str]:
    """글 안에 나온 자격 — 긴 표기부터 찾고 찾은 자리는 지워서 '건축전기설비기술사' 안의 다른 이름을 또 세지 않는다."""
    t, found = norm(text), set()
    for alias, name in table:
        a = norm(alias)
        if len(a) >= 3 and a in t:
            found.add(name)
            t = t.replace(a, "#")
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-calls", type=int, default=1500, help="이번 실행에서 새로 부를 최대 횟수 (캐시는 안 셈)")
    args = ap.parse_args()

    quals = all_quals()
    for q in quals:
        q["acq"] = ((sources.qnet.popularity(q["qual_id"], q["name"]) or {}).get("acquired") or 0) if q["source"] == "qnet" else None
    blog_targets = [q for q in quals if q["source"] != "qnet" or (q["acq"] or 0) >= BLOG_MIN_ACQ]
    blog_targets += [{"name": n, "source": "basic"} for n in EXTRA_ALIASES if n not in {q["name"] for q in quals}]
    plan = [("encyc", q["name"], 5) for q in quals] + [("blog", f"{q['name']} 다음 자격증", BLOG_SIZE) for q in blog_targets]
    cached = sum(1 for k, qy, d in plan if naver_hub._cache_path(k, qy, d).exists())
    print(f"자격 {len(quals)}개 · 백과사전 {len(quals)}회 · 블로그 {len(blog_targets)}회 = {len(plan)}회 (캐시 있음 {cached}회)")
    print(f"오늘 이미 쓴 호출 {naver_hub.used_today()}회 / 하루 상한 {naver_hub.daily_cap()}회 · 이번 실행 최대 {args.max_calls}회")
    if args.dry_run:
        return 0

    results, new_calls, t0 = {}, 0, time.time()
    for i, (kind, query, disp) in enumerate(plan, 1):
        if not naver_hub._cache_path(kind, query, disp).exists():
            if new_calls >= args.max_calls:
                print(f"이번 실행 상한 {args.max_calls}회 — 멈춤. 다시 실행하면 이어서 (캐시)")
                break
            new_calls += 1
        try:
            results[(kind, query)] = naver_hub.search(kind, query, disp)
        except naver_hub.HubError as e:
            print(f"멈춤: {e.code} — {e}")
            if e.code in ("NO_KEY", "DAILY_CAP", "INVALID_KEY", "QUOTA_EXCEEDED"):
                break
        if i % 100 == 0:
            print(f"  {i}/{len(plan)} · 새 호출 {new_calls} ({time.time() - t0:.0f}s)")

    # 백과사전 → RAG 문서 (제목이 자격명과 같은 항목만)
    docs = []
    for q in quals:
        r = results.get(("encyc", q["name"]))
        for k, it in enumerate((r or {}).get("items") or []):
            title, desc = clean(it.get("title")), clean(it.get("description"))
            if norm(title) != norm(q["name"]) or len(desc) < 20:
                continue
            docs.append({"id": f"naver-encyc:{q['name']}:{k}", "text": f"{title}: {desc}", "qual_id": q.get("qual_id"),
                         "qual_name": q["name"], "kind": "백과사전", "source": "네이버 지식백과 (NAVER API HUB 검색)",
                         "url": it.get("link") or ""})
    DOCS.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")

    # 블로그 → 함께 언급 (광고성 글 제외)
    names = [q["name"] for q in quals] + [n for n in EXTRA_ALIASES if n not in {q["name"] for q in quals}]
    table = sorted(((a, n) for n, al in aliases(names).items() for a in al), key=lambda x: -len(norm(x[0])))
    co = {}
    for q in blog_targets:
        r = results.get(("blog", f"{q['name']} 다음 자격증"))
        if not r:
            continue
        kept, ads, with_ = 0, 0, Counter()
        for it in r.get("items") or []:
            text = f"{clean(it.get('title'))} {clean(it.get('description'))}"
            if any(w in text for w in AD_WORDS):
                ads += 1
                continue
            found = mentions(text, table)
            if q["name"] not in found:          # 이 자격을 다루지 않는 글은 세지 않는다
                continue
            kept += 1
            with_.update(found - {q["name"]})
        co[q["name"]] = {"posts": kept, "ads_removed": ads, "with": dict(with_.most_common(15))}
    CO.write_text(json.dumps({"_meta": {"collected": date.today().isoformat(), "query": "{자격} 다음 자격증",
                                        "per_query": BLOG_SIZE, "ad_words": AD_WORDS,
                                        "note": "블로그 검색 결과의 제목 · 요약에서 함께 나온 자격 수. 비공식 근거"},
                              **co}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"백과사전 문서 {len(docs)}개 → {DOCS.relative_to(ROOT).as_posix()}")
    print(f"함께 언급 {len(co)}개 자격 → {CO.relative_to(ROOT).as_posix()} · 새 호출 {new_calls}회 · 오늘 누적 {naver_hub.used_today()}회")
    return 0


if __name__ == "__main__":
    sys.exit(main())
