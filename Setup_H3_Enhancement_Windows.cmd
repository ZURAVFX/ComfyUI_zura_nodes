@echo off
setlocal
set "ZURA_H3_SETUP=%~dp0setup_h3_enhancement.py"
set "ZURA_H3_COMFY=%~dp0..\.."
if exist "%ZURA_H3_COMFY%\.venv\Scripts\python.exe" (
  "%ZURA_H3_COMFY%\.venv\Scripts\python.exe" "%ZURA_H3_SETUP%" --comfy-directory "%ZURA_H3_COMFY%" %*
) else if exist "%ZURA_H3_COMFY%\..\python_embeded\python.exe" (
  "%ZURA_H3_COMFY%\..\python_embeded\python.exe" "%ZURA_H3_SETUP%" --comfy-directory "%ZURA_H3_COMFY%" %*
) else (
  python "%ZURA_H3_SETUP%" --comfy-directory "%ZURA_H3_COMFY%" %*
)
set "ZURA_H3_RESULT=%ERRORLEVEL%"
if not "%ZURA_H3_RESULT%"=="0" echo H3 enhancement setup needs attention. Read the message above before retrying.
pause
exit /b %ZURA_H3_RESULT%
