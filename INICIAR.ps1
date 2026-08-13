# =====================================================================
#  INICIAR.ps1 — sobe o Terminal SMC localmente.
#
#  Use este arquivo se o start_app.bat abrir no Edge/Bloco de Notas em
#  vez de executar. Isso acontece quando a associação de arquivos .bat
#  do Windows foi alterada por algum programa — o .ps1 não depende
#  dessa associação.
#
#  COMO RODAR:
#    Clique com o BOTÃO DIREITO neste arquivo
#    -> "Executar com o PowerShell"
#
#  Se o Windows bloquear a execução de scripts, rode uma vez:
#    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
# =====================================================================

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor DarkGray
Write-Host "   TERMINAL SMC" -ForegroundColor Yellow
Write-Host "  ============================================================" -ForegroundColor DarkGray
Write-Host ""

# --- 1. Localizar o Python ------------------------------------------
# Procura em caminhos conhecidos ANTES de confiar no PATH: o atalho da
# Microsoft Store (WindowsApps\python.exe) costuma vir primeiro no PATH
# e não é um Python funcional — já nos custou horas de depuração.
$candidatos = @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "C:\Python312\python.exe",
    "C:\Python311\python.exe"
)

$py = $null
foreach ($c in $candidatos) {
    if (Test-Path $c) { $py = $c; break }
}

if (-not $py) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike "*WindowsApps*") { $py = $cmd.Source }
}
if (-not $py) {
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) { $py = "py" }
}

if (-not $py) {
    Write-Host "  [ERRO] Python nao encontrado." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Instale o Python 3.12 em:"
    Write-Host "    https://www.python.org/downloads/release/python-31210/"
    Write-Host "  marcando a opcao 'Add python.exe to PATH'."
    Write-Host ""
    Read-Host "  Enter para fechar"
    exit 1
}
Write-Host "  Python: $py" -ForegroundColor DarkGray

# --- 2. Dependências (só na primeira vez) ---------------------------
if (-not (Test-Path ".deps_ok")) {
    Write-Host ""
    Write-Host "  Primeira execucao — instalando dependencias." -ForegroundColor Yellow
    Write-Host "  Isso leva alguns minutos, mas so acontece uma vez."
    Write-Host ""
    & $py -m pip install --upgrade pip
    & $py -m pip install -r requirements.txt
    & $py -m pip install -r requirements-local.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERRO] Falha ao instalar dependencias." -ForegroundColor Red
        Read-Host "  Enter para fechar"
        exit 1
    }
    "instalado" | Out-File ".deps_ok" -Encoding utf8
    Write-Host "  Dependencias instaladas." -ForegroundColor Green
}

# --- 3. Verificar o MetaTrader 5 ------------------------------------
Write-Host ""
Write-Host "  Verificando o MetaTrader 5..." -ForegroundColor DarkGray
& $py -c "import MetaTrader5 as mt5, sys; sys.exit(0 if mt5.initialize() else 1)" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [OK] MetaTrader 5 conectado — dados em tempo real." -ForegroundColor Green
} else {
    Write-Host "  [AVISO] MT5 nao respondeu." -ForegroundColor Yellow
    Write-Host "          Abra e faca login no MetaTrader 5 para ter tempo real."
    Write-Host "          O app sobe assim mesmo, usando Yahoo Finance."
    Write-Host "          Para investigar: .\diagnostico_mt5.ps1"
}

# --- 4. Subir o app --------------------------------------------------
Write-Host ""
Write-Host "  Abrindo em http://localhost:8501" -ForegroundColor Cyan
Write-Host "  Para ENCERRAR: feche esta janela ou pressione Ctrl+C." -ForegroundColor DarkGray
Write-Host ""

& $py -m streamlit run streamlit_app.py

Write-Host ""
Read-Host "  Encerrado. Enter para fechar"
