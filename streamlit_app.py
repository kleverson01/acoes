"""
streamlit_app.py

Interface WEB para o motor de análise em `daytrade_smc.py`. Não altera
nada do motor — só importa as funções e desenha por cima.

Dois modos (barra lateral):
    - Análise individual: gráfico de candles com EMAs/VWAP/swings/BOS-CHoCH/
      zonas de FVG, mais os painéis das 6 leituras (incluindo IFR). Pode auto-atualizar.
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
import panorama
import panorama_ui
import ui_theme as ui
from daytrade_smc import (
    ALL_MODALITIES_OPTION,
    DATA_SOURCES,
    DAYTRADE_CONFIRMATION_TIMEFRAMES,
    DAYTRADE_CONTEXT_TIMEFRAMES,
    DEFAULT_SYMBOLS,
    Direction,
    LEGACY_SYMBOLS,
    TRADING_WINDOWS_LABEL,
    MODALITY_CHOICES,
    Signal,
    SWING_CONFIRMATION_TIMEFRAMES,
    SWING_CONTEXT_TIMEFRAMES,
    analyze_symbol_mtf,
    check_signal_as_of,
    compute_market_bias,
    fetch_snapshot_timestamp,
    load_symbols,
    overall_agreement,
    overall_direction,
    overall_score,
    quality,
    save_symbols,
    trading_window_status,
    trigger_github_update,
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
        "count_label": "Candles fechados (M15 e H1)",
    },
    "Swing Trade": {
        "confirmation": SWING_CONFIRMATION_TIMEFRAMES,
        "context": SWING_CONTEXT_TIMEFRAMES,
        "count_label": "Candles fechados (Diário e Semanal)",
    },
}

st.set_page_config(page_title="Day Trade SMC", page_icon="📊", layout="wide")
ui.inject()

DIRECTION_COLOR = {
    Direction.BUY: ui.BUY,
    Direction.SELL: ui.SELL,
    Direction.NEUTRAL: ui.MUTED,
}


# ========================================================================
# Dados / cache / análise
# ========================================================================
FILTER_KEYS = ("enforce_window", "window_ok", "enforce_bias", "bias_dir")


def _mtf(symbol, count, confirmation, context, modality, source, filters):
    counts = {tf: count for tf in (*confirmation, *context)}
    return analyze_symbol_mtf(
        symbol, confirmation=confirmation, context=context, counts=counts,
        modality=modality, source=source,
        enforce_window=filters[0], window_ok=filters[1],
        enforce_bias=filters[2], bias_direction=filters[3],
        bias_label=filters[4],
    )


@st.cache_data(ttl=60, show_spinner=False)
def _cached_mtf_yahoo(symbol: str, count: int, confirmation: tuple[str, str], context: tuple[str, ...], modality: str, filters: tuple):
    return _mtf(symbol, count, confirmation, context, modality, "Yahoo Finance", filters)


@st.cache_data(ttl=3, show_spinner=False)
def _cached_mtf_mt5(symbol: str, count: int, confirmation: tuple[str, str], context: tuple[str, ...], modality: str, filters: tuple):
    return _mtf(symbol, count, confirmation, context, modality, "MetaTrader 5", filters)


@st.cache_data(ttl=10, show_spinner=False)
def _cached_mtf_github(symbol: str, count: int, confirmation: tuple[str, str], context: tuple[str, ...], modality: str, filters: tuple):
    return _mtf(symbol, count, confirmation, context, modality, "GitHub (MT5 de casa)", filters)


@st.cache_data(ttl=60, show_spinner=False)
def cached_market_bias(source: str, count: int = 200):
    """Viés do IBOV (ponto 2). Cacheado por 60s — é o mesmo pra todos os ativos."""
    return compute_market_bias(source=source, count=count)


def current_filters() -> tuple:
    """Empacota os filtros ativos num tuple hashável (pro cache do Streamlit)."""
    return (
        st.session_state.get("filter_window", True),
        st.session_state.get("_window_ok", True),
        st.session_state.get("filter_bias", True),
        st.session_state.get("_bias_dir", "NEUTRO"),
        st.session_state.get("_bias_label", ""),
    )


def cached_mtf(symbol: str, count: int, confirmation: tuple[str, str], context: tuple[str, ...], modality: str, source: str, filters: tuple | None = None):
    """
    Cacheia o pacote de timeframes. Yahoo Finance usa 60s de cache (tem
    rate limit); MetaTrader 5 direto usa 3s; GitHub (MT5 de casa) usa
    10s (só muda quando você clica em "Atualizar via MT5", então não
    precisa ser tão curto). Três funções fixas em vez de decoradas
    dinamicamente, pelo mesmo motivo dos fragmentos de auto-refresh:
    evita o bug de identidade de widget no React já corrigido antes
    neste projeto.
    """
    filters = filters or current_filters()
    if source == "MetaTrader 5":
        return _cached_mtf_mt5(symbol, count, confirmation, context, modality, filters)
    if source == "GitHub (MT5 de casa)":
        return _cached_mtf_github(symbol, count, confirmation, context, modality, filters)
    return _cached_mtf_yahoo(symbol, count, confirmation, context, modality, filters)


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
            marker=dict(symbol=symb, size=11, color=color, line=dict(width=1, color=ui.INK)),
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
                          annotation_text=f"{label}: {price:.2f}", annotation_position="top left",
                          annotation=dict(font=dict(size=10, color=color)))

    fig.update_layout(
        height=560, margin=dict(l=10, r=56, t=34, b=10),
        xaxis_rangeslider_visible=False,
    )
    ui.style_figure(fig)
    # some com as lacunas de fim de semana e da madrugada — o gráfico fica contínuo
    breaks = [dict(bounds=["sat", "mon"])]
    if len(x) > 2 and (x[1:] - x[:-1]).median() < pd.Timedelta(hours=6):
        breaks.append(dict(bounds=[18.5, 9.9], pattern="hour"))  # madrugada (horário de Brasília)
    fig.update_xaxes(rangebreaks=breaks)
    return fig


# ========================================================================
# Painéis
# ========================================================================
def render_signal_panel(signal: Signal, symbol: str, risk_budget: float | None) -> None:
    color = DIRECTION_COLOR[signal.direction]
    q = quality(signal.score)

    risk = signal.risk
    operavel = signal.direction != Direction.NEUTRAL and risk.entry is not None
    exceptional = q == "OPORTUNIDADE EXCEPCIONAL" and signal.direction != Direction.NEUTRAL
    if operavel:
        action = "Comprar" if signal.direction == Direction.BUY else "Vender"
        line = (f"{action} <b>{ui.esc(symbol)}</b> perto de <b>R$ {risk.entry:.2f}</b>, stop em "
                f"<b>R$ {risk.stop:.2f}</b>, alvo em <b>R$ {risk.target_1:.2f}</b> (R/R 1:{risk.rr:.2f})")
    else:
        line = "Sem sinal operável nesta leitura. Entrada, stop e alvos ficam bloqueados."
    ui.ticket(signal.direction.value, signal.setup, line, signal.score, q, exceptional)

    if operavel:
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


SCORE_COL = st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.1f")


def _score_cols(df: pd.DataFrame) -> dict:
    """Colunas de score viram barras de 0 a 100 — leitura imediata do ranking."""
    return {c: st.column_config.ProgressColumn(c, min_value=0, max_value=100, format="%.1f")
            for c in df.columns if str(c).startswith("Score")}


def _podium_rows(df: pd.DataFrame, score_col: str, meta_cols: tuple[str, ...]) -> list[dict]:
    rows = []
    for _, r in df.head(3).iterrows():
        if r.get("Direção") not in ("COMPRA", "VENDA") or pd.isna(r.get(score_col)):
            continue
        rows.append({
            "ativo": r["Ativo"], "direcao": r["Direção"], "score": float(r[score_col]),
            "meta": " · ".join(str(r[c]) for c in meta_cols if c in r and str(r[c]) not in ("", "nan", "None")),
            "entrada": r.get("Entrada"), "stop": r.get("Stop"), "alvo": r.get("Alvo 1"),
        })
    return rows


TIMEFRAME_LABELS = {
    "M2": "2 minutos",
    "M5": "5 minutos",
    "M15": "15 minutos",
    "H1": "60 minutos",
    "H4": "240 minutos",
    "D1": "Diário",
    "W1": "Semanal",
}


def render_filter_badges(mtf) -> None:
    """Mostra o estado dos filtros de janela de operação e viés do IBOV."""
    col1, col2 = st.columns(2)

    with col1:
        if not st.session_state.get("filter_window", True):
            ui.banner("⏰ Filtro de janela desligado", ui.esc(TRADING_WINDOWS_LABEL), ui.MUTED)
        elif mtf.window_ok:
            ui.banner(f"⏰ {ui.esc(mtf.window_note)}", "Sinais liberados.", ui.BUY)
        else:
            ui.banner(f"⏰ {ui.esc(mtf.window_note)}", "Sinais bloqueados.", ui.SELL)

    with col2:
        label = ui.esc(mtf.bias_label or "IBOV não medido")
        if not st.session_state.get("filter_bias", True):
            ui.banner("📉 Filtro de viés do IBOV desligado", "", ui.MUTED)
        elif mtf.bias_direction == Direction.BUY:
            ui.banner(f"📈 {label}", "Só compra liberada, vendas bloqueadas.", ui.BUY)
        elif mtf.bias_direction == Direction.SELL:
            ui.banner(f"📉 {label}", "Só venda liberada, compras bloqueadas.", ui.SELL)
        else:
            ui.banner(f"➖ {label}", "Sem bloqueio direcional.", ui.MUTED)

    if mtf.blocked_reasons:
        st.warning("Filtros aplicados: " + " · ".join(mtf.blocked_reasons))


def render_flow_panel(context) -> None:
    """Painel de fluxo do ativo (ponto 4)."""
    flow = context.flow
    st.markdown("### 💧 Fluxo do ativo")
    if not flow.has_volume:
        st.caption("Sem dado de volume nesta fonte — fluxo não avaliado.")
        return

    color = DIRECTION_COLOR[flow.bias]
    ui.banner(
        f"{ui.esc(flow.label)} · força {flow.strength:.0f}/100",
        "🚨 Volume anormal neste candle" if flow.spike else "", color,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("RVOL", f"{flow.rvol:.2f}x", help="Volume do candle ÷ média dos últimos 20")
    c2.metric("Vol. mesmo horário", f"{flow.intraday_ratio:.2f}x" if flow.intraday_ratio else "—",
              help="Volume atual vs. o MESMO horário nos dias anteriores")
    c3.metric("Delta da sessão", f"{flow.session_delta_pct:+.1f}%",
              help="Pressão compradora (+) ou vendedora (-) acumulada no dia")
    c4.metric("MFI (14)", f"{flow.mfi:.0f}", help="Money Flow Index — fluxo financeiro")

    for note in flow.notes:
        st.caption(f"• {note}".replace("$", "\\$"))  # "R$" não pode virar fórmula LaTeX


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
        else:
            score_for_badge = next(s.score for s in result_a.signals if s.name == mtf.modality)
        star = "🌟 " if quality(score_for_badge) == "OPORTUNIDADE EXCEPCIONAL" else ""
        ui.banner(
            f"{star}✅ Confirmado: {mtf.confirmed_direction.value}",
            f"{tf_a} e {tf_b} concordam na mesma direção, segundo a leitura <b>{mtf.modality}</b>.{agreement_note}",
            color,
        )
    else:
        ui.banner(
            f"Não confirmado · leitura {mtf.modality}",
            f"{tf_a} diz <b>{dir_a.value}</b>, {tf_b} diz <b>{dir_b.value}</b>. "
            "Só vira recomendação operável quando os dois concordam.",
            ui.MUTED,
        )


OUTCOME_LABELS = {
    "ALVO_1": ("✅ Bateu o Alvo 1", "#2ed3a3"),
    "ALVO_2": ("✅ Bateu o Alvo 2", "#2ed3a3"),
    "STOP": ("❌ Bateu o Stop", "#ff5470"),
    "EM_ABERTO": ("⏳ Ainda em aberto", "#f0b429"),
    "SEM_SINAL": ("— Sem sinal operável nesta data", "#8291a1"),
    "SEM_DADO_FUTURO": ("⏳ Sem candles seguintes disponíveis ainda", "#8291a1"),
}


@st.cache_data(ttl=600, show_spinner=False)
def _cached_ohlcv(symbol: str, timeframe: str, count: int, source: str) -> pd.DataFrame:
    return daytrade_smc.fetch_ohlcv(symbol, timeframe, count, source=source)


def retro_day(symbol: str, timeframe: str, day, modality: str, source: str, count: int,
              score_min: float, use_window: bool) -> dict:
    """
    Repassa o pregão escolhido candle a candle, sem espiar o futuro: em cada
    fechamento roda o motor só com o que existia até ali. O primeiro sinal
    operável (direção definida, entrada calculada, score ≥ corte e — se o
    filtro estiver ligado — dentro da janela de operação) é a entrada do dia
    naquele ativo, como o robô faria (uma posição por ativo). Depois confere,
    nos candles seguintes, se bateu alvo ou stop. O viés do IBOV não entra
    aqui porque exigiria o IBOV histórico de cada instante.
    """
    duration = daytrade_smc.TIMEFRAMES[timeframe]["duration"]
    hoje = pd.Timestamp.now(tz="America/Sao_Paulo").normalize()
    dias_uteis = max(1, len(pd.bdate_range(pd.Timestamp(day), hoje.tz_localize(None))))
    por_dia = {"M2": 240, "M5": 96, "M15": 32, "H1": 8, "H4": 2}.get(timeframe, 1)
    fetch_count = min(count + por_dia * (dias_uteis + 1), 3000)
    df = _cached_ohlcv(symbol, timeframe, fetch_count, source)

    local = df.index.tz_convert("America/Sao_Paulo")
    idx_dia = [i for i, t in enumerate(local) if t.date() == day]
    base = {"Ativo": symbol, "Sinais no dia": 0}
    if not idx_dia:
        return {**base, "Resultado": "SEM_DADO", "Detalhe": "Sem candles deste ativo na data."}

    sinais = 0
    primeiro = None
    for i in idx_dia:
        if i < 30:
            continue
        fechamento = local[i] + duration
        if use_window and not daytrade_smc.in_trading_window(fechamento):
            continue
        hist = df.iloc[max(0, i + 1 - count): i + 1]
        _, signals = daytrade_smc.analyze(hist)
        if modality == ALL_MODALITIES_OPTION:
            direction = overall_direction(signals)
            score = overall_score(signals)
            conf = next(s for s in signals if s.name == "Confluência")
            risk = conf.risk if conf.direction == direction else None
            setup = conf.setup
        else:
            chosen = next(s for s in signals if s.name == modality)
            direction, score, risk, setup = chosen.direction, chosen.score, chosen.risk, chosen.setup
        if direction == Direction.NEUTRAL or risk is None or risk.entry is None or score < score_min:
            continue
        sinais += 1
        if primeiro is None:
            primeiro = (i, fechamento, direction, score, risk, setup)

    if primeiro is None:
        return {**base, "Resultado": "SEM_SINAL", "Detalhe": f"Nenhum sinal com score ≥ {score_min:.0f} no dia."}

    i, fechamento, direction, score, risk, setup = primeiro
    outcome, detail, _ = daytrade_smc.evaluate_signal_outcome(risk, direction, df.iloc[i + 1:])
    return {**base, "Sinais no dia": sinais, "Hora": fechamento.strftime("%H:%M"), "Direção": direction.value,
            "Score": round(score, 1), "Setup": setup, "Entrada": round(risk.entry, 2), "Stop": round(risk.stop, 2),
            "Alvo 1": round(risk.target_1, 2) if risk.target_1 else None, "Resultado": outcome, "Detalhe": detail}


def render_retro_all(style: str, modality: str, source: str, count: int) -> None:
    st.caption(
        "Repassa o pregão escolhido em todas as ações da watchlist, candle a candle, sem espiar o futuro. "
        "Em cada ativo vale o primeiro sinal operável do dia, e depois confere se bateu alvo ou stop."
    )
    all_tfs = list(dict.fromkeys([*STYLES[style]["confirmation"], *STYLES[style]["context"]]))
    all_tfs = [tf for tf in all_tfs if tf not in ("D1", "W1")] or all_tfs
    c0, c1, c2, c3, c4 = st.columns([1.3, 1, 1, 0.8, 1])
    with c0:
        # A Retroativa tem leitura própria, com o padrão do robô (Confluência ≥ 80).
        # O score geral de "Todas as modalidades" é a MÉDIA das 6 leituras e quase
        # nunca passa de 70 (máximo de 72 em 4 pregões reais de novembro), por
        # isso não serve como corte de entrada.
        retro_mod = st.selectbox("Leitura", MODALITY_CHOICES, index=MODALITY_CHOICES.index("Confluência"),
                                 key="retro_mod",
                                 help="Padrão: Confluência, a mesma leitura que o robô usa no corte de 80. "
                                      "\"Todas as modalidades\" usa o score geral (média das 6 leituras), "
                                      "que quase nunca passa de 70.")
    with c1:
        check_tf = st.selectbox("Timeframe", all_tfs, format_func=lambda tf: TIMEFRAME_LABELS[tf], key="retro_tf")
    with c2:
        default_date = (pd.Timestamp.now(tz="America/Sao_Paulo") - pd.tseries.offsets.BDay(1)).date()
        day = st.date_input("Pregão", value=default_date, format="DD/MM/YYYY", key="retro_day")
    with c3:
        score_min = st.number_input("Score mínimo", min_value=0, max_value=100, value=80, step=5, key="retro_score",
                                    help="Padrão 80, o corte do robô. As leituras isoladas (SMC, Price Action, "
                                         "Médias, VWAP) vão no máximo a 79.")
    with c4:
        st.write("")
        run = st.button("⏪ Verificar o dia", type="primary", use_container_width=True)

    if run:
        rows = []
        symbols = st.session_state.watchlist
        use_window = bool(st.session_state.get("filter_window", True))
        prog = st.progress(0.0, text="Repassando o pregão...")
        for n, symbol in enumerate(symbols):
            prog.progress((n + 1) / len(symbols), text=f"Repassando {symbol} ({n + 1}/{len(symbols)})...")
            try:
                rows.append(retro_day(symbol, check_tf, day, retro_mod, source, count, float(score_min), use_window))
            except Exception as exc:
                rows.append({"Ativo": symbol, "Resultado": "ERRO", "Detalhe": str(exc)[:80]})
            if source != "MetaTrader 5":
                time.sleep(0.3)
        prog.empty()
        st.session_state.retro_result = (pd.DataFrame(rows), day, check_tf, score_min, retro_mod)

    if len(st.session_state.get("retro_result", ())) != 5:  # resultado salvo por uma versão anterior
        st.session_state.pop("retro_result", None)
    if "retro_result" not in st.session_state:
        st.info("Escolha o pregão e clique em **⏪ Verificar o dia**.")
        return

    df, r_day, r_tf, r_score, r_mod = st.session_state.retro_result
    labels = {k: v[0] for k, v in OUTCOME_LABELS.items()} | {"SEM_DADO": "— Sem candles na data", "ERRO": "⚠️ Erro"}
    com_sinal = df[df["Resultado"].isin(["ALVO_1", "ALVO_2", "STOP", "EM_ABERTO"])]
    ganhos = int(com_sinal["Resultado"].isin(["ALVO_1", "ALVO_2"]).sum())
    stops = int((com_sinal["Resultado"] == "STOP").sum())
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Ações verificadas", len(df))
    k2.metric("Com sinal", len(com_sinal))
    k3.metric("Bateram alvo", ganhos)
    k4.metric("Bateram stop", stops)
    k5.metric("Acerto", f"{ganhos / (ganhos + stops) * 100:.0f}%" if ganhos + stops else "—",
              help="Alvos ÷ (alvos + stops). Operações em aberto não entram na conta.")
    st.caption(f"Pregão {r_day.strftime('%d/%m/%Y')} · {TIMEFRAME_LABELS[r_tf]} · {r_mod} · score ≥ {r_score} · "
               f"filtro de janela {'ligado' if st.session_state.get('filter_window', True) else 'desligado'} · "
               "sem o filtro do IBOV (precisaria do índice de cada instante).")

    if com_sinal.empty:
        st.info("Nenhuma ação teve sinal operável neste pregão com esse corte.")
    else:
        view = com_sinal.sort_values("Score", ascending=False).copy()
        view["Resultado"] = view["Resultado"].map(labels)
        cols = [c for c in ("Ativo", "Hora", "Direção", "Score", "Resultado", "Setup", "Entrada", "Stop", "Alvo 1",
                            "Sinais no dia", "Detalhe") if c in view.columns]

        def _cor(val):
            if isinstance(val, str) and val.startswith("✅"):
                return f"color: {ui.BUY}; font-weight: 600"
            if isinstance(val, str) and val.startswith("❌"):
                return f"color: {ui.SELL}; font-weight: 600"
            if val == "COMPRA":
                return f"color: {ui.BUY}"
            if val == "VENDA":
                return f"color: {ui.SELL}"
            return ""

        st.dataframe(view[cols].style.map(_cor, subset=["Resultado", "Direção"]), hide_index=True,
                     use_container_width=True, height=min(600, 45 + 35 * len(view)),
                     column_config={"Score": SCORE_COL, **{c: st.column_config.NumberColumn(c, format="%.2f")
                                                           for c in ("Entrada", "Stop", "Alvo 1")}})

    sem = df[~df.index.isin(com_sinal.index)]
    if len(sem):
        with st.expander(f"{len(sem)} ações sem sinal ou sem dado nesta data"):
            st.dataframe(sem.assign(Resultado=sem["Resultado"].map(labels))[["Ativo", "Resultado", "Detalhe"]],
                         hide_index=True, use_container_width=True)


def render_mtf_analysis(symbol: str, confirmation: tuple[str, str], context_tfs: tuple[str, ...], modality: str, source: str, count: int, risk_budget: float | None) -> None:
    all_tfs = list(confirmation) + [tf for tf in context_tfs if tf not in confirmation]

    fonte_label = "MT5 (tempo real)" if source == "MetaTrader 5" else "Yahoo Finance (atraso ~15-20min)" if source == "Yahoo Finance" else "GitHub (MT5 de casa)"
    with st.spinner(f"Buscando {', '.join(TIMEFRAME_LABELS[tf] for tf in all_tfs)} de {symbol} via {fonte_label}..."):
        mtf = cached_mtf(symbol, count, confirmation, context_tfs, modality, source)

    render_filter_badges(mtf)
    render_confirmation_badge(mtf, confirmation)

    tf_tabs = st.tabs([TIMEFRAME_LABELS[tf] + (" (contexto)" if tf not in confirmation else "") for tf in all_tfs])
    for tab, tf in zip(tf_tabs, all_tfs):
        with tab:
            result = mtf.results[tf]
            if result.error:
                st.error(f"Não foi possível analisar {symbol} em {tf}: {result.error}")
                continue
            render_timeframe_panel(symbol, tf, result.context, result.signals, risk_budget)


def render_individual_analysis(symbol: str, style: str, modality: str, source: str, count: int, risk_budget: float | None) -> None:
    render_mtf_analysis(symbol, STYLES[style]["confirmation"], STYLES[style]["context"], modality, source, count, risk_budget)


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

    render_flow_panel(context)

    tabs = st.tabs([s.name for s in signals])
    for tab, s in zip(tabs, signals):
        with tab:
            render_signal_panel(s, symbol, risk_budget)

    st.markdown("### As 6 leituras lado a lado")
    st.dataframe(
        [{
            "Análise": s.name, "Direção": s.direction.value, "Score": round(s.score, 1),
            "Entrada": round(s.risk.entry, 2) if s.risk.entry else None,
            "Stop": round(s.risk.stop, 2) if s.risk.stop else None,
            "Alvo 1": round(s.risk.target_1, 2) if s.risk.target_1 else None,
        } for s in signals],
        hide_index=True, use_container_width=True,
        column_config={"Score": SCORE_COL},
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
def _auto_refresh_30(symbol, style, modality, source, count, risk_budget):
    render_individual_analysis(symbol, style, modality, source, count, risk_budget)


@st.fragment(run_every=60)
def _auto_refresh_60(symbol, style, modality, source, count, risk_budget):
    render_individual_analysis(symbol, style, modality, source, count, risk_budget)


@st.fragment(run_every=120)
def _auto_refresh_120(symbol, style, modality, source, count, risk_budget):
    render_individual_analysis(symbol, style, modality, source, count, risk_budget)


@st.fragment(run_every=300)
def _auto_refresh_300(symbol, style, modality, source, count, risk_budget):
    render_individual_analysis(symbol, style, modality, source, count, risk_budget)


_AUTO_REFRESH_FRAGMENTS = {
    30: _auto_refresh_30,
    60: _auto_refresh_60,
    120: _auto_refresh_120,
    300: _auto_refresh_300,
}


def run_scanner(symbols: list[str], style: str, modality: str, source: str, count: int, risk_budget: float | None) -> pd.DataFrame:
    rows = []
    filters = current_filters()
    progress = st.progress(0.0, text="Iniciando scanner...")
    confirmation = STYLES[style]["confirmation"]
    context_tfs = STYLES[style]["context"]
    tf_a, tf_b = confirmation
    col_a, col_b = f"Score {tf_a}", f"Score {tf_b}"

    for i, symbol in enumerate(symbols):
        progress.progress((i + 1) / len(symbols), text=f"Analisando {symbol} ({i+1}/{len(symbols)})...")
        mtf = cached_mtf(symbol, count, confirmation, context_tfs, modality, source, filters)
        result_a = mtf.results[tf_a]
        result_b = mtf.results[tf_b]

        if result_a.error or result_b.error:
            err = (result_a.error or result_b.error or "")[:60]
            rows.append({"Ativo": symbol, "Confirmado": "ERRO", "Destaque": "", "Direção": "ERRO", col_a: None,
                        col_b: None, "Score Geral": None, "Fluxo": "", "RVOL": None, "Setup": err,
                        "Entrada": None, "Stop": None, "Alvo 1": None, "Quantidade": None, "Total (R$)": None})
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
        else:
            conf_a = next(s for s in result_a.signals if s.name == modality)
            conf_b = next(s for s in result_b.signals if s.name == modality)
            score_a = round(conf_a.score, 1)
            score_b = round(conf_b.score, 1)
            setup_text = conf_a.setup if mtf.confirmed else f"{tf_a}={conf_a.direction.value} / {tf_b}={conf_b.direction.value}"
            risk = conf_a.risk if mtf.confirmed else None

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

        # Fluxo do ativo (ponto 4) — lido no timeframe de confirmação mais curto
        flow = result_a.context.flow
        if not flow.has_volume:
            flow_label = "—"
        else:
            icon = {"COMPRA": "🟢", "VENDA": "🔴", "NEUTRO": "⚪"}[flow.bias.value]
            flow_label = f"{icon} {flow.label.replace('FLUXO ', '')}"
            if flow.spike:
                flow_label = "🚨 " + flow_label
            if mtf.confirmed and flow.bias != Direction.NEUTRAL and flow.bias == mtf.confirmed_direction:
                destaque = (destaque + " 💧 Fluxo a favor").strip()

        rows.append({
            "Ativo": symbol,
            "Confirmado": "✅" if mtf.confirmed else "❌",
            "Destaque": destaque,
            "Direção": direction_label,
            col_a: score_a,
            col_b: score_b,
            "Score Geral": score_geral,
            "Fluxo": flow_label,
            "RVOL": round(flow.rvol, 2) if flow.has_volume else None,
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


def run_opportunities(
    symbols: list[str], style: str, source: str, count: int,
    risk_budget: float | None, threshold: float = 75.0,
    require_confirmation: bool = True,
) -> pd.DataFrame:
    """
    Varre a watchlist e devolve SÓ o que está operável agora: qualquer
    leitura (Confluência, SMC, Price Action, Médias, VWAP, IFR) com
    score acima do corte e direção definida.

    Sinais bloqueados pelos filtros (fora da janela de operação ou
    contra o viés do IBOV) já chegam aqui como NEUTRO, então saem da
    lista automaticamente — que é o comportamento desejado.
    """
    rows = []
    filters = current_filters()
    confirmation = STYLES[style]["confirmation"]
    context_tfs = STYLES[style]["context"]
    tf_a, tf_b = confirmation
    progress = st.progress(0.0, text="Procurando oportunidades...")

    for i, symbol in enumerate(symbols):
        progress.progress((i + 1) / len(symbols), text=f"Analisando {symbol} ({i+1}/{len(symbols)})...")
        try:
            # Roda em "Todas as modalidades" pra ter as 6 leituras calculadas
            mtf = cached_mtf(symbol, count, confirmation, context_tfs, ALL_MODALITIES_OPTION, source, filters)
        except Exception:
            continue

        result_a, result_b = mtf.results.get(tf_a), mtf.results.get(tf_b)
        if not result_a or result_a.error or not result_a.signals:
            if source != "MetaTrader 5":
                time.sleep(0.3)
            continue

        by_name_b = {sig.name: sig for sig in (result_b.signals or [])} if result_b and not result_b.error else {}
        flow = result_a.context.flow

        for sig in result_a.signals:
            if sig.direction == Direction.NEUTRAL or sig.score < threshold:
                continue

            # A leitura precisa se sustentar também no timeframe maior:
            # score alto só em M15 é ruído com frequência alta demais.
            other = by_name_b.get(sig.name)
            same_direction = bool(other and other.direction == sig.direction)
            if require_confirmation and not same_direction:
                continue

            risk = sig.risk
            qty = total = None
            if risk_budget and risk.entry is not None and risk.stop is not None:
                risk_per_share = abs(risk.entry - risk.stop)
                if risk_per_share > 0:
                    qty = int(risk_budget // risk_per_share)
                    total = round(qty * risk.entry, 2) if qty > 0 else 0.0

            if not flow.has_volume or flow.bias == Direction.NEUTRAL:
                flow_tag = "⚪ neutro"
            elif flow.bias == sig.direction:
                flow_tag = f"🟢 a favor ({flow.strength:.0f})" if not flow.spike else f"🚨 a favor ({flow.strength:.0f})"
            else:
                flow_tag = f"🔴 contra ({flow.strength:.0f})"

            rows.append({
                "Ativo": symbol,
                "Direção": sig.direction.value,
                "Leitura": sig.name,
                f"Score {tf_a}": round(sig.score, 1),
                f"Score {tf_b}": round(other.score, 1) if other else None,
                "Qualidade": quality(sig.score),
                "Fluxo": flow_tag,
                "RVOL": round(flow.rvol, 2) if flow.has_volume else None,
                "Setup": sig.setup,
                "Entrada": round(risk.entry, 2) if risk.entry else None,
                "Stop": round(risk.stop, 2) if risk.stop else None,
                "Alvo 1": round(risk.target_1, 2) if risk.target_1 else None,
                "R:R": round(risk.rr, 2) if risk.rr else None,
                "Quantidade": qty,
                "Total (R$)": total,
            })

        if source != "MetaTrader 5":
            time.sleep(0.3)

    progress.empty()
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(f"Score {tf_a}", ascending=False).reset_index(drop=True)
        df.insert(0, "#", range(1, len(df) + 1))
    return df


# ========================================================================
# Estado inicial (ANTES dos widgets, pra widgets com `key` já nascerem
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


@st.cache_data(ttl=120, show_spinner=False)
def cached_panorama_dados():
    """Duas chamadas em lote ao Yahoo; 2 min de cache para não estourar o limite."""
    return panorama.baixar()


# ========================================================================
# Configurações — ficam dentro da aba Oportunidades, mas valem para todas.
#
# O Streamlit apaga o estado de um widget quando ele deixa de ser desenhado
# (ao trocar de aba). Reatribuir cada chave no início de toda execução faz o
# valor sobreviver mesmo com o painel fechado.
# ========================================================================
SETTINGS_DEFAULTS = {
    "source_select": DATA_SOURCES[0],
    "style_select": "Day Trade",
    "modality_select": MODALITY_CHOICES[0],
    "filter_window": True,
    "filter_bias": True,
    "count_select": 250,
    "risk_select": 150.0,
    "symbol_select": st.session_state.watchlist[0],
}
for _k, _v in SETTINGS_DEFAULTS.items():
    st.session_state[_k] = st.session_state.get(_k, _v)

source = st.session_state.source_select
style = st.session_state.style_select
modality = st.session_state.modality_select
count = int(st.session_state.count_select)
risk_budget = float(st.session_state.risk_select) or None
conf_a, conf_b = STYLES[style]["confirmation"]
context_label = ", ".join(TIMEFRAME_LABELS[tf] for tf in STYLES[style]["context"])

window_ok, window_note = trading_window_status()
st.session_state["_window_ok"] = window_ok
bias = cached_market_bias(source)
st.session_state["_bias_dir"] = bias.direction.value
st.session_state["_bias_label"] = bias.label


def render_settings() -> None:
    """O antigo painel lateral, agora em colunas dentro da aba Oportunidades."""
    with st.expander("⚙️ Configurações — valem para todas as abas", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("#### Leitura")
            st.radio(
                "Fonte de dados", DATA_SOURCES, key="source_select", horizontal=True,
                help="Yahoo Finance funciona em qualquer lugar, com atraso de ~15-20min. MetaTrader 5 "
                     "direto é tempo real, mas só funciona rodando este app na máquina com o MT5 aberto. "
                     "\"GitHub (MT5 de casa)\" funciona de qualquer lugar e busca dado real do MT5, mas só "
                     "atualiza quando você clicar em \"Atualizar via MT5\".",
            )
            if source == "MetaTrader 5":
                st.caption("⚠️ Só funciona rodando localmente, na máquina com o MT5 aberto. No Streamlit Cloud "
                           "dá erro de conexão.")
            elif source == "GitHub (MT5 de casa)":
                last_update = fetch_snapshot_timestamp()
                if last_update:
                    st.caption(f"📅 Última atualização: {pd.Timestamp(last_update).tz_convert('America/Sao_Paulo').strftime('%d/%m/%Y %H:%M:%S')}")
                else:
                    st.caption("Nenhuma atualização publicada ainda. Clique no botão abaixo.")
                if st.button("🔄 Atualizar via MT5 (casa)", use_container_width=True):
                    ok, msg = trigger_github_update()
                    if not ok:
                        st.error(msg)
                    else:
                        st.cache_data.clear()
                        with st.spinner("Aguardando o computador de casa processar..."):
                            trigger_time = pd.Timestamp.now(tz="UTC")
                            updated = False
                            for _ in range(30):  # até ~90s de espera (30 x 3s)
                                time.sleep(3)
                                ts = fetch_snapshot_timestamp()
                                if ts and pd.Timestamp(ts) > trigger_time:
                                    updated = True
                                    break
                        if updated:
                            st.cache_data.clear()
                            st.success("Dados atualizados!")
                            st.rerun()
                        else:
                            st.warning("Não detectei a atualização em 90s. Confirme se o PC de casa está ligado, "
                                       "o MT5 aberto e logado, e o runner do GitHub Actions rodando.")
            st.radio(
                "Estilo", list(STYLES.keys()), key="style_select", horizontal=True,
                help="Day Trade confirma em M15+H1. Swing Trade confirma em Diário+Semanal, com H4 como contexto.",
            )
            st.selectbox(
                "Modalidade (leitura base da recomendação)", MODALITY_CHOICES, key="modality_select",
                help="Confluência combina SMC/Price Action/Médias/VWAP. IFR é uma leitura de exaustão independente. "
                     "\"Todas as modalidades\" usa o score geral (média das 6 leituras).",
            )
        with c2:
            st.markdown("#### Filtros e risco")
            st.checkbox(
                f"Só operar nas janelas {TRADING_WINDOWS_LABEL}", key="filter_window",
                help="Fora dessas janelas os sinais são bloqueados (viram NEUTRO). Desmarque para estudar fora do "
                     "horário ou para Swing Trade.",
            )
            st.caption(("🟢 " if window_ok else "🔴 ") + window_note)
            st.checkbox("Bloquear operações contra o IBOV", key="filter_bias",
                        help="IBOV caindo → não sugere COMPRA. IBOV subindo → não sugere VENDA.")
            if bias.error:
                st.caption(f"⚠️ Viés do índice indisponível ({bias.symbol}). Nenhum bloqueio aplicado.")
            else:
                icon = {"COMPRA": "📈", "VENDA": "📉", "NEUTRO": "➖"}[bias.direction.value]
                st.caption(f"{icon} **{bias.label}** ({bias.change_pct:+.2f}% na sessão · força {bias.score:+.0f})")
            st.slider(STYLES[style]["count_label"], min_value=50, max_value=400, step=10, key="count_select")
            st.number_input("Risco máximo por operação (R$)", min_value=0.0, step=50.0, key="risk_select",
                            help="Usado para calcular a quantidade de ações. Zero desliga o cálculo.")
            st.caption(f"Recomendação exige {TIMEFRAME_LABELS[conf_a]} e {TIMEFRAME_LABELS[conf_b]} concordando; "
                       f"{context_label} entra como contexto.")
        with c3:
            st.markdown(f"#### Ativos monitorados ({len(st.session_state.watchlist)})")
            a1, a2 = st.columns([3, 1], vertical_alignment="bottom")
            new_symbol = a1.text_input("Adicionar ativo (ex: VALE3)", key="new_symbol_input")
            if a2.button("Adicionar", use_container_width=True) and new_symbol.strip():
                value = new_symbol.strip().upper().replace(" ", "")
                if value not in st.session_state.watchlist:
                    st.session_state.watchlist.append(value)
                    _persist_watchlist()
                st.rerun()
            r1, r2 = st.columns([3, 1], vertical_alignment="bottom")
            remove_symbol = r1.selectbox("Remover ativo", ["—"] + st.session_state.watchlist, key="remove_symbol_select")
            if r2.button("Remover", use_container_width=True) and remove_symbol != "—":
                st.session_state.watchlist = [s for s in st.session_state.watchlist if s != remove_symbol]
                _persist_watchlist()
                st.rerun()
            b1, b2 = st.columns(2)
            if b1.button("Lista padrão", use_container_width=True, help=f"Restaura os {len(DEFAULT_SYMBOLS)} ativos monitorados"):
                st.session_state.watchlist = DEFAULT_SYMBOLS.copy()
                _persist_watchlist()
                st.rerun()
            if b2.button("Lista antiga", use_container_width=True, help="Restaura a watchlist anterior (VALE3, PETR4, ...)"):
                st.session_state.watchlist = LEGACY_SYMBOLS.copy()
                _persist_watchlist()
                st.rerun()
            st.caption(", ".join(st.session_state.watchlist))


# ========================================================================
# Topo fixo: faixa do panorama (texto) + navegação horizontal
# ========================================================================
@st.fragment(run_every=120)
def _faixa_panorama():
    try:
        diario, intra = cached_panorama_dados()
        st.markdown(panorama_ui.faixa(panorama.montar(diario, intra)), unsafe_allow_html=True)
    except Exception:
        st.markdown(panorama_ui.faixa(None), unsafe_allow_html=True)


MODES = ["🔥 Oportunidades agora", "Análise individual", "Scanner (todos os ativos)", "Verificação retroativa"]
_MODE_LABEL = {
    "🔥 Oportunidades agora": "🔥 Oportunidades", "Análise individual": "📈 Análise",
    "Scanner (todos os ativos)": "🔍 Scanner", "Verificação retroativa": "⏪ Retroativa",
}
if st.session_state.get("mode_select") not in MODES:
    st.session_state.mode_select = MODES[0]
with st.container(key="topnav"):
    _faixa_panorama()
    mode = st.radio("Modo", MODES, key="mode_select", horizontal=True, label_visibility="collapsed",
                    format_func=lambda m: _MODE_LABEL.get(m, m))


# ========================================================================
# Corpo principal
# ========================================================================
_MODE_SUB = {
    "🔥 Oportunidades agora": "Só o que está operável agora, em toda a watchlist",
    "Análise individual": "Gráfico e as 6 leituras de um ativo",
    "Scanner (todos os ativos)": "Ranking da watchlist pelo score geral (só score 30 ou mais)",
    "Verificação retroativa": "Um pregão passado, em todas as ações, e o que aconteceu depois",
}
if bias.error:
    _bias_chip = ("IBOV indisponível", ui.MUTED)
else:
    _bias_chip = (f"IBOV {bias.change_pct:+.2f}% · {bias.direction.value.lower()}", ui.tone_for(bias.direction.value))
ui.hero(
    "Day Trade SMC",
    _MODE_SUB.get(mode, ""),
    [
        ("Janela aberta" if window_ok else "Fora da janela", ui.BUY if window_ok else ui.SELL),
        _bias_chip,
        ({"Yahoo Finance": "Yahoo · atraso", "MetaTrader 5": "MT5 · tempo real"}.get(source, "MT5 de casa"),
         ui.GOLD if source == "Yahoo Finance" else ui.STEEL),
        (f"Risco R$ {risk_budget:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if risk_budget else "Sem risco definido", ui.STEEL),
    ],
    delay_note=source == "Yahoo Finance",
)

if mode == "🔥 Oportunidades agora":
    render_settings()

    if bias.error:
        _lado = "Viés do IBOV indisponível: nenhum bloqueio direcional."
    elif bias.direction == Direction.BUY:
        _lado = f"{bias.label}: só compra liberada."
    elif bias.direction == Direction.SELL:
        _lado = f"{bias.label}: só venda liberada."
    else:
        _lado = f"{bias.label}: os dois lados liberados."

    o1, o2, o3 = st.columns([2, 2, 1.2], vertical_alignment="bottom")
    with o1:
        opp_threshold = st.slider(
            "Score mínimo", min_value=60, max_value=95, value=75, step=5, key="opp_threshold",
            help="Leituras isoladas (SMC, Price Action, Médias, VWAP, IFR) vão no máximo a 79 pontos; "
                 "acima de 79 só aparece Confluência.",
        )
    with o2:
        opp_require_conf = st.checkbox(
            f"Exigir a mesma direção em {conf_a} e {conf_b}", value=True, key="opp_require_conf",
            help="Desmarcar aumenta muito o número de resultados, e o de falsos positivos.",
        )
    with o3:
        run_opp_clicked = st.button("🔥 Buscar oportunidades", type="primary", use_container_width=True)

    ui.banner(f"⏰ {ui.esc(window_note)}", ui.esc(_lado), ui.BUY if window_ok else ui.SELL)
    if st.session_state.get("filter_window", True) and not window_ok:
        st.warning(f"Fora da janela de operação ({TRADING_WINDOWS_LABEL}) todos os sinais são bloqueados e a "
                   "lista virá vazia. Desmarque o filtro em ⚙️ Configurações para estudar o mercado assim mesmo.")
    st.caption(f"{len(st.session_state.watchlist)} ativos · {style} · confirmação {conf_a}+{conf_b} · "
               f"{count} candles · fonte: {source}")

    if run_opp_clicked:
        st.session_state.opp_result = run_opportunities(
            st.session_state.watchlist, style, source, count, risk_budget,
            threshold=float(opp_threshold), require_confirmation=opp_require_conf,
        )
        st.session_state.opp_meta = (opp_threshold, opp_require_conf, pd.Timestamp.now(tz="America/Sao_Paulo"))
        st.session_state.opp_risk_budget = risk_budget

    if "opp_result" in st.session_state:
        opp_df = st.session_state.opp_result
        thr, req_conf, ran_at = st.session_state.get("opp_meta", (75, True, None))

        if opp_df.empty:
            st.info(
                f"Nenhuma oportunidade acima de {thr} pontos no momento"
                + (" (exigindo os dois timeframes na mesma direção)." if req_conf else ".")
                + " Na maior parte do tempo o mercado não oferece setup de alta qualidade. "
                "Rode de novo mais tarde ou baixe o corte."
            )
        else:
            ativos = opp_df["Ativo"].nunique()
            compras = int((opp_df["Direção"] == "COMPRA").sum())
            vendas = int((opp_df["Direção"] == "VENDA").sum())
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Oportunidades", len(opp_df))
            k2.metric("Ativos", ativos)
            k3.metric("Compras", compras)
            k4.metric("Vendas", vendas)
            if ran_at is not None:
                st.caption(f"Varredura de {ran_at.strftime('%d/%m/%Y %H:%M:%S')} · corte {thr} pontos")
            _sc = next(c for c in opp_df.columns if str(c).startswith("Score"))
            ui.podium(_podium_rows(opp_df, _sc, ("Leitura", "Qualidade")))

            def _color_dir_opp(val):
                if val == "COMPRA":
                    return f"color: {ui.BUY}; font-weight: 600"
                if val == "VENDA":
                    return f"color: {ui.SELL}; font-weight: 600"
                return f"color: {ui.MUTED}"

            st.dataframe(
                opp_df.style.map(_color_dir_opp, subset=["Direção"]),
                hide_index=True, use_container_width=True,
                height=min(600, 45 + 35 * len(opp_df)),
                column_config=_score_cols(opp_df),
            )

            p1, p2 = st.columns([3, 1], vertical_alignment="bottom")
            pick = p1.selectbox("Abrir análise completa de", opp_df["Ativo"].unique().tolist(), key="opp_pick_select")
            if p2.button("Ver gráfico e as 6 leituras", use_container_width=True):
                if pick not in st.session_state.watchlist:
                    st.session_state.watchlist.append(pick)
                st.session_state.jump_to_symbol = pick
                st.rerun()
    else:
        st.info("Clique em **🔥 Buscar oportunidades**. "
                f"A varredura leva ~{max(1, len(st.session_state.watchlist) * 2 // 60)}-"
                f"{max(2, len(st.session_state.watchlist) * 4 // 60)} min com {len(st.session_state.watchlist)} ativos no Yahoo Finance.")

elif mode == "Análise individual":
    if st.session_state.get("symbol_select") not in st.session_state.watchlist:
        st.session_state.symbol_select = st.session_state.watchlist[0]
    a1, a2, a3 = st.columns([2, 1, 1], vertical_alignment="bottom")
    a1.selectbox("Ativo", st.session_state.watchlist, key="symbol_select")
    auto_refresh = a2.checkbox("Atualizar sozinho", key="ind_auto")
    refresh_interval = a3.select_slider("Intervalo", options=[30, 60, 120, 300], value=60, key="ind_interval",
                                        format_func=lambda s: f"{s}s", disabled=not auto_refresh)
    symbol = st.session_state.symbol_select

    if auto_refresh:
        st.caption(f"🔄 Atualizando automaticamente a cada {refresh_interval}s")
        _AUTO_REFRESH_FRAGMENTS[refresh_interval](symbol, style, modality, source, count, risk_budget)
    else:
        render_individual_analysis(symbol, style, modality, source, count, risk_budget)

elif mode == "Scanner (todos os ativos)":
    SCORE_MIN_SCANNER = 30.0
    s1, s2 = st.columns([3, 1], vertical_alignment="bottom")
    s1.caption(f"{len(st.session_state.watchlist)} ativo(s) na watchlist · {style} · leitura: {modality} · "
               f"{count} candles · recomendação exige {conf_a}+{conf_b} concordando · "
               f"só aparecem ações com score geral ≥ {SCORE_MIN_SCANNER:.0f}")
    run_scanner_clicked = s2.button("🔍 Rodar scanner", type="primary", use_container_width=True)

    if run_scanner_clicked:
        st.session_state.scanner_result = run_scanner(st.session_state.watchlist, style, modality, source, count, risk_budget)
        st.session_state.scanner_risk_budget = risk_budget

    if "scanner_result" in st.session_state:
        full_df = st.session_state.scanner_result
        result_df = full_df[pd.to_numeric(full_df["Score Geral"], errors="coerce") >= SCORE_MIN_SCANNER].copy()
        result_df["Posição"] = range(1, len(result_df) + 1)
        ocultos = len(full_df) - len(result_df)

        def _color_direction(val):
            if val == "COMPRA":
                return f"color: {ui.BUY}; font-weight: 600"
            if val == "VENDA":
                return f"color: {ui.SELL}; font-weight: 600"
            return f"color: {ui.MUTED}"

        _conf = result_df[result_df["Confirmado"] == "✅"]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Ações com score ≥ 30", len(result_df),
                  help=f"{ocultos} ação(ões) ficaram de fora por score abaixo de 30 ou falta de dados.")
        k2.metric("Confirmados", len(_conf))
        k3.metric("Compras", int((_conf["Direção"] == "COMPRA").sum()))
        k4.metric("Vendas", int((_conf["Direção"] == "VENDA").sum()))
        ui.podium(_podium_rows(_conf, "Score Geral", ("Destaque", "Fluxo")))

        if result_df.empty:
            st.info(f"Nenhuma ação com score geral ≥ {SCORE_MIN_SCANNER:.0f} nesta varredura.")
        else:
            st.dataframe(
                result_df.style.map(_color_direction, subset=["Direção"]),
                hide_index=True, use_container_width=True, height=min(600, 45 + 35 * len(result_df)),
                column_config=_score_cols(result_df),
            )
            p1, p2 = st.columns([3, 1], vertical_alignment="bottom")
            pick = p1.selectbox("Abrir análise completa de", result_df["Ativo"].tolist(), key="scanner_pick_select")
            if p2.button("Ver gráfico e as 6 leituras", use_container_width=True):
                st.session_state.jump_to_symbol = pick
                st.rerun()
        erros = full_df[full_df["Confirmado"] == "ERRO"]
        if len(erros):
            st.caption(f"⚠️ {len(erros)} ativo(s) sem dados nesta varredura: {', '.join(erros['Ativo'])}")
    else:
        st.info("Clique em **🔍 Rodar scanner** para analisar todos os ativos da watchlist.")

else:  # Verificação retroativa
    render_retro_all(style, modality, source, count)
