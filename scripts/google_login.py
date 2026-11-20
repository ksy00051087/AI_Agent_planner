"""Google Calendar 첫 로그인 (F3023) — 브라우저가 열리면 테스트 사용자로 등록한 Gmail 로 로그인 · 허용.

    ./venv/Scripts/python scripts/google_login.py

필요: data/google/credentials.json (OAuth 데스크톱 앱 클라이언트). 결과: data/google/token.json (git 제외).
'Google 에서 확인하지 않은 앱' 경고는 테스트 앱이라 정상 → 고급 → 이동 → 허용.
그다음 .env 에 CALENDAR_BACKEND=google 을 넣고 서버를 다시 켠다.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.calendar import GoogleCalendar, google_credentials  # noqa: E402

google_credentials(interactive=True)
today = date.today()
events = GoogleCalendar().list_events(today.isoformat(), (today + timedelta(days=30)).isoformat())
print(f"로그인 완료 · 앞으로 30일 일정 {len(events)}건을 읽었습니다. (data/google/token.json 저장)")
