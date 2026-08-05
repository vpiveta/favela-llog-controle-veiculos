@echo off
setlocal
cd /d "%~dp0"
:menu
cls
color 0E
echo ============================================================
echo       FAVELA LLOG CONTROLE DE VEICULOS - ASSISTENTE
echo ============================================================
echo.
echo  1 - Preparar / atualizar ambiente local
echo  2 - Iniciar sistema local
echo  3 - Criar administrador LOCAL
echo  4 - Configurar conexao SUPABASE
echo  5 - Testar conexao e criar tabelas no SUPABASE
echo  6 - Criar / redefinir administrador no SUPABASE
echo  7 - Executar homologacao
echo  8 - Publicar atualizacao no GitHub / Render
echo  0 - Sair
echo.
set /p OP=Escolha uma opcao: 
if "%OP%"=="1" call PREPARAR_AMBIENTE.bat
if "%OP%"=="2" call INICIAR_LOCAL.bat
if "%OP%"=="3" call CRIAR_ADMIN_LOCAL.bat
if "%OP%"=="4" call CONFIGURAR_SUPABASE.bat
if "%OP%"=="5" call TESTAR_BANCO.bat
if "%OP%"=="6" call CRIAR_ADMIN_SUPABASE.bat
if "%OP%"=="7" call TESTAR_HOMOLOGACAO.bat
if "%OP%"=="8" call PUBLICAR_GITHUB.bat
if "%OP%"=="0" exit /b 0
goto menu
