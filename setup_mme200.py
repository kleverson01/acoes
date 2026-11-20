"""
setup_mme200.py

Setup "Rejeição na MME200 após movimento brusco" (M15, metas em % do preço).

Hipótese: uma subida brusca que toca a MME200 por baixo tende a corrigir (venda);
uma queda brusca que toca a MME200 por cima tende a repicar (compra).

Regras (validadas em Python com dados de 5 min da B3, jul–nov/2026, 10 ações mais
líquidas, últimos 60 pregões: 23 operações, 87% bateram o alvo, +0,33% líquido por
operação contra 54% / −0,16% com direção sorteada). Amostra pequena: tratar como
setup em validação.

  impulso  : Close − Close[N] ≥ K·ATR(14) (subida) ou ≤ −K·ATR (queda); N = 8 candles (2 h), K = 2
  origem   : Close[N] estava do outro lado da MME200 por mais de 0,5·ATR
  toque    : máxima ≥ MME200 (venda) / mínima ≤ MME200 (compra)
  rejeição : o candle do toque fecha de volta do lado de origem
  gatilho  : rompimento da mínima (venda) / máxima (compra) do candle do toque, válido por 2 candles
  alvo     : 0,5% a partir da entrada; stop de proteção: 2,5%
  janela   : entradas 10:30–16:00; zeragem 17:30 (ou último candle do dia); uma posição por ativo
  repetição: só o primeiro toque de cada sequência conta (toques a menos de 3 candles do anterior são
             ignorados) e ele próprio precisa ter rejeição

Nada aqui altera o motor de sinais (daytrade_smc.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TZ = "America/Sao_Paulo"
TOP10_LIQUIDAS = ["PETR4", "VALE3", "ITUB4", "BBDC4", "B3SA3", "AXIA3", "BBAS3", "PRIO3", "ABEV3", "RENT3"]


@dataclass(frozen=True)
class ConfigMME200:
    periodo_ema: int = 200
    n_impulso: int = 8
    k_atr: float = 2.0
    origem_atr: float = 0.5
    exigir_rejeicao: bool = True
    validade_gatilho: int = 2
    atr_periodo: int = 14
    alvo_pct: float = 0.5
    stop_pct: float = 2.5
    hora_inicio: float = 10.5
    hora_fim_entradas: float = 16.0
    hora_zeragem: float = 17.5
    tick: float = 0.01
    custo_pct: float = 0.08          # ida + volta (taxas + 1 tick de deslizamento)
    ifr_minimo: float | None = None  # ex.: 70 → venda só com IFR ≥ 70, compra só com IFR ≤ 30
    volume_minimo: float | None = None  # ex.: 1,5 → volume do toque ≥ 1,5× média dos 20 anteriores


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _atr(f: pd.DataFrame, n: int) -> pd.Series:
    tr = pd.concat([f.high - f.low, (f.high - f.close.shift()).abs(), (f.low - f.close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _ifr(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    """Candles M15 no fuso de Brasília, só o pregão (10:00–17:55), sem candles zerados."""
    f = df.copy()
    f.index = f.index.tz_convert(TZ) if f.index.tz is not None else f.index.tz_localize(TZ)
    t = f.index.time
    f = f[(t >= pd.Timestamp("10:00").time()) & (t < pd.Timestamp("17:55").time()) & (f["close"] > 0)]
    return f[["open", "high", "low", "close", "volume"]].astype(float)


def toques(f: pd.DataFrame, cfg: ConfigMME200 = ConfigMME200()) -> pd.DataFrame:
    """Uma linha por candle com as colunas usadas pelo setup e a direção do toque (−1 venda, +1 compra, 0 nada)."""
    c, h, l = f.close, f.high, f.low
    e = _ema(c, cfg.periodo_ema)
    a = _atr(f, cfg.atr_periodo)
    n = cfg.n_impulso
    imp = (c - c.shift(n)) / a
    ant = c.shift(n) - e.shift(n)
    venda = (ant < -cfg.origem_atr * a) & (imp >= cfg.k_atr) & (h >= e)
    compra = (ant > cfg.origem_atr * a) & (imp <= -cfg.k_atr) & (l <= e)
    bruto = np.where(venda, -1, np.where(compra, 1, 0))      # qualquer toque após impulso (antes dos filtros)
    if cfg.exigir_rejeicao:
        venda &= c < e
        compra &= c > e
    if cfg.ifr_minimo is not None:
        r = _ifr(c)
        venda &= r >= cfg.ifr_minimo
        compra &= r <= 100 - cfg.ifr_minimo
    if cfg.volume_minimo is not None:
        vm = f.volume.rolling(20).mean().shift(1)
        ok = f.volume >= cfg.volume_minimo * vm
        venda &= ok
        compra &= ok
    out = pd.DataFrame({"mme200": e, "atr": a, "impulso_atr": imp, "toque": bruto,
                        "dir": np.where(venda, -1, np.where(compra, 1, 0))}, index=f.index)
    out.iloc[: cfg.periodo_ema, out.columns.get_loc("dir")] = 0   # aquecimento da média
    out.iloc[: cfg.periodo_ema, out.columns.get_loc("toque")] = 0
    return out


def backtest(df: pd.DataFrame, cfg: ConfigMME200 = ConfigMME200(), ativo: str = "") -> pd.DataFrame:
    """Simula o setup candle a candle (sem olhar o futuro). Uma posição por ativo.
    Execução: gatilho = ordem stop (preenche no gatilho ou na abertura, se abrir além);
    stop e alvo no mesmo candle → conta o stop (conservador); zeragem na abertura do
    primeiro candle a partir de `hora_zeragem` ou no fechamento do último candle do dia."""
    f = preparar(df)
    if len(f) < cfg.periodo_ema + cfg.n_impulso + 5:
        return pd.DataFrame()
    tq = toques(f, cfg)
    O, H, L, C = (f[k].to_numpy() for k in ("open", "high", "low", "close"))
    dia = np.array(f.index.date)
    hora = (f.index.hour + f.index.minute / 60).to_numpy()
    d_all = tq["dir"].to_numpy()
    toque = tq["toque"].to_numpy()
    n = len(f)
    rows = []
    livre = -1
    ult_toque = -99
    for t in np.nonzero(toque)[0]:
        if not (cfg.hora_inicio <= hora[t] < cfg.hora_fim_entradas) or t + 1 >= n or dia[t + 1] != dia[t]:
            continue
        # vale só o PRIMEIRO toque de cada sequência (toques a menos de 3 candles do anterior são repetição),
        # e esse primeiro toque precisa passar nos filtros (rejeição etc.)
        if t - ult_toque < 3:
            continue
        ult_toque = t
        d = int(d_all[t])
        if d == 0 or t <= livre:
            continue
        ent = None
        trg = L[t] - cfg.tick if d == -1 else H[t] + cfg.tick
        for j in range(t + 1, min(t + 1 + cfg.validade_gatilho, n)):
            if dia[j] != dia[t] or hora[j] >= cfg.hora_zeragem:
                break
            if (L[j] <= trg) if d == -1 else (H[j] >= trg):
                ent = min(O[j], trg) if d == -1 else max(O[j], trg)
                break
        if ent is None:
            continue
        alvo = ent * (1 + d * cfg.alvo_pct / 100)
        stop = ent * (1 - d * cfg.stop_pct / 100)
        k = j
        while True:
            if (H[k] >= stop) if d == -1 else (L[k] <= stop):
                px = (max(stop, O[k]) if d == -1 else min(stop, O[k])) if k > j else stop
                como = "STOP"
                break
            if (L[k] <= alvo) if d == -1 else (H[k] >= alvo):
                px, como = alvo, "ALVO"
                break
            fim_dia = k + 1 >= n or dia[k + 1] != dia[j]
            if not fim_dia and hora[k + 1] >= cfg.hora_zeragem:
                px, como = O[k + 1], "ZERAGEM"
                k += 1
                break
            if fim_dia:
                px, como = C[k], "ZERAGEM"
                break
            k += 1
        bruto = (px - ent) * d / ent * 100
        rows.append({
            "Ativo": ativo, "Dia": dia[t], "Toque": f.index[t].strftime("%H:%M"), "Entrada às": f.index[j].strftime("%H:%M"),
            "Direção": "VENDA" if d == -1 else "COMPRA", "Entrada": round(ent, 2), "Alvo": round(alvo, 2), "Stop": round(stop, 2),
            "Saída": round(px, 2), "Saída às": f.index[k].strftime("%H:%M"), "Resultado": como,
            "Resultado %": round(bruto - cfg.custo_pct, 3), "MME200": round(tq["mme200"].iat[t], 2),
            "Impulso (ATR)": round(abs(tq["impulso_atr"].iat[t]), 1),
        })
        livre = k
    return pd.DataFrame(rows)


@dataclass
class Situacao:
    ativo: str
    estado: str                       # "SEM SINAL", "GATILHO ARMADO", "EM OPERAÇÃO", "ENCERRADA HOJE"
    direcao: str = ""
    gatilho: float | None = None
    alvo: float | None = None
    stop: float | None = None
    preco: float | None = None
    mme200: float | None = None
    detalhe: str = ""
    extras: dict = field(default_factory=dict)


def situacao_atual(df: pd.DataFrame, cfg: ConfigMME200 = ConfigMME200(), ativo: str = "") -> Situacao:
    """Leitura ao vivo: há gatilho armado (toque nos últimos candles), operação aberta ou nada?"""
    f = preparar(df)
    if len(f) < cfg.periodo_ema + cfg.n_impulso + 5:
        return Situacao(ativo, "SEM DADOS", detalhe="Histórico curto para a MME200.")
    tq = toques(f, cfg)
    preco = float(f.close.iat[-1])
    mme = float(tq["mme200"].iat[-1])
    hoje = f.index[-1].date()
    trades = backtest(df, cfg, ativo)
    if len(trades):
        ult = trades.iloc[-1]
        if ult["Dia"] == hoje:
            aberta = ult["Saída às"] == f.index[-1].strftime("%H:%M") and ult["Resultado"] == "ZERAGEM" \
                and (f.index[-1].hour + f.index[-1].minute / 60) < cfg.hora_zeragem
            if aberta:
                return Situacao(ativo, "EM OPERAÇÃO", ult["Direção"], ult["Entrada"], ult["Alvo"], ult["Stop"], preco, mme,
                                f"Entrou às {ult['Entrada às']}; agora {(preco - ult['Entrada']) / ult['Entrada'] * 100 * (1 if ult['Direção'] == 'COMPRA' else -1):+.2f}%.")
            return Situacao(ativo, "ENCERRADA HOJE", ult["Direção"], ult["Entrada"], ult["Alvo"], ult["Stop"], preco, mme,
                            f"{ult['Resultado']} às {ult['Saída às']} ({ult['Resultado %']:+.2f}% líquido).")
    # toque recente ainda dentro da validade do gatilho?
    d_all = tq["dir"].to_numpy()
    hora_ult = f.index[-1].hour + f.index[-1].minute / 60
    for back in range(0, cfg.validade_gatilho):
        t = len(f) - 1 - back
        if t < 0 or f.index[t].date() != hoje:
            break
        d = int(d_all[t])
        hora_t = f.index[t].hour + f.index[t].minute / 60
        if d != 0 and cfg.hora_inicio <= hora_t < cfg.hora_fim_entradas and hora_ult < cfg.hora_zeragem:
            trg = f.low.iat[t] - cfg.tick if d == -1 else f.high.iat[t] + cfg.tick
            return Situacao(ativo, "GATILHO ARMADO", "VENDA" if d == -1 else "COMPRA", round(trg, 2),
                            round(trg * (1 + d * cfg.alvo_pct / 100), 2), round(trg * (1 - d * cfg.stop_pct / 100), 2), preco, mme,
                            f"Toque na MME200 às {f.index[t].strftime('%H:%M')}; vale por mais {cfg.validade_gatilho - back} candle(s).")
    dist = (preco / mme - 1) * 100
    return Situacao(ativo, "SEM SINAL", preco=preco, mme200=mme, detalhe=f"Preço {dist:+.2f}% da MME200.")


def resumo(trades: pd.DataFrame) -> dict:
    if trades is None or trades.empty:
        return {"operações": 0}
    r = trades["Resultado %"]
    return {
        "operações": int(len(trades)),
        "bateram o alvo %": round((trades["Resultado"] == "ALVO").mean() * 100, 1),
        "no lucro %": round((r > 0).mean() * 100, 1),
        "ganho médio %": round(r.mean(), 3),
        "soma %": round(r.sum(), 2),
        "pior %": round(r.min(), 2),
        "stops": int((trades["Resultado"] == "STOP").sum()),
        "zeradas": int((trades["Resultado"] == "ZERAGEM").sum()),
    }
