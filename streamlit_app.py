"""
streamlit_app.py

Interface WEB para o motor de análise em `daytrade_smc.py`. Não altera
nada do motor — só importa as funções e desenha por cima.

Dois modos (barra lateral):
    - Análise individual: gráfico de candles com EMAs/VWAP/swings/BOS-CHoCH/
      zonas de FVG, mais os painéis das 6 leituras. Pode auto-atualizar.
    - Scanner: roda a análise em TODOS os ativos da watchlist de uma vez e
      mostra um ranking por score de confluência (o "Top N" do requisito
      original), com atalho pra abrir qualquer um na análise individual.

Rodar localmente (se algum dia tiver Python disponível):
    streamlit run streamlit_app.py

Rodar pela internet sem instalar nada: ver README.md.
"""

from __future__ import annotations

import hmac
import os
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import daytrade_smc

# Núcleo estável: nomes que existem desde as primeiras versões do
# motor. Se algum destes faltar, o app realmente não tem como rodar.
from daytrade_smc import (
    ALL_MODALITIES_OPTION,
    DATA_SOURCES,
    DAYTRADE_CONFIRMATION_TIMEFRAMES,
    DAYTRADE_CONTEXT_TIMEFRAMES,
    DEFAULT_SYMBOLS,
    Direction,
    MODALITY_CHOICES,
    Signal,
    SWING_CONFIRMATION_TIMEFRAMES,
    SWING_CONTEXT_TIMEFRAMES,
    analyze_symbol_mtf,
    check_signal_as_of,
    load_symbols,
    overall_agreement,
    overall_direction,
    overall_score,
    quality,
    save_symbols,
    yahoo_symbol,
)


# Recursos adicionados depois (histórico de sinais, ponte MT5, WINFUT).
# Resolvidos por getattr em vez de `from ... import`, porque um import
# rígido quebra o app INTEIRO com ImportError quando só um dos dois
# arquivos é atualizado no deploy — situação comum ao editar pelo
# navegador do GitHub. Assim, o recurso indisponível simplesmente
# desliga, e o resto continua de pé.
def _opcional(nome, padrao=None):
    return getattr(daytrade_smc, nome, padrao)


def _faltando(*_a, **_k):
    raise RuntimeError(
        "Este recurso exige uma versão mais nova do daytrade_smc.py. "
        "Atualize os DOIS arquivos (daytrade_smc.py e streamlit_app.py) juntos."
    )


clear_signal_log = _opcional("clear_signal_log", lambda: None)
delete_signal_log_entry = _opcional("delete_signal_log_entry", lambda *_: None)
load_signal_log = _opcional("load_signal_log", lambda: [])
log_signal = _opcional("log_signal", lambda *a, **k: None)
refresh_signal_log = _opcional("refresh_signal_log", lambda *a, **k: [])
fetch_snapshot_timestamp = _opcional("fetch_snapshot_timestamp", lambda: None)
request_mt5_update = _opcional(
    "request_mt5_update",
    lambda: (False, "Recurso indisponível nesta versão do daytrade_smc.py."),
)

# Recursos ausentes viram uma lista que a interface consulta pra avisar
# o usuário uma única vez, em vez de falhar silenciosamente.
_RECURSOS_AUSENTES = [
    nome for nome in (
        "load_signal_log", "log_signal", "refresh_signal_log",
        "mt5_is_available", "rsi_extremes_across_timeframes",
        "resolve_winfut_symbol", "WINFUT_CONFIRMATION_TIMEFRAMES",
    )
    if not hasattr(daytrade_smc, nome)
]

# Configura a ponte GitHub a partir dos secrets do Streamlit (Settings
# → Secrets no Streamlit Cloud, ou .streamlit/secrets.toml localmente).
# Sem isso configurado, a fonte "GitHub (MT5 de casa)" dá erro claro em
# vez de travar — ver README.
try:
    daytrade_smc.GITHUB_BRIDGE_REPO = st.secrets.get("github_repo")
    daytrade_smc.GITHUB_BRIDGE_TOKEN = st.secrets.get("github_token")
except Exception:
    daytrade_smc.GITHUB_BRIDGE_REPO = None
    daytrade_smc.GITHUB_BRIDGE_TOKEN = None

STYLES = {
    "Day Trade": {
        "confirmation": DAYTRADE_CONFIRMATION_TIMEFRAMES,
        "context": DAYTRADE_CONTEXT_TIMEFRAMES,
        "count_label": "Candles fechados (M5, M15 e H1)",
    },
    "Swing Trade": {
        "confirmation": SWING_CONFIRMATION_TIMEFRAMES,
        "context": SWING_CONTEXT_TIMEFRAMES,
        "count_label": "Candles fechados (Diário e Semanal)",
    },
    # Perfil próprio do mini índice: M5 sobe para a confirmação (nas
    # ações ele é só contexto), porque o WIN gira rápido demais para
    # esperar o fechamento do M15 como gatilho único.
    "WINFUT": {
        "confirmation": _opcional("WINFUT_CONFIRMATION_TIMEFRAMES", ("M5", "M15")),
        "context": _opcional("WINFUT_CONTEXT_TIMEFRAMES", ("H1", "D1")),
        "count_label": "Candles fechados (M5 e M15)",
    },
}

st.set_page_config(page_title="Terminal SMC · B3", page_icon="◆", layout="wide",
                   initial_sidebar_state="expanded")

# ========================================================================
# Sistema visual
#
# Direção: terminal de mesa de operações. Fundo tinta-profunda com
# viés azul (não preto puro — preto puro achata a hierarquia quando há
# muitos painéis), hierarquia construída por elevação de superfície e
# fios de 1px, nunca por sombra pesada.
#
# Tipografia com três papéis distintos, não uma família só:
#   · Space Grotesk  — títulos. Grotesca técnica, com desenho próprio
#                      nos numerais, evita o ar genérico do Inter puro.
#   · Inter          — texto corrido e controles.
#   · JetBrains Mono — TODO número. Aqui não é enfeite: numerais
#                      tabulares mantêm as casas alinhadas na vertical,
#                      o que é o que permite varrer uma coluna de
#                      preços com o olho sem ler valor por valor.
#
# Cor com significado fixo, nunca decorativa:
#   verde-azulado = compra · rosa = venda · âmbar = EXAUSTÃO.
# O âmbar é reservado exclusivamente à exaustão de IFR — é o evento
# raro que a estratégia persegue, então é a única coisa na tela com
# permissão de brilhar.
# ========================================================================
COLORS = {
    "bg": "#0A0E13",
    "surface": "#121A23",
    "surface_2": "#1A252F",
    "line": "#24323F",
    "text": "#E4EDF5",
    "muted": "#75899C",
    "buy": "#22D3A5",
    "sell": "#FF4D6D",
    "signal": "#F5B841",
}

DIRECTION_COLOR = {
    Direction.BUY: COLORS["buy"],
    Direction.SELL: COLORS["sell"],
    Direction.NEUTRAL: COLORS["muted"],
}


def inject_theme() -> None:
    st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap');

:root {{
  --bg:{COLORS['bg']}; --surface:{COLORS['surface']}; --surface-2:{COLORS['surface_2']};
  --line:{COLORS['line']}; --text:{COLORS['text']}; --muted:{COLORS['muted']};
  --buy:{COLORS['buy']}; --sell:{COLORS['sell']}; --signal:{COLORS['signal']};
}}

.stApp {{ background:var(--bg); }}
.block-container {{ padding-top:1.6rem; padding-bottom:3rem; max-width:1560px; }}
html, body, [class*="css"] {{ font-family:'Inter',sans-serif; color:var(--text); }}
h1,h2,h3,h4 {{ font-family:'Space Grotesk',sans-serif !important; letter-spacing:-0.02em; }}

/* Numerais tabulares em tudo que é dado — alinhamento vertical das casas */
[data-testid="stMetricValue"], .stDataFrame, code, .mono {{
  font-family:'JetBrains Mono',monospace !important; font-variant-numeric:tabular-nums;
}}

/* ---- Cabeçalho ---- */
.term-head {{
  display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;
  padding:0 0 14px 0; border-bottom:1px solid var(--line); margin-bottom:20px;
}}
.term-head .mark {{
  font-family:'Space Grotesk',sans-serif; font-size:1.42rem; font-weight:700;
  letter-spacing:-0.03em; color:var(--text);
}}
.term-head .mark span {{ color:var(--signal); }}
.term-head .ctx {{
  font-family:'JetBrains Mono',monospace; font-size:0.7rem; color:var(--muted);
  text-transform:uppercase; letter-spacing:0.13em;
}}
.term-head .live {{ margin-left:auto; font-family:'JetBrains Mono',monospace; font-size:0.7rem; }}
.dot {{ display:inline-block; width:6px; height:6px; border-radius:50%; margin-right:6px; }}
.dot.on {{ background:var(--buy); box-shadow:0 0 8px var(--buy); }}
.dot.off {{ background:var(--muted); }}

/* ---- Cartões ---- */
.card {{
  background:var(--surface); border:1px solid var(--line); border-radius:10px;
  padding:15px 18px; margin-bottom:14px;
}}
.card.accent-buy {{ border-left:3px solid var(--buy); }}
.card.accent-sell {{ border-left:3px solid var(--sell); }}
.card.accent-signal {{ border-left:3px solid var(--signal); background:linear-gradient(90deg,#F5B8410F,transparent 45%); }}
.card.accent-mute {{ border-left:3px solid var(--line); }}

.eyebrow {{
  font-family:'JetBrains Mono',monospace; font-size:0.63rem; letter-spacing:0.16em;
  text-transform:uppercase; color:var(--muted); margin-bottom:7px;
}}

/* ---- Trilho de IFR: o elemento-assinatura ----
   As zonas de exaustão são marcadas fisicamente no trilho, então
   "onde o marcador está" é lido como posição, não como número. */
.rsi-rail {{
  position:relative; height:26px; border-radius:5px; margin:9px 0 4px 0;
  background:linear-gradient(90deg,
    var(--buy) 0%, var(--buy) var(--os), #1E2A36 var(--os),
    #1E2A36 var(--ob), var(--sell) var(--ob), var(--sell) 100%);
  border:1px solid var(--line); overflow:hidden;
}}
.rsi-rail .zone-lab {{
  position:absolute; top:5px; font-family:'JetBrains Mono',monospace;
  font-size:0.6rem; font-weight:700; color:#0A0E13; letter-spacing:0.06em;
}}
.rsi-rail .pin {{
  position:absolute; top:-3px; bottom:-3px; width:3px; background:var(--text);
  border-radius:2px; box-shadow:0 0 0 2px var(--bg);
}}
.rsi-rail .pin.hot {{ background:var(--signal); box-shadow:0 0 0 2px var(--bg),0 0 14px var(--signal); width:4px; }}

.tf-row {{ display:flex; align-items:center; gap:11px; margin:7px 0; }}
.tf-row .tf {{
  font-family:'JetBrains Mono',monospace; font-size:0.7rem; color:var(--muted);
  width:52px; flex-shrink:0; letter-spacing:0.05em;
}}
.tf-row .val {{
  font-family:'JetBrains Mono',monospace; font-size:0.86rem; font-weight:700;
  width:44px; text-align:right; flex-shrink:0;
}}
.tf-row .bar {{
  flex:1; height:7px; border-radius:4px; background:#1B2530; position:relative; overflow:hidden;
}}
.tf-row .bar i {{ position:absolute; top:0; bottom:0; width:2px; background:var(--muted); }}
.tf-row .bar i.hot {{ width:3px; background:var(--signal); box-shadow:0 0 9px var(--signal); }}
.tf-row .tag {{
  font-family:'JetBrains Mono',monospace; font-size:0.63rem; letter-spacing:0.09em;
  width:78px; text-align:right; flex-shrink:0;
}}

/* ---- Métricas ---- */
[data-testid="stMetric"] {{
  background:var(--surface); border:1px solid var(--line);
  border-radius:9px; padding:13px 15px;
}}
[data-testid="stMetricLabel"] {{
  font-family:'JetBrains Mono',monospace !important; font-size:0.62rem !important;
  letter-spacing:0.14em; text-transform:uppercase; color:var(--muted) !important;
}}
[data-testid="stMetricValue"] {{ font-size:1.7rem !important; font-weight:700 !important; }}

/* ---- Controles ---- */
section[data-testid="stSidebar"] {{ background:var(--surface); border-right:1px solid var(--line); }}
section[data-testid="stSidebar"] .block-container {{ padding-top:1.1rem; }}

.stButton>button {{
  border-radius:7px; border:1px solid var(--line); background:var(--surface-2);
  color:var(--text); font-weight:600; font-size:0.85rem; transition:all .13s ease;
}}
.stButton>button:hover {{ border-color:var(--signal); color:var(--signal); }}
.stButton>button[kind="primary"] {{ background:var(--signal); color:#0A0E13; border-color:var(--signal); }}

.stTabs [data-baseweb="tab-list"] {{ gap:2px; border-bottom:1px solid var(--line); }}
.stTabs [data-baseweb="tab"] {{
  font-family:'JetBrains Mono',monospace; font-size:0.74rem; letter-spacing:0.06em;
  color:var(--muted); border-radius:6px 6px 0 0; padding:8px 15px;
}}
.stTabs [aria-selected="true"] {{ color:var(--signal) !important; background:var(--surface); }}

div[data-testid="stExpander"] {{ border:1px solid var(--line); border-radius:9px; background:var(--surface); }}
.stDataFrame {{ border:1px solid var(--line); border-radius:9px; }}
hr {{ border-color:var(--line); }}

/* Acessibilidade: foco visível e respeito a movimento reduzido */
*:focus-visible {{ outline:2px solid var(--signal); outline-offset:2px; }}
@media (prefers-reduced-motion:reduce) {{ * {{ transition:none !important; animation:none !important; }} }}
</style>""", unsafe_allow_html=True)


inject_theme()


# ========================================================================
# Portão de acesso
#
# Só entra em ação se houver senha configurada em
# .streamlit/secrets.toml (chave `app_password`) ou na variável de
# ambiente APP_PASSWORD. Sem senha definida, o app abre direto — é o
# comportamento certo para uso local, onde a única forma de chegar até
# ele é já estar na máquina.
#
# A senha existe para o acesso remoto: publicado por um túnel, o app
# fica alcançável por quem tiver a URL. Comparação com
# `compare_digest` para não vazar informação pelo tempo de resposta.
# ========================================================================
def _senha_configurada():
    try:
        senha = st.secrets.get("app_password")
    except Exception:
        senha = None
    return senha or os.environ.get("APP_PASSWORD") or None


def portao_de_acesso() -> None:
    senha_certa = _senha_configurada()
    if not senha_certa or st.session_state.get("_autenticado"):
        return

    _, meio, _ = st.columns([1, 1.5, 1])
    with meio:
        st.markdown(
            f'<div style="text-align:center;padding:52px 0 20px 0">'
            f'<div style="font-family:Space Grotesk,sans-serif;font-size:1.9rem;font-weight:700;'
            f'letter-spacing:-0.03em">TERMINAL <span style="color:{COLORS["signal"]}">SMC</span></div>'
            f'<div style="font-family:JetBrains Mono,monospace;font-size:0.64rem;'
            f'letter-spacing:0.16em;color:{COLORS["muted"]};text-transform:uppercase;margin-top:6px">'
            f'Acesso restrito</div></div>',
            unsafe_allow_html=True,
        )
        tentativa = st.text_input("Senha", type="password", key="_senha_input",
                                  label_visibility="collapsed", placeholder="Senha de acesso")
        if st.button("Entrar", type="primary", use_container_width=True):
            if hmac.compare_digest(str(tentativa), str(senha_certa)):
                st.session_state._autenticado = True
                st.rerun()
            else:
                st.markdown(
                    f'<div style="color:{COLORS["sell"]};font-size:0.84rem;text-align:center;'
                    f'margin-top:10px">Senha incorreta.</div>',
                    unsafe_allow_html=True,
                )
    st.stop()


portao_de_acesso()



# ========================================================================
# Dados / cache / análise
# ========================================================================
@st.cache_data(ttl=60, show_spinner=False)
def _cached_mtf_yahoo(symbol: str, count: int, confirmation: tuple[str, str], context: tuple[str, ...], modality: str, min_stop_atr_mult: float, rsi_os: float, rsi_ob: float):
    daytrade_smc.MIN_STOP_ATR_MULT = min_stop_atr_mult
    # Sobrevenda é sempre o MENOR dos dois. Ordenar aqui impede que uma
    # troca de ordem em qualquer ponto da cadeia inverta a leitura do
    # IFR silenciosamente — bug que já ocorreu e é difícil de notar,
    # porque o app continua funcionando, só que com o sinal ao contrário.
    daytrade_smc.RSI_OVERSOLD = min(rsi_os, rsi_ob)
    daytrade_smc.RSI_OVERBOUGHT = max(rsi_os, rsi_ob)
    counts = {tf: count for tf in (*confirmation, *context)}
    return analyze_symbol_mtf(symbol, confirmation=confirmation, context=context, counts=counts, modality=modality, source="Yahoo Finance")


@st.cache_data(ttl=3, show_spinner=False)
def _cached_mtf_mt5(symbol: str, count: int, confirmation: tuple[str, str], context: tuple[str, ...], modality: str, min_stop_atr_mult: float, rsi_os: float, rsi_ob: float):
    daytrade_smc.MIN_STOP_ATR_MULT = min_stop_atr_mult
    # Sobrevenda é sempre o MENOR dos dois. Ordenar aqui impede que uma
    # troca de ordem em qualquer ponto da cadeia inverta a leitura do
    # IFR silenciosamente — bug que já ocorreu e é difícil de notar,
    # porque o app continua funcionando, só que com o sinal ao contrário.
    daytrade_smc.RSI_OVERSOLD = min(rsi_os, rsi_ob)
    daytrade_smc.RSI_OVERBOUGHT = max(rsi_os, rsi_ob)
    counts = {tf: count for tf in (*confirmation, *context)}
    return analyze_symbol_mtf(symbol, confirmation=confirmation, context=context, counts=counts, modality=modality, source="MetaTrader 5")


@st.cache_data(ttl=10, show_spinner=False)
def _cached_mtf_github(symbol: str, count: int, confirmation: tuple[str, str], context: tuple[str, ...], modality: str, min_stop_atr_mult: float, rsi_os: float, rsi_ob: float):
    daytrade_smc.MIN_STOP_ATR_MULT = min_stop_atr_mult
    # Sobrevenda é sempre o MENOR dos dois. Ordenar aqui impede que uma
    # troca de ordem em qualquer ponto da cadeia inverta a leitura do
    # IFR silenciosamente — bug que já ocorreu e é difícil de notar,
    # porque o app continua funcionando, só que com o sinal ao contrário.
    daytrade_smc.RSI_OVERSOLD = min(rsi_os, rsi_ob)
    daytrade_smc.RSI_OVERBOUGHT = max(rsi_os, rsi_ob)
    counts = {tf: count for tf in (*confirmation, *context)}
    return analyze_symbol_mtf(symbol, confirmation=confirmation, context=context, counts=counts, modality=modality, source="GitHub (MT5 de casa)")


def cached_mtf(symbol: str, count: int, confirmation: tuple[str, str], context: tuple[str, ...], modality: str, source: str, min_stop_atr_mult: float, rsi_os: float, rsi_ob: float):
    """
    Cacheia o pacote de timeframes. Yahoo Finance usa 60s de cache (tem
    rate limit); MetaTrader 5 direto usa 3s; GitHub (MT5 de casa) usa
    10s (só muda quando você clica em "Atualizar via MT5", então não
    precisa ser tão curto). Três funções fixas em vez de decoradas
    dinamicamente, pelo mesmo motivo dos fragmentos de auto-refresh:
    evita o bug de identidade de widget no React já corrigido antes
    neste projeto.

    `min_stop_atr_mult` entra como parâmetro (não só variável global)
    justamente pra fazer parte da CHAVE do cache — sem isso, mudar o
    piso do stop na barra lateral continuaria mostrando, por alguns
    segundos, resultado calculado com o valor antigo.
    """
    if source == "MetaTrader 5":
        return _cached_mtf_mt5(symbol, count, confirmation, context, modality, min_stop_atr_mult, rsi_os, rsi_ob)
    if source == "GitHub (MT5 de casa)":
        return _cached_mtf_github(symbol, count, confirmation, context, modality, min_stop_atr_mult, rsi_os, rsi_ob)
    return _cached_mtf_yahoo(symbol, count, confirmation, context, modality, min_stop_atr_mult, rsi_os, rsi_ob)


def find_fvg_zone(df: pd.DataFrame, max_age: int = 20) -> dict | None:
    """
    Replica a lógica de `detect_fvg_setup` (do seu motor original), mas
    devolve os PREÇOS do gap em vez de só um texto — usado unicamente
    para desenhar a zona no gráfico. Não influencia nenhum score; a
    decisão de score continua 100% dentro de `daytrade_smc.py`.
    """
    current_price = float(df["close"].iloc[-1])
    tolerance = current_price * 0.0015
    first = max(1, len(df) - max_age)

    for middle in range(len(df) - 2, first - 1, -1):
        candle_1 = df.iloc[middle - 1]
        candle_3 = df.iloc[middle + 1]

        if candle_1["high"] < candle_3["low"]:
            bottom, top = float(candle_1["high"]), float(candle_3["low"])
            filled = bool((df["low"].iloc[middle + 2:] <= bottom).any())
            near = bottom - tolerance <= current_price <= top + tolerance
            if not filled and near:
                return {"kind": "ALTA", "bottom": bottom, "top": top, "start_idx": middle - 1}

        if candle_1["low"] > candle_3["high"]:
            bottom, top = float(candle_3["high"]), float(candle_1["low"])
            filled = bool((df["high"].iloc[middle + 2:] >= top).any())
            near = bottom - tolerance <= current_price <= top + tolerance
            if not filled and near:
                return {"kind": "BAIXA", "bottom": bottom, "top": top, "start_idx": middle - 1}

    return None


# ========================================================================
# Gráfico
# ========================================================================
def build_chart(context, active_signal: Signal | None, symbol: str) -> go.Figure:
    df = context.df
    # BUG CORRIGIDO: os candles vêm do Yahoo em UTC (fetch_ohlcv normaliza
    # tudo pra UTC internamente), mas estavam sendo plotados sem converter
    # pro horário de Brasília — isso deixava CADA candle 3 horas adiantado
    # em relação ao gráfico real, um erro sistêmico que afeta todo ativo,
    # mais visível em M15 (equivale a 12 candles de deslocamento).
    x = df.index.tz_convert("America/Sao_Paulo")

    fig = go.Figure()

    fig.add_trace(
        go.Candlestick(
            x=x, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
            name=symbol, increasing_line_color="#2ed3a3", decreasing_line_color="#ff5470",
            increasing_fillcolor="#2ed3a3", decreasing_fillcolor="#ff5470",
        )
    )

    ema_colors = {"ema_9": "#5ec8ff", "ema_21": "#a78bfa", "ema_50": "#f0b429", "ema_200": "#ff8a3d"}
    for col, color in ema_colors.items():
        fig.add_trace(
            go.Scatter(x=x, y=context.emas[col], mode="lines", name=col.upper().replace("_", " "),
                       line=dict(color=color, width=1.3))
        )

    fig.add_trace(
        go.Scatter(x=x, y=context.vwap_series, mode="lines", name="VWAP",
                   line=dict(color="#2ed3a3", width=1.6, dash="dot"))
    )

    swing_highs = [(x[s.index], s.price) for s in context.swings if s.kind == "HIGH"]
    swing_lows = [(x[s.index], s.price) for s in context.swings if s.kind == "LOW"]
    if swing_highs:
        fig.add_trace(go.Scatter(
            x=[p[0] for p in swing_highs], y=[p[1] for p in swing_highs], mode="markers",
            name="Swing High", marker=dict(symbol="triangle-down", size=7, color="#ff5470"),
        ))
    if swing_lows:
        fig.add_trace(go.Scatter(
            x=[p[0] for p in swing_lows], y=[p[1] for p in swing_lows], mode="markers",
            name="Swing Low", marker=dict(symbol="triangle-up", size=7, color="#2ed3a3"),
        ))

    for kind, symb, color in [("BOS", "diamond", "#f0b429"), ("CHOCH", "star", "#ffffff")]:
        pts = [e for e in context.events if e.kind == kind]
        if not pts:
            continue
        fig.add_trace(go.Scatter(
            x=[x[e.index] for e in pts],
            y=[df["high"].iloc[e.index] * 1.003 if e.direction == Direction.BUY else df["low"].iloc[e.index] * 0.997 for e in pts],
            mode="markers+text", name=kind,
            marker=dict(symbol=symb, size=11, color=color, line=dict(width=1, color="#0a0e13")),
            text=[kind] * len(pts), textposition="top center", textfont=dict(size=9, color=color),
        ))

    fvg = find_fvg_zone(df)
    if fvg is not None:
        color = "#2ed3a3" if fvg["kind"] == "ALTA" else "#ff5470"
        fig.add_shape(
            type="rect", xref="x", yref="y",
            x0=x[fvg["start_idx"]], x1=x[-1],
            y0=fvg["bottom"], y1=fvg["top"],
            fillcolor=color, opacity=0.12, line=dict(width=1, color=color, dash="dot"),
        )
        fig.add_annotation(
            x=x[fvg["start_idx"]], y=fvg["top"], text=f"FVG {fvg['kind']}",
            showarrow=False, font=dict(size=9, color=color), xanchor="left", yanchor="bottom",
        )

    if active_signal is not None and active_signal.risk.entry is not None:
        r = active_signal.risk
        levels = [("Entrada", r.entry, "#e7ecf1"), ("Stop", r.stop, "#ff5470"),
                  ("Alvo 1", r.target_1, "#2ed3a3"), ("Alvo 2", r.target_2, "#2ed3a3")]
        for label, price, color in levels:
            if price is None:
                continue
            fig.add_hline(y=price, line=dict(color=color, width=1.4, dash="solid" if label != "Alvo 2" else "dash"),
                          annotation_text=f"{label}: {price:.2f}", annotation_position="right",
                          annotation=dict(font=dict(size=10, color=color)))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=COLORS["surface"], plot_bgcolor=COLORS["surface"],
        height=560, margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0,
                    font=dict(size=10, color=COLORS["muted"])),
        font=dict(family="JetBrains Mono, monospace", size=11, color=COLORS["muted"]),
        xaxis=dict(gridcolor=COLORS["line"], zerolinecolor=COLORS["line"]),
        yaxis=dict(gridcolor=COLORS["line"], zerolinecolor=COLORS["line"], side="right"),
        hoverlabel=dict(bgcolor=COLORS["surface_2"], font_family="JetBrains Mono, monospace"),
    )
    return fig


# ========================================================================
# Painéis
# ========================================================================
def render_signal_panel(signal: Signal, symbol: str, risk_budget: float | None) -> None:
    color = DIRECTION_COLOR[signal.direction]
    q = quality(signal.score)

    if q == "OPORTUNIDADE EXCEPCIONAL" and signal.direction != Direction.NEUTRAL:
        action = "COMPRA" if signal.direction == Direction.BUY else "VENDA"
        st.markdown(
            f'<div style="border:2px solid #f0b429; border-radius:8px; padding:10px 16px; '
            f'background:#f0b42922; margin-bottom:12px; text-align:center;">'
            f'<span style="font-size:18px;">🌟 <b style="color:#f0b429;">OPORTUNIDADE EXCEPCIONAL</b> · '
            f'{action} · score {signal.score:.1f}/100</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    c1, c2, c3 = st.columns([2, 1, 1])
    c1.markdown(f"### {signal.setup}")
    c2.metric("Direção", signal.direction.value)
    c3.metric("Score", f"{signal.score:.1f}/100", q)

    risk = signal.risk
    if signal.direction == Direction.NEUTRAL or risk.entry is None:
        st.info("Sem sinal operável nesta leitura — entrada, stop e alvos foram bloqueados.")
    else:
        action = "COMPRAR" if signal.direction == Direction.BUY else "VENDER"
        st.markdown(
            f"> **{action} {symbol}** perto de **R$ {risk.entry:.2f}**, stop em "
            f"**R$ {risk.stop:.2f}**, alvo em **R$ {risk.target_1:.2f}** (R/R 1:{risk.rr:.2f})."
        )

        cols = st.columns(4)
        cols[0].metric("Entrada", f"R$ {risk.entry:.2f}")
        cols[1].metric("Stop", f"R$ {risk.stop:.2f}", f"{(risk.stop-risk.entry)/risk.entry*100:+.2f}%")
        cols[2].metric("Alvo 1", f"R$ {risk.target_1:.2f}", f"{(risk.target_1-risk.entry)/risk.entry*100:+.2f}%")
        cols[3].metric("Alvo 2", f"R$ {risk.target_2:.2f}", f"{(risk.target_2-risk.entry)/risk.entry*100:+.2f}%")

        st.caption(f"Risco por ação: R$ {abs(risk.entry-risk.stop):.2f} · Base do stop: {risk.stop_basis}")

        if risk_budget:
            risk_per_share = abs(risk.entry - risk.stop)
            if risk_per_share > 0:
                # +15% sobre o dimensionamento teórico: compensa o
                # alvo encurtado em 15%, mantendo o retorno financeiro
                # por operação aproximadamente igual.
                boost = getattr(daytrade_smc, "QUANTITY_BOOST", 1.0)
                qty = int((risk_budget // risk_per_share) * boost)
                st.caption(f"Com risco de R$ {risk_budget:.2f}: **{qty} ações** · "
                          f"risco real R$ {qty*risk_per_share:.2f} · total R$ {qty*risk.entry:.2f}"
                          + (f" · inclui +{(boost-1)*100:.0f}% de ajuste" if boost != 1.0 else ""))

        if risk.alternatives:
            st.markdown("**Possibilidades de saída:**")
            st.dataframe(
                [{"Método": t["method"], "Preço": round(t["price"], 2), "R/R": round(t["rr"], 2),
                  "Status": "Viável" if t["viable"] else "Fraco"} for t in risk.alternatives],
                hide_index=True, use_container_width=True,
            )

    with st.expander("Motivos e alertas"):
        for reason in signal.reasons:
            st.write(f"- {reason}")
        for alert in dict.fromkeys(signal.alerts):
            st.warning(alert)


TIMEFRAME_LABELS = {
    "M5": "5 minutos",
    "M15": "15 minutos",
    "H1": "60 minutos",
    "H4": "240 minutos",
    "D1": "Diário",
    "W1": "Semanal",
}


def render_confirmation_badge(mtf, confirmation: tuple[str, str], symbol: str, style: str, source: str, min_score_to_log: float) -> None:
    tf_a, tf_b = confirmation
    result_a = mtf.results[tf_a]
    result_b = mtf.results[tf_b]

    if result_a.error or result_b.error:
        st.warning(
            f"⚠️ Não foi possível confirmar — falha ao buscar {tf_a} e/ou {tf_b}. "
            f"{result_a.error or ''} {result_b.error or ''}".strip()
        )
        return

    if mtf.modality == ALL_MODALITIES_OPTION:
        dir_a = overall_direction(result_a.signals)
        dir_b = overall_direction(result_b.signals)
        agree_a, total_a = overall_agreement(result_a.signals)
        agree_b, total_b = overall_agreement(result_b.signals)
        agreement_note = f" ({tf_a}: {agree_a}/{total_a} leituras concordam · {tf_b}: {agree_b}/{total_b})"
    else:
        dir_a = next(s.direction for s in result_a.signals if s.name == mtf.modality)
        dir_b = next(s.direction for s in result_b.signals if s.name == mtf.modality)
        agreement_note = ""

    if mtf.confirmed:
        color = DIRECTION_COLOR[mtf.confirmed_direction]
        if mtf.modality == ALL_MODALITIES_OPTION:
            score_for_badge = overall_score(result_a.signals)
            confluence_a = next(s for s in result_a.signals if s.name == "Confluência")
            # só registra o plano de risco da Confluência se ela concordar com a
            # direção geral — senão não há entrada/stop/alvo coerentes pra logar
            loggable_signal = (
                Signal("Todas as modalidades", mtf.confirmed_direction, score_for_badge, score_for_badge,
                       confluence_a.setup, risk=confluence_a.risk)
                if confluence_a.direction == mtf.confirmed_direction else None
            )
        else:
            score_for_badge = next(s.score for s in result_a.signals if s.name == mtf.modality)
            loggable_signal = next(s for s in result_a.signals if s.name == mtf.modality)

        below_threshold = score_for_badge < min_score_to_log

        if loggable_signal is not None and not below_threshold:
            logged = log_signal(symbol, tf_a, style, mtf.modality, source, loggable_signal)
            if logged is not None:
                st.toast(f"📝 Sinal registrado no histórico às {pd.Timestamp(logged['logged_at']).strftime('%H:%M:%S')}", icon="📝")

        star = "🌟 " if quality(score_for_badge) == "OPORTUNIDADE EXCEPCIONAL" else ""

        if below_threshold:
            # Confirmado, mas abaixo do piso de qualidade escolhido:
            # aparece para estudo e NÃO entra no histórico, para não
            # misturar sinal fraco com forte nas estatísticas.
            st.markdown(
                f'<div class="card accent-mute">'
                f'<div class="eyebrow">Confirmado · score abaixo do piso</div>'
                f'<div style="font-family:Space Grotesk,sans-serif;font-size:1.14rem;font-weight:700;'
                f'color:{COLORS["muted"]}">{mtf.confirmed_direction.value} '
                f'<span class="mono" style="font-size:0.9rem;font-weight:500">'
                f'{score_for_badge:.0f}/100</span></div>'
                f'<div style="color:{COLORS["muted"]};font-size:0.84rem;margin-top:6px">'
                f'Abaixo do mínimo de {min_score_to_log:.0f} · leitura {mtf.modality}{agreement_note} · '
                f'não registrado no histórico.</div></div>',
                unsafe_allow_html=True,
            )
        else:
            classe = "accent-buy" if mtf.confirmed_direction == Direction.BUY else "accent-sell"
            st.markdown(
                f'<div class="card {classe}">'
                f'<div class="eyebrow">Confirmado · {TIMEFRAME_LABELS.get(tf_a, tf_a)} + '
                f'{TIMEFRAME_LABELS.get(tf_b, tf_b)} · {mtf.modality}</div>'
                f'<div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap">'
                f'<span style="font-family:Space Grotesk,sans-serif;font-size:1.62rem;font-weight:700;'
                f'color:{color};letter-spacing:-0.02em">{star}{mtf.confirmed_direction.value}</span>'
                f'<span class="mono" style="font-size:1.02rem;font-weight:700;color:{color}">'
                f'{score_for_badge:.0f}<span style="color:{COLORS["muted"]};font-size:0.76rem">/100</span></span>'
                f'</div>'
                f'<div style="color:{COLORS["muted"]};font-size:0.82rem;margin-top:5px">'
                f'Os dois prazos concordam{agreement_note} · registrado no histórico.</div></div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            f'<div class="card accent-mute">'
            f'<div class="eyebrow">Sem confirmação · {mtf.modality}</div>'
            f'<div style="font-family:Space Grotesk,sans-serif;font-size:1.22rem;font-weight:700;'
            f'color:{COLORS["muted"]}">AGUARDANDO</div>'
            f'<div style="color:{COLORS["muted"]};font-size:0.84rem;margin-top:6px">'
            f'{TIMEFRAME_LABELS.get(tf_a, tf_a)} indica <b style="color:{DIRECTION_COLOR[dir_a]}">{dir_a.value}</b>, '
            f'{TIMEFRAME_LABELS.get(tf_b, tf_b)} indica <b style="color:{DIRECTION_COLOR[dir_b]}">{dir_b.value}</b>. '
            f'Só vira recomendação quando os dois apontam para o mesmo lado.</div></div>',
            unsafe_allow_html=True,
        )


OUTCOME_LABELS = {
    "ALVO_1": ("Bateu o Alvo 1", COLORS["buy"]),
    "ALVO_2": ("Bateu o Alvo 2", COLORS["buy"]),
    "STOP": ("Bateu o Stop", COLORS["sell"]),
    "EM_ABERTO": ("Ainda em aberto", COLORS["signal"]),
    "ABERTO": ("Em aberto", COLORS["signal"]),
    "SEM_SINAL": ("Sem sinal operável nesta data", COLORS["muted"]),
    "SEM_DADO_FUTURO": ("⏳ Sem candles seguintes disponíveis ainda", "#8291a1"),
}


def render_winfut(style: str, modality: str, source: str, count: int, risk_budget: float | None,
                  min_stop_atr_mult: float, min_score_to_log: float,
                  rsi_os: float, rsi_ob: float) -> None:
    """
    Tela dedicada ao mini índice. Separada da watchlist de ações de
    propósito: o WIN tem código que varia por corretora e vencimento,
    prazos próprios e volatilidade de outra ordem — misturá-lo na
    mesma lista distorceria o ranking do scanner.
    """
    if source != "MetaTrader 5":
        st.markdown(
            f'<div class="card accent-signal">'
            f'<div class="eyebrow">Fonte incompatível</div>'
            f'<div style="font-size:0.92rem">O mini índice só existe via <b>MetaTrader 5</b>. '
            f'O Yahoo Finance não distribui cotação de futuros da B3.</div>'
            f'<div style="color:{COLORS["muted"]};font-size:0.85rem;margin-top:7px">'
            f'Troque a fonte para MetaTrader 5 na barra lateral, com o terminal aberto e logado '
            f'nesta máquina.</div></div>',
            unsafe_allow_html=True,
        )
        return

    resolver = getattr(daytrade_smc, "resolve_winfut_symbol", None)
    codigo = resolver() if resolver else None
    if codigo is None:
        st.markdown(
            f'<div class="card accent-sell">'
            f'<div class="eyebrow">Contrato não encontrado</div>'
            f'<div style="font-size:0.92rem">Nenhum contrato de mini índice apareceu nesta conta MT5.</div>'
            f'<div style="color:{COLORS["muted"]};font-size:0.85rem;margin-top:7px">'
            f'Rode <code>python diagnostico_mt5.py</code> na pasta do projeto — ele lista todos os '
            f'códigos com "WIN" que a sua corretora oferece e testa qual entrega candles.</div></div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f'<div class="card accent-mute" style="padding:11px 15px">'
        f'<span class="eyebrow" style="margin:0">Contrato em uso</span> '
        f'<span class="mono" style="color:{COLORS["signal"]};font-weight:700;font-size:1.02rem">{codigo}</span>'
        f'<span style="color:{COLORS["muted"]};font-size:0.8rem"> · resolvido automaticamente pelo '
        f'terminal · contínuo preferido para não quebrar o histórico na virada de vencimento</span></div>',
        unsafe_allow_html=True,
    )

    render_individual_analysis(_opcional("WINFUT_LABEL", "WINFUT"), style, modality, source, count,
                               risk_budget, min_stop_atr_mult, min_score_to_log, rsi_os, rsi_ob)


def render_signal_history() -> None:
    st.caption(
        "Toda recomendação **CONFIRMADA** (Análise individual ou Scanner) é registrada aqui "
        "automaticamente, com o horário exato em que apareceu. Clique em **Verificar sinais em "
        "aberto** para conferir, com dados reais buscados depois de cada sinal, se o preço já "
        "bateu o Alvo 1, o Alvo 2 ou o Stop."
    )

    col1, col2, _ = st.columns([1.4, 1, 2])
    with col1:
        if st.button("🔄 Verificar sinais em aberto", type="primary", use_container_width=True):
            with st.spinner("Conferindo sinais em aberto com dados reais..."):
                refresh_signal_log()
            st.rerun()
    with col2:
        if st.button("🗑️ Limpar histórico", use_container_width=True):
            clear_signal_log()
            st.rerun()

    entries = load_signal_log()
    if not entries:
        st.info(
            "Nenhuma recomendação registrada ainda. Elas aparecem aqui automaticamente assim que "
            "uma análise (Individual ou Scanner) mostrar uma recomendação **CONFIRMADA** (os dois "
            "timeframes de confirmação concordando)."
        )
        return

    open_count = sum(1 for e in entries if e.get("status") == "ABERTO")
    hit_count = sum(1 for e in entries if e.get("status") in ("ALVO_1", "ALVO_2"))
    stop_count = sum(1 for e in entries if e.get("status") == "STOP")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total registrado", len(entries))
    c2.metric("Em aberto", open_count)
    c3.metric("Bateram alvo", hit_count)
    c4.metric("Bateram stop", stop_count)

    status_filter = st.multiselect(
        "Filtrar por status",
        ["ABERTO", "ALVO_1", "ALVO_2", "STOP"],
        default=["ABERTO", "ALVO_1", "ALVO_2", "STOP"],
        format_func=lambda s: OUTCOME_LABELS.get(s, (s, ""))[0],
    )
    symbol_filter = st.multiselect(
        "Filtrar por ativo", sorted({e["symbol"] for e in entries}),
    )

    filtered = [e for e in entries if e.get("status") in status_filter]
    if symbol_filter:
        filtered = [e for e in filtered if e["symbol"] in symbol_filter]
    filtered.sort(key=lambda e: e["logged_at"], reverse=True)

    st.markdown("---")

    if not filtered:
        st.caption("Nenhum registro para os filtros selecionados.")
        return

    for e in filtered:
        status = e.get("status", "ABERTO")
        label, color = OUTCOME_LABELS.get(status, (status, "#8291a1"))
        logged_dt = pd.Timestamp(e["logged_at"])
        dir_color = DIRECTION_COLOR.get(Direction(e["direction"]), "#8291a1")

        target_1_txt = f'R$ {e["target_1"]:.2f}' if e.get("target_1") is not None else "—"
        target_2_txt = f' · Alvo 2 R$ {e["target_2"]:.2f}' if e.get("target_2") is not None else ""

        st.markdown(
            f'<div style="border:1px solid {color}; border-radius:8px; padding:12px 16px; '
            f'background:{color}18; margin-bottom:10px;">'
            f'<b>{e["symbol"]}</b> · {TIMEFRAME_LABELS.get(e["timeframe"], e["timeframe"])} · '
            f'{e.get("style","")} · leitura: {e.get("modality","")} · '
            f'<b style="color:{dir_color}">{e["direction"]}</b> · score {e.get("score","—")}/100'
            f'<br>Recomendação registrada às <b>{logged_dt.strftime("%d/%m/%Y %H:%M:%S")}</b> · '
            f'Entrada R$ {e["entry"]:.2f} · Stop R$ {e["stop"]:.2f} · Alvo 1 {target_1_txt}{target_2_txt}'
            f'<br><b style="color:{color}">{label}</b>'
            f' — {e.get("status_detail","")}'
            f'</div>',
            unsafe_allow_html=True,
        )

    with st.expander("Remover um registro específico"):
        labels = {
            f'{e["symbol"]} · {e["direction"]} · {pd.Timestamp(e["logged_at"]).strftime("%d/%m %H:%M")} · '
            f'{OUTCOME_LABELS.get(e.get("status"), (e.get("status"), ""))[0]}': e["id"]
            for e in filtered
        }
        pick_label = st.selectbox("Selecione o registro", list(labels.keys()))
        if st.button("Remover este registro"):
            delete_signal_log_entry(labels[pick_label])
            st.rerun()


def render_retro_check(symbol: str, style: str, modality: str, source: str, count: int) -> None:
    st.caption(
        "Roda a análise usando SÓ os dados que existiam até a data escolhida (sem espiar o "
        "futuro), depois confere o que aconteceu de verdade nos candles seguintes — se bateu "
        "entrada, alvo ou stop."
    )

    all_tfs = list(dict.fromkeys([*STYLES[style]["confirmation"], *STYLES[style]["context"]]))
    col1, col2 = st.columns(2)
    with col1:
        check_tf = st.selectbox("Timeframe a verificar", all_tfs, format_func=lambda tf: TIMEFRAME_LABELS[tf])
    with col2:
        default_date = pd.Timestamp.now(tz="America/Sao_Paulo").date() - pd.Timedelta(days=1)
        as_of_date = st.date_input("Data (fechamento até esse dia)", value=default_date)

    if st.button("🔍 Verificar", type="primary"):
        as_of_ts = pd.Timestamp(as_of_date).tz_localize("America/Sao_Paulo") + pd.Timedelta(hours=23, minutes=59)
        try:
            check = check_signal_as_of(symbol, check_tf, as_of_ts, count=count, modality=modality, source=source)
        except Exception as exc:
            st.error(f"Não foi possível verificar: {exc}")
            return

        st.markdown(f"**{symbol}** em **{TIMEFRAME_LABELS[check_tf]}** (leitura: **{modality}**), com dados até "
                   f"**{check.as_of.strftime('%d/%m/%Y %H:%M')}**")

        if check.direction == Direction.NEUTRAL or check.risk.entry is None:
            st.info(f"Não havia sinal operável nesta data ({modality} estava NEUTRO).")
            return

        color = DIRECTION_COLOR[check.direction]
        action = "COMPRAR" if check.direction == Direction.BUY else "VENDER"
        if quality(check.score) == "OPORTUNIDADE EXCEPCIONAL":
            st.markdown("🌟 **OPORTUNIDADE EXCEPCIONAL** nesta data")
        st.markdown(
            f'> **{action} {symbol}** perto de **R$ {check.risk.entry:.2f}**, stop em '
            f'**R$ {check.risk.stop:.2f}**, alvo em **R$ {check.risk.target_1:.2f}** '
            f'(setup: {check.setup}, score {check.score:.1f}/100)'
        )

        outcome_label, outcome_color = OUTCOME_LABELS[check.outcome]
        st.markdown(
            f'<div style="border:1px solid {outcome_color}; border-radius:8px; padding:12px 16px; '
            f'background:{outcome_color}18; margin:10px 0;">'
            f'<b style="color:{outcome_color}">{outcome_label}</b><br>{check.outcome_detail}'
            f'</div>',
            unsafe_allow_html=True,
        )

        if check.outcome in ("EM_ABERTO", "STOP", "ALVO_1", "ALVO_2"):
            st.caption(f"Candles disponíveis após a data escolhida: {check.candles_futuros_disponiveis}")


def render_individual_analysis(symbol: str, style: str, modality: str, source: str, count: int, risk_budget: float | None, min_stop_atr_mult: float, min_score_to_log: float, rsi_os: float, rsi_ob: float) -> None:
    confirmation = STYLES[style]["confirmation"]
    context_tfs = STYLES[style]["context"]
    all_tfs = list(confirmation) + [tf for tf in context_tfs if tf not in confirmation]

    fonte_label = "MT5 (tempo real)" if source == "MetaTrader 5" else "Yahoo Finance (atraso ~15-20min)"
    with st.spinner(f"Buscando {', '.join(TIMEFRAME_LABELS[tf] for tf in all_tfs)} de {symbol} via {fonte_label}..."):
        mtf = cached_mtf(symbol, count, confirmation, context_tfs, modality, source, min_stop_atr_mult, rsi_os, rsi_ob)

    render_confirmation_badge(mtf, confirmation, symbol, style, source, min_score_to_log)
    render_rsi_multi_tf(mtf)

    tf_tabs = st.tabs([TIMEFRAME_LABELS[tf] + (" (contexto)" if tf not in confirmation else "") for tf in all_tfs])
    for tab, tf in zip(tf_tabs, all_tfs):
        with tab:
            result = mtf.results[tf]
            if result.error:
                st.error(f"Não foi possível analisar {symbol} em {tf}: {result.error}")
                continue
            render_timeframe_panel(symbol, tf, result.context, result.signals, risk_budget)


def _rsi_rail_html(rsi: float, os_: float, ob: float) -> str:
    """Trilho de IFR com as zonas de exaustão marcadas fisicamente."""
    quente = rsi <= os_ or rsi >= ob
    pos = min(max(rsi, 0), 100)
    return (
        f'<div class="rsi-rail" style="--os:{os_:.0f}%; --ob:{ob:.0f}%">'
        f'<span class="zone-lab" style="left:6px">COMPRA</span>'
        f'<span class="zone-lab" style="right:6px">VENDA</span>'
        f'<span class="pin{" hot" if quente else ""}" style="left:calc({pos:.1f}% - 1.5px)"></span>'
        f'</div>'
    )


def render_rsi_multi_tf(mtf) -> None:
    """
    Consolida a leitura de IFR de todos os prazos. Cada um ganha uma
    linha com barra posicional — comparar prazos vira leitura espacial,
    não aritmética.
    """
    consolidar = getattr(daytrade_smc, "rsi_extremes_across_timeframes", None)
    if consolidar is None:
        return
    resumo = consolidar(mtf)
    por_tf = resumo["por_tf"]
    if not por_tf:
        return

    _a = getattr(daytrade_smc, "RSI_OVERBOUGHT", 90.0)
    _b = getattr(daytrade_smc, "RSI_OVERSOLD", 10.0)
    os_, ob = min(_a, _b), max(_a, _b)
    n, direcao = resumo["alinhamento"], resumo["direcao"]

    if n >= 1:
        classe, cor = "accent-signal", COLORS["signal"]
        plural = "PRAZOS" if n > 1 else "PRAZO"
        titulo = f"EXAUSTÃO EM {n} {plural} · {direcao}"
    else:
        classe, cor = "accent-mute", COLORS["muted"]
        titulo = "SEM EXAUSTÃO"

    ordem = ["M5", "M15", "H1", "H4", "D1", "W1"]
    linhas = []
    for tf in [t for t in ordem if t in por_tf]:
        valor, extremo = por_tf[tf]
        quente = extremo is not None
        cor_val = (COLORS["buy"] if extremo == Direction.BUY.value
                   else COLORS["sell"] if extremo == Direction.SELL.value else COLORS["muted"])
        tag = ("EXAURIDO ↓" if extremo == Direction.BUY.value
               else "EXAURIDO ↑" if extremo == Direction.SELL.value else "—")
        linhas.append(
            f'<div class="tf-row">'
            f'<span class="tf">{TIMEFRAME_LABELS.get(tf, tf)}</span>'
            f'<span class="val" style="color:{cor_val}">{valor:.0f}</span>'
            f'<span class="bar"><i class="{"hot" if quente else ""}" '
            f'style="left:calc({min(max(valor,0),100):.1f}% - 1px)"></i></span>'
            f'<span class="tag" style="color:{cor_val}">{tag}</span>'
            f'</div>'
        )

    st.markdown(
        f'<div class="card {classe}">'
        f'<div class="eyebrow">Índice de força relativa · limiar {os_:.0f} / {ob:.0f}</div>'
        f'<div style="font-family:Space Grotesk,sans-serif;font-size:1.02rem;'
        f'font-weight:700;color:{cor};margin-bottom:10px">{titulo}</div>'
        f'{"".join(linhas)}'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_rsi_badge(context) -> None:
    """Trilho de IFR do prazo atual, com o diário como referência."""
    rsi = context.rsi
    _a = getattr(daytrade_smc, "RSI_OVERBOUGHT", 90.0)
    _b = getattr(daytrade_smc, "RSI_OVERSOLD", 10.0)
    os_, ob = min(_a, _b), max(_a, _b)

    if rsi <= os_:
        estado, cor, classe = "EXAUSTÃO VENDEDORA → COMPRA", COLORS["buy"], "accent-signal"
    elif rsi >= ob:
        estado, cor, classe = "EXAUSTÃO COMPRADORA → VENDA", COLORS["sell"], "accent-signal"
    else:
        estado, cor, classe = "Sem exaustão", COLORS["muted"], "accent-mute"

    diario = ""
    if context.higher_rsi is not None:
        d = context.higher_rsi
        dz = "exaurido ↓" if d <= os_ else "exaurido ↑" if d >= ob else "neutro"
        diario = (f'<span style="color:{COLORS["muted"]};font-family:JetBrains Mono,monospace;'
                  f'font-size:0.74rem"> · diário {d:.0f} ({dz})</span>')

    st.markdown(
        f'<div class="card {classe}">'
        f'<div class="eyebrow">IFR (14)</div>'
        f'<div><span style="font-family:JetBrains Mono,monospace;font-size:1.5rem;'
        f'font-weight:700;color:{cor}">{rsi:.1f}</span>'
        f'<span style="color:{cor};font-size:0.82rem;margin-left:9px">{estado}</span>{diario}</div>'
        f'{_rsi_rail_html(rsi, os_, ob)}'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_timeframe_panel(symbol: str, timeframe: str, context, signals, risk_budget: float | None) -> None:
    by_name = {s.name: s for s in signals}
    last_open = context.df.index[-1].tz_convert("America/Sao_Paulo")
    fech = float(context.df["close"].iloc[-1])

    st.markdown(
        f'<div class="card accent-mute" style="padding:11px 15px;margin-bottom:12px">'
        f'<span class="mono" style="font-size:1.14rem;font-weight:700">{symbol}</span>'
        f'<span class="mono" style="color:{COLORS["muted"]};font-size:0.78rem"> · '
        f'{TIMEFRAME_LABELS.get(timeframe, timeframe)} · fech. R$ {fech:,.2f} · '
        f'último candle {last_open:%d/%m %H:%M}</span>'
        f'<div class="eyebrow" style="margin:8px 0 0 0">'
        f'ATR {context.atr:.2f} ({context.atr_pct:.2f}%) &nbsp;·&nbsp; '
        f'RVOL {context.rvol:.2f}× &nbsp;·&nbsp; VOLATILIDADE {context.volatility}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    render_rsi_badge(context)

    chart_choice = st.selectbox(
        "Ver entrada/stop/alvo de qual leitura no gráfico:",
        [s.name for s in signals], index=0, key=f"chart_choice_{timeframe}",
    )
    st.plotly_chart(build_chart(context, by_name[chart_choice], symbol), use_container_width=True, key=f"chart_{timeframe}_{chart_choice}")

    tabs = st.tabs([s.name for s in signals])
    for tab, s in zip(tabs, signals):
        with tab:
            render_signal_panel(s, symbol, risk_budget)

    st.markdown("### Resumo — as 6 leituras lado a lado")
    st.dataframe(
        [{
            "Análise": s.name, "Direção": s.direction.value, "Score": round(s.score, 1),
            "Entrada": round(s.risk.entry, 2) if s.risk.entry else None,
            "Stop": round(s.risk.stop, 2) if s.risk.stop else None,
            "Alvo 1": round(s.risk.target_1, 2) if s.risk.target_1 else None,
        } for s in signals],
        hide_index=True, use_container_width=True,
    )


# ========================================================================
# Fragmentos de auto-atualização — IMPORTANTE: precisam ser definidos
# UMA ÚNICA VEZ, em nível de módulo. Criar um `st.fragment(...)` novo
# a cada rerun do script (como dentro de um if/else no corpo principal)
# faz o Streamlit perder a referência de qual pedaço da tela pertence a
# qual fragmento entre uma atualização e outra — e o React trava tentando
# remover um nó do DOM que ele já não reconhece mais (o erro
# "removeChild ... not a child of this node"). Por isso, um fragmento
# fixo por intervalo, nunca criado dinamicamente.
# ========================================================================
@st.fragment(run_every=30)
def _auto_refresh_30(symbol, style, modality, source, count, risk_budget, min_stop_atr_mult, min_score_to_log, rsi_os, rsi_ob):
    render_individual_analysis(symbol, style, modality, source, count, risk_budget, min_stop_atr_mult, min_score_to_log, rsi_os, rsi_ob)


@st.fragment(run_every=60)
def _auto_refresh_60(symbol, style, modality, source, count, risk_budget, min_stop_atr_mult, min_score_to_log, rsi_os, rsi_ob):
    render_individual_analysis(symbol, style, modality, source, count, risk_budget, min_stop_atr_mult, min_score_to_log, rsi_os, rsi_ob)


@st.fragment(run_every=120)
def _auto_refresh_120(symbol, style, modality, source, count, risk_budget, min_stop_atr_mult, min_score_to_log, rsi_os, rsi_ob):
    render_individual_analysis(symbol, style, modality, source, count, risk_budget, min_stop_atr_mult, min_score_to_log, rsi_os, rsi_ob)


@st.fragment(run_every=300)
def _auto_refresh_300(symbol, style, modality, source, count, risk_budget, min_stop_atr_mult, min_score_to_log, rsi_os, rsi_ob):
    render_individual_analysis(symbol, style, modality, source, count, risk_budget, min_stop_atr_mult, min_score_to_log, rsi_os, rsi_ob)


_AUTO_REFRESH_FRAGMENTS = {
    30: _auto_refresh_30,
    60: _auto_refresh_60,
    120: _auto_refresh_120,
    300: _auto_refresh_300,
}


def run_scanner(symbols: list[str], style: str, modality: str, source: str, count: int, risk_budget: float | None, min_stop_atr_mult: float, min_score_to_log: float, rsi_os: float, rsi_ob: float) -> pd.DataFrame:
    rows = []
    progress = st.progress(0.0, text="Iniciando scanner...")
    confirmation = STYLES[style]["confirmation"]
    context_tfs = STYLES[style]["context"]
    tf_a, tf_b = confirmation
    col_a, col_b = f"Score {tf_a}", f"Score {tf_b}"

    for i, symbol in enumerate(symbols):
        progress.progress((i + 1) / len(symbols), text=f"Analisando {symbol} ({i+1}/{len(symbols)})...")
        mtf = cached_mtf(symbol, count, confirmation, context_tfs, modality, source, min_stop_atr_mult, rsi_os, rsi_ob)
        result_a = mtf.results[tf_a]
        result_b = mtf.results[tf_b]

        if result_a.error or result_b.error:
            err = (result_a.error or result_b.error or "")[:60]
            rows.append({"Ativo": symbol, "OK": "⚠️", "Direção": "ERRO", "Score": None,
                        col_a: None, col_b: None, f"IFR {tf_a}": None, "IFR D1": None,
                        "Entrada": None, "Stop": None, "Alvo 1": None,
                        "Setup": err})
            if source != "MetaTrader 5":
                time.sleep(0.3)
            continue

        if modality == ALL_MODALITIES_OPTION:
            score_a = round(overall_score(result_a.signals), 1)
            score_b = round(overall_score(result_b.signals), 1)
            confluence_a = next(s for s in result_a.signals if s.name == "Confluência")
            setup_text = (
                f"Score geral (média de 6 leituras) — {confluence_a.setup}" if mtf.confirmed
                else f"Score geral (média de 6 leituras) — sem confirmação entre {tf_a}/{tf_b}"
            )
            risk = confluence_a.risk if (mtf.confirmed and confluence_a.direction == mtf.confirmed_direction) else None
            loggable_signal = (
                Signal("Todas as modalidades", mtf.confirmed_direction, score_a, score_a, confluence_a.setup, risk=risk)
                if risk is not None else None
            )
        else:
            conf_a = next(s for s in result_a.signals if s.name == modality)
            conf_b = next(s for s in result_b.signals if s.name == modality)
            score_a = round(conf_a.score, 1)
            score_b = round(conf_b.score, 1)
            setup_text = conf_a.setup if mtf.confirmed else f"{tf_a}={conf_a.direction.value} / {tf_b}={conf_b.direction.value}"
            risk = conf_a.risk if mtf.confirmed else None
            loggable_signal = conf_a if mtf.confirmed else None

        if mtf.confirmed and loggable_signal is not None and loggable_signal.score >= min_score_to_log:
            log_signal(symbol, tf_a, style, modality, source, loggable_signal)

        direction_label = mtf.confirmed_direction.value if mtf.confirmed else "NEUTRO"

        score_geral = round((score_a + score_b) / 2, 1)
        destaque = mtf.confirmed and quality(score_geral) == "OPORTUNIDADE EXCEPCIONAL"

        rsi_tf = round(result_a.context.rsi, 1) if result_a.context else None
        d1_result = mtf.results.get("D1")
        rsi_d1 = round(d1_result.context.rsi, 1) if (d1_result and d1_result.context) else None

        # Recomendado = confirmado nos dois prazos E score acima do
        # piso. Sem o piso, ativos com confirmação fraca apareciam com
        # o mesmo destaque dos fortes.
        recomendado = mtf.confirmed and score_geral >= min_score_to_log

        rows.append({
            "Ativo": ("🌟 " if destaque else "") + symbol,
            "OK": "✅" if recomendado else ("~" if mtf.confirmed else "—"),
            "Direção": direction_label,
            "Score": score_geral,
            col_a: score_a,
            col_b: score_b,
            f"IFR {tf_a}": rsi_tf,
            "IFR D1": rsi_d1,
            "Entrada": round(risk.entry, 2) if risk and risk.entry else None,
            "Stop": round(risk.stop, 2) if risk and risk.stop else None,
            "Alvo 1": round(risk.target_1, 2) if risk and risk.target_1 else None,
            "Setup": setup_text,
        })
        if source != "MetaTrader 5":
            time.sleep(0.3)  # folga entre chamadas — reduz risco de rate limit do Yahoo (MT5 é chamada local, sem esse limite)

    progress.empty()
    result = pd.DataFrame(rows)
    if "Score" in result.columns:
        # Ordena confirmadas primeiro, depois pelo Score do maior pro
        # menor. A chave de ordenação NÃO pode ser a coluna "OK"
        # diretamente: ela guarda símbolos ("✅", "—", "⚠️") e a ordem
        # alfabética deles não corresponde à prioridade desejada. Por
        # isso usamos uma coluna auxiliar numérica, descartada em seguida.
        result["_ordem"] = result["OK"].map({"✅": 0, "~": 1, "—": 2, "⚠️": 3}).fillna(4)
        result = result.sort_values(["_ordem", "Score"], ascending=[True, False], na_position="last")
        result = result.drop(columns="_ordem").reset_index(drop=True)
    return result


# ========================================================================
# Estado inicial (ANTES da sidebar, pra widgets com `key` já nascerem
# com o valor certo — evita o bug clássico do Streamlit de "mudei o
# session_state depois que o widget já foi criado")
# ========================================================================
if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_symbols()

if "symbol_select" not in st.session_state:
    st.session_state.symbol_select = st.session_state.watchlist[0]

# Se o Scanner pediu pra "pular" pra um ativo, aplica ANTES do selectbox nascer
if st.session_state.get("jump_to_symbol"):
    target = st.session_state.pop("jump_to_symbol")
    if target in st.session_state.watchlist:
        st.session_state.symbol_select = target
    st.session_state.mode_select = "Análise individual"
    # limpa o estado do seletor "Ativo" do Scanner — ele não vai mais ser
    # renderizado nesta tela, e deixar a chave órfã pode confundir o
    # controle de estado de widgets em alguns cenários
    st.session_state.pop("scanner_pick_select", None)


def _persist_watchlist() -> None:
    try:
        save_symbols(st.session_state.watchlist)
    except OSError:
        pass  # ambiente somente-leitura — a lista continua funcionando na sessão


# ========================================================================
# Sidebar
# ========================================================================
with st.sidebar:
    st.markdown(
        '<div style="font-family:Space Grotesk,sans-serif;font-size:1.24rem;font-weight:700;'
        'letter-spacing:-0.03em;margin-bottom:2px">TERMINAL <span style="color:'
        + COLORS["signal"] + '">SMC</span></div>'
        '<div style="font-family:JetBrains Mono,monospace;font-size:0.6rem;letter-spacing:0.15em;'
        'color:' + COLORS["muted"] + ';text-transform:uppercase;margin-bottom:16px">'
        'SMC · Price Action · Médias · VWAP · IFR</div>',
        unsafe_allow_html=True,
    )

    mode = st.radio(
        "Modo",
        ["Análise individual", "Scanner (todos os ativos)", "WINFUT",
         "Verificação retroativa", "Histórico de Sinais"],
        key="mode_select",
    )

    st.markdown("### Fonte de dados")

    # Detecta uma vez por sessão se há um terminal MT5 acessível nesta
    # máquina. Rodando localmente com o MT5 aberto, o padrão passa a
    # ser MT5 (tempo real) em vez de Yahoo Finance (atrasado ~15-20min).
    # getattr com padrão em vez de chamada direta: se o daytrade_smc.py
    # implantado for de uma versão anterior (sem essa função), o app
    # degrada pra "MT5 indisponível" em vez de quebrar inteiro com
    # AttributeError. Acontece quando só um dos dois arquivos é
    # atualizado no deploy.
    if "mt5_available" not in st.session_state:
        checar_mt5 = getattr(daytrade_smc, "mt5_is_available", None)
        try:
            st.session_state.mt5_available = bool(checar_mt5()) if checar_mt5 else False
        except Exception:
            st.session_state.mt5_available = False

    if st.session_state.mt5_available:
        st.success("🟢 MetaTrader 5 conectado — dados em tempo real disponíveis.")
        default_source_index = DATA_SOURCES.index("MetaTrader 5")
    else:
        default_source_index = DATA_SOURCES.index("Yahoo Finance")

    source = st.radio(
        "Fonte", DATA_SOURCES, key="source_select", horizontal=True, index=default_source_index,
        help="MetaTrader 5 é tempo real, mas só funciona rodando este app na mesma máquina com o "
             "MT5 aberto (é o modo recomendado). Yahoo Finance funciona em qualquer lugar, com "
             "atraso de ~15-20min. \"GitHub (MT5 de casa)\" lê um snapshot publicado por outra "
             "máquina — só use se estiver acessando de fora.",
    )
    if source == "MetaTrader 5" and not st.session_state.mt5_available:
        st.error(
            "⚠️ Nenhum terminal MetaTrader 5 acessível neste ambiente. Isso acontece quando o app "
            "está rodando no Streamlit Cloud (servidor Linux, sem MT5) ou quando o MT5 não está "
            "aberto/logado nesta máquina. Para tempo real, rode o app localmente com o "
            "start_app.bat, na mesma máquina do MT5."
        )
    elif source == "GitHub (MT5 de casa)":
        last_update = fetch_snapshot_timestamp()
        if last_update:
            age_min = (pd.Timestamp.now(tz="UTC") - pd.Timestamp(last_update)).total_seconds() / 60
            st.caption(
                f"📅 Última atualização: {pd.Timestamp(last_update).tz_convert('America/Sao_Paulo').strftime('%d/%m/%Y %H:%M:%S')} "
                f"(há {age_min:.0f} min)"
            )
        else:
            st.caption("Nenhuma atualização publicada ainda pelo PC de casa.")

        if st.button("🔄 Atualizar via MT5 (casa)", use_container_width=True):
            ok, msg = request_mt5_update()
            if not ok:
                st.error(msg)
            else:
                st.cache_data.clear()
                with st.spinner("Aguardando seu computador em casa processar (isso leva alguns segundos)..."):
                    trigger_time = pd.Timestamp.now(tz="UTC")
                    updated = False
                    for _ in range(24):  # até ~2min de espera (24 x 5s) -- o vigia no PC checa a cada 15s
                        time.sleep(5)
                        ts = fetch_snapshot_timestamp()
                        if ts and pd.Timestamp(ts) > trigger_time:
                            updated = True
                            break
                if updated:
                    st.cache_data.clear()
                    st.success("Dados atualizados!")
                    st.rerun()
                else:
                    st.warning(
                        "Não detectei a atualização em 2 minutos. Confirme se o PC de casa está "
                        "ligado, o MT5 aberto e logado, e o script 'vigia' (watch_and_sync.ps1) "
                        "rodando. Pode levar mais tempo em alguns casos — tenta de novo em instantes."
                    )

    # No modo WINFUT o estilo é fixo — o mini índice tem recorte de
    # prazos próprio (M5+M15 confirmando), então deixar o seletor
    # aberto ali só criaria combinações sem sentido.
    if mode == "WINFUT":
        style = "WINFUT"
        st.markdown("### Prazos")
        st.caption("Confirmação em **5** e **15 minutos** · **60 minutos** e **Diário** como contexto.")
    else:
        st.markdown("### Estilo de operação")
        style = st.radio(
            "Estilo", ["Day Trade", "Swing Trade"], key="style_select", horizontal=True,
            help="Day Trade confirma em 15+60 minutos (posições no mesmo dia). "
                 "Swing Trade confirma em Diário+Semanal, com 240 minutos como contexto de entrada.",
        )
    conf_a, conf_b = STYLES[style]["confirmation"]

    st.markdown("### Modalidade")
    modality = st.selectbox(
        "Qual leitura usar como base da recomendação", MODALITY_CHOICES, key="modality_select",
        help="Confluência combina as 5 categorias. SMC/Price Action/Médias Móveis/VWAP/IFR usam só "
             "a leitura isolada daquela categoria. \"Todas as modalidades\" calcula um SCORE GERAL "
             "(média das 6 leituras) e usa ele — não uma única leitura — pra decidir a confirmação "
             "e ordenar o Scanner. O IFR usa o Diário como filtro de contexto: sobrecompra/sobrevenda "
             "alinhada nos dois prazos reforça o sinal; contrária reduz.",
    )

    # O seletor de ativo fica FORA do expander: é usado a cada análise,
    # diferente da gestão da watchlist (adicionar/remover), que é
    # configurada uma vez e raramente mexida.
    if mode in ("Análise individual", "Verificação retroativa"):
        st.selectbox("Ativo para análise", st.session_state.watchlist, key="symbol_select")

    with st.expander(f"Gerenciar watchlist ({len(st.session_state.watchlist)} ativos)", expanded=False):
        new_symbol = st.text_input("Adicionar ativo (ex: VALE3)", key="new_symbol_input")
        if st.button("Adicionar", use_container_width=True) and new_symbol.strip():
            value = new_symbol.strip().upper().replace(" ", "")
            if value not in st.session_state.watchlist:
                st.session_state.watchlist.append(value)
                _persist_watchlist()
            st.rerun()

        remove_symbol = st.selectbox("Remover ativo", ["—"] + st.session_state.watchlist, key="remove_symbol_select")
        if st.button("Remover", use_container_width=True) and remove_symbol != "—":
            st.session_state.watchlist = [s for s in st.session_state.watchlist if s != remove_symbol]
            _persist_watchlist()
            st.rerun()

        if st.button("Restaurar lista padrão", use_container_width=True):
            st.session_state.watchlist = DEFAULT_SYMBOLS.copy()
            _persist_watchlist()
            st.rerun()

    with st.expander("Ajustes avançados", expanded=False):
        st.caption(f"A recomendação exige **{TIMEFRAME_LABELS[conf_a]}** e **{TIMEFRAME_LABELS[conf_b]}** concordando. "
                  f"{', '.join(TIMEFRAME_LABELS[tf] for tf in STYLES[style]['context'])} entram como contexto.")
        count = st.slider(STYLES[style]["count_label"], min_value=50, max_value=400, value=250, step=10)
        risk_budget = st.number_input("Risco máximo (R$) — opcional", min_value=0.0, value=0.0, step=50.0)
        risk_budget = risk_budget if risk_budget > 0 else None

        min_stop_atr_mult = st.slider(
            "Piso mínimo do stop (× ATR)", min_value=0.5, max_value=2.5, value=1.0, step=0.25,
            help="Distância mínima entre entrada e stop, em múltiplos do ATR. Valor baixo deixa o "
                 "stop apertado — mais sinais, porém mais vulnerável a ruído do candle seguinte.",
        )
        min_score_to_log = st.slider(
            "Score mínimo para recomendar", min_value=0, max_value=100, value=60, step=5,
            help="Recomendações confirmadas abaixo deste score aparecem na tela, mas não entram no "
                 "Histórico de Sinais — evita misturar sinal fraco com forte nas estatísticas.",
        )

        rsi_os_default, rsi_ob_default = getattr(
            daytrade_smc, "STYLE_RSI_THRESHOLDS", {}
        ).get(style, (10.0, 90.0))
        # O slider de intervalo devolve a tupla em ordem CRESCENTE:
        # (menor, maior) = (sobrevenda, sobrecompra). Nomear na ordem
        # certa aqui é essencial — estas duas variáveis são repassadas
        # posicionalmente para as funções de cache, e uma troca aqui
        # invertia os limiares na análise inteira (IFR 65 aparecia como
        # "exaustão vendedora → compra").
        rsi_os, rsi_ob = st.slider(
            "Limiares do IFR (sobrevenda / sobrecompra)", min_value=0, max_value=100,
            value=(int(rsi_os_default), int(rsi_ob_default)), step=5,
            key=f"rsi_thresholds_{style}",
            help=f"Padrão para {style}: {rsi_os_default:.0f}/{rsi_ob_default:.0f}. "
                 "Compra só abaixo do primeiro valor; venda só acima do segundo. "
                 "Em 10/90 o IFR dispara raramente — 20/80 gera mais sinais.",
        )
        daytrade_smc.MIN_STOP_ATR_MULT = min_stop_atr_mult
        daytrade_smc.RSI_OVERSOLD = float(rsi_os)
        daytrade_smc.RSI_OVERBOUGHT = float(rsi_ob)

    if mode == "Análise individual":
        st.markdown("### Atualização")
        auto_refresh = st.checkbox("Atualizar automaticamente")
        refresh_interval = st.select_slider(
            "Intervalo", options=[30, 60, 120, 300], value=60, format_func=lambda s: f"{s}s",
            disabled=not auto_refresh,
        )
    elif mode == "Scanner (todos os ativos)":
        run_scanner_clicked = st.button("🔍 Rodar scanner", type="primary", use_container_width=True)


# ========================================================================
# Corpo principal
# ========================================================================
st.title("📊 Day Trade SMC — Análise Técnica")
_agora = pd.Timestamp.now(tz="America/Sao_Paulo")
_pregao = _agora.weekday() < 5 and 10 <= _agora.hour < 18
_fonte_viva = source == "MetaTrader 5" and st.session_state.get("mt5_available")

st.markdown(
    f'<div class="term-head">'
    f'<span class="mark">TERMINAL <span>SMC</span></span>'
    f'<span class="ctx">{mode} · {modality}</span>'
    f'<span class="live">'
    f'<span class="dot {"on" if _pregao else "off"}"></span>'
    f'<span style="color:{COLORS["buy"] if _pregao else COLORS["muted"]}">'
    f'{"PREGÃO ABERTO" if _pregao else "MERCADO FECHADO"}</span>'
    f'<span style="color:{COLORS["muted"]}"> · {_agora:%d/%m %H:%M} · '
    f'{"MT5 TEMPO REAL" if _fonte_viva else source.upper()}</span>'
    f'</span></div>',
    unsafe_allow_html=True,
)

if not _fonte_viva and source == "Yahoo Finance":
    st.markdown(
        f'<div class="card accent-mute" style="padding:11px 15px">'
        f'<span style="color:{COLORS["signal"]};font-size:0.84rem">⏱ Yahoo Finance tem atraso de '
        f'15-20 minutos.</span> <span style="color:{COLORS["muted"]};font-size:0.84rem">'
        f'Use para viés e estrutura — tendência, níveis, força relativa. Confirme o preço de '
        f'execução no MetaTrader ou na tela da corretora antes de entrar.</span></div>',
        unsafe_allow_html=True,
    )

if _RECURSOS_AUSENTES:
    st.markdown(
        f'<div class="card accent-sell">'
        f'<div class="eyebrow">Arquivos fora de sincronia</div>'
        f'<div style="font-size:0.92rem">O <code>daytrade_smc.py</code> em uso é de uma versão '
        f'anterior à do <code>streamlit_app.py</code>. Alguns recursos estão desligados.</div>'
        f'<div style="color:{COLORS["muted"]};font-size:0.84rem;margin-top:7px">'
        f'Faltando: <code>{", ".join(_RECURSOS_AUSENTES)}</code><br>'
        f'Atualize os <b>dois</b> arquivos juntos — eles mudam em conjunto.</div></div>',
        unsafe_allow_html=True,
    )

if mode == "WINFUT":
    render_winfut(style, modality, source, count, risk_budget,
                  min_stop_atr_mult, min_score_to_log, rsi_os, rsi_ob)

elif mode == "Análise individual":
    symbol = st.session_state.symbol_select

    if auto_refresh:
        st.caption(f"🔄 Atualizando automaticamente a cada {refresh_interval}s")
        _AUTO_REFRESH_FRAGMENTS[refresh_interval](symbol, style, modality, source, count, risk_budget, min_stop_atr_mult, min_score_to_log, rsi_os, rsi_ob)
    else:
        render_individual_analysis(symbol, style, modality, source, count, risk_budget, min_stop_atr_mult, min_score_to_log, rsi_os, rsi_ob)

elif mode == "Scanner (todos os ativos)":
    st.caption(f"{len(st.session_state.watchlist)} ativo(s) na watchlist · {style} · leitura: {modality} · "
              f"{count} candles · recomendação exige {conf_a}+{conf_b} concordando")

    if run_scanner_clicked:
        st.session_state.scanner_result = run_scanner(st.session_state.watchlist, style, modality, source, count, risk_budget, min_stop_atr_mult, min_score_to_log, rsi_os, rsi_ob)
        st.session_state.scanner_risk_budget = risk_budget

    if "scanner_result" in st.session_state:
        result_df = st.session_state.scanner_result

        # --- Resumo no topo: leitura de 2 segundos, antes da tabela ---
        confirmadas = result_df[result_df["OK"] == "✅"] if "OK" in result_df else result_df.iloc[0:0]
        n_compra = int((confirmadas["Direção"] == "COMPRA").sum()) if len(confirmadas) else 0
        n_venda = int((confirmadas["Direção"] == "VENDA").sum()) if len(confirmadas) else 0
        n_fracas = int((result_df["OK"] == "~").sum()) if "OK" in result_df else 0
        n_erro = int((result_df["OK"] == "⚠️").sum()) if "OK" in result_df else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Recomendações", len(confirmadas), f"de {len(result_df)} ativos")
        c2.metric("Compra", n_compra)
        c3.metric("Venda", n_venda)
        c4.metric("Score baixo", n_fracas, f"abaixo de {min_score_to_log:.0f}")
        if n_erro:
            st.caption(f"⚠️ {n_erro} ativo(s) falharam na busca — veja a coluna Setup.")

        # --- Filtros rápidos ---
        so_confirmadas = st.checkbox(f"Só recomendações (score ≥ {min_score_to_log:.0f})", value=False, key="scan_f_conf")
        view = result_df
        if so_confirmadas and "OK" in view:
            view = view[view["OK"] == "✅"]

        if view.empty:
            st.warning("Nenhum ativo atende aos filtros selecionados.")
        else:
            def _color_direction(val):
                if val == "COMPRA":
                    return "color: #2ed3a3; font-weight: 700"
                if val == "VENDA":
                    return "color: #ff5470; font-weight: 700"
                if val == "ERRO":
                    return "color: #f0b429"
                return "color: #8291a1"

            def _color_ifr(val):
                if pd.isna(val):
                    return ""
                if val <= rsi_os:
                    return "color: #2ed3a3; font-weight: 700"
                if val >= rsi_ob:
                    return "color: #ff5470; font-weight: 700"
                return "color: #8291a1"

            ifr_cols = [c for c in view.columns if c.startswith("IFR")]
            styler = (
                view.style
                .map(_color_direction, subset=["Direção"])
                .map(_color_ifr, subset=ifr_cols)
            )

            # Barras de progresso nos scores dão a leitura relativa num
            # relance — bem mais rápido que comparar números soltos.
            col_cfg = {
                "Ativo": st.column_config.TextColumn("Ativo", width="small", pinned=True),
                "OK": st.column_config.TextColumn("OK", width="small", help="✅ recomendado · ~ confirmado mas score baixo · — sem confirmação"),
                "Direção": st.column_config.TextColumn("Direção", width="small"),
                "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f", width="medium"),
                "Entrada": st.column_config.NumberColumn("Entrada", format="R$ %.2f", width="small"),
                "Stop": st.column_config.NumberColumn("Stop", format="R$ %.2f", width="small"),
                "Alvo 1": st.column_config.NumberColumn("Alvo 1", format="R$ %.2f", width="small"),
                "Setup": st.column_config.TextColumn("Setup", width="large"),
            }
            for c in ifr_cols:
                col_cfg[c] = st.column_config.NumberColumn(c, format="%.0f", width="small")

            st.dataframe(
                styler, hide_index=True, use_container_width=True,
                height=min(560, 45 + 35 * len(view)), column_config=col_cfg,
            )
            st.caption(
                f"Ordenado por recomendação e score · 🌟 = oportunidade excepcional · "
                f"IFR colorido nos extremos ({rsi_os:.0f}/{rsi_ob:.0f}) · "
                f"🎯 = exaustão em 2+ timeframes"
            )

        st.markdown("#### Abrir análise completa de um ativo")
        pick = st.selectbox("Ativo", [a.replace("🌟 ", "") for a in result_df["Ativo"].tolist()], key="scanner_pick_select")
        if st.button("Ver gráfico e as 6 leituras completas"):
            st.session_state.jump_to_symbol = pick
            st.rerun()
    else:
        st.info("Clique em **Rodar scanner** na barra lateral para analisar todos os ativos da watchlist.")

elif mode == "Verificação retroativa":
    symbol = st.session_state.symbol_select
    render_retro_check(symbol, style, modality, source, count)

else:  # Histórico de Sinais
    render_signal_history()
