"""캘린더 구현체 (F3023) — 같은 입출력의 두 구현: 로컬(SQLite) · Google Calendar.

구현체가 지킬 모양
    list_events(date_from: str, date_to: str) -> [{"event_id", "title", "date", "start_time", "end_time", "all_day", "link"}]
    create_event(title, date, start_time, end_time, description) -> {"event_id", "link"}
    name: str   ("local" | "google")
날짜는 YYYY-MM-DD, 시각은 HH:MM (모르면 None → 하루 종일 일정).
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOOGLE_DIR = ROOT / "data" / "google"
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
TZ = "Asia/Seoul"


class CalendarUnavailable(Exception):
    """인증 파일 · 토큰이 없거나 만료되어 쓸 수 없다."""


# ── 로컬 ─────────────────────────────────────────────────────────
class LocalCalendar:
    name = "local"

    def __init__(self, path: Path | str):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("""CREATE TABLE IF NOT EXISTS calendar_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, date TEXT NOT NULL,
                start_time TEXT, end_time TEXT, description TEXT, created_at TEXT NOT NULL)""")
            self._conn.commit()

    def list_events(self, date_from: str, date_to: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM calendar_events WHERE date BETWEEN ? AND ? ORDER BY date, start_time",
                                      (date_from, date_to)).fetchall()
        return [{"event_id": str(r["event_id"]), "title": r["title"], "date": r["date"], "start_time": r["start_time"],
                 "end_time": r["end_time"], "all_day": r["start_time"] is None, "link": None} for r in rows]

    def create_event(self, title: str, date_: str, start_time: str | None, end_time: str | None,
                     description: str | None) -> dict:
        with self._lock:
            cur = self._conn.execute("INSERT INTO calendar_events (title, date, start_time, end_time, description, created_at) "
                                     "VALUES (?,?,?,?,?,?)", (title, date_, start_time, end_time, description,
                                                              datetime.now().isoformat(timespec="seconds")))
            self._conn.commit()
        return {"event_id": str(cur.lastrowid), "link": None}


# ── Google ───────────────────────────────────────────────────────
def google_credentials(interactive: bool = False):
    """data/google/token.json 을 읽는다. 없거나 만료되면 interactive=True 일 때만 브라우저 로그인."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token, secret = GOOGLE_DIR / "token.json", GOOGLE_DIR / "credentials.json"
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception:
            creds = None  # 테스트 모드 토큰은 7일 뒤 만료 — 다시 로그인해야 한다
    if not interactive:
        raise CalendarUnavailable("Google 로그인이 필요합니다 (scripts/google_login.py).")
    if not secret.exists():
        raise CalendarUnavailable("data/google/credentials.json 이 없습니다.")
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES).run_local_server(port=0)
    GOOGLE_DIR.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json(), encoding="utf-8")
    return creds


class GoogleCalendar:
    name = "google"

    def __init__(self, calendar_id: str = "primary"):
        self.calendar_id = calendar_id
        self._svc = None

    def _service(self):
        if self._svc is None:
            from googleapiclient.discovery import build

            self._svc = build("calendar", "v3", credentials=google_credentials(), cache_discovery=False)
        return self._svc

    def list_events(self, date_from: str, date_to: str) -> list[dict]:
        end = (date.fromisoformat(date_to) + timedelta(days=1)).isoformat()
        out, page = [], None
        while True:
            res = self._service().events().list(
                calendarId=self.calendar_id, timeMin=f"{date_from}T00:00:00+09:00", timeMax=f"{end}T00:00:00+09:00",
                singleEvents=True, orderBy="startTime", maxResults=250, pageToken=page).execute()
            for e in res.get("items", []):
                s, t = e.get("start", {}), e.get("end", {})
                all_day = "date" in s
                out.append({"event_id": e["id"], "title": e.get("summary") or "(제목 없음)",
                            "date": s.get("date") or s.get("dateTime", "")[:10],
                            "start_time": None if all_day else s["dateTime"][11:16],
                            "end_time": None if all_day else t.get("dateTime", "")[11:16] or None,
                            "all_day": all_day, "link": e.get("htmlLink")})
            page = res.get("nextPageToken")
            if not page or len(out) >= 1000:
                return out

    def create_event(self, title: str, date_: str, start_time: str | None, end_time: str | None,
                     description: str | None) -> dict:
        if start_time:
            end = end_time or (datetime.strptime(start_time, "%H:%M") + timedelta(hours=2)).strftime("%H:%M")
            body = {"start": {"dateTime": f"{date_}T{start_time}:00", "timeZone": TZ},
                    "end": {"dateTime": f"{date_}T{end}:00", "timeZone": TZ}}
        else:
            nxt = (date.fromisoformat(date_) + timedelta(days=1)).isoformat()
            body = {"start": {"date": date_}, "end": {"date": nxt}}
        e = self._service().events().insert(calendarId=self.calendar_id,
                                            body={"summary": title, "description": description or "", **body}).execute()
        return {"event_id": e["id"], "link": e.get("htmlLink")}
