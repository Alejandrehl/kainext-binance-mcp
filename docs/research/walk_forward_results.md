# Walk-forward / OUT-OF-SAMPLE — resultados

> **STATUS: COMPLETO.** Validación honesta out-of-sample corrida sobre klines reales
> públicas de mainnet (`api.binance.com`, sin keys, sin auth, read-only) el
> `07-06-2026 18:49:20` (America/Santiago). Reproducible con `examples/walk_forward.py`.
>
> **CONCLUSIÓN DE UNA LÍNEA:** **NO hay edge out-of-sample robusto en ninguna de las 4×3×3
> = 36 celdas.** El "edge" in-sample de la matriz era overfitting: no generaliza. De 36
> celdas, **0** ganan plata en absoluto OOS con consistencia y nº de trades creíbles. La
> única celda que sobrevive a un filtro mecánico resulta, al abrirla, un artefacto de una
> sola ventana. Detalle abajo.

---

## Metodología exacta

- **Fuente de datos:** `make_public_client()` = `Client()` pelado (sin api_key/secret, sin
  testnet). `get_klines` es un endpoint PÚBLICO de `api.binance.com`: no firma requests, no
  toca cuentas, no mueve fondos — es leer historial de precios público. Para juntar varios
  miles de velas se pagina con `startTime` (la API tope 1000 velas por llamada).
- **Pares:** BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT. **Timeframes:** 1h, 4h, 1d.
- **Velas reales juntadas por par/TF:** ver tabla "Velas reales usadas" más abajo. 5000 por
  par/TF en 1h y 4h; 3000 en 1d; **excepción SOLUSDT 1d = 2127** (SOL es más joven, no hay
  más historia pública). Total ≈ 51.000 velas reales descargadas.
- **Walk-forward rolling:** la serie se parte en bloques contiguos. En cada bloque `train`
  se hace **grid-search** del mejor parámetro (el que maximiza el retorno de la estrategia
  **in-sample** del train — lo que haría un optimizador ingenuo) y ese parámetro se mide en
  el bloque `test` **siguiente** (datos jamás vistos en la selección). `step = test` ⇒
  bloques de test **no solapados**: cada punto OOS se usa una sola vez y los bloques de test
  concatenados forman una curva de equity OOS continua y real.
- **Tamaños de ventana (velas):** 1h → train 800 / test 200; 4h → 500 / 150; 1d → 400 / 100.
  Esto da 17–30 ventanas de test por celda (ver tabla).
- **Grillas (rangos chicos a propósito):** `ema_cross` fast∈{5,8,12,20} × slow∈{21,26,50,100,200}
  (fast<slow); `rsi_threshold` low∈{20,25,30,35} × high∈{65,70,75,80}, n=14;
  `ema_cross_regime` = ema_cross que **sólo opera cuando hay tendencia fuerte**
  (`|EMA_fast/EMA_slow − 1| > θ`, θ∈{0, 0.01, 0.02, 0.05}; θ=0 colapsa al ema_cross plano).
- **Anti-lookahead (triple candado):** (1) los parámetros se eligen SÓLO con datos del
  bloque train; (2) dentro de cada ventana la simulación es la del harness — la posición que
  se mantiene entrando en la vela `i` la decide `signal[i-1]` y el fill ocurre en `open[i]`,
  nunca al `close` de la propia vela; (3) la señal se computa sobre la serie COMPLETA una vez
  por combinación de parámetros (EMA/RSI tibias en todo el rango, sin artefacto de reinicio
  de indicador al empezar cada ventana), pero la contabilidad de equity se restringe a los
  índices de la ventana. Las señales son causales (en `t` sólo usan closes ≤ `t`).
- **Costos:** comisión taker **0.1% por lado**. **Sin slippage** (limitación documentada; el
  mercado real es peor).
- **buy&hold OOS:** medido sobre EXACTAMENTE el mismo span concatenado (apples-to-apples).
- **Definición DURA de "edge creíble" (anti-auto-engaño):** una celda sólo es creíble si
  (1) le gana a b&h, **Y** (2) **gana plata en absoluto** (ret OOS > 0) — "perder menos que
  b&h en un tramo bajista" NO es alpha porque sentarse en USDT logra lo mismo con 0 trades y
  0 comisión, **Y** (3) trades OOS ≥ 20 (si no, es ruido), **Y** (4) consistencia > 50% (le
  gana a b&h en la mayoría de las ventanas, no por 1-2 ventanas explosivas con suerte).

---

## Velas reales usadas (paginadas con startTime)

| Par | TF | Velas | train | test | step | ventanas WF |
|---|---|---:|---:|---:|---:|---:|
| BTCUSDT | 1h | 5000 | 800 | 200 | 200 | 21 |
| BTCUSDT | 4h | 5000 | 500 | 150 | 150 | 30 |
| BTCUSDT | 1d | 3000 | 400 | 100 | 100 | 26 |
| ETHUSDT | 1h | 5000 | 800 | 200 | 200 | 21 |
| ETHUSDT | 4h | 5000 | 500 | 150 | 150 | 30 |
| ETHUSDT | 1d | 3000 | 400 | 100 | 100 | 26 |
| SOLUSDT | 1h | 5000 | 800 | 200 | 200 | 21 |
| SOLUSDT | 4h | 5000 | 500 | 150 | 150 | 30 |
| SOLUSDT | 1d | 2127 | 400 | 100 | 100 | 17 |
| BNBUSDT | 1h | 5000 | 800 | 200 | 200 | 21 |
| BNBUSDT | 4h | 5000 | 500 | 150 | 150 | 30 |
| BNBUSDT | 1d | 3000 | 400 | 100 | 100 | 26 |

## Resultados OUT-OF-SAMPLE (agregado sobre bloques de test concatenados)

`edge` = retorno OOS estrategia − retorno OOS buy&hold (mismo span). `consistencia` = % de
ventanas de test donde la estrategia le gana a buy&hold (~50% = volado de moneda).
`trades OOS` < 20 ⇒ ruido. La columna `¿creíble?` usa la **definición dura** de arriba.

| Estrategia | Par | TF | ret OOS | b&h OOS | edge | trades OOS | ventanas | gana b&h | consistencia | ¿creíble? |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|:--:|
| ema_cross | BNBUSDT | 1d | +4815.22% | +2696.58% | +2118.64% | 34 | 26 | 9 | +34.62% | — |
| ema_cross_regime | BNBUSDT | 1d | +3700.91% | +2696.58% | +1004.33% | 35 | 26 | 10 | +38.46% | — |
| ema_cross | ETHUSDT | 1d | +1263.86% | +1111.21% | +152.65% | 33 | 26 | 13 | +50.00% | — |
| ema_cross_regime | SOLUSDT | 1d | +111.26% | -36.63% | +147.89% | 26 | 17 | 6 | +35.29% | — |
| ema_cross_regime | ETHUSDT | 4h | +59.43% | -57.52% | +116.96% | 34 | 30 | 17 | +56.67% | ✅ |
| ema_cross_regime | ETHUSDT | 1d | +1168.09% | +1111.21% | +56.88% | 38 | 26 | 13 | +50.00% | — |
| rsi_threshold | BNBUSDT | 4h | +46.85% | -8.73% | +55.58% | 13 | 30 | 11 | +36.67% | — |
| ema_cross | ETHUSDT | 4h | -19.29% | -57.52% | +38.23% | 56 | 30 | 15 | +50.00% | — |
| ema_cross_regime | SOLUSDT | 1h | -12.05% | -49.63% | +37.57% | 35 | 21 | 12 | +57.14% | — |
| ema_cross | SOLUSDT | 1h | -18.55% | -49.63% | +31.08% | 75 | 21 | 9 | +42.86% | — |
| ema_cross | BTCUSDT | 4h | +10.04% | -16.39% | +26.43% | 51 | 30 | 15 | +50.00% | — |
| ema_cross | ETHUSDT | 1h | -23.72% | -46.54% | +22.82% | 45 | 21 | 10 | +47.62% | — |
| ema_cross_regime | BTCUSDT | 4h | +5.51% | -16.39% | +21.90% | 51 | 30 | 15 | +50.00% | — |
| ema_cross | BNBUSDT | 1h | -12.65% | -32.17% | +19.52% | 47 | 21 | 9 | +42.86% | — |
| rsi_threshold | BTCUSDT | 4h | +2.12% | -16.39% | +18.51% | 17 | 30 | 14 | +46.67% | — |
| ema_cross_regime | ETHUSDT | 1h | -30.51% | -46.54% | +16.02% | 44 | 21 | 9 | +42.86% | — |
| ema_cross_regime | SOLUSDT | 4h | -51.27% | -66.67% | +15.40% | 63 | 30 | 17 | +56.67% | — |
| ema_cross_regime | BTCUSDT | 1h | -15.36% | -29.58% | +14.21% | 22 | 21 | 9 | +42.86% | — |
| ema_cross | SOLUSDT | 4h | -53.10% | -66.67% | +13.56% | 62 | 30 | 14 | +46.67% | — |
| ema_cross_regime | BNBUSDT | 1h | -19.32% | -32.17% | +12.85% | 27 | 21 | 10 | +47.62% | — |
| rsi_threshold | SOLUSDT | 1h | -43.02% | -49.63% | +6.61% | 15 | 21 | 11 | +52.38% | — |
| rsi_threshold | ETHUSDT | 1h | -43.63% | -46.54% | +2.91% | 9 | 21 | 11 | +52.38% | — |
| ema_cross | SOLUSDT | 1d | -33.95% | -36.63% | +2.68% | 34 | 17 | 5 | +29.41% | — |
| ema_cross | BTCUSDT | 1h | -30.56% | -29.58% | -0.99% | 52 | 21 | 6 | +28.57% | — |
| rsi_threshold | BTCUSDT | 1h | -32.58% | -29.58% | -3.00% | 11 | 21 | 7 | +33.33% | — |
| rsi_threshold | BNBUSDT | 1h | -38.34% | -32.17% | -6.17% | 8 | 21 | 7 | +33.33% | — |
| ema_cross | BNBUSDT | 4h | -15.13% | -8.73% | -6.40% | 57 | 30 | 10 | +33.33% | — |
| ema_cross_regime | BNBUSDT | 4h | -20.87% | -8.73% | -12.14% | 57 | 30 | 11 | +36.67% | — |
| rsi_threshold | SOLUSDT | 4h | -80.25% | -66.67% | -13.59% | 8 | 30 | 12 | +40.00% | — |
| rsi_threshold | ETHUSDT | 4h | -86.18% | -57.52% | -28.66% | 7 | 30 | 9 | +30.00% | — |
| rsi_threshold | SOLUSDT | 1d | -80.89% | -36.63% | -44.26% | 4 | 17 | 6 | +35.29% | — |
| ema_cross_regime | BTCUSDT | 1d | +618.36% | +1228.95% | -610.59% | 46 | 26 | 8 | +30.77% | — |
| ema_cross | BTCUSDT | 1d | +524.69% | +1228.95% | -704.26% | 45 | 26 | 8 | +30.77% | — |
| rsi_threshold | ETHUSDT | 1d | +103.74% | +1111.21% | -1007.47% | 6 | 26 | 9 | +34.62% | — |
| rsi_threshold | BTCUSDT | 1d | -49.15% | +1228.95% | -1278.10% | 3 | 26 | 8 | +30.77% | — |
| rsi_threshold | BNBUSDT | 1d | +257.36% | +2696.58% | -2439.22% | 7 | 26 | 6 | +23.08% | — |

## Resumen

- Celdas OOS que corrieron: **36 / 36** (ninguna falló).
- Celdas donde la estrategia le gana a buy&hold en retorno OOS agregado (**SIN** filtro de
  robustez): **23 / 36**. Suena bien… hasta que se mira el filtro duro.
- De esas 23, **13 le ganan a b&h PERDIENDO PLATA en absoluto** (ret OOS ≤ 0): sólo cayeron
  menos en tramos bajistas. Sentarse en USDT logra lo mismo, con 0 trades y 0 comisión. **NO
  es edge.**
- Celdas con edge OOS **CREÍBLE** (gana a b&h **Y** ret OOS > 0 **Y** trades ≥ 20 **Y**
  consistencia > 50%): **1** … y al abrirla, también se cae (ver "Autopsia" abajo).

### La única celda que pasa el filtro mecánico — y por qué tampoco cuenta

| Estrategia | Par | TF | edge | ret OOS | b&h OOS | trades | consistencia |
|---|---|---|---:|---:|---:|---:|---:|
| ema_cross_regime | ETHUSDT | 4h | +116.96% | +59.43% | -57.52% | 34 | +56.67% |

**Autopsia (por-ventana, 30 ventanas, 34 trades ⇒ ~1.1 trades/ventana):**

- La **mediana** del retorno por ventana es **0.00%**: en la mayoría de las ventanas la
  estrategia **no operó** (quedó flat en cash). Muchas ventanas tienen **0 trades**.
- El +59.4% OOS viene **casi entero de UNA ventana** (la #15: +42.6%, con **0 trades** — fue
  simplemente estar long durante un rally, o sea buy&hold de ese bloque). **Quitando esa
  única ventana, el +59.4% se desploma a +11.8%.** Eso es fragilidad de cola, no edge.
- De sus 17 "victorias" sobre b&h, **9 son ventanas con 0 trades** (retorno exactamente
  0.00%): pura evitación de caídas (b&h bajó −18% a −29% y la estrategia, flat, hizo 0%). De
  nuevo: "estar en USDT", no timing.
- Consistencia 56.7% sobre 30 ventanas está dentro del ruido de un volado de moneda; con un
  grid-search de por medio (sesgo de selección), no es evidencia de nada.

**Veredicto de la celda:** artefacto. No es alpha tradeable.

## ¿El filtro de régimen mejora el OOS? (ema_cross_regime vs ema_cross)

| Par | TF | edge ema_cross | edge ema_cross_regime | ¿mejora? |
|---|---|---:|---:|:--:|
| BTCUSDT | 1h | -0.99% | +14.21% | sí |
| BTCUSDT | 4h | +26.43% | +21.90% | no |
| BTCUSDT | 1d | -704.26% | -610.59% | sí |
| ETHUSDT | 1h | +22.82% | +16.02% | no |
| ETHUSDT | 4h | +38.23% | +116.96% | sí |
| ETHUSDT | 1d | +152.65% | +56.88% | no |
| SOLUSDT | 1h | +31.08% | +37.57% | sí |
| SOLUSDT | 4h | +13.56% | +15.40% | sí |
| SOLUSDT | 1d | +2.68% | +147.89% | sí |
| BNBUSDT | 1h | +19.52% | +12.85% | no |
| BNBUSDT | 4h | -6.40% | -12.14% | no |
| BNBUSDT | 1d | +2118.64% | +1004.33% | no |

El filtro de régimen mejora el edge OOS en **6/12 celdas** — exactamente un **volado de
moneda**. No hay mejora sistemática; el filtro a veces ayuda (evita whipsaws en rango) y a
veces hace que te pierdas el inicio de la tendencia. Net: **no resuelve nada.**

---

## CONCLUSIÓN HONESTA (sin adornos)

**No hay edge out-of-sample robusto en ninguna estrategia / par / TF probados.** El "edge"
in-sample de la matriz era overfitting: cuando se eligen los parámetros con datos de train y
se miden en datos no vistos, el edge se evapora. Concretamente:

1. **0 de 36 celdas** ganan plata en absoluto OOS con un nº de trades creíble (≥20) **y**
   consistencia por encima del volado de moneda. La única que pasaba el filtro mecánico
   (ETH 4h ema_cross_regime) es, al abrir las ventanas, un artefacto de **una sola ventana**
   (sin ella: +59% → +12%) y de **estar flat en cash** durante caídas (9 de 17 "victorias"
   con 0 trades).

2. **El espejismo de "23/36 le ganan a b&h"** se desarma solo: **13** de esas 23 lo hacen
   **perdiendo plata** (b&h perdió más), lo cual es trivial — un bono en USDT te da lo mismo
   sin operar ni pagar comisión. Las otras 10 tienen consistencia de moneda al aire
   (≈30–50%) y/o pocos trades.

3. **En los activos en tendencia secular alcista (BTC 1d, BNB 1d), donde b&h compuso fortunas
   (+1229%, +2697%), TODAS las estrategias fueron destrozadas vs b&h** (edge −610% a −2439%).
   Esta es la verdad estructural: para un activo long-only en uptrend, estar en cash parte
   del tiempo es un lastre garantizado. Para superarlo, el timing tendría que ser
   extraordinariamente bueno — y no lo es.

4. **Los pocos retornos absolutos espectaculares** (BNB 1d ema_cross +4815%, ETH 1d +1264%)
   tienen consistencia de 35–50%: el retorno vino de 1–2 ventanas explosivas donde el
   parámetro quedó long en un moonshot. Eso es **suerte / dependencia de trayectoria**, no
   edge repetible. Clásico artefacto de cola en muestra chica.

5. **El filtro de régimen no salva nada:** mejora 6/12 celdas (moneda al aire).

**Implicación práctica para no perder plata real:** ninguna de estas estrategias simples
(ema_cross, rsi_threshold, ni la variante con filtro de régimen) justifica operar capital
real esperando ganarle a comprar y mantener. El experimento confirma —ahora con metodología
out-of-sample honesta y sin lookahead— lo que la matriz in-sample ya insinuaba: **no hay edge
fácil.** Este es un resultado válido y valioso: evita quemar capital persiguiendo un fantasma.

**Caveats que juegan A FAVOR de esta conclusión (es decir, la realidad es aún peor):** modelo
**sin slippage**, **long-only** (no captura caídas con cortos), comisión sólo taker 0.1%/lado,
y los costos reales (spread, profundidad, latencia, fills parciales) sólo empeoran el
resultado de cualquier estrategia que opere mucho. Donde una estrategia "ganó" fue justamente
operando poco o nada — es decir, acercándose a buy&hold o a estar en cash, no batiéndolos por
habilidad.

> **Reproducir:** `python examples/walk_forward.py` (read-only; datos públicos de mainnet, sin
> keys). Modelo sin slippage, long-only, comisión taker 0.1%/lado — aproximación optimista;
> el mercado real es peor.
