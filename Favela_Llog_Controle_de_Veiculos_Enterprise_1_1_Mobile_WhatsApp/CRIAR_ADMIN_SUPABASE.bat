@echo off
setlocal
cd /d "%~dp0"
title Criar Admin Supabase - Favela Llog Controle de Veiculos
call PREPARAR_AMBIENTE.bat
if errorlevel 1 exit /b 1
set "PYTHONPATH=%CD%"
".venv\Scripts\python.exe" -m scripts.criar_admin_supabase
set RC=%ERRORLEVEL%
pause
exit /b %RC%
