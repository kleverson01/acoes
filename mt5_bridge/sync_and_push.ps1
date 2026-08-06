# ========================================================================
# sync_and_push.ps1
#
# Roda no PC de casa, via Agendador de Tarefas do Windows, a cada
# poucos minutos. Busca os candles reais no MT5 e publica direto no
# GitHub — SEM passar por GitHub Actions / self-hosted runner.
#
# Por que essa troca: o runner tinha várias camadas frágeis (token de
# 'workflow', ambiente isolado de processo com PATH diferente da sessão
# interativa, ExecutionPolicy dentro do runner) que causaram uma
# sequência de erros difíceis de depurar. Este script faz a mesma
# coisa de um jeito direto: Task Scheduler → PowerShell → Python → git
# push. Menos peças, menos pontos de falha.
#
# CONFIGURAÇÃO NECESSÁRIA ANTES DE USAR (só uma vez):
#   1. Ajuste as duas variáveis abaixo ($pythonExe e $repoDir) para o
#      caminho real desta máquina.
#   2. Rode estes 3 comandos MANUALMENTE uma vez, na pasta do repositório,
#      para configurar o push sem pedir senha toda vez:
#         git config user.name "MT5 Bridge (automatico)"
#         git config user.email "mt5-bridge@local"
#         git remote set-url origin https://SEU_TOKEN_AQUI@github.com/kleverson01/acoes.git
#      (o SEU_TOKEN_AQUI é o mesmo Personal Access Token que você já
#      usa em st.secrets — precisa ter permissão "repo" / Contents:
#      Read and write. NÃO precisa da permissão "workflow" nem
#      "Actions" — não usamos mais GitHub Actions.)
# ========================================================================

$ErrorActionPreference = "Stop"

# --- AJUSTE ESTAS DUAS LINHAS PARA O CAMINHO REAL DESTA MÁQUINA ---
$pythonExe = "C:\Users\kleve\AppData\Local\Programs\Python\Python312\python.exe"
$repoDir   = "C:\Users\kleve\Documents\acoes"
# --------------------------------------------------------------------

$logFile = Join-Path $repoDir "mt5_bridge\sync_log.txt"

function Log($msg) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp - $msg" | Out-File -FilePath $logFile -Append -Encoding utf8
}

try {
    Set-Location $repoDir
    Log "Iniciando sincronizacao..."

    & $pythonExe "mt5_bridge\update_data.py"
    if ($LASTEXITCODE -ne 0) {
        Log "ERRO: update_data.py terminou com codigo $LASTEXITCODE (provavelmente MT5 fechado ou deslogado)"
        exit 1
    }

    git add data\mt5_snapshot.json
    git diff --staged --quiet
    if ($LASTEXITCODE -eq 0) {
        Log "Nada novo para publicar (dados identicos ao ultimo snapshot)."
    } else {
        $commitMsg = "Atualizacao automatica via MT5 - $(Get-Date -Format o)"
        git commit -m $commitMsg | Out-Null
        git push | Out-Null
        Log "Snapshot publicado com sucesso."
    }
}
catch {
    Log "ERRO: $_"
    exit 1
}
