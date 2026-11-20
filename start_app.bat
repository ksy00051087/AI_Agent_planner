@echo off
rem 자격증 장기 플래너 실행 — 더블클릭하면 서버를 켜고 브라우저를 연다. 끄려면 이 창을 닫는다.
chcp 65001 > nul
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
    echo [안내] venv 가 없습니다. 처음 한 번:  python -m venv venv  ^&^&  venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)
if not exist .env (
    echo [안내] .env 가 없습니다. .env.example 을 .env 로 복사하고 키를 채우세요.
    pause
    exit /b 1
)
netstat -ano | findstr ":8000 " | findstr LISTENING > nul && (
    echo 이미 8000 번 포트에서 서버가 실행 중입니다.
    echo 예전 방식으로 켠 서버면 코드를 고쳐도 반영되지 않습니다.
    choice /c RB /n /m "[R] 끄고 자동 재시작 서버로 다시 켜기   [B] 브라우저만 열기 : "
    if errorlevel 2 (
        start "" http://localhost:8000
        exit /b 0
    )
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do taskkill /f /t /pid %%p > nul 2>&1
    timeout /t 2 > nul
)
echo 서버를 켭니다... (이 창을 닫으면 서버가 꺼집니다)
start "" cmd /c "timeout /t 4 > nul && start http://localhost:8000"
rem app 폴더 코드가 바뀌면 서버가 저절로 다시 켜진다 (scripts/dev_server.py — 윈도우에서 uvicorn --reload 가 멈추는 문제를 피함)
rem web/ 화면과 data/*.json 은 브라우저 새로고침만 하면 반영
venv\Scripts\python.exe scripts\dev_server.py 8000
pause
