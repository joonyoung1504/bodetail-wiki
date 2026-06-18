@echo off
chcp 65001 > nul
title bodetail watchdog

REM ── API 키 설정 ──────────────────────────────────────────────
REM 아래 YOUR_KEY_HERE 를 실제 Anthropic API 키로 교체하세요.
REM 또는 Windows 시스템 환경변수에 ANTHROPIC_API_KEY 를 등록하면
REM 이 줄은 삭제해도 됩니다.
set ANTHROPIC_API_KEY=YOUR_KEY_HERE

REM ── Vault 경로 ───────────────────────────────────────────────
set VAULT=C:\Users\이준영\Desktop\옵시디언\bodetail-vault

REM ── Python 가상환경 (있을 경우 활성화) ──────────────────────
REM call %VAULT%\scripts\venv\Scripts\activate.bat

cd /d "%VAULT%"

echo [watchdog] bodetail-vault raw/ 감시를 시작합니다...
echo [watchdog] 종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo.

python scripts\watchdog.py

echo.
echo [watchdog] 스크립트가 종료되었습니다.
pause
