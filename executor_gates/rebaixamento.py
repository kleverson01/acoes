"""Trava de rebaixamento automático (DESLIGADA por padrão).

No backtest nenhuma regra de rebaixamento foi robusta: todas desligam o VWAP em julho (mês ruim)
e, com volta manual, ele nunca mais religa — perdendo a recuperação de set/out. Com volta
automática o resultado depende muito do parâmetro. Use como trava de segurança, não como melhoria.

Regra: com `janela` resultados (reais + SHADOW simulados), se média + z·erro < 0 → SHADOW.
Em SHADOW, se a média da janela voltar a > `volta_media` → PAPER (nunca direto para LIVE).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class RebaixamentoConfig:
    ativo: bool = False
    janela: int = 100
    z: float = 1.64
    volta_media: float = 0.0


def avaliar_modo(modo_atual: str, resultados_r: list[float], cfg: RebaixamentoConfig) -> tuple[str, str]:
    """Devolve (novo_modo, motivo). resultados_r em ordem cronológica, incluindo SHADOW simulado."""
    if not cfg.ativo or len(resultados_r) < cfg.janela:
        return modo_atual, ""
    x = resultados_r[-cfg.janela:]
    m = sum(x) / len(x)
    sd = math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))
    if modo_atual in ("LIVE", "PAPER") and m + cfg.z * sd / math.sqrt(len(x)) < 0:
        return "SHADOW", f"REBAIXADO: média {m:+.3f}R nas últimas {cfg.janela} (evidência de prejuízo)"
    if modo_atual == "SHADOW" and m > cfg.volta_media:
        return "PAPER", f"REPROMOVIDO A PAPER: média {m:+.3f}R nas últimas {cfg.janela}"
    return modo_atual, ""
