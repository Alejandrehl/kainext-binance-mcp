# CLAUDE.md — orientación para una sesión nueva

Este repo es **dos cosas a la vez**, y confundirlas es el error caro:

1. **Un servidor MCP de Binance spot, en producción, con dinero real.** Publicado en PyPI
   (`kainext-binance-mcp`) y en el MCP Registry. Lo usa el operador a diario. 25 tools,
   5 prompts, 8 recursos `kb://`.
2. **Un motor de research de futuros USD-M**, offline y sin keys, detrás del extra
   `[research]`. No expone ninguna tool. Es la Fase 0 de **Alpha**, el programa de trading sistemático del operador.

**Qué NO es:** un bot de trading. La ejecución de órdenes es spot-only y requiere un clic
humano en un proceso aparte. El motor de futuros investiga; no puede colocar una orden.

---

## Invariantes — romper uno de estos es un incidente, no un bug

| Invariante | Por qué |
|---|---|
| **El modelo nunca tiene una trade key** | El servidor corre con key read-only. La trade key vive SOLO en el proceso confirmer, que el operador lanza aparte. Es la garantía central del producto |
| **`futures/` es keyless y offline** | No importa un client, no lee una API key, no usa el secret. Lee archivos públicos. Si alguna vez necesita una key, el diseño está mal |
| **El servidor no importa `futures/`** | Import perezoso. Sin el extra `[research]` el servidor arranca igual. Romperlo deja sin servidor a quien instala por `uvx` |
| **`_INSTRUCTIONS` (`server.py`) es comportamiento, no documentación** | FastMCP lo inyecta en **toda sesión de todo cliente MCP**. Editarlo cambia cómo se comporta cada sesión de IA. Ya causó un incidente: en mcp 2.0 el 2º posicional pasó de `instructions` a `title`, y pasarlo posicional dejaba la doctrina sin inyectar, en silencio |
| **`instructions=` va por nombre** | Ver arriba. `tests/test_consistency.py` lo verifica |
| **Nada de credenciales en `.mcp.json`** | El repo es público. El archivo se versiona pero solo declara MCPs remotos con OAuth; el gate rompe el build si aparece algo con forma de key |

---

## La doctrina tiene dos regímenes (y no se mezclan)

`kb://discipline` cambió el `23-08-2026`. Antes decía "never use leverage". Ahora:

- **Reglas 1-6 — portafolio de largo plazo.** Spot, sin apalancamiento, DCA, position
  sizing, cosecha. **Intactas.**
- **Regla 7 — research sistemático.** Admite apalancamiento **solo** si pasa todas:
  validación out-of-sample corregida por multiple testing (DSR + PBO), reglas escritas
  antes de ejecutar, sizing por volatilidad, circuit breaker, capital segregado, y registro
  de cada decisión y fill.

El apalancamiento **direccional discrecional sigue prohibido**. La regla 7 no es una puerta
trasera, y el texto lo dice así. Si te preguntan por el portafolio, la respuesta sale de las
reglas 1-6.

---

## Gates — lo que te va a rechazar

```bash
uv pip install -e ".[dev,research]"       # sin `research`, futures/ no importa y divergís del CI
ruff check src/ tests/ examples/ && mypy && pytest -q
```

- **Cobertura ≥ 90%**, medida sobre todo `kainext_binance_mcp` (incluye `futures/`).
- **Cero warnings.** `filterwarnings = ["error"]`: un warning nuevo rompe el build. Los
  ignores existentes nombran su causa upstream — no agregues uno sin explicar por qué.
- **`tests/test_consistency.py`** falla cuando la documentación deja de describir el
  producto: versión en lockstep, conteos del README (total **y** por sección), alcance
  declarado, y credenciales en `.mcp.json`. Es el test que más rechaza PRs de solo-docs.
- **`mypy --strict`** sobre los dos paquetes de `src/`. `examples/` NO está cubierto por
  mypy: por eso la lógica de research vive en `futures/`, no ahí.

CI corre esas mismas cosas en 4 celdas (ubuntu/macos × py3.12/3.13) + `pip-audit` + CodeQL.

---

## El objetivo es plata, y el rigor es el seguro

**Alpha** existe para generar ingresos — el nombre es la métrica: el *alpha* es el retorno
*por sobre* el benchmark. Si holdear rinde más, el alpha es cero y no hay negocio.

Los gates de acá arriba no son celo técnico: son lo que impide meter capital real en un edge
que no existe. Probar 1.000 configuraciones **garantiza** encontrar ruido que parece alpha;
DSR y PBO son lo que separa una de la otra. El rigor protege la plata, no la reemplaza.

## Nunca complaciente: la autoridad es la evidencia

Regla del operador (`kainext-hq/CLAUDE.md` §4.5.11), y acá pesa más que en ningún otro repo
porque hay dinero real en juego:

- **No asumas que el operador tiene razón por ser el operador.** Su input es contexto, no
  mandato: contrastalo con el estado del arte y decile si hay algo mejor, aunque ya lo haya
  empezado a construir.
- **Tampoco asumas que vos tenés razón.** Tu salida suena segura incluso cuando está
  equivocada. **Verificá toda afirmación que mueva una decisión** antes de presentarla, y
  decí explícitamente **qué no pudiste verificar**.
- En este repo eso es literal: un CI puede reportar verde por un exit code mientras el run
  está en `failure`, y un backtest puede verse espectacular por un artefacto de datos.
  **Complacer y capitular son la misma falla con distinto disfraz.**

## Estado y siguiente paso

**Fase 0 va en 2 de 8 módulos.** `futures/data.py` y `futures/universe.py` están hechos,
testeados y verificados contra datos reales. Faltan `costs`, `portfolio`, `stats`,
`research`, `db/` y `strategies/`.

El detalle, con el estado real de las tres fases, está en **[`ROADMAP.md`](ROADMAP.md)**.
La arquitectura y los gotchas de datos, en
**[`docs/architecture.md`](docs/architecture.md)**.

---

## Dónde vive el resto

- **Board (to-dos):** Linear, team `Ale Hernández SpA`, proyecto **Alpha**. El MCP de Linear
  está declarado en el `.mcp.json` de este repo.
- **Decisiones y hallazgos (no to-dos):** el vault Obsidian del operador,
  `06-finanzas/inversiones/trading-journal/`. **Linear = accionable, vault = segundo
  cerebro.** No mezclar.
- **Centro de mando:** `~/Sites/kainext-workspace/kainext-hq` — reglas transversales del
  operador (`CLAUDE.md` §4): plan→revisión→aprobación antes de ejecutar, barra 10/10,
  fechas `DD-MM-YYYY`, verificar la hora real antes de escribir un timestamp.

## Convenciones

- **Docs publicados y superficie del producto: inglés.** Comentarios y docstrings del
  código: español (es lo que ya hay). Los dos write-ups de `docs/research/` están en
  español y se quedan así.
- **Conventional Commits.** Toda entrada visible al usuario va al `CHANGELOG.md`.
- **Sin deuda técnica**: nada de `TODO`/`FIXME` ni placeholders. Si encontrás deuda, se
  arregla o se documenta con su causa — no se rodea.
