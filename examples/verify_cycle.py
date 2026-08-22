"""Verificación del ciclo con DATOS REALES públicos (sin keys, sin cuentas).
Para BTC/ETH/SOL/LINK: precio actual, máximo de los últimos ~1000 días + su fecha,
caída desde ese máximo (drawdown), mínimo del periodo, y cambio interanual.
Confirma o refuta la tesis 'el pico ya pasó, estamos en bear' con precios, no opiniones.
"""
from __future__ import annotations

from datetime import UTC, datetime

from binance.client import Client

from kainext_binance_mcp.klines import fetch_klines

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT"]


def _d(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%d-%m-%Y")


def main() -> None:
    c = Client()  # público
    print("== VERIFICACIÓN DE CICLO (datos reales, velas diarias ~1000d) ==\n")
    for sym in PAIRS:
        df = fetch_klines(c, sym, "1d", 1000)
        n = len(df)
        last = float(df["close"].iloc[-1])
        hi_idx = int(df["high"].astype(float).idxmax())
        hi = float(df["high"].iloc[hi_idx])
        hi_when = _d(int(df["open_time"].iloc[hi_idx]))
        lo_idx = int(df["low"].astype(float).idxmin())
        lo = float(df["low"].iloc[lo_idx])
        lo_when = _d(int(df["open_time"].iloc[lo_idx]))
        dd = (last - hi) / hi * 100
        # cambio interanual (~365 velas atrás)
        yr_ago = float(df["close"].iloc[-366]) if n >= 366 else float(df["close"].iloc[0])
        yr_chg = (last - yr_ago) / yr_ago * 100
        # cuánto subió desde el mínimo del periodo hasta el máximo
        days_since_hi = n - 1 - hi_idx
        print(f"--- {sym.replace('USDT','')} ---")
        print(f"  Precio actual:        ${last:,.2f}")
        print(f"  Máximo periodo:       ${hi:,.2f}  ({hi_when})  [hace {days_since_hi} días]")
        print(f"  Caída desde el máx:   {dd:+.1f}%   <-- drawdown")
        print(f"  Mínimo periodo:       ${lo:,.2f}  ({lo_when})")
        print(f"  Cambio ~1 año:        {yr_chg:+.1f}%")
        print(f"  (velas analizadas: {n}, desde {_d(int(df['open_time'].iloc[0]))})\n")

    # Halving ref
    print("== Referencia de ciclo ==")
    print("  Último halving BTC: ~20-abr-2024 (reward 6.25 -> 3.125 BTC).")
    print("  Patrón histórico: pico ~12-18 meses post-halving -> oct-2025/abr-2026.")
    print("  Próximo halving estimado: ~abril 2028.")


if __name__ == "__main__":
    main()
