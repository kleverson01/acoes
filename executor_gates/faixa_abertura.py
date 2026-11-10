"""Filtro de faixa de abertura (Toby Crabel, "Day Trading with Short Term Price Patterns
and Opening Range Breakout").

Regra validada no backtest (15 ações líquidas, M15, jul–nov/2026, dados Yahoo):
    faixa = máxima e mínima dos candles com abertura entre 10:00 e 10:30 (horário de Brasília);
    COMPRA só se o FECHAMENTO do candle do sinal > máxima da faixa;
    VENDA  só se o FECHAMENTO do candle do sinal < mínima da faixa.
Resultado: executor de −0,051R para −0,015R por operação; VWAP de −0,08R para +0,005R.

Uso no executor (antes do envio, depois dos gates atuais):
    ok, info = checar_faixa(direcao, fechamento_sinal, candle_time_utc, candles_do_dia, cfg)
    if not ok: registrar NO_TRADE com info["motivo"]
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd

TZ = "America/Sao_Paulo"


@dataclass
class FaixaConfig:
    ativo: bool = True
    inicio: time = time(10, 0)       # abertura do pregão de ações
    minutos: int = 30                # duração da faixa
    timeframe_min: int = 15          # timeframe dos candles do sinal (para saber quando o candle FECHA)


def _local(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.tz_convert(TZ)


def calcular_faixa(candles_dia: pd.DataFrame, cfg: FaixaConfig) -> tuple[float, float] | None:
    """candles_dia: candles do ativo no dia (índice = horário de ABERTURA do candle, UTC ou com fuso;
    colunas high/low ou máxima/mínima). Usa só candles que começam dentro da faixa."""
    if candles_dia is None or not len(candles_dia):
        return None
    df = candles_dia.rename(columns={"máxima": "high", "maxima": "high", "mínima": "low", "minima": "low"})
    idx = pd.DatetimeIndex([_local(t) for t in df.index])
    ini = idx.normalize() + pd.Timedelta(hours=cfg.inicio.hour, minutes=cfg.inicio.minute)
    fim = ini + pd.Timedelta(minutes=cfg.minutos)
    m = (idx >= ini) & (idx < fim)
    if not m.any():
        return None
    return float(df.loc[m, "high"].max()), float(df.loc[m, "low"].min())


def checar_faixa(direcao: str, fechamento: float, candle_time, candles_dia: pd.DataFrame,
                 cfg: FaixaConfig | None = None) -> tuple[bool, dict]:
    """direcao: 'COMPRA' | 'VENDA'. candle_time: abertura do candle do sinal (UTC, como na tabela signals).
    Devolve (pode_entrar, info) com info = {motivo, faixa_max, faixa_min, posicao_faixa}."""
    cfg = cfg or FaixaConfig()
    info = {"motivo": "", "faixa_max": None, "faixa_min": None, "posicao_faixa": None}
    if not cfg.ativo:
        return True, info
    t_abre = _local(candle_time)
    t_fecha = t_abre + pd.Timedelta(minutes=cfg.timeframe_min)
    fim_faixa = t_abre.normalize() + pd.Timedelta(hours=cfg.inicio.hour, minutes=cfg.inicio.minute + cfg.minutos)
    if t_fecha < fim_faixa:                     # o candle do sinal fecha antes de a faixa terminar
        info["motivo"] = "FAIXA_ABERTURA_NAO_FORMADA"
        return False, info
    # só candles do mesmo dia e já fechados até o fim da faixa
    dia = candles_dia[[(_local(t).date() == t_abre.date()) for t in candles_dia.index]] if len(candles_dia) else candles_dia
    fx = calcular_faixa(dia, cfg)
    if fx is None:
        info["motivo"] = "FAIXA_ABERTURA_SEM_DADOS"
        return False, info
    hi, lo = fx
    info["faixa_max"], info["faixa_min"] = hi, lo
    pos = "ACIMA" if fechamento > hi else ("ABAIXO" if fechamento < lo else "DENTRO")
    info["posicao_faixa"] = pos
    d = str(direcao).upper()
    if (d == "COMPRA" and pos == "ACIMA") or (d == "VENDA" and pos == "ABAIXO"):
        return True, info
    info["motivo"] = "DENTRO_DA_FAIXA" if pos == "DENTRO" else "CONTRA_A_FAIXA"
    return False, info
