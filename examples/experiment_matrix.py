"""Matriz de backtests in-sample sobre datos reales — INVESTIGACIÓN, 100% read-only.

Objetivo (honestidad total): medir si alguna estrategia le gana a buy&hold de forma
CREÍBLE sobre una muestra de históricos. No buscamos un ganador; medimos la verdad.

Matriz:
- PARES:       BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT
- TIMEFRAMES:  1h, 4h, 1d
- ESTRATEGIAS: composite (signals.backtest_signal), ema_cross, rsi_threshold (capa 2)

Por celda recolecta: total_return_pct, buy_hold_return_pct, edge (=total-buyhold),
n_trades, win_rate, max_drawdown_pct. Errores de red/datos por celda → N/A (no aborta).

CRITERIO DE CREDIBILIDAD: una celda con edge>0 sólo se considera "creíble" si además
tiene n_trades>=10. Pocas operaciones = el resultado es ruido/suerte, no edge.

ADVERTENCIA METODOLÓGICA: todo esto es IN-SAMPLE (un solo tramo de ~1000 velas, sin
out-of-sample, sin walk-forward, sin múltiples ventanas). Cualquier "ganador" aquí es
una hipótesis de trabajo, NO evidencia de edge real. Para afirmar edge haría falta
validación out-of-sample en datos no vistos.

FUENTE DE DATOS — ``DATA_SOURCE = "mainnet_public"``:
El testnet de Binance NO tiene históricos reales (devuelve 5-106 velas sintéticas con
saltos irreales), así que esta matriz se corre contra las klines PÚBLICAS de mainnet.
``get_klines`` es un endpoint PÚBLICO de ``api.binance.com``: sin auth, sin keys firmadas,
no toca ninguna cuenta, no mueve plata — es sólo descargar historial de precios público
(como mirar un gráfico). Por eso el client se construye con ``Client()`` pelado (sin keys,
sin testnet), sin pasar por ``make_client`` (que requeriría keys y apuntaría a testnet).
"""
from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass

from binance.client import Client

from kainext_binance_mcp.backtest import backtest_df
from kainext_binance_mcp.klines import fetch_klines
from kainext_binance_mcp.signals.backtest_signal import backtest_signal

# Fuente de datos: klines PÚBLICAS de mainnet (sin keys, sin auth, read-only puro).
DATA_SOURCE = "mainnet_public"

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
TIMEFRAMES = ["1h", "4h", "1d"]
STRATEGIES = ["composite", "ema_cross", "rsi_threshold"]
LIMIT = 1000
MIN_TRADES_CREDIBLE = 10


def make_public_client() -> Client:
    """Client de datos públicos de mainnet: ``Client()`` pelado (sin api_key/secret, sin
    testnet). Pega a ``api.binance.com``; ``get_klines`` es público y devuelve hasta 1000
    velas reales. No firma requests, no toca cuentas, no mueve fondos."""
    return Client()


@dataclass
class Cell:
    pair: str
    timeframe: str
    strategy: str
    ok: bool
    total_return_pct: float | None = None
    buy_hold_return_pct: float | None = None
    edge: float | None = None
    n_trades: int | None = None
    win_rate: float | None = None
    max_drawdown_pct: float | None = None
    error: str | None = None


def run_cell(df, pair: str, timeframe: str, strategy: str) -> Cell:
    """Corre una estrategia sobre un DataFrame ya fetcheado. Devuelve la celda con métricas."""
    if strategy == "composite":
        res = backtest_signal(df, symbol=pair, interval=timeframe)
    elif strategy in ("ema_cross", "rsi_threshold"):
        res = backtest_df(df, symbol=pair, interval=timeframe, strategy=strategy)
    else:  # pragma: no cover - guard
        return Cell(pair, timeframe, strategy, ok=False, error=f"estrategia desconocida: {strategy}")

    edge = res.total_return_pct - res.buy_hold_return_pct
    return Cell(
        pair=pair,
        timeframe=timeframe,
        strategy=strategy,
        ok=True,
        total_return_pct=res.total_return_pct,
        buy_hold_return_pct=res.buy_hold_return_pct,
        edge=edge,
        n_trades=res.n_trades,
        win_rate=res.win_rate,
        max_drawdown_pct=res.max_drawdown_pct,
    )


def _fmt(v: float | None, suffix: str = "") -> str:
    if v is None:
        return "N/A"
    return f"{v:+.2f}{suffix}" if suffix == "%" else f"{v:.2f}{suffix}"


def main() -> int:
    print(
        f"# Matriz de backtests in-sample  "
        f"(DATA_SOURCE={DATA_SOURCE}, limit={LIMIT} velas/celda)\n"
    )
    print(
        "Datos: klines PÚBLICAS de mainnet (api.binance.com, sin keys, sin auth, read-only).\n"
    )
    print("Construyendo client público read-only (Client() pelado)...", file=sys.stderr)
    client = make_public_client()

    cells: list[Cell] = []

    for pair in PAIRS:
        for tf in TIMEFRAMES:
            # Un solo fetch por (par, tf); las 3 estrategias comparten el mismo DataFrame.
            try:
                df = fetch_klines(client, pair, tf, LIMIT)
            except Exception as exc:  # noqa: BLE001 - aislamos la celda, no abortamos
                msg = f"{type(exc).__name__}: {exc}"
                print(f"  [fetch FALLÓ] {pair} {tf}: {msg}", file=sys.stderr)
                for strat in STRATEGIES:
                    cells.append(Cell(pair, tf, strat, ok=False, error=f"fetch: {msg}"))
                continue

            n = len(df)
            print(f"  {pair} {tf}: {n} velas", file=sys.stderr)
            for strat in STRATEGIES:
                try:
                    cells.append(run_cell(df, pair, tf, strat))
                except Exception as exc:  # noqa: BLE001 - aislamos la celda
                    msg = f"{type(exc).__name__}: {exc}"
                    print(f"    [backtest FALLÓ] {pair} {tf} {strat}: {msg}", file=sys.stderr)
                    traceback.print_exc(file=sys.stderr)
                    cells.append(Cell(pair, tf, strat, ok=False, error=msg))

    # ---------- TABLA ----------
    # Ordenada por edge desc (las celdas N/A al final).
    def sort_key(c: Cell):
        return (0, -c.edge) if (c.ok and c.edge is not None) else (1, 0.0)

    cells_sorted = sorted(cells, key=sort_key)

    print("\n## Tabla de resultados (ordenada por edge desc)\n")
    header = (
        "| Par | TF | Estrategia | total_return | buy&hold | edge | n_trades | win_rate | max_dd |"
    )
    sep = "|---|---|---|---:|---:|---:|---:|---:|---:|"
    print(header)
    print(sep)
    for c in cells_sorted:
        if not c.ok:
            print(
                f"| {c.pair} | {c.timeframe} | {c.strategy} | N/A | N/A | N/A | N/A | N/A | N/A |"
                f"  <!-- {c.error} -->"
            )
            continue
        wr = None if c.win_rate is None else c.win_rate * 100.0
        print(
            f"| {c.pair} | {c.timeframe} | {c.strategy} "
            f"| {_fmt(c.total_return_pct, '%')} "
            f"| {_fmt(c.buy_hold_return_pct, '%')} "
            f"| {_fmt(c.edge, '%')} "
            f"| {c.n_trades} "
            f"| {_fmt(wr, '%')} "
            f"| {_fmt(c.max_drawdown_pct, '%')} |"
        )

    # ---------- RESUMEN ----------
    ran = [c for c in cells if c.ok]
    failed = [c for c in cells if not c.ok]
    edge_pos = [c for c in ran if c.edge is not None and c.edge > 0.0]
    credible = [c for c in edge_pos if c.n_trades is not None and c.n_trades >= MIN_TRADES_CREDIBLE]

    print("\n## Resumen\n")
    print(f"- Celdas totales en la matriz: {len(cells)} ({len(PAIRS)}×{len(TIMEFRAMES)}×{len(STRATEGIES)})")
    print(f"- Celdas que corrieron OK: {len(ran)}")
    print(f"- Celdas N/A (fetch/backtest falló): {len(failed)}")
    print(f"- Celdas con edge>0 (sin filtro de trades): {len(edge_pos)} / {len(ran)}")
    print(
        f"- Celdas con edge>0 **Y** n_trades>={MIN_TRADES_CREDIBLE} (las únicas creíbles): "
        f"{len(credible)} / {len(ran)}"
    )

    if credible:
        print("\n### Celdas con edge creíble (edge>0 y n_trades>=10)\n")
        print("| Par | TF | Estrategia | edge | total_return | buy&hold | n_trades | win_rate | max_dd |")
        print("|---|---|---|---:|---:|---:|---:|---:|---:|")
        for c in sorted(credible, key=lambda x: -x.edge):  # type: ignore[arg-type]
            wr = c.win_rate * 100.0 if c.win_rate is not None else None
            print(
                f"| {c.pair} | {c.timeframe} | {c.strategy} "
                f"| {_fmt(c.edge, '%')} | {_fmt(c.total_return_pct, '%')} "
                f"| {_fmt(c.buy_hold_return_pct, '%')} | {c.n_trades} "
                f"| {_fmt(wr, '%')} | {_fmt(c.max_drawdown_pct, '%')} |"
            )
    else:
        print("\n### Celdas con edge creíble: NINGUNA")
        print(
            "No hay ninguna celda que le gane a buy&hold con un número de operaciones "
            "suficiente (>=10) para descartar la suerte."
        )

    # Para contraste: edge>0 pero con POCOS trades (no creíbles, casualidad probable).
    lucky = [c for c in edge_pos if c.n_trades is not None and c.n_trades < MIN_TRADES_CREDIBLE]
    if lucky:
        print(
            f"\n_(Nota: {len(lucky)} celda(s) tienen edge>0 pero con <{MIN_TRADES_CREDIBLE} "
            "operaciones — se descartan por no creíbles: muestra de trades insuficiente.)_"
        )

    print(
        "\n> ADVERTENCIA: resultados IN-SAMPLE (un solo tramo de velas, sin out-of-sample). "
        "Cualquier 'ganador' es una hipótesis, no evidencia de edge real. Validación "
        "out-of-sample en datos no vistos es obligatoria antes de afirmar nada."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
