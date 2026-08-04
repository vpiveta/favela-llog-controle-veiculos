@echo off
setlocal
cd /d "%~dp0"

if not exist .venv py -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 goto :erro

python -m compileall -q app run.py wsgi.py
if errorlevel 1 goto :erro

python -c "from app import create_app; app=create_app(); c=app.test_client(); r=c.get('/login'); assert r.status_code==200; print('OK: login e inicializacao validados')"
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
