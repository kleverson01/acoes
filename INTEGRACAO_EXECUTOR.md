# Integração dos gates novos no executor (`executor/executor.py`)

Validado em backtest no Laboratório de Setups (15 ações líquidas, M15, 10/07–09/11/2026, dados Yahoo,
custo 0,08%, regras do executor reproduzidas: score ≥ 80/85, EMA200, proteção 0,8R, limites de carteira).

| Cenário | Operações | Acerto | Por operação | Total | R$ (R$150/op) |
|---|---|---|---|---|---|
| Atual | 1.610 | 49,4% | −0,051R | −81,9R | −R$12.285 |
| Com faixa de abertura + VWAP ≥ 70 | 1.647 | 51,4% | −0,015R | −24,9R | −R$3.735 |
| (só após 18/09, fora do ajuste) atual × novo | 661 × 677 | 53,6% × 54,4% | −0,017R × −0,006R | | |

Melhor que a direção sorteada (p = 0,024), mas ainda NÃO lucrativo: manter o VWAP em PAPER.

## Onde ligar (ordem dos gates da seção 7)
Depois de `_elegiveis` passar os testes atuais (entrada/stop, símbolo, MTF, frescor) e ANTES do
bloqueio por EMA200:

```python
from executor_gates import FaixaConfig, checar_faixa, score_minimo

# 1) score mínimo por modalidade (substitui EXECUTOR_SCORE_MINIMO / _BAIXA_LIQUIDEZ)
faixa_on = cfg_gates["faixa_abertura"]["ativo"] and modalidade in cfg_gates["faixa_abertura"]["aplicar_em"]
minimo = score_minimo(modalidade, _liquidez_alta(symbol), faixa_on, cfg_gates["score_minimo"])
if sinal.score < minimo:
    registrar_no_trade(sinal, f"SCORE {sinal.score:.1f} < {minimo:.1f}"); continue

# 2) faixa de abertura (candles M15 do dia até o candle do sinal, índice = abertura em UTC)
if faixa_on:
    ok, info = checar_faixa(sinal.direction, sinal.close, sinal.candle_time, candles_dia_m15,
                            FaixaConfig(minutos=cfg_gates["faixa_abertura"]["minutos"]))
    gravar_no_log(sinal, faixa_max=info["faixa_max"], faixa_min=info["faixa_min"],
                  posicao_faixa=info["posicao_faixa"])
    if not ok:
        registrar_no_trade(sinal, info["motivo"]); continue
```

Motivos novos de NO_TRADE: `FAIXA_ABERTURA_NAO_FORMADA`, `FAIXA_ABERTURA_SEM_DADOS`
(dia sem candle entre 10:00 e 10:30, como em abertura atrasada/circuit breaker), `DENTRO_DA_FAIXA`,
`CONTRA_A_FAIXA`. Todos devem ir também para o Telegram no formato de "sinal bloqueado".

## Modo do VWAP
`config/setups_gates.json` → `"modo_inicial": {"VWAP": "PAPER"}`. Aplicar o mais restritivo entre
esse modo, `setups.json` e `parametros_aprendidos.json` (regra atual do executor).

## Rebaixamento (opcional, desligado)
`executor_gates.rebaixamento.avaliar_modo(modo, resultados_r, cfg)` — chamar após cada saída com os
resultados reais + SHADOW do setup. No backtest nenhuma regra foi robusta (todas desligaram o VWAP
em julho e perderam a recuperação de set/out). Ligue só como trava de segurança.

## Testes
`python tests/test_executor_gates.py` (17 testes). Conferência com o backtest: 2.987 de 3.000
decisões iguais; as 13 diferenças são dos dias 05/10 e 26/10 (abertura atrasada), em que o módulo
recusa por `FAIXA_ABERTURA_SEM_DADOS` — comportamento intencional.
