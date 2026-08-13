# Day Trade SMC — Como usar

## O diagnóstico: por que nada funcionava

Passamos horas brigando com uma arquitetura que era complexa demais para o
objetivo. O caminho era:

```
App na nuvem → API do GitHub → GitHub Actions → self-hosted runner
→ PowerShell isolado → Python → git push → GitHub → app na nuvem
```

Sete elos. Cada um virou um ponto de falha: branch errada, ExecutionPolicy,
NumPy incompatível com a CPU, Pandas incompatível com a CPU, PATH do pip
sequestrado pelo atalho da Microsoft Store, arquivo colado no lugar errado,
push rejeitado por falta de pull. Consertar um revelava o próximo.

**Mas você não precisa de nada disso.** Você quer rodar o scanner com dados
do MT5 — e o MT5 está na sua máquina. O caminho certo é:

```
App rodando na sua máquina → MT5 (mesma máquina)
```

Um elo. Sem GitHub, sem token, sem runner, sem workflow, sem tarefa agendada,
sem sincronização. Dados em tempo real de verdade, não um snapshot de minutos
atrás.

---

## Como usar (a partir de agora)

### 1. Abra o MetaTrader 5 e faça login

### 2. Dê duplo clique em `start_app.bat`

Só isso. O arquivo cuida do resto:
- Acha o Python sozinho (sem depender do PATH, que já nos deu dor de cabeça)
- Instala as dependências na primeira vez (depois pula essa etapa)
- Testa a conexão com o MT5 e avisa se ele não estiver aberto
- Sobe o app e abre no navegador

Na barra lateral, você verá **🟢 MetaTrader 5 conectado** e a fonte já vem
selecionada como MT5 automaticamente.

Para encerrar: feche a janela preta do terminal.

---

## O que também foi corrigido

**Bug de conexão no MT5 (causa dos "15 erros")**
O código conectava e desconectava do terminal a cada busca — numa varredura de
24 ativos × 5 timeframes, isso eram 120 ciclos de conexão. Agora conecta uma
vez e mantém aberto. Além de eliminar as falhas intermitentes, a varredura
ficou bem mais rápida. Há também uma nova tentativa automática quando o
terminal ainda não carregou o histórico de um símbolo recém-adicionado ao
Market Watch.

**Fonte de dados automática**
O app detecta se há um MT5 acessível e já seleciona ele por padrão, em vez de
cair no Yahoo Finance (atrasado 15-20 min) sem você perceber.

**Watchlist**
Os 24 ativos que você pediu já vêm como padrão. Se a lista antiga aparecer,
clique em "Restaurar lista padrão" na barra lateral.

**Filtros de qualidade** (da conversa anterior, mantidos)
- Piso mínimo do stop em múltiplos de ATR (padrão 1.0× — antes era 0.75×, que
  gerava stops de 4-5 centavos, tocados por puro ruído no M15)
- Score mínimo para registrar no Histórico de Sinais (padrão 55)
- Alerta ⚠️ ao lado do ativo no Scanner quando o score está abaixo do mínimo

---

## Limpeza: o que desativar

Nada disso é mais necessário. Pode desativar sem medo:

1. **Tarefa agendada** — `taskschd.msc` → "Sincronizar MT5" → Desabilitar
2. **Script vigia** — se estiver rodando o `watch_and_sync.ps1`, feche a janela
3. **Runner do GitHub** — `github.com/kleverson01/acoes/settings/actions/runners`
   → Remove (e pode apagar a pasta `C:\GitHub-Runner`)
4. **Workflow** — pode apagar `.github/workflows/mt5-update.yml` do repositório

O `sync_and_push.ps1` e o `watch_and_sync.ps1` podem ficar onde estão; só não
são mais usados.

---

## E o acesso remoto (do trabalho)?

Essa era a única razão de existir toda a ponte via GitHub. Se ainda quiser
isso, há um caminho muito mais simples que o anterior — mas **teste primeiro o
modo local**, que é o que resolve seu objetivo principal.

**Opção A — outra máquina na mesma rede (casa)**
Suba o app com:
```
python -m streamlit run streamlit_app.py --server.address 0.0.0.0
```
Depois acesse `http://IP-DA-MAQUINA:8501` de qualquer aparelho na mesma rede.

**Opção B — de qualquer lugar (Cloudflare Tunnel)**
Instale o `cloudflared` e rode, com o app já no ar:
```
cloudflared tunnel --url http://localhost:8501
```
Ele devolve uma URL pública temporária. Sem abrir porta no roteador, sem token,
sem configuração.

**Opção C — a ponte via GitHub**
O código dela continua no projeto (fonte "GitHub (MT5 de casa)"), caso um dia
queira retomar. Mas, sinceramente: para o que você precisa, as opções A e B
resolvem com uma fração da complexidade.

---

## Se algo der errado

**"Python nao encontrado"** — instale o Python 3.12 marcando "Add python.exe to
PATH": https://www.python.org/downloads/release/python-31210/

**"MT5 nao respondeu"** — abra e faça login no MetaTrader 5, depois rode o
`start_app.bat` de novo.

**Algum ativo dá erro no scanner** — o código pode ser diferente na sua
corretora (algumas usam sufixo, tipo `PETR4F`). Confirme no Market Watch do MT5
e ajuste na watchlist.

**Quer reinstalar as dependências do zero** — apague o arquivo `.deps_ok` da
pasta e rode o `start_app.bat` novamente.
