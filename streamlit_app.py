"""
streamlit_app.py

Interface WEB para o motor de análise em `daytrade_smc.py`. Não altera
nada do motor — só importa as funções e desenha por cima.

Dois modos (barra lateral):
    - Análise individual: gráfico de candles com EMAs/VWAP/swings/BOS-CHoCH/
      zonas de FVG, mais os painéis das 5 leituras. Pode auto-atualizar.
    - Scanner: roda a análise em TODOS os ativos da watchlist de uma vez e
      mostra um ranking por score de confluência (o "Top N" do requisito
      original), com atalho pra abrir qualquer um na análise individual.

Rodar localmente (se algum dia tiver Python disponível):
    streamlit run streamlit_app.py

Rodar pela internet sem instalar nada: ver README.md.
"""

from __future__ import annotations

import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from daytrade_smc import (
    DAYTRADE_CONFIRMATION_TIMEFRAMES,
    DAYTRADE_CONTEXT_TIMEFRAMES,
    DEFAULT_SYMBOLS,
    Direction,
    MODALITIES,
    Signal,
    SWING_CONFIRMATION_TIMEFRAMES,
    SWING_CONTEXT_TIMEFRAMES,
    analyze_symbol_mtf,
    check_signal_as_of,
    load_symbols,
    quality,
    save_symbols,
    yahoo_symbol,
)

STYLES = {
    "Day Trade": {
        "confirmation": DAYTRADE_CONFIRMATION_TIMEFRAMES,
        "context": DAYTRADE_CONTEXT_TIMEFRAMES,
        "count_label": "Candles fechados (M15 e H1)",
    },
    "Swing Trade": {
        "confirmation": SWING_CONFIRMATION_TIMEFRAMES,
        "context": SWING_CONTEXT_TIMEFRAMES,
        "count_label": "Candles fechados (Diário e Semanal)",
    },
}

st.set_page_config(page_title="Day Trade SMC", page_icon="📊", layout="wide")

DIRECTION_COLOR = {
    Direction.BUY: "#2ed3a3",
    Direction.SELL: "#ff5470",
    Direction.NEUTRAL: "#8291a1",
}


# ========================================================================
# Dados / cache / análise
# ========================================================================
@st.cache_data(ttl=60, show_spinner=False)
def cached_mtf(symbol: str, count: int, confirmation: tuple[str, str], context: tuple[str, ...], modality: str):
    """Cacheia o pacote de timeframes por 60s — evita rebuscar no Yahoo a cada rerun do Streamlit."""
    counts = {tf: count for tf in (*confirmation, *context)}
    return analyze_symbol_mtf(symbol, confirmation=confirmation, context=context, counts=counts, modality=modality)


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
        paper_bgcolor="#0a0e13", plot_bgcolor="#0a0e13",
        height=560, margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0),
        font=dict(family="IBM Plex Mono, monospace", size=11, color="#8291a1"),
    )
    return fig


# ========================================================================
# Painéis
# ========================================================================
def render_signal_panel(signal: Signal, symbol: str, risk_budget: float | None) -> None:
    color = DIRECTION_COLOR[signal.direction]

    c1, c2, c3 = st.columns([2, 1, 1])
    c1.markdown(f"### {signal.setup}")
    c2.metric("Direção", signal.direction.value)
    c3.metric("Score", f"{signal.score:.1f}/100", quality(signal.score))

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
                qty = int(risk_budget // risk_per_share)
                st.caption(f"Com risco de R$ {risk_budget:.2f}: **{qty} ações** · "
                          f"risco real R$ {qty*risk_per_share:.2f} · total R$ {qty*risk.entry:.2f}")

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
    "M15": "15 minutos",
    "H1": "60 minutos",
    "H4": "240 minutos",
    "D1": "Diário",
    "W1": "Semanal",
}


def render_confirmation_badge(mtf, confirmation: tuple[str, str]) -> None:
    tf_a, tf_b = confirmation
    result_a = mtf.results[tf_a]
    result_b = mtf.results[tf_b]

    if result_a.error or result_b.error:
        st.warning(
            f"⚠️ Não foi possível confirmar — falha ao buscar {tf_a} e/ou {tf_b}. "
            f"{result_a.error or ''} {result_b.error or ''}".strip()
        )
        return

    dir_a = next(s.direction for s in result_a.signals if s.name == mtf.modality)
    dir_b = next(s.direction for s in result_b.signals if s.name == mtf.modality)

    if mtf.confirmed:
        color = DIRECTION_COLOR[mtf.confirmed_direction]
        st.markdown(
            f'<div style="border:1px solid {color}; border-radius:8px; padding:12px 16px; '
            f'background:{color}18; margin-bottom:14px;">'
            f'✅ <b style="color:{color}">CONFIRMADO: {mtf.confirmed_direction.value}</b> — '
            f"{tf_a} e {tf_b} concordam na mesma direção, segundo a leitura <b>{mtf.modality}</b>."
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div style="border:1px solid #8291a1; border-radius:8px; padding:12px 16px; '
            f'background:#8291a118; margin-bottom:14px;">'
            f"❌ <b>NÃO CONFIRMADO</b> (leitura: <b>{mtf.modality}</b>) — {tf_a} diz <b>{dir_a.value}</b>, "
            f"{tf_b} diz <b>{dir_b.value}</b>. Só é recomendação operável quando os dois concordam."
            f"</div>",
            unsafe_allow_html=True,
        )


OUTCOME_LABELS = {
    "ALVO_1": ("✅ Bateu o Alvo 1", "#2ed3a3"),
    "ALVO_2": ("✅ Bateu o Alvo 2", "#2ed3a3"),
    "STOP": ("❌ Bateu o Stop", "#ff5470"),
    "EM_ABERTO": ("⏳ Ainda em aberto", "#f0b429"),
    "SEM_SINAL": ("— Sem sinal operável nesta data", "#8291a1"),
    "SEM_DADO_FUTURO": ("⏳ Sem candles seguintes disponíveis ainda", "#8291a1"),
}


def render_retro_check(symbol: str, style: str, modality: str, count: int) -> None:
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
            check = check_signal_as_of(symbol, check_tf, as_of_ts, count=count, modality=modality)
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


def render_individual_analysis(symbol: str, style: str, modality: str, count: int, risk_budget: float | None) -> None:
    confirmation = STYLES[style]["confirmation"]
    context_tfs = STYLES[style]["context"]
    all_tfs = list(confirmation) + [tf for tf in context_tfs if tf not in confirmation]

    with st.spinner(f"Buscando {', '.join(TIMEFRAME_LABELS[tf] for tf in all_tfs)} de {symbol}..."):
        mtf = cached_mtf(symbol, count, confirmation, context_tfs, modality)

    render_confirmation_badge(mtf, confirmation)

    tf_tabs = st.tabs([TIMEFRAME_LABELS[tf] + (" (contexto)" if tf not in confirmation else "") for tf in all_tfs])
    for tab, tf in zip(tf_tabs, all_tfs):
        with tab:
            result = mtf.results[tf]
            if result.error:
                st.error(f"Não foi possível analisar {symbol} em {tf}: {result.error}")
                continue
            render_timeframe_panel(symbol, tf, result.context, result.signals, risk_budget)


def render_timeframe_panel(symbol: str, timeframe: str, context, signals, risk_budget: float | None) -> None:
    by_name = {s.name: s for s in signals}
    last_open = context.df.index[-1].tz_convert("America/Sao_Paulo")
    st.caption(f"{symbol} ({yahoo_symbol(symbol)}) · {timeframe} · último candle: {last_open} · "
              f"ATR {context.atr:.2f} ({context.atr_pct:.2f}%) · RVOL {context.rvol:.2f}x · "
              f"Volatilidade {context.volatility} · atualizado às "
              f"{pd.Timestamp.now(tz='America/Sao_Paulo').strftime('%H:%M:%S')}")

    chart_choice = st.selectbox(
        "Ver entrada/stop/alvo de qual leitura no gráfico:",
        [s.name for s in signals], index=0, key=f"chart_choice_{timeframe}",
    )
    st.plotly_chart(build_chart(context, by_name[chart_choice], symbol), use_container_width=True, key=f"chart_{timeframe}_{chart_choice}")

    tabs = st.tabs([s.name for s in signals])
    for tab, s in zip(tabs, signals):
        with tab:
            render_signal_panel(s, symbol, risk_budget)

    st.markdown("### Resumo — as 5 leituras lado a lado")
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
def _auto_refresh_30(symbol, style, modality, count, risk_budget):
    render_individual_analysis(symbol, style, modality, count, risk_budget)


@st.fragment(run_every=60)
def _auto_refresh_60(symbol, style, modality, count, risk_budget):
    render_individual_analysis(symbol, style, modality, count, risk_budget)


@st.fragment(run_every=120)
def _auto_refresh_120(symbol, style, modality, count, risk_budget):
    render_individual_analysis(symbol, style, modality, count, risk_budget)


@st.fragment(run_every=300)
def _auto_refresh_300(symbol, style, modality, count, risk_budget):
    render_individual_analysis(symbol, style, modality, count, risk_budget)


_AUTO_REFRESH_FRAGMENTS = {
    30: _auto_refresh_30,
    60: _auto_refresh_60,
    120: _auto_refresh_120,
    300: _auto_refresh_300,
}


def run_scanner(symbols: list[str], style: str, modality: str, count: int, risk_budget: float | None) -> pd.DataFrame:
    rows = []
    progress = st.progress(0.0, text="Iniciando scanner...")
    confirmation = STYLES[style]["confirmation"]
    context_tfs = STYLES[style]["context"]
    tf_a, tf_b = confirmation
    col_a, col_b = f"Score {tf_a}", f"Score {tf_b}"

    for i, symbol in enumerate(symbols):
        progress.progress((i + 1) / len(symbols), text=f"Analisando {symbol} ({i+1}/{len(symbols)})...")
        mtf = cached_mtf(symbol, count, confirmation, context_tfs, modality)
        result_a = mtf.results[tf_a]
        result_b = mtf.results[tf_b]

        if result_a.error or result_b.error:
            err = (result_a.error or result_b.error or "")[:60]
            rows.append({"Ativo": symbol, "Confirmado": "ERRO", "Direção": "ERRO", col_a: None,
                        col_b: None, "Setup": err, "Entrada": None, "Stop": None, "Alvo 1": None,
                        "Quantidade": None, "Total (R$)": None})
            time.sleep(0.3)
            continue

        conf_a = next(s for s in result_a.signals if s.name == modality)
        conf_b = next(s for s in result_b.signals if s.name == modality)

        direction_label = mtf.confirmed_direction.value if mtf.confirmed else "NEUTRO"
        risk = conf_a.risk if mtf.confirmed else None

        qty = None
        total = None
        if mtf.confirmed and risk_budget and risk.entry is not None and risk.stop is not None:
            risk_per_share = abs(risk.entry - risk.stop)
            if risk_per_share > 0:
                qty = int(risk_budget // risk_per_share)
                total = round(qty * risk.entry, 2) if qty > 0 else 0.0

        rows.append({
            "Ativo": symbol,
            "Confirmado": "✅" if mtf.confirmed else "❌",
            "Direção": direction_label,
            col_a: round(conf_a.score, 1),
            col_b: round(conf_b.score, 1),
            "Setup": conf_a.setup if mtf.confirmed else f"{tf_a}={conf_a.direction.value} / {tf_b}={conf_b.direction.value}",
            "Entrada": round(risk.entry, 2) if risk and risk.entry else None,
            "Stop": round(risk.stop, 2) if risk and risk.stop else None,
            "Alvo 1": round(risk.target_1, 2) if risk and risk.target_1 else None,
            "Quantidade": qty,
            "Total (R$)": total,
        })
        time.sleep(0.3)  # folga entre chamadas — reduz risco de rate limit do Yahoo (2 timeframes por ativo agora)

    progress.empty()
    result = pd.DataFrame(rows)
    if col_a in result.columns:
        result = result.sort_values(["Confirmado", col_a], ascending=[True, False], na_position="last")
    return result.reset_index(drop=True)


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
    st.markdown("## 📊 Day Trade SMC")
    st.caption("SMC · Price Action · Médias Móveis · VWAP")

    mode = st.radio("Modo", ["Análise individual", "Scanner (todos os ativos)", "Verificação retroativa"], key="mode_select")

    st.markdown("### Estilo de operação")
    style = st.radio(
        "Estilo", list(STYLES.keys()), key="style_select", horizontal=True,
        help="Day Trade confirma em M15+H1 (posições no mesmo dia). "
             "Swing Trade confirma em Diário+Semanal (posições de dias a semanas), com H4 como contexto de timing de entrada.",
    )
    conf_a, conf_b = STYLES[style]["confirmation"]

    st.markdown("### Modalidade")
    modality = st.selectbox(
        "Qual leitura usar como base da recomendação", MODALITIES, key="modality_select",
        help="Confluência combina as 4 categorias. As outras (SMC, Price Action, Médias Móveis, "
             "VWAP) usam só a leitura isolada daquela categoria, com stop/alvo calculados só a "
             "partir dela — a mesma lógica das abas na Análise Individual, só que agora também "
             "decide a confirmação multi-timeframe e o Scanner.",
    )

    st.markdown("### Ativos monitorados")
    new_symbol = st.text_input("Adicionar ativo (ex: VALE3)", key="new_symbol_input")
    if st.button("Adicionar", use_container_width=True) and new_symbol.strip():
        value = new_symbol.strip().upper().replace(" ", "")
        if value not in st.session_state.watchlist:
            st.session_state.watchlist.append(value)
            _persist_watchlist()
        st.rerun()

    if mode in ("Análise individual", "Verificação retroativa"):
        st.selectbox("Ativo para análise", st.session_state.watchlist, key="symbol_select")

    remove_symbol = st.selectbox("Remover ativo", ["—"] + st.session_state.watchlist, key="remove_symbol_select")
    if st.button("Remover", use_container_width=True) and remove_symbol != "—":
        st.session_state.watchlist = [s for s in st.session_state.watchlist if s != remove_symbol]
        _persist_watchlist()
        st.rerun()

    if st.button("Restaurar lista padrão", use_container_width=True):
        st.session_state.watchlist = DEFAULT_SYMBOLS.copy()
        _persist_watchlist()
        st.rerun()

    st.markdown("### Parâmetros")
    st.caption(f"A recomendação exige **{TIMEFRAME_LABELS[conf_a]}** e **{TIMEFRAME_LABELS[conf_b]}** concordando "
              f"(ver \"Filtro multi-timeframe\" no rodapé). "
              f"{', '.join(TIMEFRAME_LABELS[tf] for tf in STYLES[style]['context'])} aparece como contexto adicional.")
    count = st.slider(STYLES[style]["count_label"], min_value=50, max_value=400, value=250, step=10)
    risk_budget = st.number_input("Risco máximo (R$) — opcional", min_value=0.0, value=0.0, step=50.0)
    risk_budget = risk_budget if risk_budget > 0 else None

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
st.warning(
    "⚠️ **Dados do Yahoo Finance com atraso de ~15-20 minutos.** Use esta ferramenta para "
    "**viés e estrutura** (tendência, níveis, força relativa entre ativos) — **nunca para o "
    "preço/timing exato de execução.** Antes de entrar numa operação, confirme o preço real "
    "no ProfitChart ou na tela da sua corretora.",
    icon="⏱️",
)

if mode == "Análise individual":
    symbol = st.session_state.symbol_select

    if auto_refresh:
        st.caption(f"🔄 Atualizando automaticamente a cada {refresh_interval}s")
        _AUTO_REFRESH_FRAGMENTS[refresh_interval](symbol, style, modality, count, risk_budget)
    else:
        render_individual_analysis(symbol, style, modality, count, risk_budget)

elif mode == "Scanner (todos os ativos)":
    st.caption(f"{len(st.session_state.watchlist)} ativo(s) na watchlist · {style} · leitura: {modality} · "
              f"{count} candles · recomendação exige {conf_a}+{conf_b} concordando")

    if run_scanner_clicked:
        st.session_state.scanner_result = run_scanner(st.session_state.watchlist, style, modality, count, risk_budget)
        st.session_state.scanner_risk_budget = risk_budget

    if "scanner_result" in st.session_state:
        result_df = st.session_state.scanner_result

        if not st.session_state.get("scanner_risk_budget"):
            st.info("Defina o **Risco máximo (R$)** na barra lateral e rode o scanner de novo pra ver a "
                    "quantidade sugerida de ações em cada ativo.")

        def _color_direction(val):
            if val == "COMPRA":
                return "color: #2ed3a3; font-weight: 600"
            if val == "VENDA":
                return "color: #ff5470; font-weight: 600"
            return "color: #8291a1"

        st.dataframe(
            result_df.style.map(_color_direction, subset=["Direção"]),
            hide_index=True, use_container_width=True, height=min(450, 45 + 35 * len(result_df)),
        )

        st.markdown("#### Abrir análise completa de um ativo")
        pick = st.selectbox("Ativo", result_df["Ativo"].tolist(), key="scanner_pick_select")
        if st.button("Ver gráfico e as 5 leituras completas"):
            st.session_state.jump_to_symbol = pick
            st.rerun()
    else:
        st.info("Clique em **Rodar scanner** na barra lateral para analisar todos os ativos da watchlist.")

else:  # Verificação retroativa
    symbol = st.session_state.symbol_select
    render_retro_check(symbol, style, modality, count)
