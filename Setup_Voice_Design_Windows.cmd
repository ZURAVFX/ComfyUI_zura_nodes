@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo Install uv first. See VOICE_DESIGN.md for setup instructions.
  pause
  exit /b 1
)
uv run --python 3.11 --no-project --no-config setup_voice_design.py --install
set result=%errorlevel%
pause
exit /b %result%
