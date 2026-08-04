@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo ERRO: Python nao encontrado. Instale o Python 3.11 ou superior.
  pause
  exit /b 1
)

if not exist .venv (
  echo [1/4] Criando ambiente virtual...
  py -m venv .venv
)

call .venv\Scripts\activate

echo [2/4] Atualizando instalador...
python -m pip install --upgrade pip
if errorlevel 1 goto :erro

echo [3/4] Instalando dependencias...
python -m pip install -r requirements.txt
if errorlevel 1 goto :erro

echo [4/4] Iniciando Favela Llog Controle de Veiculos...
python run.py
goto :fim

:erro
echo.
echo ERRO: Nao foi possivel preparar o sistema. Copie a mensagem acima.
pause
exit /b 1

:fim
pause
