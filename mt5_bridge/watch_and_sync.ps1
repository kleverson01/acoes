# ========================================================================
# watch_and_sync.ps1
#
# Fica rodando em segundo plano no PC de casa, checando a cada 15
# segundos se você clicou em "Atualizar via MT5 (casa)" no app. Quando
# detecta um pedido novo, busca os dados reais no MT5 e publica no
# GitHub. Não atualiza sozinho em intervalos fixos — só quando você
# pede.
#
# Diferente da versão anterior (GitHub Actions self-hosted runner),
# isso é só um script PowerShell simples rodando localmente — sem
# runner, sem workflow, sem token de 'workflow'.
#
# CONFIGURAÇÃO NECESSÁRIA (só uma vez): ajuste as 3 variáveis abaixo.
# ========================================================================

$ErrorActionPreference = "Stop"

# --- AJUSTE ESTAS LINHAS PARA O CAMINHO REAL DESTA MÁQUINA ---
$pythonExe = "C:\Users\kleve\AppData\Local\Programs\Python\Python312\python.exe"
$repoDir   = "C:\Users\kleve\Documents\acoes"
$repoSlug  = "kleverson01/acoes"
# ----------------------------------------------------------------

$logFile  = Join-Path $repoDir "mt5_bridge\watch_log.txt"
$lastFile = Join-Path $repoDir "mt5_bridge\last_processed.txt"

function Log($msg) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp - $msg" | Out-File -FilePath $logFile -Append -Encoding utf8
    Write-Host "$timestamp - $msg"
}

$lastProcessed = ""
if (Test-Path $lastFile) {
    $lastProcessed = (Get-Content $lastFile -Raw).Trim()
}

Log "Vigia iniciado. Verificando pedidos a cada 15s... (Ctrl+C para parar)"

while ($true) {
    try {
        $cacheBust = [int][double]::Parse((Get-Date -UFormat %s))
        $url = "https://raw.githubusercontent.com/$repoSlug/main/data/update_request.json?_cb=$cacheBust"

        $response = $null
        try {
            $response = Invoke-RestMethod -Uri $url -TimeoutSec 10 -ErrorAction Stop
        } catch {
            # Arquivo ainda não existe (primeiro uso) ou falha de rede
            # passageira -- não é erro grave, só tenta de novo no próximo ciclo.
            $response = $null
        }

        if ($response -and $response.requested_at -and ($response.requested_at -ne $lastProcessed)) {
            Log "Pedido novo detectado: $($response.requested_at)"

            Set-Location $repoDir
            & $pythonExe "mt5_bridge\update_data.py"

            if ($LASTEXITCODE -eq 0) {
                git add data\mt5_snapshot.json
                git diff --staged --quiet
                if ($LASTEXITCODE -ne 0) {
                    git commit -m "Atualizacao sob demanda via MT5 - $(Get-Date -Format o)" | Out-Null
                    git pull origin main --no-edit | Out-Null
                    git push
                    if ($LASTEXITCODE -eq 0) {
                        Log "Snapshot publicado com sucesso."
                    } else {
                        Log "ERRO: git push falhou."
                    }
                } else {
                    Log "MT5 buscado, mas dados identicos ao ultimo snapshot -- nada novo pra publicar."
                }
            } else {
                Log "ERRO: update_data.py falhou (codigo $LASTEXITCODE) -- confirme se o MT5 esta aberto e logado."
            }

            $lastProcessed = $response.requested_at
            $lastProcessed | Out-File -FilePath $lastFile -Encoding utf8 -NoNewline
        }
    }
    catch {
        Log "Aviso: falha no ciclo de verificacao - $_"
    }

    Start-Sleep -Seconds 15
}
