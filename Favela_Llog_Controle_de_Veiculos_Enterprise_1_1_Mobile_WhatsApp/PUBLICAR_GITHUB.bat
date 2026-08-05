@echo off
setlocal
cd /d "%~dp0"
title Publicar GitHub - Favela Llog Controle de Veiculos

echo ============================================================
echo  FAVELA LLOG CONTROLE DE VEICULOS - PUBLICAR GITHUB
echo ============================================================

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo ERRO: esta pasta ainda nao esta vinculada ao Git.
  echo Execute os comandos de vinculacao do repositorio antes de publicar.
  pause
  exit /b 1
)

git status --short
set /p MSG=Mensagem da atualizacao: 
if "%MSG%"=="" set "MSG=Atualizacao Favela Llog Controle de Veiculos"

git add --all -- .
git diff --cached --quiet
if not errorlevel 1 (
  echo Nenhuma alteracao do sistema para publicar.
  pause
  exit /b 0
)

git commit -m "%MSG%"
if errorlevel 1 (
  echo ERRO ao criar commit.
  pause
  exit /b 1
)

git push origin main
if errorlevel 1 (
  echo ERRO ao enviar para o GitHub.
  pause
  exit /b 1
)

echo.
echo Publicacao enviada. O Render iniciara o deploy automatico.
pause
