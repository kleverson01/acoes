"""
panorama.py

Panorama de mercado: o placar do contexto externo que pesa sobre o Ibovespa e o
mini índice (WINFUT). É uma leitura de contexto, separada do motor de sinais —
não altera score, filtro nem setup de `daytrade_smc.py`.

Como cada número é calculado (tudo com dados do Yahoo Finance):

    movimento  = variação % do preço atual contra a referência
                 · Diário:  fechamento do pregão anterior
                 · 60 min:  preço de 60 minutos atrás (candles de 5 min)
    z          = movimento ÷ desvio-padrão típico desse ativo no mesmo horizonte
                 (60 pregões para o diário; 5 dias de janelas de 60 min)
    score      = limite(±10) de 5 × z × sentido
                 sentido = +1 se o ativo sobe junto com a bolsa brasileira
                           (S&P, Ibovespa, Petrobras...) e −1 se sobe contra
                           (dólar, DXY, VIX, ouro, juros americanos)
    impacto    = Forte |score| ≥ 7 · Moderado ≥ 4 · Fraco ≥ 1 · Neutro abaixo
    bloco      = média dos scores ponderada pelo peso de cada ativo
    cobertura  = peso dos ativos com dado ÷ peso total do bloco

Usar o desvio típico em vez de uma régua fixa deixa os ativos comparáveis:
+1% no VIX é quase nada, +1% no S&P é um dia forte. Os pesos e sentidos abaixo
são escolhas de contexto (correlação conhecida com a B3), não parâmetros
otimizados — ajuste à vontade.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TZ = "America/Sao_Paulo"


@dataclass(frozen=True)
class Ativo:
    ticker: str
    nome: str
    sentido: int = 1
    peso: float = 1.0


# Ativos acompanhados no diário e no 60 min
ATIVOS = (
    Ativo("^BVSP", "Ibovespa", 1, 2.0),
    Ativo("EWZ", "EWZ (ETF Brasil)", 1, 1.5),
    Ativo("^GSPC", "S&P 500", 1, 1.5),
    Ativo("^IXIC", "Nasdaq", 1, 1.0),
    Ativo("^DJI", "Dow Jones", 1, 0.5),
    Ativo("^NYA", "NYSE Comp.", 1, 0.5),
    Ativo("PETR4.SA", "Petrobras", 1, 1.0),
    Ativo("VALE3.SA", "Vale", 1, 1.0),
    Ativo("BRL=X", "Dólar (USD/BRL)", -1, 1.5),
    Ativo("DX-Y.NYB", "DXY", -1, 1.0),
    Ativo("^VIX", "VIX", -1, 1.0),
    Ativo("BZ=F", "Brent", 1, 0.5),
    Ativo("GC=F", "Ouro", -1, 0.5),
)

# Blocos de contexto medidos só contra o fechamento anterior
FUTUROS = (
    Ativo("ES=F", "S&P Fut", 1, 1.5),
    Ativo("NQ=F", "Nasdaq Fut", 1, 1.0),
    Ativo("YM=F", "Dow Fut", 1, 0.5),
    Ativo("RTY=F", "Russell Fut", 1, 0.5),
)
JUROS = (
    Ativo("^IRX", "Treasury 13 sem.", -1, 0.5),
    Ativo("^FVX", "Treasury 5 anos", -1, 1.0),
    Ativo("^TNX", "Treasury 10 anos", -1, 1.5),
    Ativo("^TYX", "Treasury 30 anos", -1, 0.5),
)
BOLSAS = (
    Ativo("^STOXX50E", "Euro Stoxx 50", 1, 1.5),
    Ativo("^GDAXI", "DAX", 1, 1.0),
    Ativo("^FTSE", "FTSE 100", 1, 0.5),
    Ativo("^N225", "Nikkei", 1, 0.5),
    Ativo("^HSI", "Hang Seng", 1, 1.0),
    Ativo("000001.SS", "Xangai", 1, 0.5),
)

# Peso de cada bloco no placar geral do WINFUT
PESO_BLOCO = {"Diário": 0.30, "60 min": 0.30, "Futuros globais": 0.20, "Curva de juros": 0.10, "Bolsas globais": 0.10}


def todos_tickers() -> list[str]:
    return list(dict.fromkeys(a.ticker for grupo in (ATIVOS, FUTUROS, JUROS, BOLSAS) for a in grupo))


# ------------------------------------------------------------------ régua
def impacto(score: float | None) -> str:
    if score is None or not np.isfinite(score):
        return "Sem base"
    s = abs(score)
    return "Forte" if s >= 7 else "Moderado" if s >= 4 else "Fraco" if s >= 1 else "Neutro"


def leitura(total: float | None) -> str:
    """Texto do placar de um bloco."""
    if total is None or not np.isfinite(total):
        return "Sem dados"
    s = abs(total)
    if s < 1:
        return "Neutro"
    if s < 3:
        return "Misto / atenção"
    lado = "Comprador" if total > 0 else "Vendedor"
    return f"{lado} {'forte' if s >= 6 else 'moderado'}"


def pontuar(mov_pct: float | None, sigma_pct: float | None, sentido: int) -> float | None:
    if mov_pct is None or sigma_pct is None or not np.isfinite(mov_pct) or not sigma_pct or sigma_pct <= 0:
        return None
    return float(np.clip(5.0 * mov_pct / sigma_pct, -10, 10) * sentido)


# ------------------------------------------------------------------ leitura dos dados
@dataclass
class Linha:
    ativo: Ativo
    preco: float | None = None
    ref: float | None = None
    mov: float | None = None
    score: float | None = None
    quando: pd.Timestamp | None = None
    ref_quando: pd.Timestamp | None = None
    aberto: bool = False

    @property
    def impacto(self) -> str:
        return impacto(self.score)


@dataclass
class Bloco:
    nome: str
    linhas: list[Linha] = field(default_factory=list)

    @property
    def total(self) -> float | None:
        ok = [(l.score, l.ativo.peso) for l in self.linhas if l.score is not None]
        if not ok:
            return None
        return float(sum(s * w for s, w in ok) / sum(w for _, w in ok))

    @property
    def cobertura(self) -> float:
        tot = sum(l.ativo.peso for l in self.linhas)
        return 0.0 if not tot else sum(l.ativo.peso for l in self.linhas if l.score is not None) / tot


def _col(df: pd.DataFrame, campo: str, ticker: str, intraday: bool = True) -> pd.Series:
    """Extrai uma série do formato do yf.download (colunas MultiIndex campo/ticker)."""
    if df is None or df.empty:
        return pd.Series(dtype=float)
    try:
        if isinstance(df.columns, pd.MultiIndex):
            lv0 = df.columns.get_level_values(0)
            s = df[(campo, ticker)] if campo in lv0 else df[(ticker, campo)]
        else:
            s = df[campo]
    except KeyError:
        return pd.Series(dtype=float)
    s = pd.to_numeric(s, errors="coerce").dropna()
    if intraday and s.index.tz is None:
        s.index = s.index.tz_localize("UTC")
    if not intraday and s.index.tz is not None:
        # candle diário: a data que vale é a do próprio pregão, sem converter fuso
        s.index = s.index.tz_localize(None)
    return s.sort_index()


def linha_diaria(a: Ativo, diario: pd.DataFrame, intra: pd.DataFrame, agora: pd.Timestamp) -> Linha:
    d = _col(diario, "Close", a.ticker, intraday=False)
    i = _col(intra, "Close", a.ticker)
    ln = Linha(a)
    if len(d) < 3:
        return ln
    # O candle diário do dia corrente (se existir) é parcial: a referência é o último
    # fechamento de um dia ANTERIOR ao do preço atual.
    preco_ts = i.index[-1] if len(i) else d.index[-1]
    preco = float(i.iloc[-1]) if len(i) else float(d.iloc[-1])
    dia_preco = preco_ts.tz_convert(TZ).date() if preco_ts.tz is not None else preco_ts.date()
    anteriores = d[d.index.date < dia_preco] if len(i) else d.iloc[:-1]
    if anteriores.empty:
        return ln
    ref = float(anteriores.iloc[-1])
    sigma = float(anteriores.pct_change().dropna().tail(60).std() * 100)
    ln.preco, ln.ref, ln.quando, ln.ref_quando = preco, ref, preco_ts, anteriores.index[-1]
    ln.mov = (preco / ref - 1) * 100 if ref else None
    ln.score = pontuar(ln.mov, sigma, a.sentido)
    ln.aberto = bool(len(i)) and (agora - preco_ts) <= pd.Timedelta(minutes=45)
    return ln


def linha_60m(a: Ativo, intra: pd.DataFrame, agora: pd.Timestamp) -> Linha:
    i = _col(intra, "Close", a.ticker)
    ln = Linha(a)
    if len(i) < 20:
        return ln
    ts = i.index[-1]
    anteriores = i[i.index <= ts - pd.Timedelta(minutes=60)]
    # A referência precisa ser do mesmo pregão (não comparar com a véspera).
    if anteriores.empty or anteriores.index[-1].tz_convert(TZ).date() != ts.tz_convert(TZ).date():
        ln.preco, ln.quando = float(i.iloc[-1]), ts
        return ln
    ref = float(anteriores.iloc[-1])
    # desvio típico de janelas de 60 min (12 candles de 5 min) nos dias disponíveis
    r60 = (i / i.shift(12) - 1).dropna()
    r60 = r60[[x.tz_convert(TZ).date() == (x - pd.Timedelta(minutes=60)).tz_convert(TZ).date() for x in r60.index]]
    sigma = float(r60.std() * 100) if len(r60) > 20 else None
    ln.preco, ln.ref, ln.quando, ln.ref_quando = float(i.iloc[-1]), ref, ts, anteriores.index[-1]
    ln.mov = (ln.preco / ref - 1) * 100
    ln.score = pontuar(ln.mov, sigma, a.sentido)
    ln.aberto = (agora - ts) <= pd.Timedelta(minutes=45)
    return ln


@dataclass
class Panorama:
    blocos: dict[str, Bloco]
    diario: dict[str, Linha]
    m60: dict[str, Linha]
    gerado: pd.Timestamp

    @property
    def geral(self) -> float | None:
        ok = [(b.total, PESO_BLOCO[n]) for n, b in self.blocos.items() if b.total is not None]
        if not ok:
            return None
        return float(sum(s * w for s, w in ok) / sum(w for _, w in ok))

    @property
    def cobertura(self) -> float:
        return sum(PESO_BLOCO[n] * b.cobertura for n, b in self.blocos.items())


def montar(diario: pd.DataFrame, intra: pd.DataFrame, agora: pd.Timestamp | None = None) -> Panorama:
    agora = agora or pd.Timestamp.now(tz="UTC")
    d = {a.ticker: linha_diaria(a, diario, intra, agora) for a in ATIVOS}
    m = {a.ticker: linha_60m(a, intra, agora) for a in ATIVOS}
    blocos = {
        "Diário": Bloco("Diário", list(d.values())),
        "60 min": Bloco("60 min", list(m.values())),
        "Futuros globais": Bloco("Futuros globais", [linha_diaria(a, diario, intra, agora) for a in FUTUROS]),
        "Curva de juros": Bloco("Curva de juros", [linha_diaria(a, diario, intra, agora) for a in JUROS]),
        "Bolsas globais": Bloco("Bolsas globais", [linha_diaria(a, diario, intra, agora) for a in BOLSAS]),
    }
    return Panorama(blocos, d, m, agora)


def baixar() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Duas chamadas em lote ao Yahoo (diário de 6 meses e 5 min de 5 dias)."""
    import yfinance as yf

    tickers = todos_tickers()
    kw = dict(group_by="column", auto_adjust=False, progress=False, threads=True)
    diario = yf.download(tickers, period="6mo", interval="1d", **kw)
    intra = yf.download(tickers, period="5d", interval="5m", **kw)
    return diario, intra
