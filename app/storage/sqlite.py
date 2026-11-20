"""SQLite 저장소 (Frameworks & Drivers) — 계획(F3015 · F3016)과 실행 로그(F3013 · F3014).

라우터는 이 파일의 PlanStore · LogStore 메서드만 안다. 실행 로그에는 수정 메서드가 없다.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from app.domain.planning import find_overlaps

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "app.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    plan_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id     TEXT,             -- 같은 대화에서 함께 저장한 계획 묶음
    qual_id      TEXT,
    qual_name    TEXT NOT NULL,
    stage        TEXT,
    round_name   TEXT,
    plan_date    TEXT NOT NULL,    -- 시험일 YYYY-MM-DD
    start_time   TEXT,             -- HH:MM (모르면 NULL)
    end_time     TEXT,
    practical_date TEXT,
    registration_end TEXT,
    study_start  TEXT,
    estimated    INTEGER NOT NULL DEFAULT 0,
    source       TEXT,
    memo         TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    run_id     TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    ts         TEXT NOT NULL,
    type       TEXT NOT NULL,
    node       TEXT,
    payload    TEXT NOT NULL      -- 이벤트 나머지 필드 (JSON)
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, id);
CREATE TABLE IF NOT EXISTS inspections (   -- F3020 판정(규칙)과 진단(LLM)을 칸으로 나눠 저장
    run_id      TEXT PRIMARY KEY,
    session_id  TEXT,
    verdict     TEXT NOT NULL,         -- 정상 · 이상 · 판정 불가
    warnings    TEXT NOT NULL,         -- JSON
    reason      TEXT,
    counts      TEXT,
    diagnosis   TEXT,                  -- 이상일 때만, LLM 진단 (경고 수에 섞지 않는다)
    diagnosis_status TEXT,             -- NULL(대상 아님) · pending · ok · failed
    created_at  TEXT NOT NULL
);
"""

PLAN_FIELDS = ("group_id", "qual_id", "qual_name", "stage", "round_name", "plan_date", "start_time", "end_time",
               "practical_date", "registration_end", "study_start", "estimated", "source", "memo")
EDITABLE = ("qual_name", "stage", "round_name", "plan_date", "start_time", "end_time", "practical_date",
            "registration_end", "study_start", "memo")


class Database:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["estimated"] = bool(d.get("estimated"))
    return d


class PlanStore:
    def __init__(self, db: Database):
        self.db = db

    def _overlaps(self, conn, plan: dict) -> list[dict]:
        same_day = [_row(r) for r in conn.execute("SELECT * FROM plans WHERE plan_date = ?", (plan["plan_date"],))]
        mine = {**plan, "plan_date": date.fromisoformat(plan["plan_date"])}
        others = [{**p, "plan_date": date.fromisoformat(p["plan_date"])} for p in same_day]
        hits = find_overlaps(mine, others)
        return [{k: (v.isoformat() if isinstance(v, date) else v) for k, v in h.items()} for h in hits]

    def create(self, plan: dict) -> tuple[dict, list[dict]]:
        """저장은 막지 않는다. 같은 날짜 · 겹치는 시간의 기존 계획을 함께 돌려준다 (F3015)."""
        now = _now()
        values = {f: plan.get(f) for f in PLAN_FIELDS}
        values["estimated"] = int(bool(values["estimated"]))
        with self.db.tx() as conn:
            overlaps = self._overlaps(conn, values)
            cur = conn.execute(
                f"INSERT INTO plans ({', '.join(PLAN_FIELDS)}, created_at, updated_at) "
                f"VALUES ({', '.join('?' * len(PLAN_FIELDS))}, ?, ?)", (*values.values(), now, now))
            saved = _row(conn.execute("SELECT * FROM plans WHERE plan_id = ?", (cur.lastrowid,)).fetchone())
        return saved, overlaps

    def list(self) -> list[dict]:
        with self.db.tx() as conn:
            return [_row(r) for r in conn.execute("SELECT * FROM plans ORDER BY plan_date, start_time, plan_id")]

    def get(self, plan_id: int) -> dict | None:
        with self.db.tx() as conn:
            r = conn.execute("SELECT * FROM plans WHERE plan_id = ?", (plan_id,)).fetchone()
        return _row(r) if r else None

    def update(self, plan_id: int, changes: dict) -> tuple[dict | None, list[dict]]:
        changes = {k: v for k, v in changes.items() if k in EDITABLE}
        with self.db.tx() as conn:
            if not conn.execute("SELECT 1 FROM plans WHERE plan_id = ?", (plan_id,)).fetchone():
                return None, []
            if changes:
                sets = ", ".join(f"{k} = ?" for k in changes)
                conn.execute(f"UPDATE plans SET {sets}, updated_at = ? WHERE plan_id = ?",
                             (*changes.values(), _now(), plan_id))
            saved = _row(conn.execute("SELECT * FROM plans WHERE plan_id = ?", (plan_id,)).fetchone())
            overlaps = self._overlaps(conn, saved)  # 자기 자신은 find_overlaps 가 뺀다
        return saved, overlaps

    def delete(self, plan_id: int) -> bool:
        with self.db.tx() as conn:
            return conn.execute("DELETE FROM plans WHERE plan_id = ?", (plan_id,)).rowcount > 0


class LogStore:
    """실행 로그 — 덧붙이기 · 조회 · 삭제만. 수정은 없다 (F3014)."""

    COMMON = ("session_id", "run_id", "seq", "ts", "type", "node")

    def __init__(self, db: Database):
        self.db = db

    def append(self, event: dict) -> None:
        payload = {k: v for k, v in event.items() if k not in self.COMMON}
        with self.db.tx() as conn:
            conn.execute("INSERT INTO events (session_id, run_id, seq, ts, type, node, payload) VALUES (?,?,?,?,?,?,?)",
                         (*(event.get(k) for k in self.COMMON), json.dumps(payload, ensure_ascii=False, default=str)))

    def sessions(self) -> list[dict]:
        with self.db.tx() as conn:
            rows = conn.execute(
                "SELECT session_id, COUNT(DISTINCT run_id) AS runs, COUNT(*) AS events, MIN(ts) AS started_at, "
                "MAX(ts) AS last_at, SUM(type = 'replan') AS replans, SUM(type = 'error') AS errors, "
                "SUM(type = 'tool_result' AND json_extract(payload, '$.ok') = 0) AS tool_failures "
                "FROM events GROUP BY session_id ORDER BY last_at DESC").fetchall()
        return [dict(r) for r in rows]

    def events(self, session_id: str) -> list[dict]:
        with self.db.tx() as conn:
            rows = conn.execute("SELECT * FROM events WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()
        return [{**{k: r[k] for k in self.COMMON}, **json.loads(r["payload"])} for r in rows]

    def delete(self, session_id: str) -> int:
        with self.db.tx() as conn:
            conn.execute("DELETE FROM inspections WHERE session_id = ?", (session_id,))
            return conn.execute("DELETE FROM events WHERE session_id = ?", (session_id,)).rowcount

    # ── F3020 이상 징후 판정 · 진단 ────────────────────────────────
    def save_inspection(self, r: dict) -> None:
        status = "pending" if r["verdict"] == "이상" else None
        with self.db.tx() as conn:
            conn.execute("INSERT OR REPLACE INTO inspections (run_id, session_id, verdict, warnings, reason, counts, "
                         "diagnosis, diagnosis_status, created_at) VALUES (?,?,?,?,?,?,NULL,?,?)",
                         (r["run_id"], r["session_id"], r["verdict"], json.dumps(r["warnings"], ensure_ascii=False),
                          r.get("reason"), json.dumps(r.get("counts") or {}), status, _now()))

    def save_diagnosis(self, run_id: str, text: str | None, status: str) -> None:
        with self.db.tx() as conn:
            conn.execute("UPDATE inspections SET diagnosis = ?, diagnosis_status = ? WHERE run_id = ?",
                         (text, status, run_id))

    def inspections(self, session_id: str) -> list[dict]:
        with self.db.tx() as conn:
            rows = conn.execute("SELECT * FROM inspections WHERE session_id = ? ORDER BY created_at, rowid",
                                (session_id,)).fetchall()
        return [{**dict(r), "warnings": json.loads(r["warnings"]), "counts": json.loads(r["counts"] or "{}")}
                for r in rows]

    def latest_inspection(self, session_id: str) -> dict | None:
        rows = self.inspections(session_id)
        return rows[-1] if rows else None
