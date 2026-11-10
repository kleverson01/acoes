"""Score mínimo por modalidade.

Hoje o executor usa 80 (alta liquidez) / 85 (baixa) para tudo, e as leituras isoladas são capadas
em 79 pelo motor — então só a Confluência vira ordem. No backtest, liberar as isoladas sem filtro
PIOROU o resultado (Médias e SMC perdem); liberar só o VWAP ≥ 70 COM o filtro de faixa melhorou.
Por isso: VWAP 70/75 só vale se o filtro de faixa estiver ligado; caso contrário volta ao corte global.
"""
from __future__ import annotations

PADRAO = {
    "Confluência": (80.0, 85.0),
    "VWAP": (70.0, 75.0),           # exige faixa de abertura ligada
    "SMC": (80.0, 85.0),
    "Médias Móveis": (80.0, 85.0),
    "Price Action": (80.0, 85.0),
}
EXIGE_FAIXA = {"VWAP"}
GLOBAL = (80.0, 85.0)


def score_minimo(modalidade: str, liquidez_alta: bool, faixa_ligada: bool, tabela: dict | None = None) -> float:
    t = {**PADRAO, **(tabela or {})}
    alta, baixa = t.get(modalidade, GLOBAL)
    if modalidade in EXIGE_FAIXA and not faixa_ligada:
        alta, baixa = GLOBAL
    return float(alta if liquidez_alta else baixa)
