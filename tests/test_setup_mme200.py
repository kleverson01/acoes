"""Testes do setup de rejeição na MME200 (dados sintéticos, contas à mão)."""
import numpy as np
import pandas as pd

import setup_mme200 as S


def _serie(precos, inicio="2026-11-03 10:00"):
    """Candles M15 de pregão (10:00–17:45) a partir de uma lista de (o, h, l, c)."""
    idx = []
    dia = pd.Timestamp(inicio)
    while len(idx) < len(precos):
        for k in range(32):
            if len(idx) == len(precos):
                break
            idx.append(dia.normalize() + pd.Timedelta(hours=10) + pd.Timedelta(minutes=15 * k))
        dia = dia + pd.offsets.BDay(1)
    df = pd.DataFrame(precos, columns=["open", "high", "low", "close"], index=pd.DatetimeIndex(idx).tz_localize(S.TZ))
    df["volume"] = 1000.0
    return df


def _base_com_toque(direcao=-1):
    """250 candles parados em 100 (MME200 ≈ 100), depois um impulso que toca a média e rejeita."""
    p = [(100, 100.05, 99.95, 100)] * 250
    # recuo para baixo da média (venda: origem abaixo) - 12 candles
    nivel = 100.0
    for _ in range(12):
        nivel -= 0.25 * -direcao
        p.append((nivel, nivel + 0.05, nivel - 0.05, nivel))
    return p, nivel


def test_toque_e_alvo_venda():
    p, nivel = _base_com_toque(-1)          # preço caiu até ~97
    # impulso de alta forte em 8 candles até tocar a média (~99,9) e fechar abaixo dela (rejeição)
    for i in range(7):
        nivel += 0.35
        p.append((nivel - 0.3, nivel + 0.02, nivel - 0.32, nivel))
    p.append((nivel, 100.2, nivel - 0.05, nivel + 0.05))          # toque: máxima acima da MME200, fecha abaixo
    toque = len(p) - 1
    p.append((nivel, nivel + 0.02, nivel - 0.30, nivel - 0.25))   # rompe a mínima do toque → entra vendido
    for _ in range(4):
        p.append((nivel - 0.25, nivel - 0.2, nivel - 1.2, nivel - 1.0))  # cai > 0,5% → alvo
    df = _serie(p)
    tq = S.toques(S.preparar(df))
    assert tq["dir"].iat[toque] == -1, "o candle do toque deve gerar sinal de venda"
    T = S.backtest(df)
    assert len(T) == 1
    op = T.iloc[0]
    assert op["Direção"] == "VENDA" and op["Resultado"] == "ALVO"
    assert abs(op["Resultado %"] - (0.5 - 0.08)) < 1e-6           # alvo de 0,5% menos o custo


def test_sem_rejeicao_nao_entra():
    p, nivel = _base_com_toque(-1)
    for i in range(7):
        nivel += 0.35
        p.append((nivel - 0.3, nivel + 0.02, nivel - 0.32, nivel))
    p.append((nivel, 100.4, nivel - 0.05, 100.3))                 # fecha ACIMA da MME200: rompeu, não rejeitou
    p += [(100.3, 100.5, 100.2, 100.4)] * 10
    T = S.backtest(_serie(p))
    assert T.empty


def test_stop_de_protecao():
    p, nivel = _base_com_toque(-1)
    for i in range(7):
        nivel += 0.35
        p.append((nivel - 0.3, nivel + 0.02, nivel - 0.32, nivel))
    p.append((nivel, 100.2, nivel - 0.05, nivel + 0.05))
    p.append((nivel, nivel + 0.02, nivel - 0.30, nivel - 0.25))   # entra vendido em ~mínima do toque − 1 tick
    p.append((nivel, nivel + 3.5, nivel - 0.1, nivel + 3.4))       # dispara +3,5% → stop de 2,5%
    T = S.backtest(_serie(p))
    assert len(T) == 1 and T.iloc[0]["Resultado"] == "STOP"
    assert abs(T.iloc[0]["Resultado %"] - (-2.5 - 0.08)) < 1e-6


def test_zeragem_no_fim_do_dia():
    p, nivel = _base_com_toque(-1)
    for i in range(7):
        nivel += 0.35
        p.append((nivel - 0.3, nivel + 0.02, nivel - 0.32, nivel))
    p.append((nivel, 100.2, nivel - 0.05, nivel + 0.05))
    p.append((nivel, nivel + 0.02, nivel - 0.30, nivel - 0.25))
    p += [(nivel - 0.25, nivel - 0.2, nivel - 0.3, nivel - 0.25)] * 40   # anda de lado: nem alvo nem stop
    T = S.backtest(_serie(p))
    assert len(T) == 1 and T.iloc[0]["Resultado"] == "ZERAGEM"
    assert T.iloc[0]["Saída às"] <= "17:30"


def test_situacao_gatilho_armado():
    p, nivel = _base_com_toque(-1)
    for i in range(7):
        nivel += 0.35
        p.append((nivel - 0.3, nivel + 0.02, nivel - 0.32, nivel))
    p.append((nivel, 100.2, nivel - 0.05, nivel + 0.05))          # último candle = toque
    s = S.situacao_atual(_serie(p), ativo="TESTE3")
    assert s.estado == "GATILHO ARMADO" and s.direcao == "VENDA"
    assert abs(s.alvo - s.gatilho * 0.995) < 0.011 and abs(s.stop - s.gatilho * 1.025) < 0.011
