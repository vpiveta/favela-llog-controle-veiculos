@echo off
setlocal
cd /d "%~dp0"
title Publicar GitHub - Favela Llog Controle de Veiculos
where git >nul 2>nul
if errorlevel 1 (
  echo ERRO: Git nao encontrado.
  pause
  exit /b 1
)
echo.
git status
echo.
set /p MSG=Mensagem da atualizacao: 
if "%MSG%"=="" set "MSG=Atualizacao Favela Llog Controle de Veiculos"
git add .
git commit -m "%MSG%"
if errorlevel 1 (
  echo Nenhuma alteracao nova para publicar ou ocorreu um erro.
)
git push origin main
if errorlevel 1 goto :erro
echo.
echo PUBLICACAO ENVIADA AO GITHUB. O Render iniciara o deploy automatico.
pause
exit /b 0
:erro
echo.
echo ERRO ao publicar. Nao execute pull/rebase; copie a mensagem acima.
pause
exit /b 1
