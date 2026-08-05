@echo off
setlocal
cd /d "%~dp0"
title Preparar Ambiente - Favela Llog Controle de Veiculos

if not exist "app\__init__.py" (
  echo ERRO: pasta app nao encontrada ao lado deste BAT.
  echo Extraia o pacote completo e execute o BAT dentro da pasta do projeto.
  pause
  exit /b 1
)

set "PYTHONPATH=%CD%"

where py >nul 2>nul
if errorlevel 1 (
  echo ERRO: Python nao encontrado. Instale Python 3.11, 3.12 ou 3.13.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Criando ambiente virtual...
  py -m venv .venv
  if errorlevel 1 goto :erro
)

echo [2/3] Atualizando pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :erro

echo [3/3] Instalando dependencias...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :erro

echo.
echo AMBIENTE PREPARADO COM SUCESSO.
exit /b 0

:erro
echo.
echo ERRO ao preparar o ambiente. Copie a mensagem acima.
pause
exit /b 1
