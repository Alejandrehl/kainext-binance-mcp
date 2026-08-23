"""D4 — `examples/walk_forward.py` reimplementa el motor de `backtest.py`.

`sim_window` es una segunda implementacion del bucle de `simulate`, escrita a mano en el
script de research. Dos motores que deberian coincidir es exactamente como un resultado
publicado se vuelve incorrecto sin que nadie lo note.

Este test los enfrenta: si divergen, el research publicado en
`docs/research/walk_forward_results.md` esta mal y hay que republicarlo.
"""
import numpy as np
import pandas as pd
import pytest

from examples.walk_forward import sim_window
from kainext_binance_mcp.backtest import COMMISSION_TAKER, backtest_df


def _series(n: int, seed: int) -> pd.DataFrame:
    """Precios deterministas (sin aleatoriedad de test: mismo seed, misma serie)."""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, n)))
    open_ = np.concatenate([[100.0], close[:-1]]) * (1.0 + rng.normal(0.0, 0.001, n))
    return pd.DataFrame({
        "open_time": np.arange(n, dtype="int64"),
        "open": open_,
        "high": np.maximum(open_, close) * 1.001,
        "low": np.minimum(open_, close) * 0.999,
        "close": close,
        "volume": np.full(n, 10.0),
        "close_time": np.arange(n, dtype="int64") + 1,
    })


@pytest.mark.parametrize("seed", [1, 7, 42, 1234])
@pytest.mark.parametrize("fast,slow", [(5, 21), (8, 26), (12, 50)])
def test_sim_window_matches_the_library_engine(seed: int, fast: int, slow: int) -> None:
    """Sobre la serie COMPLETA, ambos motores deben dar el mismo retorno y los mismos trades."""
    df = _series(400, seed)
    result = backtest_df(df, "TESTUSDT", "1d", "ema_cross", fast=fast, slow=slow)

    from kainext_binance_mcp.backtest import ema_cross
    sig = ema_cross(df, fast=fast, slow=slow).to_numpy()
    ret_pct, n_trades = sim_window(
        df["open"].to_numpy(dtype="float64"),
        df["close"].to_numpy(dtype="float64"),
        sig, 0, len(df), COMMISSION_TAKER,
    )

    assert ret_pct == pytest.approx(result.total_return_pct, rel=1e-9, abs=1e-9)
    assert n_trades == result.n_trades


def test_both_engines_agree_on_a_hand_checkable_case() -> None:
    """Caso con aritmetica verificable a mano: una sola entrada, una sola salida."""
    df = pd.DataFrame({
        "open_time": [0, 1, 2, 3],
        "open": [10.0, 10.0, 20.0, 20.0],
        "high": [10.0, 20.0, 20.0, 20.0],
        "low": [10.0, 10.0, 20.0, 20.0],
        "close": [10.0, 20.0, 20.0, 20.0],
        "volume": [1.0] * 4,
        "close_time": [1, 2, 3, 4],
    })
    sig = pd.Series([1, 1, 0, 0])          # entra en open[1]=10, sale en open[2]=20
    c = 0.001
    expected = ((1.0 * (1 - c) / 10.0) * 20.0 * (1 - c) - 1.0) * 100.0   # ~+99.6%

    result = backtest_df(df, "T", "1d", "ema_cross", commission=c, _signal_override=sig)
    ret_pct, n_trades = sim_window(
        df["open"].to_numpy(dtype="float64"), df["close"].to_numpy(dtype="float64"),
        sig.to_numpy(), 0, len(df), c,
    )
    assert result.total_return_pct == pytest.approx(expected, abs=1e-9)
    assert ret_pct == pytest.approx(expected, abs=1e-9)
    assert n_trades == result.n_trades == 1
