@echo off
cd /d "%~dp0"
where uv >nul 2>&1
if errorlevel 1 (
  echo Install uv and Git first. See LONGCAT.md.
  pause
  exit /b 1
)
uv run --python 3.11 --no-project --no-config setup_longcat.py --install
if errorlevel 1 echo Setup failed. Read the message above before retrying.
pause
