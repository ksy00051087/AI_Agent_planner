"""출처 어댑터: 표 형태 데이터 — 설정(data/sources.json) 한 줄로 새 출처를 붙인다. 코드 수정 없음.

지원 형태 (kind)
    csv      공공데이터포털 '파일데이터' CSV 를 내려받아 둔 것 (utf-8 / cp949 자동)
    odcloud  파일데이터의 자동변환 오픈API (api.odcloud.kr) — 응답 {"data": [ {컬럼: 값} ]}
    xml_api  공공데이터포털 일반 오픈API (apis.data.go.kr) — 응답 <item><태그>값</태그></item>

설정 항목 (data/sources.json 의 sources 배열 원소)
    id · label · organization · source_url · license    식별자 접두어와 출처 표시 (NF3007)
    kind          csv + path  |  odcloud + endpoint  |  xml_api + endpoint (+ params, year_param)
    key_env       키 환경변수 (기본 DATA_GO_KR_KEY)
    fallback_path API 가 실패하면 읽을 CSV (scripts/download_datasets.py 로 받은 것)
    year_param    xml_api 에서 연도를 인자로 받으면 그 인자 이름. 작년 · 올해 · 내년을 차례로 부른다
    field · sub_field · grade · qual_type     후보 검색용 분류
    qual_name_fixed   파일 하나가 자격 하나면 그 이름 (이때 columns.qual_name 은 없어도 된다)
    columns       정규화 이름 → 원본 컬럼명
                  qual_name · round · stage · exam_time · app.domain.schedule.FIELD_NAMES (written_* · practical_*)
    ranges        {원본 컬럼: [시작 필드, 끝 필드]} — '2025-09-24 ~ 2025-10-02' 처럼 한 칸에 범위가 든 경우
    name_stage_pattern  자격명에 단계가 붙은 경우의 정규식 (이름 그룹 name, 단계 그룹 stage). 예: '의사(실기)'
    stage_fixed   단계 컬럼이 없을 때 붙일 단계 이름
    name_map      원본 이름 → 대표 이름 (해마다 바뀐 이름 · '-필기/-실기' 묶기)
    row_filter    {컬럼: [허용 값, ...]}

행 하나 = 접수부터 시험까지 한 단계. 같은 회차가 시험장마다 반복되면 하나로 합친다.
날짜는 2026-01-30 · 2026.01.30 · 2026/01/30 · 20260130 을 받아들인다. 못 읽는 값은 비워 둔다 (추측하지 않는다).
"""

from __future__ import annotations

import csv
import json
import os
import re
import time as _time
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import requests

from app.domain.schedule import FIELD_NAMES

from ..base import INVALID_KEY, NO_DATA, NOT_FOUND, UPSTREAM_ERROR, fail

ROOT = Path(__file__).resolve().parents[3]
CONFIG_FILE = ROOT / "data" / "sources.json"
TIMEOUT = 15
TTL_SEC = 3600
PER_PAGE = 1000
MAX_PAGES = 10
KINDS = ("csv", "odcloud", "xml_api")

_cache: dict[str, tuple[float, list[dict]]] = {}


def clear_cache() -> None:
    _cache.clear()


def configs() -> list[dict]:
    try:
        body = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [c for c in body.get("sources", [])
            if c.get("id") and c.get("kind") in KINDS
            and (c.get("columns", {}).get("qual_name") or c.get("qual_name_fixed"))]


def to_ymd(value) -> str | None:
    """여러 날짜 표기 → 'YYYYMMDD'. 못 읽으면 None."""
    if value is None:
        return None
    m = re.search(r"(\d{4})\D?(\d{1,2})\D?(\d{1,2})", str(value))
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{y}{int(mo):02d}{int(d):02d}"


def split_range(value) -> tuple[str | None, str | None]:
    """'2025-09-24 ~ 2025-10-02' → ('20250924', '20251002'). 날짜가 하나면 (그 날, None)."""
    found = re.findall(r"\d{4}\D?\d{1,2}\D?\d{1,2}", str(value or ""))
    if not found:
        return None, None
    return to_ymd(found[0]), (to_ymd(found[1]) if len(found) > 1 else None)


def to_hm(value) -> str | None:
    """'09:00:00' · '9:00' → '09:00'. 못 읽으면 None."""
    m = re.search(r"(\d{1,2}):(\d{2})", str(value or ""))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def _read_csv(path: Path) -> list[dict]:
    for enc in ("utf-8-sig", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV 인코딩을 읽지 못했습니다")


def _key(cfg: dict, label: str):
    key_env = cfg.get("key_env", "DATA_GO_KR_KEY")
    key = (os.getenv(key_env) or "").strip()
    return (None if key else fail(INVALID_KEY, f"{label}: {key_env} 가 없습니다.")), key


def _http_error(res: requests.Response, label: str):
    if res.status_code in (401, 403):
        return fail(INVALID_KEY, f"{label}: 서비스키가 틀렸거나 활용신청이 안 되었습니다.")
    return fail(UPSTREAM_ERROR, f"{label}: HTTP {res.status_code}.")


def _fetch_odcloud(cfg: dict, label: str):
    err, key = _key(cfg, label)
    if err:
        return err, None
    rows: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        try:
            res = requests.get(cfg["endpoint"], timeout=TIMEOUT,
                               params={"serviceKey": key, "page": page, "perPage": PER_PAGE, "returnType": "JSON"})
        except requests.RequestException:
            return fail(UPSTREAM_ERROR, f"{label}: API 를 부르지 못했습니다."), None
        if res.status_code != 200:
            return _http_error(res, label), None
        try:
            body = res.json()
        except ValueError:
            return fail(UPSTREAM_ERROR, f"{label}: JSON 이 아닌 응답."), None
        batch = body.get("data", [])
        rows.extend(batch)
        if not batch or len(rows) >= int(body.get("totalCount") or 0):
            break
    return None, rows


def _fetch_xml_api(cfg: dict, label: str):
    err, key = _key(cfg, label)
    if err:
        return err, None
    year_param = cfg.get("year_param")
    this_year = date.today().year
    calls = [{year_param: str(y)} for y in (this_year - 1, this_year, this_year + 1)] if year_param else [{}]
    rows: list[dict] = []
    for extra in calls:
        try:
            res = requests.get(cfg["endpoint"], timeout=TIMEOUT, params={
                "serviceKey": key, "numOfRows": PER_PAGE, "pageNo": 1, **cfg.get("params", {}), **extra})
        except requests.RequestException:
            return fail(UPSTREAM_ERROR, f"{label}: API 를 부르지 못했습니다."), None
        if res.status_code != 200 or "SERVICE_KEY" in res.text:
            return _http_error(res, label) if res.status_code != 200 else fail(INVALID_KEY, f"{label}: 서비스키 오류."), None
        try:
            root = ET.fromstring(res.text.strip().encode("utf-8"))
        except ET.ParseError:
            return fail(UPSTREAM_ERROR, f"{label}: XML 이 아닌 응답."), None
        code = root.findtext(".//resultCode")
        if code not in (None, "00", "0000", "200"):
            if code in ("03", "301"):  # 그 해 데이터 없음 — 다른 해로 계속
                continue
            return fail(UPSTREAM_ERROR, f"{label}: resultCode={code}."), None
        rows.extend({c.tag: (c.text or "").strip() for c in it} for it in root.findall(".//item"))
    return None, rows


def _rows(cfg: dict):
    """(실패 | None, rows) — row_filter 적용 전 원본 행"""
    hit = _cache.get(cfg["id"])
    if hit and _time.time() - hit[0] < TTL_SEC:
        return None, hit[1]
    label = cfg.get("label", cfg["id"])
    if cfg["kind"] == "csv":
        path = ROOT / cfg.get("path", "")
        if not path.is_file():
            return fail(NO_DATA, f"{label}: 파일 {cfg.get('path')} 이 없습니다."), None
        try:
            rows = _read_csv(path)
        except (OSError, ValueError):
            return fail(UPSTREAM_ERROR, f"{label}: CSV 를 읽지 못했습니다."), None
    else:
        fetch = _fetch_odcloud if cfg["kind"] == "odcloud" else _fetch_xml_api
        err, rows = fetch(cfg, label)
        if err:
            # API 가 안 되면(키 · 활용신청 · 장애) 내려받아 둔 CSV 로 대체한다
            fallback = ROOT / cfg["fallback_path"] if cfg.get("fallback_path") else None
            if not (fallback and fallback.is_file()):
                return err, None
            try:
                rows = _read_csv(fallback)
            except (OSError, ValueError):
                return err, None
    _cache[cfg["id"]] = (_time.time(), rows)
    return None, rows


class TableSource:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.NAME = cfg["id"]
        self.prefix = f"{cfg['id']}:"
        self.cols = cfg.get("columns", {})
        self.name_map = cfg.get("name_map", {})
        self.row_filter = cfg.get("row_filter", {})
        pattern = cfg.get("name_stage_pattern")
        self.name_stage = re.compile(pattern) if pattern else None

    def owns(self, qual_id: str) -> bool:
        return (qual_id or "").startswith(self.prefix)

    def _name_stage(self, row: dict) -> tuple[str, str | None]:
        """(대표 자격명, 이름에서 떼어 낸 단계)"""
        if self.cfg.get("qual_name_fixed"):
            raw = self.cfg["qual_name_fixed"]
        else:
            raw = str(row.get(self.cols.get("qual_name", ""), "") or "").strip()
        stage = None
        if self.name_stage and raw:
            m = self.name_stage.match(raw)
            if m:
                raw, stage = m.group("name").strip(), m.group("stage")
        return self.name_map.get(raw, raw), stage

    def _kept(self, rows: list[dict]) -> list[dict]:
        return [r for r in rows
                if all(str(r.get(col, "")).strip() in allowed for col, allowed in self.row_filter.items())]

    def list_quals(self):
        err, rows = _rows(self.cfg)
        if err:
            return err, None
        names = sorted({self._name_stage(r)[0] for r in self._kept(rows)} - {""})
        return None, [{
            "qual_id": f"{self.prefix}{n}",
            "name": n,
            "grade": self.cfg.get("grade"),
            "qual_type": self.cfg.get("qual_type"),
            "field": self.cfg.get("field"),
            "sub_field": self.cfg.get("sub_field"),
            "organization": self.cfg.get("organization"),
            "source": self.NAME,
        } for n in names]

    def _round(self, name: str, name_stage: str | None, row: dict) -> dict:
        dates = {f: to_ymd(row.get(self.cols[f])) for f in FIELD_NAMES if self.cols.get(f)}
        for col, (start_f, end_f) in self.cfg.get("ranges", {}).items():
            start, end = split_range(row.get(col))
            # columns 로 이미 채운 값이 있으면 그대로 둔다
            if start and not dates.get(start_f):
                dates[start_f] = start
            if end_f and end and not dates.get(end_f):
                dates[end_f] = end
        round_no = str(row.get(self.cols.get("round", ""), "") or "").strip()
        stage = (str(row.get(self.cols.get("stage", ""), "") or "").strip() or name_stage
                 or self.cfg.get("stage_fixed"))
        label = f"{name} 제{round_no}회" if round_no.isdigit() else f"{name} {round_no}".strip()
        return {"name": f"{label} {stage}" if stage else label, "dates": dates, "stage": stage,
                "exam_time": to_hm(row.get(self.cols.get("exam_time", "")))}

    def get_schedule(self, qual_id: str):
        err, rows = _rows(self.cfg)
        if err:
            return err, None, None
        name = qual_id[len(self.prefix):]
        rounds, seen = [], set()
        for row in self._kept(rows):
            row_name, name_stage = self._name_stage(row)
            if row_name != name:
                continue
            r = self._round(name, name_stage, row)
            key = (r["name"], tuple(sorted(r["dates"].items())))
            if key in seen:  # 시험장마다 반복되는 같은 회차
                continue
            seen.add(key)
            rounds.append(r)
        if not rounds:
            return fail(NOT_FOUND, f"'{name}' 는 {self.cfg.get('label', self.NAME)} 에 없습니다."), None, None
        return None, rounds, {
            "name": name,
            "grade": self.cfg.get("grade"),
            "organization": self.cfg.get("organization"),
            "source": f"{self.cfg.get('label', self.NAME)} ({self.cfg.get('source_url', '출처 미기재')})",
            "fee": None,
            "fee_text": None,
        }
