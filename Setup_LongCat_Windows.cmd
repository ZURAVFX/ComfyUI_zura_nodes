@echo off
cd /d "%~dp0"
where uv >nul 2>&1
if errorlevel 1 (
  echo Install uv and Git first. See LONGCAT.md.
  pause
  exit /b 1
)
where git >nul 2>&1
if errorlevel 1 (
  echo Install Git first. See LONGCAT.md.
  pause
  exit /b 1
)
where python >nul 2>&1
if errorlevel 1 (
  echo Install Python first. See LONGCAT.md.
  pause
  exit /b 1
)
python "%~dp0setup_longcat.py" --install
if errorlevel 1 echo Setup failed. Read the message above before retrying.
pause
