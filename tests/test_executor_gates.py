"""Testes dos gates novos do executor. Rodar: python tests/test_executor_gates.py"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from executor_gates import FaixaConfig, RebaixamentoConfig, avaliar_modo, calcular_faixa, checar_faixa, score_minimo  # noqa: E402

ok = []


def check(nome, cond):
    assert cond, f"FALHOU: {nome}"
    ok.append(nome)


def dia(precos, data="2026-11-10"):
    """candles M15 a partir das 10:00 de Brasília; índice em UTC (como a tabela signals)."""
    idx = pd.date_range(f"{data} 10:00", periods=len(precos), freq="15min", tz="America/Sao_Paulo").tz_convert("UTC")
    return pd.DataFrame(precos, columns=["open", "high", "low", "close"], index=idx)


C = dia([(10, 10.20, 9.90, 10.1), (10.1, 10.30, 10.0, 10.2), (10.2, 10.5, 10.15, 10.45), (10.45, 10.5, 9.7, 9.8)])
cfg = FaixaConfig()

check("faixa = máx/mín dos candles 10:00 e 10:15", calcular_faixa(C, cfg) == (10.30, 9.90))
okk, inf = checar_faixa("COMPRA", 10.2, C.index[1], C.iloc[:2], cfg)
check("sinal no candle 10:15 (fecha 10:30) com faixa completa é avaliado", inf["motivo"] in ("DENTRO_DA_FAIXA", "") and inf["faixa_max"] == 10.30)
okk, inf = checar_faixa("COMPRA", 10.1, C.index[0], C.iloc[:1], cfg)
check("sinal no candle 10:00 → FAIXA_ABERTURA_NAO_FORMADA", not okk and inf["motivo"] == "FAIXA_ABERTURA_NAO_FORMADA")
okk, inf = checar_faixa("COMPRA", 10.45, C.index[2], C.iloc[:3], cfg)
check("compra com fechamento acima da faixa → entra", okk and inf["posicao_faixa"] == "ACIMA")
okk, inf = checar_faixa("COMPRA", 10.2, C.index[2], C.iloc[:3], cfg)
check("compra dentro da faixa → DENTRO_DA_FAIXA", not okk and inf["motivo"] == "DENTRO_DA_FAIXA")
okk, inf = checar_faixa("VENDA", 9.8, C.index[3], C, cfg)
check("venda abaixo da faixa → entra", okk and inf["posicao_faixa"] == "ABAIXO")
okk, inf = checar_faixa("VENDA", 10.45, C.index[2], C.iloc[:3], cfg)
check("venda acima da faixa → CONTRA_A_FAIXA", not okk and inf["motivo"] == "CONTRA_A_FAIXA")
okk, inf = checar_faixa("COMPRA", 10.2, C.index[2], C.iloc[:3], FaixaConfig(ativo=False))
check("filtro desligado não bloqueia", okk)
# candles de outro dia não contaminam a faixa
prev = dia([(9, 20, 1, 9)], data="2026-11-09")
okk, inf = checar_faixa("COMPRA", 10.45, C.index[2], pd.concat([prev, C.iloc[:3]]), cfg)
check("candles do dia anterior são ignorados", okk and inf["faixa_max"] == 10.30)

check("VWAP 70 com faixa ligada", score_minimo("VWAP", True, True) == 70)
check("VWAP sem faixa volta ao corte global 80", score_minimo("VWAP", True, False) == 80)
check("Confluência continua 80/85", score_minimo("Confluência", True, True) == 80 and score_minimo("Confluência", False, True) == 85)
check("SMC/Médias/PA continuam 80", all(score_minimo(m, True, True) == 80 for m in ("SMC", "Médias Móveis", "Price Action")))

rc = RebaixamentoConfig(ativo=True, janela=100)
check("rebaixamento desligado por padrão", avaliar_modo("PAPER", [-1.0] * 200, RebaixamentoConfig())[0] == "PAPER")
check("prejuízo claro → SHADOW", avaliar_modo("PAPER", [-1.0, 0.5] * 50, rc)[0] == "SHADOW")
check("SHADOW com média positiva → PAPER (nunca LIVE)", avaliar_modo("SHADOW", [1.5, -1.0] * 50, rc)[0] == "PAPER")
check("ruído em torno de zero não rebaixa", avaliar_modo("PAPER", [1.5, -1.0, -0.5] * 34, rc)[0] == "PAPER")

print("\n".join(f"  ✅ {n}" for n in ok))
print(f"\nTODOS OS {len(ok)} TESTES PASSARAM")
