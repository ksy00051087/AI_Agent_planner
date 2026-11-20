"""RAG 색인 만들기 (F3022) — 자격 정보 문서를 모아 Chroma 에 넣는다.

    ./venv/Scripts/python scripts/build_index.py fetch     # 1) 문서 모으기 → data/rag/docs.json (API 호출, 임베딩 없음)
    ./venv/Scripts/python scripts/build_index.py embed     # 2) 임베딩 · 색인 → data/rag/chroma (GMS 임베딩)
    ./venv/Scripts/python scripts/build_index.py           # 1 + 2

문서 출처
    · 큐넷 종목별 취득방법 · 출제경향 (InquiryInformationTradeNTQSVC, 613종목) — 시험과목 · 검정방법 · 합격기준 · 응시자격 안내
    · 한국직업능력연구원 국가전문자격정보 (data/raw/15090299.csv) — 소관부처 · 시행기관 · 홈페이지 · 관련법
    · 네이버 지식백과 (data/rag/naver_docs.json, scripts/collect_naver.py 로 먼저 모은다) — embed 단계에서 함께 넣는다
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.rag import store  # noqa: E402
from app.tools.sources import qnet, table  # noqa: E402

RAG_DIR = ROOT / "data" / "rag"
DOCS = RAG_DIR / "docs.json"
CHUNK = 900
INFOS = ("취득방법", "출제경향")   # '출제기준' 은 "자료실을 보라" 는 안내문뿐이라 뺀다
QNET_PAGE = "https://www.q-net.or.kr/crf005.do?id=crf00503&jmCd={jmcd}"


def clean(text: str) -> str:
    t = html.unescape(text or "").replace("\r", "\n")
    t = re.sub(r"<[^>]+>", " ", t)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in t.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def chunks(text: str, size: int = CHUNK) -> list[str]:
    out, buf = [], ""
    for para in text.split("\n"):
        if len(buf) + len(para) + 1 > size and buf:
            out.append(buf)
            buf = ""
        buf = f"{buf}\n{para}" if buf else para
    if buf:
        out.append(buf)
    return out


def fetch() -> list[dict]:
    err, quals = qnet.list_quals()
    if err:
        raise SystemExit(f"큐넷 종목 목록 실패: {err['error']['message']}")
    print(f"큐넷 {len(quals)}종목의 취득방법 · 출제경향을 받습니다 (동시 6개)…")

    def one(q):
        e, rows = qnet._call("InquiryInformationTradeNTQSVC/getList", jmCd=q["qual_id"])
        return q, ([] if e else rows)

    docs, t0 = [], time.time()
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, (q, rows) in enumerate(pool.map(one, quals), 1):
            for r in rows:
                if r.get("infogb") not in INFOS:
                    continue
                text = clean(r.get("contents"))
                if len(text) < 30:
                    continue
                for k, part in enumerate(chunks(text)):
                    docs.append({"id": f"qnet:{q['qual_id']}:{r['infogb']}:{k}", "text": part,
                                 "qual_id": q["qual_id"], "qual_name": q["name"], "kind": r["infogb"],
                                 "source": "큐넷 국가자격 종목별 정보 (한국산업인력공단)",
                                 "url": QNET_PAGE.format(jmcd=q["qual_id"])})
            if i % 100 == 0:
                print(f"  {i}/{len(quals)} ({time.time() - t0:.0f}s)")

    csv_path = ROOT / "data" / "raw" / "15090299.csv"
    if csv_path.exists():
        for i, r in enumerate(table._read_csv(csv_path)):
            name = (r.get("자격명") or "").strip()
            if not name:
                continue
            text = (f"{name} ({r.get('등급') or '등급 없음'}) — 소관부처 {r.get('소관부처')}, 시행기관 {r.get('시행기관')}. "
                    f"관련법 {r.get('관련법')}. 시행기관 홈페이지 {r.get('시행기관홈페이지')}. {r.get('비고') or ''}").strip()
            docs.append({"id": f"krivet:{i}", "text": text, "qual_id": None, "qual_name": name, "kind": "시행기관",
                         "source": "한국직업능력연구원 국가전문자격정보 (공공데이터포털 15090299)",
                         "url": r.get("시행기관홈페이지") or "https://www.data.go.kr/data/15090299/fileData.do"})
    else:
        print("data/raw/15090299.csv 없음 — scripts/download_datasets.py 로 받으면 시행기관 문서도 들어갑니다.")

    RAG_DIR.mkdir(parents=True, exist_ok=True)
    DOCS.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    chars = sum(len(d["text"]) for d in docs)
    print(f"문서 {len(docs)}개 · {chars:,}자 → {DOCS.relative_to(ROOT).as_posix()}")
    return docs


def embed() -> None:
    docs = json.loads(DOCS.read_text(encoding="utf-8"))
    naver = RAG_DIR / "naver_docs.json"           # scripts/collect_naver.py 가 모은 네이버 지식백과 문서
    if naver.exists():
        extra = json.loads(naver.read_text(encoding="utf-8"))
        docs += extra
        print(f"네이버 지식백과 문서 {len(extra)}개 추가")
    n = store.rebuild(docs, progress=lambda done, total: print(f"  임베딩 {done}/{total}"))
    print(f"색인 완료: {n}개 문서 → {store.CHROMA_DIR.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("fetch", "all"):
        fetch()
    if step in ("embed", "all"):
        embed()
