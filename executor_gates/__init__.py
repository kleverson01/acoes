"""Gates adicionais do executor (validados em backtest no Laboratório de Setups, nov/2026).

- faixa_abertura: só entra com o preço FORA da faixa dos primeiros 30 min, a favor da operação.
- score_gate: score mínimo por modalidade (VWAP 70 exige o filtro de faixa ligado).
- rebaixamento: trava opcional que manda o setup para SHADOW com evidência estatística de prejuízo.

Nenhum módulo envia ordem nem altera o cálculo do score do motor.
"""
from .faixa_abertura import FaixaConfig, calcular_faixa, checar_faixa
from .score_gate import score_minimo
from .rebaixamento import RebaixamentoConfig, avaliar_modo
