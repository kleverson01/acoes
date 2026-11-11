"""
panorama_ui.py

Faixa fixa no topo da página com o panorama de mercado, só em texto:
cada ativo com a variação do dia à frente, verde quando sobe e vermelho
quando cai. O placar geral (regra em `panorama.py`) abre a faixa.
"""

from __future__ import annotations

import numpy as np

import panorama as P
import ui_theme as ui

# Ordem e agrupamento da faixa
GRUPOS = (
    ("Brasil", ("^BVSP", "EWZ", "PETR4.SA", "VALE3.SA", "BRL=X")),
    ("EUA", ("^GSPC", "^IXIC", "^DJI", "^NYA", "^VIX")),
    ("Futuros", ("ES=F", "NQ=F", "YM=F", "RTY=F")),
    ("Juros EUA", ("^IRX", "^FVX", "^TNX", "^TYX")),
    ("Moedas e commodities", ("DX-Y.NYB", "BZ=F", "GC=F")),
    ("Bolsas", ("^STOXX50E", "^GDAXI", "^FTSE", "^N225", "^HSI", "000001.SS")),
)

# nomes curtos para caber na faixa
CURTO = {
    "^BVSP": "Ibovespa", "EWZ": "EWZ", "PETR4.SA": "Petrobras", "VALE3.SA": "Vale", "BRL=X": "Dólar",
    "^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow", "^NYA": "NYSE", "^VIX": "VIX",
    "ES=F": "S&P fut", "NQ=F": "Nasdaq fut", "YM=F": "Dow fut", "RTY=F": "Russell fut",
    "^IRX": "3 meses", "^FVX": "5 anos", "^TNX": "10 anos", "^TYX": "30 anos",
    "DX-Y.NYB": "DXY", "BZ=F": "Brent", "GC=F": "Ouro",
    "^STOXX50E": "Euro Stoxx", "^GDAXI": "DAX", "^FTSE": "FTSE", "^N225": "Nikkei", "^HSI": "Hang Seng",
    "000001.SS": "Xangai",
}

_CSS = """
<style>
.fx { display:flex; flex-wrap:wrap; align-items:baseline; gap: 4px 14px; padding: 8px 14px; margin-bottom: 8px;
      border-radius: 12px; background: rgba(6,11,20,.72); box-shadow: 0 1px 0 rgba(255,255,255,.05) inset, 0 3px 0 rgba(0,0,0,.5);
      font-size: .8rem; line-height: 1.5; color: var(--muted); }
.fx .g { color: var(--muted); font-weight: 700; font-size: .72rem; }
.fx .a { white-space: nowrap; color: var(--text); }
.fx .a b { font-weight: 700; margin-left: 4px; }
.fx .up { color: var(--buy); } .fx .dn { color: var(--sell); } .fx .nd { color: var(--muted); }
.fx .pl { white-space: nowrap; color: var(--text); font-weight: 700; padding-right: 6px; border-right: 1px solid rgba(255,255,255,.1); }
.fx .hr { margin-left: auto; white-space: nowrap; font-size: .72rem; }
</style>
"""


def _pct(v) -> str:
    if v is None or not np.isfinite(v):
        return '<b class="nd">—</b>'
    cls = "up" if v > 0 else "dn" if v < 0 else "nd"
    return f'<b class="{cls}">{v:+.2f}%</b>'.replace(".", ",")


def faixa(pn: P.Panorama | None) -> str:
    if pn is None:
        return _CSS + '<div class="fx">Panorama indisponível agora: o Yahoo não respondeu. Tenta de novo em 2 min.</div>'

    linhas = {ln.ativo.ticker: ln for b in pn.blocos.values() if b.nome != "60 min" for ln in b.linhas}
    geral = pn.geral
    if geral is None:
        placar = '<span class="pl">Placar —</span>'
    else:
        cls = "up" if geral > 0 else "dn" if geral < 0 else "nd"
        placar = (f'<span class="pl">Placar <b class="{cls}">{geral:+.2f}</b>'.replace(".", ",")
                  + f' {ui.esc(P.leitura(geral).lower())}</span>')

    partes = [placar]
    for nome, tickers in GRUPOS:
        itens = []
        for t in tickers:
            ln = linhas.get(t)
            if ln is None:
                continue
            dica = f"{ln.ativo.nome} ({t}) · fechamento anterior {ln.ref:.2f}" if ln.ref else ln.ativo.nome
            itens.append(f'<span class="a" title="{ui.esc(dica)}">{ui.esc(CURTO.get(t, ln.ativo.nome))}{_pct(ln.mov)}</span>')
        if itens:
            # o nome do grupo nunca fica sozinho no fim da linha
            itens[0] = f'<span class="a"><span class="g">{ui.esc(nome)}</span> {itens[0]}</span>'
            partes.extend(itens)
    partes.append(f'<span class="hr">variação no dia · {pn.gerado.tz_convert(P.TZ).strftime("%H:%M")}</span>')
    return _CSS + f'<div class="fx">{"".join(partes)}</div>'
