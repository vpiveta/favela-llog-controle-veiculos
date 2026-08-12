@echo off
setlocal
cd /d "%~dp0"
title Homologacao - Favela Llog Controle de Veiculos
call PREPARAR_AMBIENTE.bat
if errorlevel 1 exit /b 1
set "DATABASE_URL="
".venv\Scripts\python.exe" -m compileall -q app scripts run.py wsgi.py
if errorlevel 1 goto :erro
".venv\Scripts\python.exe" scripts\testar_enterprise_17.py
if errorlevel 1 goto :erro
echo.
echo HOMOLOGACAO APROVADA.
pause
exit /b 0
:erro
echo.
echo HOMOLOGACAO REPROVADA. Copie a mensagem acima.
pause
exit /b 1
