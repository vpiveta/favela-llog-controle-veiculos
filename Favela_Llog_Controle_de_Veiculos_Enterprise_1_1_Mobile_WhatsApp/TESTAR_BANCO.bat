@echo off
setlocal
cd /d "%~dp0"
call PREPARAR_AMBIENTE.bat
if errorlevel 1 exit /b 1
set "PYTHONPATH=%CD%"
".venv\Scripts\python.exe" -m scripts.testar_banco
set RC=%ERRORLEVEL%
pause
exit /b %RC%
