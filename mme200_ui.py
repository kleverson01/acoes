"""
mme200_ui.py

Aba "🎯 MME200" do site: setup de rejeição na MME200 após movimento brusco (M15, metas em %).
Mostra (1) a situação AGORA em cada ativo — gatilho armado, operação aberta, encerrada ou nada —
e (2) o histórico do setup nos dados disponíveis (Yahoo: até ~60 dias de M15).
As regras ficam em `setup_mme200.py`.
"""

from __future__ import annotations

import time

import pandas as pd
import streamlit as st

import daytrade_smc
import setup_mme200 as S
import ui_theme as ui

CANDLES_M15 = 1600   # ~60 pregões, o máximo que o Yahoo entrega em 15 min


@st.cache_data(ttl=300, show_spinner=False)
def _m15(symbol: str, source: str) -> pd.DataFrame:
    return daytrade_smc.fetch_ohlcv(symbol, "M15", CANDLES_M15, source=source)


_COR = {"GATILHO ARMADO": ui.GOLD, "EM OPERAÇÃO": ui.STEEL, "ENCERRADA HOJE": ui.MUTED, "SEM SINAL": ui.MUTED, "SEM DADOS": ui.SELL, "ERRO": ui.SELL}


def _cartao(s: S.Situacao) -> str:
    tom = _COR.get(s.estado, ui.MUTED)
    if s.direcao:
        tom = ui.BUY if s.direcao == "COMPRA" else ui.SELL if s.estado in ("GATILHO ARMADO", "EM OPERAÇÃO") else tom
    linhas = ""
    if s.gatilho is not None:
        rot = "Gatilho" if s.estado == "GATILHO ARMADO" else "Entrada"
        linhas = (f'<div class="lv"><div><small>{rot}</small><b>{s.gatilho:.2f}</b></div>'
                  f'<div><small>Alvo</small><b style="color:{ui.BUY}">{s.alvo:.2f}</b></div>'
                  f'<div><small>Stop</small><b style="color:{ui.SELL}">{s.stop:.2f}</b></div></div>')
    preco = f"{s.preco:.2f}" if s.preco else "—"
    mme = f" · MME200 {s.mme200:.2f}" if s.mme200 else ""
    return (f'<div class="pcard" style="--tone:{tom}"><div class="top"><span class="sym">{ui.esc(s.ativo)}</span>'
            f'<span class="sc">{ui.esc(s.direcao + " · " if s.direcao else "")}{ui.esc(s.estado.capitalize())}</span></div>'
            f'<div class="meta">R$ {preco}{mme}<br>{ui.esc(s.detalhe)}</div>{linhas}</div>')


def render(source: str, watchlist: list[str]) -> None:
    st.caption(
        "Depois de um impulso de 2 horas (≥ 2 ATR), o preço toca a MME200 do M15 e o candle fecha de volta → "
        "entrada no rompimento desse candle, alvo de 0,5%, stop de proteção de 2,5%, zeragem às 17:30. "
        "Testado nas 10 ações mais líquidas (últimos 60 pregões até 19/11: 23 operações, 87% no alvo, "
        "+0,33% líquido por operação). Amostra pequena: use na conta simulada até confirmar."
    )
    with st.expander("⚙️ Parâmetros do setup", expanded=False):
        c1, c2, c3 = st.columns(3)
        alvo = c1.number_input("Alvo (%)", 0.1, 3.0, 0.5, 0.1, key="mme_alvo")
        stop = c1.number_input("Stop de proteção (%)", 0.3, 5.0, 2.5, 0.1, key="mme_stop")
        n_imp = c2.select_slider("Impulso (candles de 15 min)", options=[4, 6, 8, 10, 12], value=8, key="mme_n",
                                 format_func=lambda n: f"{n} ({n * 15 // 60}h{(n * 15) % 60:02d})")
        k_atr = c2.number_input("Tamanho mínimo do impulso (ATR)", 1.0, 4.0, 2.0, 0.5, key="mme_k")
        usar_ifr = c3.checkbox("Exigir IFR(14) ≥ 70 / ≤ 30", value=False, key="mme_ifr",
                               help="Deixa o setup bem mais raro. No teste não houve amostra para validar nas mais líquidas.")
        usar_vol = c3.checkbox("Exigir volume ≥ 1,5× a média", value=False, key="mme_vol",
                               help="No M5 ajudou; no M15 não melhorou de forma consistente.")
        opcoes = list(dict.fromkeys(S.TOP10_LIQUIDAS + list(watchlist)))
        ativos = st.multiselect("Ativos", opcoes, default=S.TOP10_LIQUIDAS, key="mme_ativos",
                                help="Padrão: as 10 mais líquidas, onde o setup foi validado.")
    cfg = S.ConfigMME200(alvo_pct=float(alvo), stop_pct=float(stop), n_impulso=int(n_imp), k_atr=float(k_atr),
                         ifr_minimo=70.0 if usar_ifr else None, volume_minimo=1.5 if usar_vol else None)
    ativos = st.session_state.get("mme_ativos", S.TOP10_LIQUIDAS) or S.TOP10_LIQUIDAS

    b1, b2 = st.columns([1, 3], vertical_alignment="center")
    rodar = b1.button("🎯 Verificar agora", type="primary", use_container_width=True)
    b2.caption(f"{len(ativos)} ativo(s) · M15 · fonte: {source} · leitura e histórico na mesma busca")

    if rodar:
        situacoes, trades, erros = [], [], []
        prog = st.progress(0.0, text="Buscando candles de 15 min...")
        for i, a in enumerate(ativos):
            prog.progress((i + 1) / len(ativos), text=f"{a} ({i + 1}/{len(ativos)})")
            try:
                df = _m15(a, source)
                situacoes.append(S.situacao_atual(df, cfg, a))
                t = S.backtest(df, cfg, a)
                if len(t):
                    trades.append(t)
            except Exception as exc:  # noqa: BLE001 - mostra o erro por ativo e segue
                erros.append(f"{a}: {exc}")
                situacoes.append(S.Situacao(a, "ERRO", detalhe=str(exc)[:80]))
            if source == "Yahoo Finance":
                time.sleep(0.3)
        prog.empty()
        st.session_state.mme_resultado = (situacoes, pd.concat(trades, ignore_index=True) if trades else pd.DataFrame(), erros,
                                          pd.Timestamp.now(tz=S.TZ), cfg)

    if "mme_resultado" not in st.session_state:
        st.info("Clique em **🎯 Verificar agora** para ver os gatilhos armados e o histórico do setup.")
        return

    situacoes, T, erros, quando, cfg_usada = st.session_state.mme_resultado
    ordem = {"EM OPERAÇÃO": 0, "GATILHO ARMADO": 1, "ENCERRADA HOJE": 2, "SEM SINAL": 3, "SEM DADOS": 4, "ERRO": 5}
    situacoes = sorted(situacoes, key=lambda s: ordem.get(s.estado, 9))
    ativos_sinal = [s for s in situacoes if s.estado in ("EM OPERAÇÃO", "GATILHO ARMADO")]

    st.markdown(f"### Agora · {quando.strftime('%d/%m %H:%M')}")
    if ativos_sinal:
        ui.banner(f"{len(ativos_sinal)} ativo(s) com sinal", "Gatilho armado = ordem de entrada no preço indicado, válida pelos próximos candles.", ui.GOLD)
    else:
        st.caption("Nenhum gatilho armado ou operação aberta neste momento. O setup é raro: cerca de 2 entradas por semana somando as 10 ações.")
    st.markdown(f'<div class="podium">{"".join(_cartao(s) for s in situacoes)}</div>', unsafe_allow_html=True)

    st.markdown("### Histórico nos dados disponíveis")
    if T.empty:
        st.info("Nenhuma operação do setup no período carregado.")
    else:
        r = S.resumo(T)
        k = st.columns(6)
        k[0].metric("Operações", r["operações"])
        k[1].metric("Bateram o alvo", f"{r['bateram o alvo %']:.0f}%")
        k[2].metric("Ganho médio", f"{r['ganho médio %']:+.2f}%", help="Por operação, já descontado o custo de 0,08%.")
        k[3].metric("Soma", f"{r['soma %']:+.2f}%")
        k[4].metric("Pior operação", f"{r['pior %']:+.2f}%")
        k[5].metric("Stops", r["stops"], help=f"{r['zeradas']} operação(ões) foram zeradas no fim do dia.")
        st.caption(f"De {T['Dia'].min().strftime('%d/%m/%Y')} a {T['Dia'].max().strftime('%d/%m/%Y')} · alvo {cfg_usada.alvo_pct:g}% · "
                   f"stop {cfg_usada.stop_pct:g}% · impulso {cfg_usada.n_impulso} candles ≥ {cfg_usada.k_atr:g} ATR · custo {cfg_usada.custo_pct:g}% por operação")

        def _cor(v):
            if v == "ALVO":
                return f"color: {ui.BUY}; font-weight: 600"
            if v == "STOP":
                return f"color: {ui.SELL}; font-weight: 600"
            if isinstance(v, (int, float)):
                return f"color: {ui.BUY if v > 0 else ui.SELL}"
            return ""

        vis = T.sort_values(["Dia", "Toque"], ascending=False)
        st.dataframe(vis.style.map(_cor, subset=["Resultado", "Resultado %"]), hide_index=True, use_container_width=True,
                     height=min(520, 45 + 35 * len(vis)),
                     column_config={"Dia": st.column_config.DateColumn("Dia", format="DD/MM/YYYY"),
                                    "Resultado %": st.column_config.NumberColumn("Resultado %", format="%+.2f%%")})
        por = T.groupby("Ativo")["Resultado %"].agg(Operações="count", Soma="sum", Média="mean").round(2).sort_values("Soma", ascending=False)
        with st.expander("Resultado por ativo"):
            st.dataframe(por, use_container_width=True)
    if erros:
        st.caption("⚠️ Sem dados: " + " · ".join(erros))
