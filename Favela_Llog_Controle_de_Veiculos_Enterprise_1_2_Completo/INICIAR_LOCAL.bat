@echo off
setlocal
cd /d "%~dp0"
title Favela Llog Controle de Veiculos - Local
call PREPARAR_AMBIENTE.bat
if errorlevel 1 exit /b 1
set "DATABASE_URL="
".venv\Scripts\python.exe" run.py
pause
