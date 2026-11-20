"""개발용 서버 — app/ 의 .py 가 바뀌면 서버를 저절로 다시 켠다.

    ./venv/Scripts/python scripts/dev_server.py          # 8000 번
    ./venv/Scripts/python scripts/dev_server.py 8001     # 다른 포트

uvicorn --reload 를 쓰지 않는 이유: uvicorn 0.52 는 윈도우에서 재시작할 때 이전 서버에 Ctrl+C 를 보내고
시간 제한 없이 기다린다 (supervisors/basereload.py). 신호가 전달되지 않으면 'Reloading...' 에서 멈추고
예전 코드가 계속 응답한다. watchfiles.run_process 는 윈도우에서 이전 서버를 바로 끄고 새로 켠다.
화면(web/)과 설정(data/*.json)은 요청마다 읽으므로 서버를 다시 켤 필요 없이 브라우저 새로고침만 하면 된다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def serve(port: int) -> None:
    sys.path.insert(0, str(ROOT))
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=port)


def changed(changes) -> None:
    names = sorted({Path(p).relative_to(ROOT).as_posix() for _, p in changes})
    print(f"\n[dev_server] 코드가 바뀌어 서버를 다시 켭니다: {', '.join(names[:5])}", flush=True)


if __name__ == "__main__":
    from watchfiles import PythonFilter, run_process

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"[dev_server] http://localhost:{port} — app/ 코드가 바뀌면 저절로 다시 켭니다 (끄려면 Ctrl+C)", flush=True)
    run_process(ROOT / "app", target=serve, args=(port,), watch_filter=PythonFilter(), callback=changed)
