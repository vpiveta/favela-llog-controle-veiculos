@echo off
setlocal
cd /d "%~dp0"
title Criar Admin Supabase - Favela Llog Controle de Veiculos
call PREPARAR_AMBIENTE.bat
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" scripts\criar_admin_supabase.py
set RC=%ERRORLEVEL%
pause
exit /b %RC%
