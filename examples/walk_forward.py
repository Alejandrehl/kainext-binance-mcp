"""Validación walk-forward / OUT-OF-SAMPLE sobre klines reales públicas — INVESTIGACIÓN, 100% read-only.

Pregunta honesta: ¿alguna estrategia simple tiene edge ROBUSTO out-of-sample, o el
"edge" in-sample de la matriz era overfitting que NO generaliza?

La matriz previa (``experiment_matrix.py``) era IN-SAMPLE: un solo tramo, parámetros
fijos, sin datos no vistos. Esto es lo opuesto: walk-forward rolling. En cada ventana
de "train" se eligen los MEJORES parámetros (grid search) y se miden esos parámetros en
la ventana de "test" SIGUIENTE (datos jamás vistos en la selección). Se rueda en bloques
contiguos no solapados, así cada punto OOS se usa una sola vez y los bloques de test
concatenados forman una curva de equity OOS continua y real.

ANTI-LOOKAHEAD (doble candado):
1. Los parámetros se eligen SÓLO con datos de la ventana train (índices < test_start).
2. Dentro de cada ventana, la simulación es la misma anti-lookahead del harness:
   la posición que se mantiene entrando en la vela ``i`` la decide ``signal[i-1]`` y el
   fill ocurre en ``open[i]`` (nunca al ``close`` de la propia vela que generó la señal).
3. Calentamiento de indicadores: la señal se computa sobre la serie COMPLETA una vez por
   combinación de parámetros (las EMA/RSI quedan tibias en todo el rango); la contabilidad
   de equity se restringe a los índices de la ventana. Así NO hay artefacto de reinicio de
   indicador al empezar cada ventana, y tampoco lookahead (la señal en ``t`` sólo usa
   closes hasta ``t``, son causales).

COMISIÓN: taker 0.1% por lado (igual que el harness). SIN slippage (limitación
documentada del modelo; mercado real tiene slippage/profundidad).

FUENTE DE DATOS — ``DATA_SOURCE = "mainnet_public"`` (idéntico a experiment_matrix.py):
klines PÚBLICAS de ``api.binance.com`` vía ``Client()`` pelado (sin keys, sin auth, sin
testnet). ``get_klines`` es un endpoint PÚBLICO: no firma requests, no toca cuentas, no
mueve fondos — es leer historial de precios público (como mirar un gráfico). Para juntar
varios miles de velas se pagina con ``startTime`` (la API tope 1000 velas por llamada).

GUARDIAS CONTRA AUTO-ENGAÑO:
- Pocas operaciones OOS (< MIN_OOS_TRADES) => resultado marcado como RUIDO, no edge.
- Consistencia entre ventanas: % de ventanas de test donde la estrategia le gana a
  buy&hold. ~50% = volado de moneda, no señal.
- Buy&hold OOS se mide sobre EXACTAMENTE el mismo span concatenado (apples-to-apples).
"""
from __future__ import annotations

import sys
import time
import traceback
from dataclasses import dataclass, field
from itertools import product

import numpy as np
import pandas as pd
from binance.client import Client

from kainext_binance_mcp import indicators
from kainext_binance_mcp.backtest import COMMISSION_TAKER, ema_cross, rsi_threshold

DATA_SOURCE = "mainnet_public"

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
TIMEFRAMES = ["1h", "4h", "1d"]

# Cuántas velas intentar juntar por par/TF (paginando con startTime). El real puede ser
# menor (depende de cuánta historia tenga el par; SOL/BNB son más jóvenes).
TARGET_CANDLES = {"1h": 5000, "4h": 5000, "1d": 3000}

# Tamaños de ventana walk-forward (en velas) por TF. step = test => bloques de test
# contiguos NO solapados (cada punto OOS se usa una vez).
WINDOWS = {
    #  TF : (train, test, step)
    "1h": (800, 200, 200),
    "4h": (500, 150, 150),
    "1d": (400, 100, 100),
}

# Grilla de parámetros (rangos CHICOS a propósito: grids grandes inflan el overfit
# in-sample y empeoran el OOS — eso también lo queremos exponer, no esconder).
EMA_GRID = [
    (f, s) for f, s in product([5, 8, 12, 20], [21, 26, 50, 100, 200]) if f < s
]
RSI_GRID = [
    (low, high) for low, high in product([20, 25, 30, 35], [65, 70, 75, 80])
]
# Umbral de régimen (|ema_fast/ema_slow - 1|) para la variante con filtro.
REGIME_THETAS = [0.0, 0.01, 0.02, 0.05]

MIN_OOS_TRADES = 20  # menos que esto => el OOS es ruido, no edge


# --------------------------------------------------------------------------- #
# Datos: paginación de klines públicas con startTime
# --------------------------------------------------------------------------- #

_MS = {"1h": 3600_000, "4h": 4 * 3600_000, "1d": 24 * 3600_000}


def make_public_client() -> Client:
    """Client de datos públicos de mainnet: ``Client()`` pelado (sin keys, sin testnet).
    Pega a ``api.binance.com``; ``get_klines`` es público. No firma, no toca cuentas."""
    return Client()


def fetch_klines_paged(client: Client, symbol: str, interval: str, target: int) -> pd.DataFrame:
    """Junta hasta ``target`` velas paginando con ``startTime`` (la API tope 1000/llamada).

    Devuelve un DataFrame OHLC ordenado por tiempo, sin duplicados. La cantidad real puede
    ser < target si el par no tiene tanta historia.
    """
    step_ms = _MS[interval]
    now_ms = int(time.time() * 1000)
    # Punto de partida: target velas hacia atrás desde ahora (con colchón).
    start = now_ms - target * step_ms - step_ms
    rows: list[list] = []
    last_open_time = -1
    while len(rows) < target:
        batch = client.get_klines(
            symbol=symbol, interval=interval, limit=1000, startTime=start
        )
        if not batch:
            break
        # Evitar bucle infinito si la API devuelve el mismo lote.
        if batch[0][0] == last_open_time and len(batch) <= 1:
            break
        rows.extend(batch)
        last_open_time = batch[-1][0]
        next_start = batch[-1][0] + step_ms
        if next_start <= start:
            break
        start = next_start
        if len(batch) < 1000:
            # No hay más historia disponible hacia adelante.
            if start >= now_ms:
                break
    if not rows:
        raise RuntimeError(f"sin datos para {symbol} {interval}")
    # Dedup por open_time y ordenar.
    seen: dict[int, list] = {}
    for r in rows:
        seen[int(r[0])] = r
    ordered = [seen[k] for k in sorted(seen)]
    df = pd.DataFrame(
        {
            "open_time": np.array([int(r[0]) for r in ordered], dtype="int64"),
            "open": np.array([float(r[1]) for r in ordered], dtype="float64"),
            "high": np.array([float(r[2]) for r in ordered], dtype="float64"),
            "low": np.array([float(r[3]) for r in ordered], dtype="float64"),
            "close": np.array([float(r[4]) for r in ordered], dtype="float64"),
            "volume": np.array([float(r[5]) for r in ordered], dtype="float64"),
        }
    )
    return df.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Señales (incluye variante con filtro de régimen)
# --------------------------------------------------------------------------- #

def regime_strength(close: pd.Series, fast: int, slow: int) -> pd.Series:
    """|EMA_fast/EMA_slow - 1| — proxy de fuerza de tendencia (0 = sin tendencia)."""
    ef = indicators.ema(close, fast)
    es = indicators.ema(close, slow)
    return (ef / es - 1.0).abs()


def ema_cross_regime(df: pd.DataFrame, fast: int, slow: int, theta: float) -> pd.Series:
    """ema_cross que SÓLO opera (long) cuando la tendencia es fuerte (strength > theta).

    Si theta=0 colapsa al ema_cross normal. Idea (item 2): la estrategia de tendencia
    sólo debería operar en régimen tendencial; en rango se queda flat.
    """
    base = ema_cross(df, fast=fast, slow=slow)
    if theta <= 0.0:
        return base
    strong = (regime_strength(df["close"], fast, slow) > theta).astype("int64")
    return (base & strong).astype("int64")


# --------------------------------------------------------------------------- #
# Simulación windowed, warm-up-correct, anti-lookahead
# --------------------------------------------------------------------------- #

def sim_window(
    opens: np.ndarray,
    closes: np.ndarray,
    sig: np.ndarray,
    start: int,
    end: int,
    commission: float = COMMISSION_TAKER,
) -> tuple[float, int]:
    """Simula long-only sobre el bloque [start, end) usando ``sig`` (ya computada sobre la
    serie COMPLETA => indicadores tibios). Anti-lookahead: la posición entrando en ``i`` la
    decide ``sig[i-1]`` y el fill es ``open[i]``. Marca a close cualquier posición abierta al
    final del bloque (no fuerza un fill de salida).

    Devuelve (retorno_total_pct, n_trades_cerrados).
    """
    cash = 1.0
    units = 0.0
    pos = 0
    n_trades = 0
    last_close = closes[start]
    # i = start+1: el primer fill ejecutable usa sig[start] (decidido al close de start).
    for i in range(start + 1, end):
        target = int(sig[i - 1])
        fill = opens[i]
        if target == 1 and pos == 0:
            units = (cash * (1.0 - commission)) / fill
            cash = 0.0
            pos = 1
        elif target == 0 and pos == 1:
            proceeds = units * fill * (1.0 - commission)
            cash = proceeds
            units = 0.0
            pos = 0
            n_trades += 1
        last_close = closes[i]
    equity = cash + units * last_close
    return (equity - 1.0) * 100.0, n_trades


def buy_hold_window(opens: np.ndarray, closes: np.ndarray, start: int, end: int) -> float:
    """Buy&hold del bloque: comprar al primer open ejecutable (open[start+1]) y marcar al
    último close del bloque."""
    if end - start < 2:
        return 0.0
    first_open = opens[start + 1]
    last_close = closes[end - 1]
    if first_open <= 0:
        return 0.0
    return (last_close / first_open - 1.0) * 100.0


# --------------------------------------------------------------------------- #
# Walk-forward por estrategia
# --------------------------------------------------------------------------- #

@dataclass
class WFResult:
    pair: str
    timeframe: str
    strategy: str
    n_candles: int
    n_windows: int = 0
    oos_return_pct: float = 0.0       # compuesto sobre bloques de test concatenados
    oos_buyhold_pct: float = 0.0      # mismo span, apples-to-apples
    oos_trades: int = 0
    windows_beat_bh: int = 0          # # ventanas test donde strat > b&h
    per_window: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def edge(self) -> float:
        return self.oos_return_pct - self.oos_buyhold_pct

    @property
    def consistency(self) -> float:
        return (self.windows_beat_bh / self.n_windows) if self.n_windows else 0.0

    @property
    def credible(self) -> bool:
        """Edge OOS creíble (definición DURA, anti-auto-engaño):

        1. le gana a buy&hold (edge > 0), **y**
        2. **gana plata en términos absolutos** (ret OOS > 0) — "perder menos que b&h en un
           tramo bajista" NO es alpha: sentarse en USDT (0 trades, 0 comisión) logra lo
           mismo. Sin esta cláusula, una estrategia que sólo reduce drawdown se disfraza de
           ganadora, **y**
        3. trades OOS suficientes (≥ MIN_OOS_TRADES) para que no sea ruido, **y**
        4. consistencia > 50% (le gana a b&h en la mayoría de las ventanas, no por 1-2
           ventanas explosivas con suerte).
        """
        return (
            self.error is None
            and self.edge > 0.0
            and self.oos_return_pct > 0.0
            and self.oos_trades >= MIN_OOS_TRADES
            and self.consistency > 0.5
        )


def _grid_for(strategy: str):
    if strategy in ("ema_cross", "ema_cross_regime"):
        return EMA_GRID
    if strategy == "rsi_threshold":
        return RSI_GRID
    raise ValueError(strategy)


def _signal_full(df: pd.DataFrame, strategy: str, params: tuple) -> np.ndarray:
    """Señal {0,1} sobre la serie COMPLETA para una combinación de parámetros."""
    if strategy == "ema_cross":
        f, s = params
        return ema_cross(df, fast=f, slow=s).to_numpy()
    if strategy == "rsi_threshold":
        low, high = params
        return rsi_threshold(df, low=float(low), high=float(high)).to_numpy()
    if strategy == "ema_cross_regime":
        f, s, theta = params
        return ema_cross_regime(df, fast=f, slow=s, theta=theta).to_numpy()
    raise ValueError(strategy)


def walk_forward(df: pd.DataFrame, pair: str, tf: str, strategy: str) -> WFResult:
    """Corre walk-forward para una (estrategia, par, TF). Selección de params SÓLO en train."""
    n = len(df)
    train, test, step = WINDOWS[tf]
    res = WFResult(pair=pair, timeframe=tf, strategy=strategy, n_candles=n)

    opens = df["open"].to_numpy(dtype="float64")
    closes = df["close"].to_numpy(dtype="float64")

    # Precomputar señales de toda la grilla una sola vez (warm-up correcto, sin lookahead:
    # cada señal en t usa sólo closes <= t). Para regime, expandimos thetas.
    if strategy == "ema_cross_regime":
        grid = [(f, s, th) for (f, s) in EMA_GRID for th in REGIME_THETAS]
    else:
        grid = _grid_for(strategy)
    sig_cache: dict[tuple, np.ndarray] = {}
    for params in grid:
        try:
            sig_cache[params] = _signal_full(df, strategy, params)
        except Exception:  # noqa: BLE001 - param inválido => se omite
            continue

    if not sig_cache:
        res.error = "grilla vacía / señales inválidas"
        return res

    # Rolling: train=[ws, ws+train), test=[ws+train, ws+train+test)
    oos_equity = 1.0
    oos_bh_equity = 1.0
    ws = 0
    while ws + train + test <= n:
        tr_s, tr_e = ws, ws + train
        te_s, te_e = ws + train, ws + train + test

        # 1) Elegir mejor param EN TRAIN (maximiza retorno de la estrategia in-sample del
        #    bloque train). Es lo que haría un optimizador ingenuo => el test honesto del
        #    overfitting. La selección NO mira un solo dato de test.
        best_params = None
        best_train_ret = -float("inf")
        for params, sig in sig_cache.items():
            tr_ret, _ = sim_window(opens, closes, sig, tr_s, tr_e)
            if tr_ret > best_train_ret:
                best_train_ret = tr_ret
                best_params = params

        # 2) Aplicar esos params al bloque de TEST (datos no vistos en la selección).
        sig = sig_cache[best_params]
        te_ret, te_trades = sim_window(opens, closes, sig, te_s, te_e)
        bh_ret = buy_hold_window(opens, closes, te_s, te_e)

        oos_equity *= (1.0 + te_ret / 100.0)
        oos_bh_equity *= (1.0 + bh_ret / 100.0)
        res.oos_trades += te_trades
        res.n_windows += 1
        if te_ret > bh_ret:
            res.windows_beat_bh += 1
        res.per_window.append(
            {
                "win": res.n_windows,
                "params": best_params,
                "train_ret": round(best_train_ret, 2),
                "test_ret": round(te_ret, 2),
                "bh_ret": round(bh_ret, 2),
                "trades": te_trades,
            }
        )
        ws += step

    res.oos_return_pct = (oos_equity - 1.0) * 100.0
    res.oos_buyhold_pct = (oos_bh_equity - 1.0) * 100.0
    return res


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

STRATEGIES = ["ema_cross", "rsi_threshold", "ema_cross_regime"]


def _fmt(v: float | None, suffix: str = "") -> str:
    if v is None:
        return "N/A"
    return f"{v:+.2f}{suffix}" if suffix == "%" else f"{v:.2f}{suffix}"


def main() -> int:
    client = make_public_client()
    print(f"# Walk-forward / OUT-OF-SAMPLE  (DATA_SOURCE={DATA_SOURCE})\n", flush=True)
    print(
        "Datos: klines PÚBLICAS de mainnet (api.binance.com, sin keys, sin auth, read-only), "
        "paginadas con startTime. Comisión taker 0.1%/lado, sin slippage.\n",
        flush=True,
    )

    results: list[WFResult] = []
    candle_counts: dict[tuple[str, str], int] = {}

    for pair in PAIRS:
        for tf in TIMEFRAMES:
            try:
                df = fetch_klines_paged(client, pair, tf, TARGET_CANDLES[tf])
            except Exception as exc:  # noqa: BLE001
                msg = f"{type(exc).__name__}: {exc}"
                print(f"  [fetch FALLÓ] {pair} {tf}: {msg}", file=sys.stderr, flush=True)
                for strat in STRATEGIES:
                    r = WFResult(pair, tf, strat, n_candles=0)
                    r.error = f"fetch: {msg}"
                    results.append(r)
                continue
            n = len(df)
            candle_counts[(pair, tf)] = n
            print(f"  {pair} {tf}: {n} velas reales", file=sys.stderr, flush=True)
            for strat in STRATEGIES:
                try:
                    results.append(walk_forward(df, pair, tf, strat))
                except Exception as exc:  # noqa: BLE001
                    msg = f"{type(exc).__name__}: {exc}"
                    print(f"    [wf FALLÓ] {pair} {tf} {strat}: {msg}", file=sys.stderr, flush=True)
                    traceback.print_exc(file=sys.stderr)
                    r = WFResult(pair, tf, strat, n_candles=n)
                    r.error = msg
                    results.append(r)

    # ---------- Velas por par/TF ----------
    print("## Velas reales usadas (paginadas con startTime)\n")
    print("| Par | TF | Velas | train | test | step | ventanas WF |")
    print("|---|---|---:|---:|---:|---:|---:|")
    for pair in PAIRS:
        for tf in TIMEFRAMES:
            n = candle_counts.get((pair, tf), 0)
            tr, te, st = WINDOWS[tf]
            nw = max(0, (n - tr - te) // st + 1) if n >= tr + te else 0
            print(f"| {pair} | {tf} | {n} | {tr} | {te} | {st} | {nw} |")

    # ---------- Tabla OOS ----------
    ok = [r for r in results if r.error is None and r.n_windows > 0]
    ok_sorted = sorted(ok, key=lambda r: -r.edge)
    print("\n## Resultados OUT-OF-SAMPLE (agregado sobre bloques de test concatenados)\n")
    print(
        "edge = retorno OOS estrategia − retorno OOS buy&hold (mismo span). "
        "consistencia = % de ventanas de test donde la estrategia le gana a buy&hold "
        f"(~50% = volado de moneda). trades OOS < {MIN_OOS_TRADES} ⇒ ruido.\n"
    )
    print("| Estrategia | Par | TF | ret OOS | b&h OOS | edge | trades OOS | ventanas | gana b&h | consistencia | ¿creíble? |")
    print("|---|---|---|---:|---:|---:|---:|---:|---:|---:|:--:|")
    for r in ok_sorted:
        cred = "✅" if r.credible else "—"
        print(
            f"| {r.strategy} | {r.pair} | {r.timeframe} "
            f"| {_fmt(r.oos_return_pct, '%')} | {_fmt(r.oos_buyhold_pct, '%')} "
            f"| {_fmt(r.edge, '%')} | {r.oos_trades} | {r.n_windows} "
            f"| {r.windows_beat_bh} | {_fmt(r.consistency * 100, '%')} | {cred} |"
        )
    # N/A al final
    for r in results:
        if r.error is not None or r.n_windows == 0:
            err = r.error or "sin ventanas (pocos datos)"
            print(
                f"| {r.strategy} | {r.pair} | {r.timeframe} | N/A | N/A | N/A | N/A | N/A | N/A | N/A | — |"
                f"  <!-- {err} -->"
            )

    # ---------- Resumen / conclusión ----------
    credible = [r for r in ok if r.credible]
    beat_bh_raw = [r for r in ok if r.edge > 0.0]  # gana en agregado, sin filtros de robustez
    print("\n## Resumen\n")
    print(f"- Celdas OOS que corrieron: {len(ok)} / {len(results)}")
    print(f"- Celdas donde la estrategia le gana a buy&hold en retorno OOS agregado (SIN filtro de robustez): {len(beat_bh_raw)}")
    print(
        f"- Celdas con edge OOS **CREÍBLE** (gana a b&h **Y** ret OOS>0 **Y** "
        f"trades≥{MIN_OOS_TRADES} **Y** consistencia>50%): **{len(credible)}**"
    )
    # Trampa clásica: "le gana a b&h" pero PERDIENDO plata (b&h perdió más). Eso NO es alpha.
    lose_less = [r for r in ok if r.edge > 0.0 and r.oos_return_pct <= 0.0]
    print(
        f"- De las que 'le ganan a b&h', {len(lose_less)} lo hacen **perdiendo plata en "
        "absoluto** (ret OOS ≤ 0): sólo cayeron menos en tramos bajistas — sentarse en USDT "
        "logra lo mismo sin operar. NO es edge."
    )

    if credible:
        print("\n### Celdas con edge OOS creíble\n")
        print("| Estrategia | Par | TF | edge | ret OOS | b&h OOS | trades | consistencia |")
        print("|---|---|---|---:|---:|---:|---:|---:|")
        for r in sorted(credible, key=lambda x: -x.edge):
            print(
                f"| {r.strategy} | {r.pair} | {r.timeframe} | {_fmt(r.edge, '%')} "
                f"| {_fmt(r.oos_return_pct, '%')} | {_fmt(r.oos_buyhold_pct, '%')} "
                f"| {r.oos_trades} | {_fmt(r.consistency * 100, '%')} |"
            )
    else:
        print("\n### Celdas con edge OOS creíble: NINGUNA")

    # Comparar variante de régimen vs ema_cross plano (item 2).
    print("\n## ¿El filtro de régimen mejora el OOS? (ema_cross_regime vs ema_cross)\n")
    print("| Par | TF | edge ema_cross | edge ema_cross_regime | ¿mejora? |")
    print("|---|---|---:|---:|:--:|")
    by_key = {(r.pair, r.timeframe, r.strategy): r for r in ok}
    regime_better = 0
    regime_total = 0
    for pair in PAIRS:
        for tf in TIMEFRAMES:
            base = by_key.get((pair, tf, "ema_cross"))
            reg = by_key.get((pair, tf, "ema_cross_regime"))
            if base is None or reg is None:
                continue
            regime_total += 1
            better = reg.edge > base.edge
            regime_better += int(better)
            print(
                f"| {pair} | {tf} | {_fmt(base.edge, '%')} | {_fmt(reg.edge, '%')} "
                f"| {'sí' if better else 'no'} |"
            )
    if regime_total:
        print(
            f"\nEl filtro de régimen mejora el edge OOS en {regime_better}/{regime_total} celdas."
        )

    print(
        "\n> ADVERTENCIA: modelo sin slippage, long-only, comisión taker 0.1%/lado. "
        "Es una aproximación; el mercado real es peor (slippage, profundidad, latencia)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
