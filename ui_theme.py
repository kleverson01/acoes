"""
ui_theme.py

Camada visual do Terminal SMC. Só aparência: nenhuma função aqui decide
sinal, score ou filtro — isso continua 100% em `daytrade_smc.py`.

Ideia do desenho: cada bloco é uma "placa" com espessura (borda de luz em
cima, borda escura embaixo e sombra projetada), como teclas e placas de uma
mesa de operação. Os botões afundam ao clicar. A placa do topo fica
levemente inclinada em perspectiva — é o único elemento "chamativo"; o
resto é sóbrio para não competir com o gráfico.
"""

from __future__ import annotations

import html

import streamlit as st

# ---------------------------------------------------------------- paleta
INK = "#0e1726"        # fundo
SLAB = "#16233a"       # placa
SLAB_UP = "#1d2e4a"    # placa elevada
EDGE = "#0a111d"       # espessura (lado de baixo da placa)
TEXT = "#e6edf6"
MUTED = "#8a9bb4"
BUY = "#2ed3a3"
SELL = "#ff5470"
GOLD = "#f0b429"
STEEL = "#5b8cff"      # interação (foco, botão primário)

FONT_HEAD = "Sora"
FONT_BODY = "Manrope"

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Sora:wght@500;600;700;800&display=swap');
:root {{
  --ink:{INK}; --slab:{SLAB}; --slab-up:{SLAB_UP}; --edge:{EDGE};
  --text:{TEXT}; --muted:{MUTED}; --buy:{BUY}; --sell:{SELL}; --gold:{GOLD}; --steel:{STEEL};
  --hl: rgba(255,255,255,.07);
  --depth: 0 1px 0 var(--hl) inset, 0 5px 0 var(--edge), 0 16px 28px rgba(0,0,0,.45);
  --depth-lo: 0 1px 0 var(--hl) inset, 0 2px 0 var(--edge), 0 6px 12px rgba(0,0,0,.35);
}}
html, body, .stApp, [data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(1200px 600px at 85% -10%, rgba(91,140,255,.10), transparent 60%),
    radial-gradient(900px 500px at -10% 110%, rgba(46,211,163,.06), transparent 60%),
    var(--ink) !important;
  color: var(--text);
  font-family: '{FONT_BODY}', system-ui, sans-serif;
  font-variant-numeric: tabular-nums;
}}
[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 1.6rem; max-width: 1480px; }}
h1, h2, h3, h4 {{ font-family: '{FONT_HEAD}', sans-serif !important; letter-spacing: -.01em; color: var(--text); }}
h3 {{ font-size: 1.15rem !important; font-weight: 700 !important; margin-top: .6rem; }}
h4 {{ font-size: 1rem !important; font-weight: 600 !important; }}
p, li, label, .stMarkdown {{ font-family: '{FONT_BODY}', sans-serif; }}
[data-testid="stCaptionContainer"], .stCaption {{ color: var(--muted) !important; }}
/* ------------------------------------------------ sidebar */
[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, #121e31 0%, #0c1522 100%) !important;
  border-right: 1px solid rgba(255,255,255,.05);
  box-shadow: 8px 0 24px rgba(0,0,0,.35);
}}
[data-testid="stSidebar"] h3 {{
  font-size: .82rem !important; color: var(--muted); font-weight: 600 !important;
  margin: 1.1rem 0 .35rem; padding-top: .9rem; border-top: 1px solid rgba(255,255,255,.06);
}}
.side-brand {{ display:flex; align-items:center; gap:.7rem; margin-bottom:.4rem; }}
.side-brand .cube {{
  width:38px; height:38px; border-radius:10px; flex:none;
  background: linear-gradient(145deg, var(--steel), #3a5fd0);
  box-shadow: 0 1px 0 rgba(255,255,255,.35) inset, 0 4px 0 #24408f, 0 10px 18px rgba(0,0,0,.45);
  display:grid; place-items:center; font: 800 15px '{FONT_HEAD}', system-ui, sans-serif; color:#fff;
}}
.side-brand b {{ font: 700 1.05rem '{FONT_HEAD}', system-ui, sans-serif; color: var(--text); display:block; }}
.side-brand span {{ font-size:.78rem; color: var(--muted); }}
/* opções do menu lateral viram teclas: a marcada fica elevada */
[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 6px !important; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{
  margin: 0 !important; padding: 7px 10px !important; border-radius: 10px;
  background: rgba(0,0,0,.18); box-shadow: 0 1px 2px rgba(0,0,0,.35) inset;
}}
[data-testid="stSidebar"] [role="radiogroup"][aria-orientation="vertical"] > div, [data-testid="stSidebar"] [role="radiogroup"][aria-orientation="vertical"] label {{ width: 100%; }}
[data-testid="stSidebar"] [role="radiogroup"] label[data-selected="true"],
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
  background: linear-gradient(180deg, var(--slab-up), var(--slab)); box-shadow: var(--depth-lo);
}}
[data-testid="stSidebar"] [role="radiogroup"] label[data-selected="true"] p,
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{ color: var(--text); font-weight: 700; }}
/* ------------------------------------------------ placas genéricas */
.slab {{
  background: linear-gradient(180deg, var(--slab-up), var(--slab));
  border-radius: 16px; padding: 16px 18px; box-shadow: var(--depth);
  margin: 4px 0 18px;
}}
.slab.tone {{ border-left: 4px solid var(--tone); }}
.slab .t {{ font: 700 .98rem '{FONT_HEAD}', system-ui, sans-serif; color: var(--tone, var(--text)); }}
.slab .d {{ color: var(--text); opacity:.85; font-size:.9rem; margin-top:.2rem; }}
/* metric do streamlit vira bloco com espessura */
[data-testid="stMetric"] {{
  background: linear-gradient(180deg, var(--slab-up), var(--slab));
  border-radius: 14px; padding: 12px 14px 10px; box-shadow: var(--depth-lo);
}}
[data-testid="stMetricLabel"] p {{ color: var(--muted) !important; font-size:.78rem !important; font-weight:600; }}
[data-testid="stMetricValue"] {{ font-family:'{FONT_HEAD}', system-ui, sans-serif !important; font-weight:700; font-size:1.45rem !important; }}
/* ------------------------------------------------ botões = teclas */
.stButton > button, .stDownloadButton > button {{
  border-radius: 12px !important; border: 0 !important; font-weight: 700 !important;
  background: linear-gradient(180deg, #24385a, #1b2b46) !important; color: var(--text) !important;
  box-shadow: 0 1px 0 rgba(255,255,255,.1) inset, 0 4px 0 var(--edge), 0 8px 14px rgba(0,0,0,.35) !important;
  transform: translateY(0); transition: transform .08s ease, box-shadow .08s ease;
}}
.stButton > button[kind="primary"] {{
  background: linear-gradient(180deg, #6d99ff, var(--steel)) !important; color:#fff !important;
  box-shadow: 0 1px 0 rgba(255,255,255,.35) inset, 0 4px 0 #2c4fb5, 0 10px 18px rgba(40,80,200,.35) !important;
}}
.stButton > button:active {{ transform: translateY(3px); box-shadow: 0 1px 0 rgba(255,255,255,.1) inset, 0 1px 0 var(--edge), 0 3px 6px rgba(0,0,0,.35) !important; }}
.stButton > button:focus-visible {{ outline: 2px solid var(--steel) !important; outline-offset: 3px; }}
/* abas = fileira de teclas */
[role="tablist"] {{
  gap: 6px !important; background: rgba(0,0,0,.22); padding: 6px; border-radius: 14px;
  box-shadow: 0 2px 6px rgba(0,0,0,.4) inset; border: 0 !important; width: fit-content; max-width: 100%;
}}
[role="tab"] {{
  border-radius: 10px !important; padding: 6px 14px !important; height: auto !important; color: var(--muted);
  border: 0 !important;
}}
[role="tab"] p {{ font-weight: 600; }}
[role="tab"][aria-selected="true"] {{
  background: linear-gradient(180deg, var(--slab-up), var(--slab)); color: var(--text) !important;
  box-shadow: var(--depth-lo);
}}
[role="tab"]:focus-visible {{ outline: 2px solid var(--steel); outline-offset: 2px; }}
.react-aria-SelectionIndicator, [data-baseweb="tab-highlight"], [data-baseweb="tab-border"] {{ display:none !important; }}
/* tabelas, gráficos, expanders, alertas */
[data-testid="stDataFrame"], [data-testid="stPlotlyChart"] {{
  border-radius: 16px; overflow: hidden; box-shadow: var(--depth);
  background: var(--slab);
}}
[data-testid="stPlotlyChart"] {{ padding: 6px; }}
[data-testid="stExpander"] {{ border: 0 !important; border-radius: 14px; background: var(--slab); box-shadow: var(--depth-lo); }}
[data-testid="stAlert"] {{ border-radius: 14px; box-shadow: var(--depth-lo); }}
[data-baseweb="select"] > div, [data-baseweb="input"] > div, .stNumberInput input, .stTextInput input {{ border-radius: 10px !important; }}
/* ------------------------------------------------ placa do topo (perspectiva) */
.hero-wrap {{ perspective: 1400px; margin: 0 0 22px; }}
.hero {{
  transform: rotateX(7deg); transform-origin: 50% 100%;
  background:
    linear-gradient(115deg, rgba(91,140,255,.16), transparent 45%),
    linear-gradient(180deg, #213456, #182740);
  border-radius: 22px; padding: 22px 26px 20px;
  box-shadow: 0 1px 0 rgba(255,255,255,.12) inset, 0 9px 0 #0b1424, 0 30px 46px rgba(0,0,0,.55);
  display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 18px; align-items: center;
  animation: rise .55s cubic-bezier(.2,.7,.2,1) both;
}}
@keyframes rise {{ from {{ opacity:0; transform: rotateX(28deg) translateY(16px); }} to {{ opacity:1; transform: rotateX(7deg); }} }}
.hero h1 {{ font: 800 clamp(1.5rem, 2.6vw, 2.2rem)/1.05 '{FONT_HEAD}', system-ui, sans-serif !important; margin: 0 !important; padding:0 !important; }}
.hero .sub {{ color: var(--muted); margin-top: 6px; font-size: .95rem; }}
.chips {{ display:flex; flex-wrap:wrap; gap:10px; justify-content:flex-end; }}
.chip {{
  display:flex; align-items:center; gap:8px; padding: 9px 14px; border-radius: 12px;
  background: rgba(8,14,24,.55); font-weight: 600; font-size:.86rem; color: var(--text);
  box-shadow: 0 1px 0 rgba(255,255,255,.06) inset, 0 3px 0 rgba(0,0,0,.45);
}}
.chip i {{ width:9px; height:9px; border-radius:50%; background: var(--c); box-shadow: 0 0 0 3px color-mix(in srgb, var(--c) 25%, transparent), 0 0 12px var(--c); }}
.delay {{ grid-column: 1 / -1; font-size:.82rem; color: #c9b27a; border-top: 1px solid rgba(255,255,255,.07); padding-top: 10px; }}
.delay b {{ color: var(--gold); }}
/* ------------------------------------------------ bilhete do sinal */
.ticket {{
  display:grid; grid-template-columns: auto minmax(0,1fr) auto; gap: 18px; align-items:center;
  background: linear-gradient(180deg, var(--slab-up), var(--slab));
  border-radius: 18px; padding: 16px 20px; box-shadow: var(--depth); margin: 6px 0 16px;
  border-top: 3px solid var(--tone);
}}
.ticket.gold {{ box-shadow: var(--depth), 0 0 0 1px rgba(240,180,41,.55), 0 0 28px rgba(240,180,41,.18); }}
.dir {{
  font: 800 1.05rem '{FONT_HEAD}', system-ui, sans-serif; color: #08121f; background: var(--tone);
  padding: 12px 16px; border-radius: 12px; min-width: 96px; text-align:center;
  box-shadow: 0 1px 0 rgba(255,255,255,.45) inset, 0 4px 0 color-mix(in srgb, var(--tone) 55%, #000), 0 10px 18px rgba(0,0,0,.4);
}}
.dir.neutral {{ color: var(--text); }}
.ticket .setup {{ font: 700 1.05rem '{FONT_HEAD}', system-ui, sans-serif; }}
.ticket .line {{ color: var(--muted); font-size: .9rem; margin-top: 3px; }}
.ticket .line b {{ color: var(--text); }}
.ring {{
  --p: 0; width: 74px; height: 74px; border-radius: 50%; display:grid; place-items:center;
  background: conic-gradient(var(--tone) calc(var(--p) * 1%), rgba(255,255,255,.07) 0);
  box-shadow: 0 6px 14px rgba(0,0,0,.45);
}}
.ring span {{
  width: 56px; height: 56px; border-radius: 50%; background: var(--slab); display:grid; place-items:center;
  font: 800 1.05rem '{FONT_HEAD}', system-ui, sans-serif; box-shadow: 0 2px 4px rgba(0,0,0,.5) inset;
}}
.ring small {{ display:block; font: 600 .62rem '{FONT_BODY}', system-ui, sans-serif; color: var(--muted); margin-top:-4px; }}
.qual {{ font-size:.8rem; color: var(--muted); text-align:center; margin-top:4px; }}
/* ------------------------------------------------ cartões de destaque (top 3) */
.podium {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; margin: 6px 0 20px; }}
.pcard {{
  background: linear-gradient(180deg, var(--slab-up), var(--slab)); border-radius: 16px; padding: 14px 16px;
  box-shadow: var(--depth); border-top: 3px solid var(--tone);
}}
.pcard .top {{ display:flex; justify-content:space-between; align-items:baseline; }}
.pcard .sym {{ font: 800 1.25rem '{FONT_HEAD}', system-ui, sans-serif; }}
.pcard .sc {{ font: 700 1rem '{FONT_HEAD}', system-ui, sans-serif; color: var(--tone); }}
.pcard .meta {{ color: var(--muted); font-size: .84rem; margin: 2px 0 10px; }}
.pcard .lv {{ display:grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }}
.pcard .lv div {{ background: rgba(0,0,0,.22); border-radius: 9px; padding: 6px 8px; box-shadow: 0 1px 3px rgba(0,0,0,.4) inset; }}
.pcard .lv small {{ display:block; color: var(--muted); font-size: .7rem; }}
.pcard .lv b {{ font-size: .92rem; }}
@media (max-width: 760px) {{
  .hero {{ grid-template-columns: 1fr; transform: none; animation: none; }}
  .chips {{ justify-content: flex-start; }}
  .ticket {{ grid-template-columns: 1fr auto; }}
  .ticket .dir {{ grid-column: 1 / -1; }}
}}
@media (prefers-reduced-motion: reduce) {{
  .hero {{ animation: none; }}
  .stButton > button {{ transition: none; }}
}}
</style>
"""


def inject() -> None:
    """Injeta fonte e CSS uma vez por rerun (barato; o navegador cacheia a fonte)."""
    st.markdown(_CSS, unsafe_allow_html=True)


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def tone_for(direction_value: str) -> str:
    return {"COMPRA": BUY, "VENDA": SELL}.get(direction_value, MUTED)


def sidebar_brand() -> None:
    st.markdown(
        '<div class="side-brand"><div class="cube">SMC</div>'
        '<div><b>Day Trade SMC</b><span>Leitura técnica da B3</span></div></div>',
        unsafe_allow_html=True,
    )


def hero(title: str, subtitle: str, chips: list[tuple[str, str]], delay_note: bool) -> None:
    """chips: lista de (texto, cor) — a bolinha usa a cor para indicar estado."""
    chip_html = "".join(f'<div class="chip" style="--c:{c}"><i></i>{esc(t)}</div>' for t, c in chips)
    delay = (
        '<div class="delay">Yahoo Finance chega com <b>15 a 20 minutos de atraso</b>. Use para viés e estrutura; '
        'confirme o preço no ProfitChart ou na corretora antes de executar.</div>'
        if delay_note else ""
    )
    st.markdown(
        f'<div class="hero-wrap"><div class="hero"><div><h1>{esc(title)}</h1>'
        f'<div class="sub">{esc(subtitle)}</div></div><div class="chips">{chip_html}</div>{delay}</div></div>',
        unsafe_allow_html=True,
    )


def banner(title: str, detail: str = "", tone: str = MUTED) -> None:
    """Placa com faixa colorida à esquerda (substitui os <div> com borda soltos)."""
    st.markdown(
        f'<div class="slab tone" style="--tone:{tone}"><div class="t">{title}</div>'
        + (f'<div class="d">{detail}</div>' if detail else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def ticket(direction_value: str, setup: str, line_html: str, score: float, quality_label: str, exceptional: bool) -> None:
    tone = tone_for(direction_value)
    dir_cls = "dir" if direction_value in ("COMPRA", "VENDA") else "dir neutral"
    dir_style = "" if direction_value in ("COMPRA", "VENDA") else "background:#2a3a55"
    st.markdown(
        f'<div class="ticket{" gold" if exceptional else ""}" style="--tone:{GOLD if exceptional else tone}">'
        f'<div class="{dir_cls}" style="{dir_style}">{esc(direction_value)}</div>'
        f'<div><div class="setup">{"🌟 " if exceptional else ""}{esc(setup)}</div><div class="line">{line_html}</div></div>'
        f'<div><div class="ring" style="--p:{max(0.0, min(100.0, score)):.0f}"><span><div>{score:.0f}<small>/100</small></div></span></div>'
        f'<div class="qual">{esc(quality_label.capitalize())}</div></div></div>',
        unsafe_allow_html=True,
    )


def podium(rows: list[dict]) -> None:
    """rows: dicts com ativo, direcao, score, meta, entrada, stop, alvo."""
    if not rows:
        return
    cards = []
    for r in rows:
        tone = tone_for(r["direcao"])
        def fmt(v):
            return "—" if v is None or v != v else f"{v:.2f}"
        cards.append(
            f'<div class="pcard" style="--tone:{tone}"><div class="top"><span class="sym">{esc(r["ativo"])}</span>'
            f'<span class="sc">{esc(r["direcao"])} {r["score"]:.0f}</span></div>'
            f'<div class="meta">{esc(r["meta"])}</div><div class="lv">'
            f'<div><small>Entrada</small><b>{fmt(r["entrada"])}</b></div>'
            f'<div><small>Stop</small><b style="color:{SELL}">{fmt(r["stop"])}</b></div>'
            f'<div><small>Alvo 1</small><b style="color:{BUY}">{fmt(r["alvo"])}</b></div></div></div>'
        )
    st.markdown(f'<div class="podium">{"".join(cards)}</div>', unsafe_allow_html=True)


def style_figure(fig) -> None:
    """Aplica o tema da placa ao gráfico plotly (fundo, grade, fonte)."""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=SLAB, plot_bgcolor=SLAB,
        font=dict(family=f"{FONT_BODY}, sans-serif", size=11, color=MUTED),
        hoverlabel=dict(bgcolor=SLAB_UP, bordercolor=STEEL, font=dict(family=FONT_BODY, color=TEXT)),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0, bgcolor="rgba(0,0,0,0)"),
    )
    grid = dict(gridcolor="rgba(255,255,255,.05)", zeroline=False, linecolor="rgba(255,255,255,.08)")
    fig.update_xaxes(**grid)
    fig.update_yaxes(**grid, side="right")
