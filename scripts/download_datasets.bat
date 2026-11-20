@echo off
rem 공공데이터포털 파일데이터(CSV)를 data\raw 로 내려받는다. 더블클릭하거나 터미널에서 실행.
chcp 65001 > nul
cd /d "%~dp0.."
if exist venv\Scripts\python.exe (
    venv\Scripts\python.exe scripts\download_datasets.py %*
) else (
    python scripts\download_datasets.py %*
)
pause
