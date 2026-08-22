<!-- Generado por examples/experiment_matrix.py — corrida 07-06-2026 18:36:42 (America/Santiago).
     Reproducir: .venv/bin/python examples/experiment_matrix.py
     Las klines de mainnet son móviles (ventana de 1000 velas hasta el momento de la corrida),
     así que volver a correr dará otra ventana y otros números. Esta tabla es esa corrida. -->

# Matriz de backtests in-sample  (DATA_SOURCE=mainnet_public, limit=1000 velas/celda)

Datos: klines PÚBLICAS de mainnet (api.binance.com, sin keys, sin auth, read-only).


## Tabla de resultados (ordenada por edge desc)

| Par | TF | Estrategia | total_return | buy&hold | edge | n_trades | win_rate | max_dd |
|---|---|---|---:|---:|---:|---:|---:|---:|
| SOLUSDT | 1d | ema_cross | +313.94% | +272.25% | +41.69% | 15 | +40.00% | +55.80% |
| ETHUSDT | 1d | ema_cross | +47.52% | +5.85% | +41.67% | 17 | +29.41% | +46.03% |
| ETHUSDT | 1d | composite | +27.82% | +5.85% | +21.97% | 57 | +50.88% | +42.69% |
| SOLUSDT | 1h | ema_cross | -0.79% | -21.78% | +20.99% | 15 | +20.00% | +12.81% |
| BTCUSDT | 1d | ema_cross | +162.37% | +144.93% | +17.44% | 16 | +37.50% | +31.87% |
| SOLUSDT | 4h | ema_cross | -29.22% | -46.58% | +17.36% | 17 | +23.53% | +41.62% |
| ETHUSDT | 1h | ema_cross | -10.43% | -27.20% | +16.77% | 13 | +15.38% | +17.16% |
| SOLUSDT | 4h | rsi_threshold | -30.54% | -46.58% | +16.04% | 4 | +75.00% | +42.95% |
| BTCUSDT | 1h | ema_cross | -2.67% | -18.44% | +15.78% | 12 | +16.67% | +10.08% |
| ETHUSDT | 4h | ema_cross | -28.30% | -43.30% | +15.00% | 16 | +25.00% | +33.73% |
| BNBUSDT | 1h | ema_cross | +10.98% | -3.18% | +14.16% | 14 | +42.86% | +6.17% |
| BNBUSDT | 4h | rsi_threshold | -17.38% | -28.96% | +11.58% | 4 | +50.00% | +35.70% |
| SOLUSDT | 1h | composite | -11.44% | -21.78% | +10.34% | 49 | +32.65% | +16.05% |
| BNBUSDT | 1h | composite | +5.48% | -3.18% | +8.66% | 53 | +45.28% | +8.09% |
| SOLUSDT | 4h | composite | -38.72% | -46.58% | +7.86% | 53 | +49.06% | +48.16% |
| BTCUSDT | 1h | composite | -10.94% | -18.44% | +7.51% | 45 | +28.89% | +12.04% |
| BNBUSDT | 4h | ema_cross | -21.74% | -28.96% | +7.22% | 17 | +29.41% | +28.28% |
| ETHUSDT | 1h | rsi_threshold | -20.11% | -27.20% | +7.09% | 4 | +50.00% | +30.48% |
| SOLUSDT | 1h | rsi_threshold | -18.45% | -21.78% | +3.33% | 2 | +50.00% | +29.83% |
| BTCUSDT | 4h | ema_cross | -24.96% | -27.96% | +3.00% | 23 | +26.09% | +29.01% |
| ETHUSDT | 4h | composite | -40.60% | -43.30% | +2.70% | 44 | +31.82% | +46.05% |
| ETHUSDT | 1h | composite | -25.08% | -27.20% | +2.12% | 43 | +23.26% | +25.79% |
| BTCUSDT | 1h | rsi_threshold | -16.40% | -18.44% | +2.04% | 3 | +33.33% | +23.20% |
| BTCUSDT | 4h | composite | -25.93% | -27.96% | +2.03% | 54 | +33.33% | +28.07% |
| BTCUSDT | 4h | rsi_threshold | -25.97% | -27.96% | +1.99% | 3 | +66.67% | +32.51% |
| ETHUSDT | 4h | rsi_threshold | -42.46% | -43.30% | +0.84% | 3 | +66.67% | +49.14% |
| BNBUSDT | 1h | rsi_threshold | -3.32% | -3.18% | -0.14% | 4 | +75.00% | +15.77% |
| BNBUSDT | 4h | composite | -37.99% | -28.96% | -9.03% | 49 | +30.61% | +41.00% |
| BNBUSDT | 1d | ema_cross | +163.89% | +187.45% | -23.56% | 19 | +36.84% | +35.33% |
| ETHUSDT | 1d | rsi_threshold | -48.55% | +5.85% | -54.40% | 2 | +50.00% | +58.52% |
| BNBUSDT | 1d | composite | +115.67% | +187.45% | -71.79% | 62 | +59.68% | +40.11% |
| BTCUSDT | 1d | composite | +70.86% | +144.93% | -74.07% | 59 | +50.85% | +20.12% |
| SOLUSDT | 1d | composite | +152.05% | +272.25% | -120.20% | 45 | +48.89% | +58.81% |
| BTCUSDT | 1d | rsi_threshold | +4.97% | +144.93% | -139.96% | 3 | +100.00% | +25.94% |
| BNBUSDT | 1d | rsi_threshold | +17.83% | +187.45% | -169.63% | 3 | +66.67% | +38.48% |
| SOLUSDT | 1d | rsi_threshold | -35.52% | +272.25% | -307.77% | 2 | +50.00% | +53.85% |

## Resumen

- Celdas totales en la matriz: 36 (4×3×3)
- Celdas que corrieron OK: 36
- Celdas N/A (fetch/backtest falló): 0
- Celdas con edge>0 (sin filtro de trades): 26 / 36
- Celdas con edge>0 **Y** n_trades>=10 (las únicas creíbles): 19 / 36

### Celdas con edge creíble (edge>0 y n_trades>=10)

| Par | TF | Estrategia | edge | total_return | buy&hold | n_trades | win_rate | max_dd |
|---|---|---|---:|---:|---:|---:|---:|---:|
| SOLUSDT | 1d | ema_cross | +41.69% | +313.94% | +272.25% | 15 | +40.00% | +55.80% |
| ETHUSDT | 1d | ema_cross | +41.67% | +47.52% | +5.85% | 17 | +29.41% | +46.03% |
| ETHUSDT | 1d | composite | +21.97% | +27.82% | +5.85% | 57 | +50.88% | +42.69% |
| SOLUSDT | 1h | ema_cross | +20.99% | -0.79% | -21.78% | 15 | +20.00% | +12.81% |
| BTCUSDT | 1d | ema_cross | +17.44% | +162.37% | +144.93% | 16 | +37.50% | +31.87% |
| SOLUSDT | 4h | ema_cross | +17.36% | -29.22% | -46.58% | 17 | +23.53% | +41.62% |
| ETHUSDT | 1h | ema_cross | +16.77% | -10.43% | -27.20% | 13 | +15.38% | +17.16% |
| BTCUSDT | 1h | ema_cross | +15.78% | -2.67% | -18.44% | 12 | +16.67% | +10.08% |
| ETHUSDT | 4h | ema_cross | +15.00% | -28.30% | -43.30% | 16 | +25.00% | +33.73% |
| BNBUSDT | 1h | ema_cross | +14.16% | +10.98% | -3.18% | 14 | +42.86% | +6.17% |
| SOLUSDT | 1h | composite | +10.34% | -11.44% | -21.78% | 49 | +32.65% | +16.05% |
| BNBUSDT | 1h | composite | +8.66% | +5.48% | -3.18% | 53 | +45.28% | +8.09% |
| SOLUSDT | 4h | composite | +7.86% | -38.72% | -46.58% | 53 | +49.06% | +48.16% |
| BTCUSDT | 1h | composite | +7.51% | -10.94% | -18.44% | 45 | +28.89% | +12.04% |
| BNBUSDT | 4h | ema_cross | +7.22% | -21.74% | -28.96% | 17 | +29.41% | +28.28% |
| BTCUSDT | 4h | ema_cross | +3.00% | -24.96% | -27.96% | 23 | +26.09% | +29.01% |
| ETHUSDT | 4h | composite | +2.70% | -40.60% | -43.30% | 44 | +31.82% | +46.05% |
| ETHUSDT | 1h | composite | +2.12% | -25.08% | -27.20% | 43 | +23.26% | +25.79% |
| BTCUSDT | 4h | composite | +2.03% | -25.93% | -27.96% | 54 | +33.33% | +28.07% |

_(Nota: 7 celda(s) tienen edge>0 pero con <10 operaciones — se descartan por no creíbles: muestra de trades insuficiente.)_

> ADVERTENCIA: resultados IN-SAMPLE (un solo tramo de velas, sin out-of-sample). Cualquier 'ganador' es una hipótesis, no evidencia de edge real. Validación out-of-sample en datos no vistos es obligatoria antes de afirmar nada.
