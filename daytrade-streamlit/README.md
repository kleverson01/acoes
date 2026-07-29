# Day Trade SMC — versão web (Streamlit)

## O que mudou em relação à sua versão

- `daytrade_smc.py` — **seu arquivo original, sem nenhuma alteração**. Todo o motor de análise (SMC, Price Action, Médias, VWAP, Confluência, alvos alternativos) continua exatamente como você construiu.
- `streamlit_app.py` — **novo**. É a camada visual: importa as funções do seu arquivo e desenha um gráfico de candles real (Plotly) com EMAs, VWAP, swings e marcações de BOS/CHoCH, mais os painéis das 5 leituras.

Por que isso resolve os 3 pontos que você pediu:
1. **Roda pela internet, sem instalar nada** — Streamlit Community Cloud hospeda de graça, e o navegador do visitante só acessa uma URL normal.
2. **Vira ferramenta gráfica de verdade** — antes era tudo texto; agora tem candle, EMA, VWAP e swings desenhados.
3. **Lista fixa de ativos** — sua `DEFAULT_SYMBOLS` já existia e continua sendo o ponto de partida da watchlist, editável na barra lateral.

**Importante sobre a interface Tkinter que você fez:** ela continua no arquivo e funciona normalmente se um dia você rodar num Windows local. Só não dá pra publicar na internet, porque interface de desktop precisa de tela — servidor não tem. O Streamlit substitui essa parte pra uso online; localmente, se quiser, ainda pode usar `python daytrade_smc.py --gui`.

---

## Como publicar na internet (sem instalar nada, 100% pelo navegador)

### Passo 1 — Criar uma conta no GitHub (gratuito)
Acesse **github.com**, crie uma conta se ainda não tiver.

### Passo 2 — Criar o repositório e subir os arquivos
1. No GitHub, clique em **"New repository"** (botão verde).
2. Dê um nome, ex: `daytrade-smc`. Marque como **Public**. Clique em **Create repository**.
3. Na página do repositório vazio, clique em **"uploading an existing file"**.
4. Arraste estes 3 arquivos (estão nesta pasta que te entreguei):
   - `daytrade_smc.py`
   - `streamlit_app.py`
   - `requirements.txt`
5. Clique em **Commit changes**.

Isso é só upload de arquivo pelo navegador — sem terminal, sem git instalado, sem nada.

### Passo 3 — Conectar no Streamlit Community Cloud
1. Acesse **share.streamlit.io** e entre com sua conta GitHub (botão "Continue with GitHub").
2. Clique em **"New app"**.
3. Selecione o repositório `daytrade-smc` que você acabou de criar.
4. No campo **"Main file path"**, digite: `streamlit_app.py`
5. Clique em **Deploy**.

Em 1-2 minutos o app fica no ar, com uma URL tipo `https://seu-usuario-daytrade-smc.streamlit.app` — acessível de qualquer navegador, computador ou celular, sem login nem instalação pra quem for usar.

### Atualizando depois
Qualquer mudança nos arquivos: edite direto na página do arquivo no GitHub (ícone de lápis) e clique em **Commit changes**. O Streamlit Cloud redeploya sozinho em menos de um minuto.

---

## Usando pelo celular

Depois de publicado, é só abrir a URL no navegador do celular — a interface do Streamlit já se adapta a telas pequenas. Pra ficar com "cara de app", use a opção **"Adicionar à tela inicial"** do navegador.

---

## Testando localmente antes de publicar (opcional, se algum dia tiver Python)

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

---

## O que tem agora (além da análise individual)

- **Modo Scanner** — roda a análise em TODOS os ativos da watchlist de uma vez e mostra um ranking por score de confluência, com um botão pra abrir a análise completa de qualquer um deles direto do ranking. É o "Top N" do seu prompt original.
- **Zonas de FVG desenhadas no gráfico** — retângulo sombreado mostrando o gap ainda não preenchido, além da marcação em texto que já existia no painel SMC.
- **Watchlist persistida** — usa as funções `load_symbols`/`save_symbols` que você já tinha; a lista sobrevive a recarregamentos de página enquanto o servidor não reiniciar (ver ressalva abaixo).
- **Atualização automática** — checkbox na análise individual, com intervalo configurável (30s a 5min), usando `st.fragment` do Streamlit pra atualizar só o painel, sem recarregar a página inteira.

**Ressalva sobre a persistência:** no Streamlit Community Cloud, o disco do servidor é resetado a cada novo deploy (quando você edita um arquivo no GitHub) e após longos períodos de inatividade. Ou seja, a lista sobrevive a você só recarregar a página ou vários usuários acessando ao mesmo tempo, mas não sobrevive a um redeploy. Se isso incomodar, a solução definitiva é salvar num banco externo (ex: um Google Sheets ou um banco gratuito tipo Supabase) em vez de arquivo local — posso implementar isso se quiser.

## O que ainda pode ser melhorado

1. **Persistência de verdade entre deploys** — trocar o arquivo local por um banco externo gratuito (Google Sheets via API, ou Supabase), pra lista sobreviver a redeploys.
2. **Alertas por e-mail/Telegram** — disparar uma notificação quando o Scanner encontrar um score acima de um limiar (ex: 80+) em algum ativo da watchlist.
3. **Múltiplos timeframes na mesma tela** — hoje é M15 OU H1; dá pra mostrar as duas análises lado a lado, com um indicador de alinhamento entre elas.
4. **Histórico de sinais** — guardar os sinais gerados ao longo do tempo pra depois conferir se o setup teria funcionado (uma espécie de backtest simplificado direto na interface).

Me avisa qual desses (ou outra ideia) você quer que eu implemente a seguir.