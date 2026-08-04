@echo off
setlocal
cd /d "%~dp0"
call PREPARAR_AMBIENTE.bat
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" scripts\testar_banco.py
set RC=%ERRORLEVEL%
pause
exit /b %RC%
