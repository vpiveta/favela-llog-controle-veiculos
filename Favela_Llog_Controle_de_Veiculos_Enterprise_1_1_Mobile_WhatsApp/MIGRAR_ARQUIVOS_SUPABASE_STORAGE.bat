@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m scripts.migrar_arquivos_storage
) else (
  python -m scripts.migrar_arquivos_storage
)
pause
