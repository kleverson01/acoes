"""
panorama_ui.py

Desenha a aba "Panorama de mercado" em caixas pequenas, em faixas horizontais:

    [ WINFUT geral ][ Diário ][ 60 min ][ Futuros ][ Juros ][ Bolsas ]   ← placar
    [ ativo ][ ativo ][ ativo ][ ativo ] ...                              ← dia + 60 min no mesmo cartão
    [ Futuros globais ]   [ Curva de juros ]   [ Bolsas globais ]         ← contexto

Diário e 60 min ficam no MESMO cartão de cada ativo (antes eram duas tabelas
com os mesmos nomes repetidos). Fonte e horários ficam na dica do cartão
(passe o mouse), para não poluir a leitura.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import panorama as P
import ui_theme as ui

_CSS = """
<style>
.pn-row { display:grid; gap:12px; margin: 4px 0 20px; }
.pn-placar { grid-template-columns: minmax(0, 1.35fr) repeat(5, minmax(0, 1fr)); }
.pn-grid { grid-template-columns: repeat(auto-fill, minmax(232px, 1fr)); }
.pn-box {
  background: linear-gradient(180deg, var(--slab-up), var(--slab)); border-radius: 14px;
  padding: 11px 13px; box-shadow: var(--depth-lo); border-top: 3px solid var(--tone); min-width: 0;
}
.pn-box.main { box-shadow: var(--depth); padding: 14px 16px; }
.pn-k { color: var(--muted); font-size: .78rem; font-weight: 600; }
.pn-v { font: 800 1.45rem 'Sora', system-ui, sans-serif; color: var(--tone); line-height: 1.15; margin-top: 2px; }
.pn-box.main .pn-v { font-size: 1.9rem; }
.pn-l { font-size: .84rem; color: var(--text); font-weight: 600; margin-top: 2px; }
.pn-c { font-size: .72rem; color: var(--muted); margin-top: 6px; }
.pn-bar { position: relative; height: 6px; border-radius: 4px; background: rgba(0,0,0,.35);
          box-shadow: 0 1px 2px rgba(0,0,0,.5) inset; margin-top: 8px; overflow: hidden; }
.pn-bar::after { content:""; position:absolute; left:50%; top:-2px; bottom:-2px; width:1px; background: rgba(255,255,255,.25); }
.pn-bar i { position:absolute; top:0; bottom:0; background: var(--tone); border-radius: 4px; }
.pn-head { display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.pn-name { font: 700 .92rem 'Sora', system-ui, sans-serif; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.pn-px { font-weight: 700; font-size: .9rem; }
.pn-st { font-size: .68rem; color: var(--muted); }
.pn-st b { color: var(--buy); font-weight: 600; }
.pn-st b.off { color: var(--muted); }
.pn-m { display:grid; grid-template-columns: 40px 66px minmax(0,1fr) 44px; gap: 7px; align-items:center; margin-top: 7px; font-size: .8rem; }
.pn-m .h { color: var(--muted); font-size: .72rem; }
.pn-m .mv { font-weight: 700; }
.pn-m .sc { font-weight: 700; font-size: .74rem; padding: 2px 0; text-align:center; border-radius: 7px; background: rgba(0,0,0,.28); }
.pn-m .pn-bar { margin: 0; height: 5px; }
.pn-sec { font: 700 1rem 'Sora', system-ui, sans-serif; margin: 6px 0 8px; display:flex; flex-wrap:wrap; column-gap:10px; align-items:baseline; }
.pn-sec span { font: 600 .8rem 'Manrope', system-ui, sans-serif; color: var(--muted); }
.pn-list .pn-box { padding: 8px 12px; margin-bottom: 8px; border-top: 0; border-left: 3px solid var(--tone); }
.pn-list .pn-m { margin-top: 2px; grid-template-columns: minmax(0,1fr) auto 44px; }
@media (max-width: 1100px) { .pn-placar { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 640px)  { .pn-placar { grid-template-columns: repeat(2, minmax(0, 1fr)); } .pn-placar .main { grid-column: 1 / -1; } }
</style>
"""


def _tone(score):
    if score is None or not np.isfinite(score) or abs(score) < 1:
        return ui.MUTED
    return ui.BUY if score > 0 else ui.SELL


def _bar(score) -> str:
    if score is None or not np.isfinite(score):
        return '<div class="pn-bar"></div>'
    w = min(abs(score), 10) * 5  # metade da barra = 10 pontos
    left = 50 if score >= 0 else 50 - w
    return f'<div class="pn-bar"><i style="left:{left:.1f}%;width:{w:.1f}%"></i></div>'


def _fmt_px(v) -> str:
    if v is None or not np.isfinite(v):
        return "—"
    txt = f"{v:,.2f}" if abs(v) < 100000 else f"{v:,.0f}"
    return txt.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_mv(v) -> str:
    if v is None or not np.isfinite(v):
        return "—"
    seta = "▲" if v > 0.005 else "▼" if v < -0.005 else "■"
    return f"{seta} {v:+.2f}%".replace(".", ",")


def _fmt_sc(v) -> str:
    return "N/D" if v is None or not np.isfinite(v) else f"{v:+.1f}".replace(".", ",")


def _hora(ts) -> str:
    if ts is None:
        return "—"
    ts = pd.Timestamp(ts)
    if ts.tz is None:
        return ts.strftime("%d/%m")
    return ts.tz_convert(P.TZ).strftime("%d/%m %H:%M")


def _dica(ln: P.Linha, horizonte: str) -> str:
    return (f"{horizonte} · Yahoo {ln.ativo.ticker} · preço {_hora(ln.quando)} · referência {_hora(ln.ref_quando)} "
            f"· peso {ln.ativo.peso:g} · {'sobe junto com a B3' if ln.ativo.sentido > 0 else 'sobe contra a B3'}")


def _placar_box(nome: str, total, sub: str, main: bool = False) -> str:
    tone = _tone(total)
    val = "—" if total is None else f"{total:+.2f}".replace(".", ",")
    return (f'<div class="pn-box{" main" if main else ""}" style="--tone:{tone}">'
            f'<div class="pn-k">{ui.esc(nome)}</div><div class="pn-v">{val}</div>'
            f'<div class="pn-l">{ui.esc(P.leitura(total))}</div>{_bar(total)}'
            f'<div class="pn-c">{ui.esc(sub)}</div></div>')


def _mini(rotulo: str, ln: P.Linha, horizonte: str) -> str:
    """Uma linha por horizonte: rótulo · movimento · barra do score · score (impacto na dica)."""
    tone = _tone(ln.score)
    dica = f"{ln.impacto} · " + _dica(ln, horizonte)
    return (f'<div class="pn-m" title="{ui.esc(dica)}"><span class="h">{rotulo}</span>'
            f'<span class="mv" style="color:{tone}">{_fmt_mv(ln.mov)}</span>{_bar(ln.score)}'
            f'<span class="sc" style="color:{tone}">{_fmt_sc(ln.score)}</span></div>')


def _ativo_card(d: P.Linha, m: P.Linha) -> str:
    tone = _tone(d.score if d.score is not None else m.score)
    preco = d.preco if d.preco is not None else m.preco
    aberto = d.aberto or m.aberto
    status = '<b>● aberto</b>' if aberto else '<b class="off">● fechado</b>'
    return (f'<div class="pn-box" style="--tone:{tone}"><div class="pn-head">'
            f'<span class="pn-name" title="{ui.esc(d.ativo.ticker)}">{ui.esc(d.ativo.nome)}</span>'
            f'<span class="pn-px">{_fmt_px(preco)}</span></div>'
            f'<div class="pn-st">{status} · ref. {_fmt_px(d.ref)}</div>'
            f'{_mini("Dia", d, "Diário")}{_mini("60 min", m, "60 min")}</div>')


def _lista(bloco: P.Bloco) -> str:
    itens = []
    for ln in bloco.linhas:
        tone = _tone(ln.score)
        itens.append(
            f'<div class="pn-box" style="--tone:{tone}" title="{ui.esc(_dica(ln, bloco.nome))}">'
            f'<div class="pn-head"><span class="pn-name">{ui.esc(ln.ativo.nome)}</span>'
            f'<span class="pn-px">{_fmt_px(ln.preco)}</span></div>'
            f'<div class="pn-m"><span class="mv" style="color:{tone}">{_fmt_mv(ln.mov)}</span>'
            f'<span class="pn-st">{ui.esc(ln.impacto)}</span>'
            f'<span class="sc" style="color:{tone}">{_fmt_sc(ln.score)}</span></div></div>'
        )
    tot = bloco.total
    head = (f'<div class="pn-sec">{ui.esc(bloco.nome)}<span>{_fmt_sc(tot)} · {ui.esc(P.leitura(tot))} · '
            f'cobertura {bloco.cobertura:.0%}</span></div>')
    return head + f'<div class="pn-list">{"".join(itens)}</div>'


def render(pn: P.Panorama) -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    b = pn.blocos

    # 1) placar — uma faixa horizontal
    boxes = [_placar_box("WINFUT · placar geral", pn.geral, f"Cobertura efetiva {pn.cobertura:.0%}", main=True)]
    for nome, bloco in b.items():
        boxes.append(_placar_box(nome, bloco.total, f"Peso {P.PESO_BLOCO[nome]:.0%} · cobertura {bloco.cobertura:.0%}"))
    st.markdown(f'<div class="pn-row pn-placar">{"".join(boxes)}</div>', unsafe_allow_html=True)

    # 2) ativos — diário e 60 min no mesmo cartão
    st.markdown(
        f'<div class="pn-sec">Ativos<span>cada cartão mostra o dia (contra o fechamento anterior) e os últimos '
        f'60 min · passe o mouse para ver fonte e horários</span></div>', unsafe_allow_html=True)
    cards = [_ativo_card(pn.diario[a.ticker], pn.m60[a.ticker]) for a in P.ATIVOS]
    st.markdown(f'<div class="pn-row pn-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

    # 3) contexto — três colunas lado a lado
    cols = st.columns(3)
    for col, nome in zip(cols, ("Futuros globais", "Curva de juros", "Bolsas globais")):
        with col:
            st.markdown(_lista(b[nome]), unsafe_allow_html=True)

    st.caption(f"Atualizado às {pn.gerado.tz_convert(P.TZ).strftime('%H:%M:%S')} · Yahoo Finance com atraso de "
               "até 15-30 min conforme o ativo · contexto, não sinal de entrada.")
    with st.expander("Como o placar é calculado"):
        st.markdown(
            "- **Movimento**: variação do preço contra o fechamento anterior (Dia) ou contra 60 minutos atrás.\n"
            "- **Score**: movimento ÷ desvio típico do próprio ativo × 5, limitado a ±10. Assim +1% no VIX "
            "pesa pouco e +1% no S&P pesa muito.\n"
            "- **Sentido**: dólar, DXY, VIX, ouro e juros americanos contam ao contrário (subir é ruim para a B3).\n"
            "- **Impacto**: forte a partir de 7, moderado de 4, fraco de 1.\n"
            "- **Bloco**: média ponderada pelos pesos dos ativos. **WINFUT geral**: média dos blocos "
            "(Diário 30%, 60 min 30%, Futuros 20%, Juros 10%, Bolsas 10%).\n"
            "- Pesos e sentidos são escolhas de contexto, não parâmetros otimizados; ficam em `panorama.py`."
        )
