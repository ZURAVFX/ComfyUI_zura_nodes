@echo off
setlocal
set "ZURA_COMFY=%~dp0..\.."
if exist "%ZURA_COMFY%\.venv\Scripts\python.exe" (
  "%ZURA_COMFY%\.venv\Scripts\python.exe" "%~dp0setup_speech.py" %*
) else if exist "%ZURA_COMFY%\..\python_embeded\python.exe" (
  "%ZURA_COMFY%\..\python_embeded\python.exe" "%~dp0setup_speech.py" %*
) else (
  python "%~dp0setup_speech.py" %*
)
pause
