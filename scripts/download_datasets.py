"""공공데이터포털 파일데이터(CSV)를 data/raw/ 로 내려받는다 — 자동변환 API 가 실패할 때의 예비 자료.

    ./venv/Scripts/python scripts/download_datasets.py            # 목록 전부
    ./venv/Scripts/python scripts/download_datasets.py 15155201   # 하나만

- 파일데이터는 로그인 없이 받을 수 있다 (포털 안내). 활용신청은 하지 않는다 — 그건 본인이 직접.
- 포털이 캡차(자동 입력 방지)를 요구하면 우회하지 않고 멈춘다. 남은 것은 브라우저에서 직접 받는다.
- 요청 사이에 쉬어서 포털에 부담을 주지 않는다.
- 받은 파일마다 컬럼 이름을 출력한다 (data/sources.json 연결용).
"""

from __future__ import annotations

import csv
import io
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw"
BASE = "https://www.data.go.kr"
PAUSE_SEC = 2.0

# docs/research/data_sources.md 의 파일데이터 (일정 · 판단 근거)
DATASETS = {
    "15155201": "한국사능력검정시험 일정",
    "15061941": "국시원 시험일정 정보",
    "15162720": "게임국가기술자격검정 시험일정",
    "15117003": "해기사 필기 시험(상시) 일정",
    "15115098": "해기사 필기 시험(정기) 일정",
    "15116999": "해기사 면접 시험(상시) 일정",
    "15115099": "해기사 면접 시험(정기) 일정",
    "15118963": "선박조리사 시험 일정",
    "15115100": "의료관리자 시험(정기) 일정",
    "15118964": "산지경매사 시험 일정",
    "15150011": "수산질병관리사 시험일정",
    "15120423": "환경영향평가사 자격시험 일정",
    "15119099": "산림복지전문가 시험일정",
    "15151128": "무대예술전문인 자격검정 시험 정보",
    "15150863": "의료통역검정시험 시행정보",
    "15171670": "한국광해광업공단 자격검정시험정보",
    "15119473": "항공종사자 자격시험 시행계획",
    "3048945": "철도자격(면허) 정보",
    "3033611": "국가공무원 시험일정",
    "15129287": "국가공무원 공채 상세일정",
    "15056419": "제주 지방공무원 임용시험 일정",
    "15062838": "데이터 자격검정 시험 정보",
    "15120651": "국가자격 시험면제과목 기준",
    "15137959": "국가기술자격시험 시험상호 면제 정보",
    "15090299": "국가전문자격정보 (한국직업능력연구원)",
    "15112802": "국가자격종목별 주무부처",
    "15132361": "한국사능력검정 회차별 시험 통계",
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class CaptchaRequired(Exception):
    pass


def _columns(raw: bytes) -> tuple[str, list[str], int]:
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            rows = list(csv.reader(io.StringIO(text)))
            return enc, rows[0] if rows else [], max(0, len(rows) - 1)
        except UnicodeDecodeError:
            continue
    return "?", [], 0


def download(session: requests.Session, pk: str) -> Path:
    page = session.get(f"{BASE}/data/{pk}/fileData.do", timeout=30).text
    m = re.search(r"fn_fileDataDown\('(\d+)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)'\)", page)
    if not m:
        raise RuntimeError("다운로드 버튼을 찾지 못함 (파일데이터가 아니거나 페이지 구조가 바뀜)")
    public_pk, detail_pk, atch, sn, _hist = m.groups()

    info = session.post(f"{BASE}/tcs/dss/selectFileDataDownload.do", timeout=30, data={
        "publicDataDetailPk": detail_pk, "publicDataPk": public_pk, "atchFileId": atch,
        "fileDetailSn": sn, "publicDataTyCode": "PR0051"}).json()
    if not info.get("status"):
        raise RuntimeError(f"다운로드 정보 요청 실패: {info.get('error') or '이유 없음'}")
    atch, sn = info["atchFileId"], info["fileDetailSn"]
    detail = info.get("dataSetFileDetailInfo", {})
    name = detail.get("dataNm") or detail.get("publicDataSj") or pk

    limit = session.post(f"{BASE}/cmm/cmm/check-limit.json", timeout=30, data={"atchFileId": atch, "fileDetailSn": sn})
    if limit.status_code == 403 or (limit.ok and limit.json().get("needCaptcha")):
        raise CaptchaRequired()

    res = session.get(f"{BASE}/cmm/cmm/fileDownload.do?atchFileId={atch}&fileDetailSn={sn}&dataNm={quote(name)}",
                      timeout=60)
    res.raise_for_status()
    ext = ".csv"
    cd = res.headers.get("Content-Disposition", "")
    m2 = re.search(r"\.(\w{2,5})\"?$", cd)
    if m2:
        ext = "." + m2.group(1).lower()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{pk}{ext}"
    path.write_bytes(res.content)
    return path


def main(ids: list[str]) -> int:
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (cert-planner dataset fetch)"
    done, failed = [], []
    for i, pk in enumerate(ids):
        label = DATASETS.get(pk, pk)
        try:
            path = download(session, pk)
        except CaptchaRequired:
            rest = ids[i:]
            print(f"\n⛔ 포털이 캡차를 요구해 멈춥니다. 남은 {len(rest)}건은 브라우저에서 직접 받아 data/raw/<번호>.csv 로 저장하세요:")
            for r in rest:
                print(f"   {BASE}/data/{r}/fileData.do  ({DATASETS.get(r, '')})")
            break
        except Exception as e:  # 한 건 실패해도 다음으로
            failed.append(pk)
            print(f"❌ {pk} {label}: {type(e).__name__} {str(e)[:100]}")
        else:
            enc, cols, n = _columns(path.read_bytes()) if path.suffix == ".csv" else ("-", [], 0)
            done.append(pk)
            print(f"✅ {pk} {label} → {path.relative_to(ROOT).as_posix()} ({n}행, {enc})")
            if cols:
                print(f"     컬럼: {cols}")
        time.sleep(PAUSE_SEC)
    print(f"\n완료 {len(done)} · 실패 {len(failed)} · 전체 {len(ids)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or list(DATASETS)))
