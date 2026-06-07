# kainext-binance-mcp

MCP server de Binance (**spot, capa 1**) — producto KaiNext. Permite, desde Claude Code,
ver saldos/órdenes/precios y **ejecutar órdenes spot con dinero real**, bajo un gate de
confirmación humana: nada se ejecuta sin un clic físico del operador, y el humano confirma
**exactamente** los campos que se ejecutan.

> ⚠️ **PLATA REAL.** En `mainnet` cada orden mueve dinero de verdad. **Empezá siempre en
> testnet** (ver más abajo) y pasá a mainnet sólo con todo verificado.
> ⚠️ **Capa 1 requiere macOS.** El confirmador usa `osascript` (diálogo nativo) para pedir
> el clic. En otros sistemas el confirmador no funciona todavía (ver Roadmap).

---

## Arquitectura: dos procesos, privilegio mínimo

| Proceso | Lo lanza | Key | Rol |
|---|---|---|---|
| **MCP server** `kainext-binance-mcp` | Claude Code (stdio) | **read-only** (`BINANCE_READ_*`) | lee, pre-valida y **propone** órdenes al confirmador. **No ejecuta, no tiene trade key.** |
| **Confirmador** `kainext-binance-mcp-confirmer` | vos, en otra terminal | **trade** (`BINANCE_TRADE_*`) | **única autoridad:** recibe los campos canónicos, renderiza el diálogo, re-valida, y **ejecuta sólo al clic**. |

Para que se ejecute una orden se necesitan **las dos cosas**: la trade key (sólo en el
confirmador) **y** el clic humano (sólo vos). El modelo nunca tiene ninguna de las dos.

**Single-tenant: un proceso por cuenta.** Cada server+confirmador atiende **una** cuenta de
Binance (las keys vienen del entorno). Para varias cuentas, levantá procesos separados con
sus propias env vars; no hay multiplexación dentro de un proceso.

---

## (a) Crear DOS API keys spot en Binance

Andá a Binance → **API Management** y creá **dos** keys spot distintas:

1. **READ-ONLY** (la usa el server):
   - **Enable Reading**: ON.
   - **Spot & Margin Trading**: **OFF**.
   - Withdrawals / Universal Transfer / Internal Transfer / Margin / Futures: **OFF**.

2. **TRADE** (la usa el confirmador):
   - **Enable Spot & Margin Trading**: **ON** (es el único flag que habilita tradear spot).
   - **Enable Withdrawals**: **OFF**.
   - **Permits Universal Transfer**: **OFF**.
   - **Enable Internal Transfer**: **OFF**.
   - **Margin / Futures / Portfolio Margin**: **OFF**.
   - **IP whitelist (Restrict access to trusted IPs only): OBLIGATORIA.** Sin IP whitelist
     Binance termina auto-borrando la key, y una trade key usable desde cualquier IP es un
     riesgo inaceptable. El confirmador **aborta el arranque** en mainnet si la trade key no
     tiene `ipRestrict` activo o tiene cualquiera de los permisos peligrosos arriba.

> El flag `enableSpotAndMarginTrading` agrupa spot + margin (Binance no los separa). La
> no-ejecución de margin se garantiza **en código**: el confirmador nunca llama endpoints de
> margin. Retiros y transferencias quedan **fuera de alcance permanente** (ninguna key los
> habilita).

---

## (b) Setear las env vars

| Variable | Proceso | Dónde va |
|---|---|---|
| `BINANCE_ENV` | ambos | `testnet` o `mainnet` (sin default → **aborta** si falta o es inválida) |
| `BINANCE_READ_API_KEY` / `BINANCE_READ_API_SECRET` | server | `.mcp.json` (vía `${VAR}`) o el shell del server |
| `BINANCE_TRADE_API_KEY` / `BINANCE_TRADE_API_SECRET` | confirmador | **SÓLO el shell donde lanzás el confirmador** |

> 🔒 **Regla dura:** la **trade key NUNCA va en `.mcp.json`** ni en el entorno de Claude Code.
> Vive sólo en el shell del confirmador. Así, aunque el modelo controle por completo el server,
> no tiene con qué ejecutar. Todas las variables son obligatorias y no-vacías en su proceso
> (whitespace cuenta como vacío → aborta).

En el shell del confirmador:

```bash
export BINANCE_ENV=testnet
export BINANCE_TRADE_API_KEY="...tu trade key..."
export BINANCE_TRADE_API_SECRET="...tu trade secret..."
```

---

## (c) Ejemplo de bloque `.mcp.json`

Sólo la **read key** + `BINANCE_ENV` (la trade key jamás va acá):

```json
{
  "mcpServers": {
    "binance": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/kainext/kainext-binance-mcp", "kainext-binance-mcp"],
      "env": {
        "BINANCE_ENV": "${BINANCE_ENV}",
        "BINANCE_READ_API_KEY": "${BINANCE_READ_API_KEY}",
        "BINANCE_READ_API_SECRET": "${BINANCE_READ_API_SECRET}"
      }
    }
  }
}
```

Los `${VAR}` se resuelven desde tu shell. Si una variable llega **sin expandir** (literal
`"${BINANCE_READ_API_KEY}"`), el server **aborta** con un mensaje claro: exportá las
variables antes de lanzar Claude Code. `.mcp.json` con secretos va en `.gitignore` (nunca se
versiona).

---

## (d) Arrancar el confirmador (requerido para ejecutar)

El confirmador **debe estar corriendo** para poder proponer/ejecutar órdenes. Las tools de
**lectura** funcionan sin él; las de **escritura** (`*_propose`) devuelven un error claro si
el confirmador no está.

En una terminal aparte (con la trade key exportada — paso (b)):

```bash
kainext-binance-mcp-confirmer
```

Queda escuchando en un Unix socket local. Cuando Claude proponga una orden, **aparece un
diálogo nativo** con los campos exactos (símbolo, lado, tipo, cantidad efectiva, precio,
`timeInForce`, notional estimado, y banner `TESTNET` / `⚠️ PLATA REAL`). El botón por
defecto es **Cancelar**; sólo al tocar **Confirmar** se ejecuta la orden.

---

## (e) Testnet-first (recomendado)

1. Sacá keys de testnet en **https://testnet.binance.vision** (login con GitHub → *Generate
   HMAC_SHA256 Key*). En testnet una sola key sirve para read y trade (no hay `apiRestrictions`).
2. Exportá `BINANCE_ENV=testnet` y las keys de testnet en `BINANCE_READ_*` / `BINANCE_TRADE_*`.
3. Probá el flujo completo con plata falsa antes de tocar mainnet.

**Test de integración** (corre el flujo real contra testnet; el clic se stubea, no abre
osascript):

```bash
export BINANCE_ENV=testnet
export BINANCE_TRADE_API_KEY=...   BINANCE_TRADE_API_SECRET=...
export BINANCE_READ_API_KEY=...    BINANCE_READ_API_SECRET=...
.venv/bin/python -m pytest -m integration -v
```

Sin keys de testnet, ese test **skipea** limpio. El resto de la suite corre sin red:
`.venv/bin/python -m pytest -q`.

## (f) Mainnet = plata real + macOS

- En `mainnet` cada orden mueve **dinero real**: el confirmador re-valida contra los filtros
  del símbolo, muestra el banner `⚠️ PLATA REAL` y espera tu clic. Empezá con órdenes mínimas.
- **Capa 1 requiere macOS**: el diálogo de confirmación usa `osascript`. Sin macOS el
  confirmador no puede pedir el clic (impl. headless/no-macOS pendiente).

## (g) Single-tenant (un proceso por cuenta)

Cada par server + confirmador opera **una sola** cuenta de Binance, definida por las env
vars de ese proceso. Para operar otra cuenta, levantá otro par de procesos con sus propias
credenciales. No hay multi-cuenta dentro de un mismo proceso.

---

## Tools disponibles (9)

### Lectura (5 · read key · sin gate)

| Tool | Qué hace | Params |
|---|---|---|
| `binance_get_balance` | Saldos spot (free/locked) no-cero | — |
| `binance_get_open_orders` | Órdenes spot abiertas + estado | `symbol?` |
| `binance_get_order_history` | Historial spot cerrado | `symbol`, `limit?` |
| `binance_get_account_info` | Flags + comisiones; permisos de la key (mainnet) | — |
| `binance_get_price` | Precio/ticker de un símbolo | `symbol` |

### Escritura (4 · two-phase · sólo spot · el server nunca ejecuta)

| Tool | Qué hace | Params |
|---|---|---|
| `binance_spot_order_propose` | Propone una orden; **no ejecuta**. Devuelve `intent_id` | `symbol`, `side`, `type`, `env`, `quantity?`, `quote_quantity?`, `price?`, `time_in_force?` |
| `binance_spot_order_status` | Consulta el desenlace de la propuesta | `intent_id` |
| `binance_cancel_order_propose` | Propone cancelar (re-consulta estado); **no cancela** | `symbol`, `order_id`, `env` |
| `binance_cancel_order_status` | Consulta el desenlace de la cancelación | `intent_id` |

## Flujo two-phase

1. **propose** — Claude llama `binance_spot_order_propose`. El server arma los campos
   canónicos, los manda al confirmador y devuelve un `intent_id` al instante (sin tocar
   Binance).
2. **confirmás** — en el confirmador aparece el diálogo con los valores exactos que se van a
   ejecutar. Tocás **Confirmar** (o **Cancelar**). Sólo al confirmar, el confirmador re-valida
   y ejecuta con la trade key.
3. **status** — Claude pollea `binance_spot_order_status(intent_id)`: `pending` → `executed`
   (con el resultado) / `rejected` / `expired` / `failed`. Si el confirmador está caído, el
   estado es `unknown` (verificá en Binance; la orden pudo haberse ejecutado).

La cancelación sigue el mismo patrón con `binance_cancel_order_propose` / `_status`.
