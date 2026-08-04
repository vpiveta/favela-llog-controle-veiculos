@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
  echo Ambiente virtual ainda nao existe. Execute INICIAR_LOCAL.bat primeiro.
  pause
  exit /b 1
)

call .venv\Scripts\activate
python -m flask --app wsgi:app create-admin
pause
