@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title Publicar GitHub - Favela Llog Controle de Veiculos

set "REPO_URL=https://github.com/vpiveta/favela-llog-controle-veiculos.git"
set "APP_DIR=Favela_Llog_Controle_de_Veiculos_Enterprise_1_1_Mobile_WhatsApp"
set "SOURCE_DIR=%CD%"
set "WORK_DIR=%TEMP%\favela_llog_publicacao_%RANDOM%_%RANDOM%"
set "APP_VERSION=atualizacao"
if exist "%SOURCE_DIR%\VERSION" set /p APP_VERSION=<"%SOURCE_DIR%\VERSION"

echo ============================================================
echo  FAVELA LLOG - PUBLICACAO AUTOMATICA NO GITHUB
echo ============================================================
echo.
echo Versao local: %APP_VERSION%
echo.

where git >nul 2>&1
if errorlevel 1 goto :git_missing

where robocopy >nul 2>&1
if errorlevel 1 goto :robocopy_missing

if not exist "%SOURCE_DIR%\wsgi.py" goto :invalid_package
if not exist "%SOURCE_DIR%\app" goto :invalid_package

set "GCM_INTERACTIVE=Always"

echo [1/4] Baixando a versao atual do GitHub...
git clone --quiet --branch main --single-branch "%REPO_URL%" "%WORK_DIR%"
if errorlevel 1 goto :clone_error

if not exist "%WORK_DIR%\%APP_DIR%" mkdir "%WORK_DIR%\%APP_DIR%"

echo [2/4] Preparando os arquivos da versao %APP_VERSION%...
robocopy "%SOURCE_DIR%" "%WORK_DIR%\%APP_DIR%" /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS /NP /XD ".git" ".venv" "venv" "__pycache__" "instance" "uploads" /XF ".env" "*.pyc" "*.pyo" "*.db" "*.sqlite" "*.sqlite3" "*.zip" "PUBLICACAO_GITHUB.log"
set "COPY_RESULT=%ERRORLEVEL%"
if %COPY_RESULT% GEQ 8 goto :copy_error

echo [3/4] Criando a atualizacao...
git -C "%WORK_DIR%" add --all -- "%APP_DIR%"
git -C "%WORK_DIR%" diff --cached --quiet -- "%APP_DIR%"
if not errorlevel 1 goto :nothing_to_publish

git -C "%WORK_DIR%" config user.name >nul 2>&1
if errorlevel 1 git -C "%WORK_DIR%" config user.name "Favela Llog"
git -C "%WORK_DIR%" config user.email >nul 2>&1
if errorlevel 1 git -C "%WORK_DIR%" config user.email "vpiveta@users.noreply.github.com"

git -C "%WORK_DIR%" commit -m "Enterprise %APP_VERSION% - publicacao automatica"
if errorlevel 1 goto :commit_error

echo [4/4] Enviando ao GitHub...
echo.
echo IMPORTANTE: se abrir uma tela no navegador, entre na conta do
echo GitHub que possui acesso ao repositorio e autorize o Git.
echo.
git -C "%WORK_DIR%" push origin main
if errorlevel 1 goto :push_error

echo.
echo ============================================================
echo  PUBLICACAO CONCLUIDA COM SUCESSO
echo ============================================================
echo O GitHub recebeu a versao %APP_VERSION%.
echo O Render iniciara a atualizacao automaticamente.
goto :success

:nothing_to_publish
echo.
echo O GitHub ja possui os mesmos arquivos desta pasta.
echo Nao havia nenhuma nova alteracao para enviar.
goto :success

:git_missing
echo ERRO: o Git para Windows nao esta instalado ou nao foi encontrado.
echo.
echo Instale pelo endereco abaixo e mantenha o Git Credential Manager marcado:
echo https://git-scm.com/download/win
echo.
echo Depois de instalar, feche esta janela e abra o BAT novamente.
goto :failure

:robocopy_missing
echo ERRO: o comando ROBOCOPY do Windows nao foi encontrado.
echo Execute este BAT em um computador com Windows 10 ou Windows 11.
goto :failure

:invalid_package
echo ERRO: este BAT nao esta dentro da pasta completa do sistema.
echo Extraia todo o ZIP e execute PUBLICAR_GITHUB.bat dentro da pasta extraida.
goto :failure

:clone_error
echo.
echo ERRO: nao foi possivel acessar o repositorio no GitHub.
echo Verifique a internet e confirme que sua conta possui acesso a:
echo %REPO_URL%
goto :cleanup_failure

:copy_error
echo.
echo ERRO: o Windows nao conseguiu preparar os arquivos para publicacao.
echo Codigo do ROBOCOPY: %COPY_RESULT%
goto :cleanup_failure

:commit_error
echo.
echo ERRO: nao foi possivel criar a atualizacao local do Git.
goto :cleanup_failure

:push_error
echo.
echo ============================================================
echo  O ENVIO AO GITHUB NAO FOI AUTORIZADO
echo ============================================================
echo Entre no GitHub pelo navegador com a conta que possui acesso ao repositorio.
echo Depois execute este BAT novamente e conclua a autorizacao quando ela abrir.
echo.
echo Se continuar falhando, tire uma foto desta janela inteira e envie no chat.
goto :cleanup_failure

:success
if exist "%WORK_DIR%\.git" rmdir /s /q "%WORK_DIR%"
echo.
pause
exit /b 0

:cleanup_failure
if exist "%WORK_DIR%" rmdir /s /q "%WORK_DIR%"

:failure
echo.
pause
exit /b 1
