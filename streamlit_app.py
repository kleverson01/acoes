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

import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import daytrade_smc
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
    clear_signal_log,
    delete_signal_log_entry,
    fetch_snapshot_timestamp,
    load_signal_log,
    load_symbols,
    log_signal,
    overall_agreement,
    overall_direction,
    overall_score,
    quality,
    refresh_signal_log,
    request_mt5_update,
    save_symbols,
    yahoo_symbol,
)

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
def _cached_mtf_yahoo(symbol: str, count: int, confirmation: tuple[str, str], context: tuple[str, ...], modality: str, min_stop_atr_mult: float, rsi_os: float, rsi_ob: float):
    daytrade_smc.MIN_STOP_ATR_MULT = min_stop_atr_mult
    daytrade_smc.RSI_OVERSOLD = rsi_os
    daytrade_smc.RSI_OVERBOUGHT = rsi_ob
    counts = {tf: count for tf in (*confirmation, *context)}
    return analyze_symbol_mtf(symbol, confirmation=confirmation, context=context, counts=counts, modality=modality, source="Yahoo Finance")


@st.cache_data(ttl=3, show_spinner=False)
def _cached_mtf_mt5(symbol: str, count: int, confirmation: tuple[str, str], context: tuple[str, ...], modality: str, min_stop_atr_mult: float, rsi_os: float, rsi_ob: float):
    daytrade_smc.MIN_STOP_ATR_MULT = min_stop_atr_mult
    daytrade_smc.RSI_OVERSOLD = rsi_os
    daytrade_smc.RSI_OVERBOUGHT = rsi_ob
    counts = {tf: count for tf in (*confirmation, *context)}
    return analyze_symbol_mtf(symbol, confirmation=confirmation, context=context, counts=counts, modality=modality, source="MetaTrader 5")


@st.cache_data(ttl=10, show_spinner=False)
def _cached_mtf_github(symbol: str, count: int, confirmation: tuple[str, str], context: tuple[str, ...], modality: str, min_stop_atr_mult: float, rsi_os: float, rsi_ob: float):
    daytrade_smc.MIN_STOP_ATR_MULT = min_stop_atr_mult
    daytrade_smc.RSI_OVERSOLD = rsi_os
    daytrade_smc.RSI_OVERBOUGHT = rsi_ob
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
            # Confirmado (M15+H1 concordam), mas score abaixo do piso de
            # qualidade escolhido na barra lateral — mostra pra estudo,
            # mas NÃO registra como recomendação no histórico, pra não
            # misturar sinais fracos com sinais fortes nas estatísticas.
            st.markdown(
                f'<div style="border:1px solid #8291a1; border-radius:8px; padding:12px 16px; '
                f'background:#8291a118; margin-bottom:14px;">'
                f'⚠️ <b>CONFIRMADO, mas score baixo</b> ({score_for_badge:.1f}/100, abaixo do mínimo de '
                f'{min_score_to_log:.0f} definido na barra lateral) — direção <b style="color:{color}">'
                f'{mtf.confirmed_direction.value}</b> segundo <b>{mtf.modality}</b>.{agreement_note} '
                f"Não foi registrado no histórico de sinais."
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div style="border:1px solid {color}; border-radius:8px; padding:12px 16px; '
                f'background:{color}18; margin-bottom:14px;">'
                f'{star}✅ <b style="color:{color}">CONFIRMADO: {mtf.confirmed_direction.value}</b> — '
                f"{tf_a} e {tf_b} concordam na mesma direção, segundo a leitura <b>{mtf.modality}</b>."
                f"{agreement_note} · registrado automaticamente no histórico de sinais."
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
    "ABERTO": ("⏳ Em aberto", "#f0b429"),
    "SEM_SINAL": ("— Sem sinal operável nesta data", "#8291a1"),
    "SEM_DADO_FUTURO": ("⏳ Sem candles seguintes disponíveis ainda", "#8291a1"),
}


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


def render_rsi_multi_tf(mtf) -> None:
    """Consolida os extremos de IFR de todos os timeframes analisados."""
    resumo = daytrade_smc.rsi_extremes_across_timeframes(mtf)
    por_tf = resumo["por_tf"]
    if not por_tf:
        return

    ob, os_ = daytrade_smc.RSI_OVERBOUGHT, daytrade_smc.RSI_OVERSOLD
    alinhamento, direcao = resumo["alinhamento"], resumo["direcao"]

    partes = []
    for tf, (valor, extremo) in por_tf.items():
        rotulo = TIMEFRAME_LABELS.get(tf, tf)
        if extremo == Direction.BUY.value:
            partes.append(f'<b style="color:#2ed3a3">{rotulo}: {valor:.0f} ↓</b>')
        elif extremo == Direction.SELL.value:
            partes.append(f'<b style="color:#ff5470">{rotulo}: {valor:.0f} ↑</b>')
        else:
            partes.append(f'<span style="color:#8291a1">{rotulo}: {valor:.0f}</span>')

    if alinhamento >= 2:
        cor = "#2ed3a3" if direcao == Direction.BUY.value else "#ff5470"
        titulo = (f'🎯 <b style="color:{cor}">EXAUSTÃO EM {alinhamento} TIMEFRAMES — {direcao}</b>')
    elif alinhamento == 1:
        cor = "#f0b429"
        titulo = f'<b style="color:{cor}">Exaustão em 1 timeframe — {direcao}</b>'
    else:
        cor = "#8291a1"
        titulo = '<span style="color:#8291a1">Nenhum timeframe em exaustão</span>'

    st.markdown(
        f'<div style="border:1px solid {cor}; border-radius:8px; padding:10px 14px; '
        f'background:{cor}18; margin:6px 0 14px 0;">'
        f'{titulo} <span style="color:#8291a1">· limiares {os_:.0f}/{ob:.0f}</span><br>'
        f'<span style="font-size:0.92em">IFR(14) — {" · ".join(partes)}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_rsi_badge(context) -> None:
    """Faixa visual do IFR do timeframe atual, com o Diário ao lado quando disponível."""
    rsi = context.rsi
    ob, os_ = daytrade_smc.RSI_OVERBOUGHT, daytrade_smc.RSI_OVERSOLD
    near_os = os_ + (50 - os_) * 0.35
    near_ob = ob - (ob - 50) * 0.35

    if rsi <= os_:
        zona, cor = f"SOBREVENDA EXTREMA (≤{os_:.0f})", "#2ed3a3"
    elif rsi >= ob:
        zona, cor = f"SOBRECOMPRA EXTREMA (≥{ob:.0f})", "#ff5470"
    elif rsi <= near_os:
        zona, cor = "Aproximando da sobrevenda", "#f0b429"
    elif rsi >= near_ob:
        zona, cor = "Aproximando da sobrecompra", "#f0b429"
    else:
        zona, cor = "Fora dos extremos", "#8291a1"

    diario = ""
    if context.higher_rsi is not None:
        d = context.higher_rsi
        d_zona = "extremo ↓" if d <= os_ else "extremo ↑" if d >= ob else "neutro"
        diario = f" · <b>Diário:</b> {d:.1f} ({d_zona})"

    st.markdown(
        f'<div style="border:1px solid {cor}; border-radius:8px; padding:10px 14px; '
        f'background:{cor}18; margin:6px 0 14px 0;">'
        f'<b>IFR (14):</b> <b style="color:{cor}">{rsi:.1f} — {zona}</b>{diario}'
        f'<div style="background:#8291a133; height:8px; border-radius:4px; margin-top:8px; position:relative;">'
        f'<div style="position:absolute; left:{os_:.0f}%; top:0; bottom:0; width:1px; background:#8291a1;"></div>'
        f'<div style="position:absolute; left:{ob:.0f}%; top:0; bottom:0; width:1px; background:#8291a1;"></div>'
        f'<div style="position:absolute; left:calc({min(max(rsi,0),100):.0f}% - 4px); top:-2px; '
        f'width:8px; height:12px; border-radius:2px; background:{cor};"></div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def render_timeframe_panel(symbol: str, timeframe: str, context, signals, risk_budget: float | None) -> None:
    by_name = {s.name: s for s in signals}
    last_open = context.df.index[-1].tz_convert("America/Sao_Paulo")
    st.caption(f"{symbol} ({yahoo_symbol(symbol)}) · {timeframe} · último candle: {last_open} · "
              f"ATR {context.atr:.2f} ({context.atr_pct:.2f}%) · RVOL {context.rvol:.2f}x · "
              f"Volatilidade {context.volatility} · atualizado às "
              f"{pd.Timestamp.now(tz='America/Sao_Paulo').strftime('%H:%M:%S')}")

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
            rows.append({"Ativo": symbol, "Alerta": "", "Confirmado": "ERRO", "Destaque": "", "Direção": "ERRO", col_a: None,
                        col_b: None, "Score Geral": None, f"IFR {tf_a}": None, "IFR Diário": None, "Zona IFR": "", "Exaustão IFR": "",
                        "Setup": err, "Entrada": None, "Stop": None,
                        "Alvo 1": None, "Quantidade": None, "Total (R$)": None})
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

        qty = None
        total = None
        if mtf.confirmed and risk_budget and risk and risk.entry is not None and risk.stop is not None:
            risk_per_share = abs(risk.entry - risk.stop)
            if risk_per_share > 0:
                qty = int(risk_budget // risk_per_share)
                total = round(qty * risk.entry, 2) if qty > 0 else 0.0

        score_geral = round((score_a + score_b) / 2, 1)
        destaque = "🌟 Excepcional" if (mtf.confirmed and quality(score_geral) == "OPORTUNIDADE EXCEPCIONAL") else ""
        alerta = f"⚠️ Abaixo do score mínimo ({min_score_to_log:.0f})" if score_geral < min_score_to_log else ""

        rsi_tf = round(result_a.context.rsi, 1) if result_a.context else None
        d1_result = mtf.results.get("D1")
        rsi_d1 = round(d1_result.context.rsi, 1) if (d1_result and d1_result.context) else None
        if rsi_tf is None:
            rsi_zona = ""
        elif rsi_tf <= rsi_os:
            rsi_zona = "🟢 Sobrevenda extrema"
        elif rsi_tf >= rsi_ob:
            rsi_zona = "🔴 Sobrecompra extrema"
        else:
            rsi_zona = ""

        # Quantos timeframes estão em exaustão simultânea na mesma
        # direção — é o filtro mais seletivo que o IFR oferece aqui.
        resumo_rsi = daytrade_smc.rsi_extremes_across_timeframes(mtf)
        n_extremos = resumo_rsi["alinhamento"]
        if n_extremos >= 2:
            seta = "🟢↓" if resumo_rsi["direcao"] == Direction.BUY.value else "🔴↑"
            exaustao = f"🎯 {n_extremos} TFs {seta}"
        elif n_extremos == 1:
            seta = "↓" if resumo_rsi["direcao"] == Direction.BUY.value else "↑"
            exaustao = f"1 TF {seta}"
        else:
            exaustao = ""

        rows.append({
            "Ativo": symbol,
            "Alerta": alerta,
            "Confirmado": "✅" if mtf.confirmed else "❌",
            "Destaque": destaque,
            "Direção": direction_label,
            col_a: score_a,
            col_b: score_b,
            "Score Geral": score_geral,
            f"IFR {tf_a}": rsi_tf,
            "IFR Diário": rsi_d1,
            "Zona IFR": rsi_zona,
            "Exaustão IFR": exaustao,
            "Setup": setup_text,
            "Entrada": round(risk.entry, 2) if risk and risk.entry else None,
            "Stop": round(risk.stop, 2) if risk and risk.stop else None,
            "Alvo 1": round(risk.target_1, 2) if risk and risk.target_1 else None,
            "Quantidade": qty,
            "Total (R$)": total,
        })
        if source != "MetaTrader 5":
            time.sleep(0.3)  # folga entre chamadas — reduz risco de rate limit do Yahoo (MT5 é chamada local, sem esse limite)

    progress.empty()
    result = pd.DataFrame(rows)
    if "Score Geral" in result.columns:
        # As recomendações são ordenadas pelo Score Geral (média das leituras em ambos os
        # timeframes de confirmação) — confirmadas primeiro, da maior pontuação pra menor.
        result = result.sort_values(["Confirmado", "Score Geral"], ascending=[True, False], na_position="last")
        result = result.reset_index(drop=True)
        # Posição: 1 = melhor colocado, numeração crescente conforme desce no ranking
        result.insert(0, "Posição", range(1, len(result) + 1))
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
    st.markdown("## 📊 Day Trade SMC")
    st.caption("SMC · Price Action · Médias Móveis · VWAP · IFR")

    mode = st.radio(
        "Modo",
        ["Análise individual", "Scanner (todos os ativos)", "Verificação retroativa", "Histórico de Sinais"],
        key="mode_select",
    )

    st.markdown("### Fonte de dados")

    # Detecta uma vez por sessão se há um terminal MT5 acessível nesta
    # máquina. Rodando localmente com o MT5 aberto, o padrão passa a
    # ser MT5 (tempo real) em vez de Yahoo Finance (atrasado ~15-20min).
    if "mt5_available" not in st.session_state:
        st.session_state.mt5_available = daytrade_smc.mt5_is_available()

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

    st.markdown("### Estilo de operação")
    style = st.radio(
        "Estilo", list(STYLES.keys()), key="style_select", horizontal=True,
        help="Day Trade confirma em M15+H1 (posições no mesmo dia). "
             "Swing Trade confirma em Diário+Semanal (posições de dias a semanas), com H4 como contexto de timing de entrada.",
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

    st.markdown("### Filtros de qualidade")
    min_stop_atr_mult = st.slider(
        "Piso mínimo do stop (× ATR)", min_value=0.5, max_value=2.5, value=1.0, step=0.25,
        help="Distância mínima entre entrada e stop, em múltiplos do ATR do timeframe. Valor baixo "
             "(ex: 0.75) deixa o stop mais apertado — mais sinais, porém mais vulnerável a ser tocado "
             "só por ruído normal do candle seguinte. Valor mais alto (ex: 1.5) reduz esse \"stop por "
             "ruído\", ao custo de arriscar mais por operação.",
    )
    min_score_to_log = st.slider(
        "Score mínimo para registrar no histórico", min_value=0, max_value=100, value=55, step=5,
        help="Recomendações CONFIRMADAS (M15+H1 concordando) com score abaixo deste valor ainda "
             "aparecem na tela pra estudo, mas não são registradas no Histórico de Sinais — evita "
             "misturar sinais fracos com sinais fortes nas estatísticas de acerto.",
    )
    # Os limiares acompanham o estilo: Day Trade usa extremos verdadeiros
    # (10/90) porque em M5/M15/H1 o IFR alcança esses níveis com alguma
    # regularidade; Swing usa 20/80, já que no Diário/Semanal o 90/10 é
    # raríssimo e quase nunca dispararia. O `key` inclui o estilo pra que
    # o slider REINICIE nos novos padrões ao trocar de estilo, em vez de
    # manter o valor do estilo anterior.
    rsi_os_default, rsi_ob_default = daytrade_smc.STYLE_RSI_THRESHOLDS[style]
    rsi_ob, rsi_os = st.slider(
        "Limiares do IFR (sobrevenda / sobrecompra)", min_value=0, max_value=100,
        value=(int(rsi_os_default), int(rsi_ob_default)), step=5,
        key=f"rsi_thresholds_{style}",
        help=f"Padrão para {style}: {rsi_os_default:.0f}/{rsi_ob_default:.0f}. "
             "Day Trade usa 10/90 (exaustão verdadeira, aplicada em 5, 15 e 60 minutos); "
             "Swing usa 20/80, porque no Diário/Semanal o IFR raramente chega a 10/90 e "
             "80/20 já representa exaustão real naquele horizonte. Vale para todos os "
             "timeframes do estilo escolhido.",
    )
    daytrade_smc.MIN_STOP_ATR_MULT = min_stop_atr_mult
    daytrade_smc.RSI_OVERSOLD = float(rsi_ob)
    daytrade_smc.RSI_OVERBOUGHT = float(rsi_os)

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

        if not st.session_state.get("scanner_risk_budget"):
            st.info("Defina o **Risco máximo (R$)** na barra lateral e rode o scanner de novo pra ver a "
                    "quantidade sugerida de ações em cada ativo.")

        def _color_direction(val):
            if val == "COMPRA":
                return "color: #2ed3a3; font-weight: 600"
            if val == "VENDA":
                return "color: #ff5470; font-weight: 600"
            return "color: #8291a1"

        def _color_alerta(val):
            return "color: #f0b429; font-weight: 600" if val else ""

        st.dataframe(
            result_df.style.map(_color_direction, subset=["Direção"]).map(_color_alerta, subset=["Alerta"]),
            hide_index=True, use_container_width=True, height=min(450, 45 + 35 * len(result_df)),
        )

        st.markdown("#### Abrir análise completa de um ativo")
        pick = st.selectbox("Ativo", result_df["Ativo"].tolist(), key="scanner_pick_select")
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
