@echo off
setlocal
set "ZURA_WAN_SETUP=%~dp0setup_wan_speech.py"
set "ZURA_WAN_COMFY=%~dp0..\.."
if exist "%ZURA_WAN_COMFY%\.venv\Scripts\python.exe" (
  "%ZURA_WAN_COMFY%\.venv\Scripts\python.exe" "%ZURA_WAN_SETUP%" --comfy-directory "%ZURA_WAN_COMFY%" %*
) else if exist "%ZURA_WAN_COMFY%\..\python_embeded\python.exe" (
  "%ZURA_WAN_COMFY%\..\python_embeded\python.exe" "%ZURA_WAN_SETUP%" --comfy-directory "%ZURA_WAN_COMFY%" %*
) else (
  python "%ZURA_WAN_SETUP%" --comfy-directory "%ZURA_WAN_COMFY%" %*
)
set "ZURA_WAN_RESULT=%ERRORLEVEL%"
if not "%ZURA_WAN_RESULT%"=="0" echo Wan speech setup needs attention. Read the message above before retrying.
pause
exit /b %ZURA_WAN_RESULT%
