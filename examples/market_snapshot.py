"""Snapshot de mercado en vivo (datos PÚBLICOS de Binance, sin keys, sin tocar cuentas).
Para cada par líquido: precio, % cambio 24h, volumen 24h (USDT), RSI(14 1h), ATR% (volatilidad),
y posición en el rango 24h (0=mínimo, 100=máximo). NO predice dirección — caracteriza
liquidez y volatilidad para informar (no para apostar).
"""
from __future__ import annotations

from binance.client import Client

from kainext_binance_mcp.indicators import atr, rsi
from kainext_binance_mcp.klines import fetch_klines

PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "TRXUSDT", "DOTUSDT", "NEARUSDT",
    "SUIUSDT", "LTCUSDT", "MATICUSDT",
]


def main() -> None:
    c = Client()  # público, sin auth
    rows = []
    for sym in PAIRS:
        try:
            t = c.get_ticker(symbol=sym)
            df = fetch_klines(c, sym, "1h", 300)
            last_rsi = float(rsi(df["close"], 14).iloc[-1])
            last_atr = float(atr(df["high"], df["low"], df["close"], 14).iloc[-1])
            last = float(t["lastPrice"])
            atr_pct = last_atr / last * 100 if last else 0.0
            hi = float(t["highPrice"])
            lo = float(t["lowPrice"])
            pos = (last - lo) / (hi - lo) * 100 if hi > lo else 50.0
            rows.append({
                "sym": sym.replace("USDT", ""),
                "price": last,
                "chg24": float(t["priceChangePercent"]),
                "vol24_musdt": float(t["quoteVolume"]) / 1_000_000,
                "rsi": last_rsi,
                "atr_pct": atr_pct,
                "rangepos": pos,
            })
        except Exception as e:  # noqa: BLE001
            rows.append({"sym": sym.replace("USDT", ""), "error": str(e)})

    rows_ok = [r for r in rows if "error" not in r]
    rows_ok.sort(key=lambda r: r["vol24_musdt"], reverse=True)

    print("== SNAPSHOT DE MERCADO (datos públicos en vivo) ==")
    print(f"{'Cripto':<7}{'Precio':>14}{'24h %':>9}{'Vol24h M$':>12}{'RSI(1h)':>9}"
          f"{'ATR% (vol)':>12}{'Rango24h':>10}")
    for r in rows_ok:
        print(f"{r['sym']:<7}{r['price']:>14.4f}{r['chg24']:>+9.2f}{r['vol24_musdt']:>12.0f}"
              f"{r['rsi']:>9.1f}{r['atr_pct']:>11.2f}%{r['rangepos']:>9.0f}%")
    for r in rows:
        if "error" in r:
            print(f"  {r['sym']}: ERROR {r['error']}")

    print("\nLeyenda: RSI<30 sobreventa / >70 sobrecompra (NO es señal de compra/venta confiable). "
          "ATR% = volatilidad típica por hora (más alto = se mueve más, en CUALQUIER dirección). "
          "Rango24h: 0%=en el mínimo del día, 100%=en el máximo. Esto caracteriza el mercado, "
          "NO predice quién sube.")


if __name__ == "__main__":
    main()
