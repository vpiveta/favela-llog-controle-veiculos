param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectDir
)

$ErrorActionPreference = 'Stop'
$ProjectDir = (Resolve-Path $ProjectDir).Path
Set-Location $ProjectDir

function Write-Title {
    Clear-Host
    Write-Host '============================================================' -ForegroundColor Yellow
    Write-Host ' FAVELA LLOG CONTROLE DE VEICULOS' -ForegroundColor White
    Write-Host ' CRIAR ADMINISTRADOR NO SUPABASE' -ForegroundColor Yellow
    Write-Host '============================================================' -ForegroundColor Yellow
    Write-Host
}

Write-Title

$python = Join-Path $ProjectDir '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host 'Ambiente virtual nao encontrado.' -ForegroundColor Red
    Write-Host 'Execute INICIAR_LOCAL.bat uma vez antes de usar este assistente.' -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path (Join-Path $ProjectDir 'wsgi.py'))) {
    Write-Host 'ERRO: wsgi.py nao encontrado na pasta do projeto.' -ForegroundColor Red
    exit 1
}

Write-Host 'No Supabase, copie a URI do Session Pooler.' -ForegroundColor Cyan
Write-Host 'Ela deve comecar com postgresql:// e terminar com /postgres.' -ForegroundColor DarkGray
Write-Host
$databaseUrl = Read-Host 'Cole a DATABASE_URL completa'

if ([string]::IsNullOrWhiteSpace($databaseUrl)) {
    Write-Host 'DATABASE_URL nao informada.' -ForegroundColor Red
    exit 1
}

if (-not ($databaseUrl.StartsWith('postgresql://') -or $databaseUrl.StartsWith('postgres://'))) {
    Write-Host 'A conexao deve comecar com postgresql:// ou postgres://.' -ForegroundColor Red
    exit 1
}

# Remove aspas e espacos copiados acidentalmente.
$databaseUrl = $databaseUrl.Trim().Trim('"').Trim("'")
$env:DATABASE_URL = $databaseUrl

if ([string]::IsNullOrWhiteSpace($env:SECRET_KEY)) {
    $env:SECRET_KEY = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
}

Write-Host
Write-Host 'Testando a conexao e preparando as tabelas...' -ForegroundColor Cyan

$testCode = @'
from sqlalchemy import text
from app import create_app
from app.models import db
app = create_app()
with app.app_context():
    db.session.execute(text("SELECT 1"))
    db.session.commit()
print("CONEXAO_OK")
'@

$testFile = Join-Path $env:TEMP ('fleet_db_test_' + [Guid]::NewGuid().ToString('N') + '.py')
Set-Content -Path $testFile -Value $testCode -Encoding UTF8
try {
    & $python $testFile
    if ($LASTEXITCODE -ne 0) {
        throw 'Falha ao conectar ao Supabase.'
    }
}
finally {
    Remove-Item $testFile -Force -ErrorAction SilentlyContinue
}

Write-Host
Write-Host 'Conexao aprovada. Agora informe os dados do administrador.' -ForegroundColor Green
Write-Host

& $python -m flask --app wsgi:app create-admin
if ($LASTEXITCODE -ne 0) {
    Write-Host
    Write-Host 'Nao foi possivel criar o administrador.' -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host
Write-Host '============================================================' -ForegroundColor Green
Write-Host ' ADMINISTRADOR CRIADO NO BANCO ONLINE COM SUCESSO' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host
Write-Host 'Agora entre no endereco online usando o login criado.' -ForegroundColor White

Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
exit 0
