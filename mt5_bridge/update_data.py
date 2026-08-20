"""
mt5_bridge/update_data.py

Roda no PC de casa (Windows, com o MetaTrader 5 aberto e logado).
Busca os candles REAIS via MT5 pra todos os ativos da watchlist, em
todos os timeframes que o app usa (M15, H1, H4, D1, W1), e salva num
arquivo JSON. O GitHub Actions cuida de subir esse arquivo pro
repositório depois que este script terminar.

NÃO roda sozinho em loop — só é disparado sob demanda, quando você
clica em "Atualizar via MT5" no app (isso dispara o workflow do GitHub
Actions, que aciona o runner instalado nesta máquina).

Uso manual (pra testar sem passar pelo GitHub Actions):
    python mt5_bridge/update_data.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# garante que 'daytrade_smc.py' (na raiz do projeto) é encontrado
# mesmo rodando este script de dentro da pasta mt5_bridge/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from daytrade_smc import WINFUT_SYMBOL, _fetch_ohlcv_mt5, load_symbols  # noqa: E402

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "mt5_snapshot.json"

# Watchlist de ações: os timeframes que o Day Trade / Swing Trade usam.
STOCK_TIMEFRAMES = ["M15", "H1", "H4", "D1", "W1"]
STOCK_CANDLES_PER_TIMEFRAME = {"M15": 300, "H1": 300, "H4": 200, "D1": 300, "W1": 200}

# WINFUT (mini índice): timeframes próprios, mais rápidos — contrato futuro.
WINFUT_TIMEFRAMES = ["M2", "M5", "M15", "H1"]
WINFUT_CANDLES_PER_TIMEFRAME = {"M2": 300, "M5": 300, "M15": 300, "H1": 300}


def fetch_symbol(snapshot: dict, symbol: str, timeframes: list[str], candles: dict[str, int]) -> tuple[int, int]:
    snapshot["symbols"][symbol] = {}
    ok, err = 0, 0
    for tf in timeframes:
        try:
            df = _fetch_ohlcv_mt5(symbol, tf, candles[tf])
            records = [
                {
                    "time": idx.isoformat(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
                for idx, row in df.iterrows()
            ]
            snapshot["symbols"][symbol][tf] = {"ok": True, "candles": records, "error": None}
            print(f"  OK   {symbol:<8} {tf:<4} {len(records)} candles")
            ok += 1
        except Exception as exc:  # noqa: BLE001 — precisa continuar pros outros timeframes/ativos mesmo se um falhar
            snapshot["symbols"][symbol][tf] = {"ok": False, "candles": [], "error": str(exc)}
            print(f"  ERRO {symbol:<8} {tf:<4} {exc}")
            err += 1
    return ok, err


def main() -> None:
    symbols = load_symbols()
    print(f"Atualizando {len(symbols)} ativo(s) da watchlist + {WINFUT_SYMBOL} via MT5: {', '.join(symbols)}\n")

    snapshot: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": {},
    }

    ok_count = 0
    error_count = 0

    for symbol in symbols:
        ok, err = fetch_symbol(snapshot, symbol, STOCK_TIMEFRAMES, STOCK_CANDLES_PER_TIMEFRAME)
        ok_count += ok
        error_count += err

    print(f"\n--- {WINFUT_SYMBOL} (mini índice) ---")
    ok, err = fetch_symbol(snapshot, WINFUT_SYMBOL, WINFUT_TIMEFRAMES, WINFUT_CANDLES_PER_TIMEFRAME)
    ok_count += ok
    error_count += err

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nSalvo em {OUTPUT_PATH}")
    print(f"Sucesso: {ok_count}  ·  Erros: {error_count}")

    if error_count > 0 and ok_count == 0:
        # nada funcionou — provavelmente MT5 fechado/deslogado. Sinaliza
        # falha pro GitHub Actions não commitar um snapshot vazio/inútil.
        sys.exit(1)


if __name__ == "__main__":
    main()
