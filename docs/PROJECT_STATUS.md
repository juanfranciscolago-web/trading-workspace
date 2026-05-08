# trading-workspace — Project Status

**Última actualización**: 7 de mayo 2026 (Sprint 2B.4 cerrado, post push commit `0d930c3`)
**Branch**: `main` — up to date with `origin/main`
**Owner**: Juan
**Repo**: github.com/juanfranciscolago-web/trading-workspace
**Local**: /Users/JUAN/Documents/trading-workspace

Este documento describe **cómo va la implementación**: visión, sprints cerrados, bloques pendientes, tech debt, convenciones y metodología. Se actualiza después de cada sprint o milestone significativo.

Para la **especificación detallada del sistema** (arquitectura completa, agentes, protocolos, schemas, riesgo, stack, dashboard, métricas), ver `docs/sistema_multiagente_trading.md`.

Si hay contradicciones entre los dos documentos, gana este (la realidad construida) y se documenta la divergencia para revisar la spec.

---

## 1. Visión

Sistema multi-agente de trading que combina varios agentes LLM especializados (ATHENA, APOLLO, HERMES, NYX, VESTA) bajo supervisión de un agente de riesgo (ATLAS). El sistema opera en paper trading hasta validación, después transición gradual a capital real. Stack: Python 3.14 + FastAPI + PostgreSQL/TimescaleDB + Redis Streams en backend, Next.js 16 + React 19 + Tailwind v4 en frontend.

El objetivo del proyecto no es solo construir el sistema de trading sino también construir la observabilidad y el riesgo **antes** de generar alpha. La filosofía es: nunca poner capital sin un dashboard que muestre qué hace el sistema, sin alertas cuando algo falla, y sin un agente de riesgo (ATLAS) que pueda parar todo.

---

## 2. Roadmap macro (8 sprints)

| # | Sprint | Objetivo | Status |
| :---- | :---- | :---- | :---- |
| 1 | Foundations | Schemas, bus Redis, migraciones, mock agents | ✅ Completo (28 abr 2026) |
| 2 | ATLAS + Dashboard | ATLAS operativo, dashboard observabilidad, alertas | 🔄 ~90% (sub-fase 2B.4 cerrada, próximo 2B.5) |
| 3 | ATHENA debate-only | ATHENA generando research, sin ejecución | ⏳ |
| 4 | APOLLO + HERMES debate-only | Agentes ejecutivos en modo debate | ⏳ |
| 5 | Schwab paper trading | Conexión real al broker, paper trades reales | ⏳ |
| 6 | APOLLO + HERMES ejecutando | Trades reales en paper | ⏳ |
| 7 | NYX integration | Agente de noticias macro | ⏳ |
| 8 | VESTA integration | Agente de cobertura/hedging | ⏳ |
| — | Mes 5-6 | Estabilización y validación en paper | ⏳ |
| — | Mes 7+ | Transición gradual a capital real | ⏳ |

---

## 3. Sprint 1 — Foundations ✅

**Período**: completado 28 abril 2026. **Métricas**: 249 tests, +5009 LOC, 43 archivos. **Último commit**: `76e6a0b` (Sprint 1 COMPLETE).

### Entregables

- Schemas Pydantic completos para mensajes inter-agente.  
- Bus Redis Streams operativo para comunicación async.  
- PostgreSQL + 9 migraciones iniciales (V001-V009).  
- 5 mock agents alpha + ATLAS.  
- Flujo completo proposal → critique → decision testeado end-to-end.

### Tech debt heredada a Sprint 2

- ⚠️ ClaudeRouter integración real (movida a Sprint 2).  
- ⚠️ LLM cost tracking llamada real (movida a Sprint 2 — implementada en 2B.1).  
- ⚠️ `run_cycle.py` sin DB obligatoria (media prioridad, sigue abierta).  
- ⚠️ Error handling en `MessageRepository` (media prioridad, sigue abierta).

---

## 4. Sprint 2 — ATLAS + Dashboard 🔄

**Período**: arrancó después del 28 abril, en progreso. **Métricas hasta hoy**: ~39 commits, ~26300 / -350 LOC, 170+ archivos. **Sub-fases**: 2A → 2B.1 → 2B.2 → 2B.3 → 2B.4 (cerradas).

### 4.1 Sprint 2A: ATLAS infrastructure ✅

**Commit**: `b19919e`. Stat: 39 files, +4283 / -250 LOC.

Entregables:

- `config/limits.yaml` + `config/buckets.yaml` — Phase 1 calibration: 25 tickers, 7 buckets.  
- `src/multi_agent/risk/`: ATLAS core, 8 risk checks, portfolio snapshot. 96 tests.  
- `src/multi_agent/consumers/`: AtlasConsumer (Redis Streams, fail-closed, DLQ). 13 tests.  
- `src/multi_agent/execution/`: PaperExecutor (Level-2 slippage, partial fills). 15 tests.  
- DB migraciones V010-V013.  
- `scripts/seed_portfolio.py`: 10 posiciones sintéticas para testing.  
- `run_async_cycle.py`: orchestrator del flujo async.

### 4.2 Sprint 2B.1: API + LLM tracking ✅

**Commits**: `39d80b8`, `3f1a682`, `63f32cc`.

Entregables:

- **LLM cost tracking**: `track_llm_cost` decorator (sync/async), `LLMCostRepository` con 5 métodos. Config en `config/llm_pricing.yaml`. Migración V014. 28 tests.  
- **FastAPI foundation**: lifespan async, TTL-cached snapshot, launcher localhost-only.  
- **Endpoints ATLAS**: `GET /atlas/health`, `POST /atlas/validate`, `GET /atlas/limits`, `GET /atlas/buckets`. 30 tests.  
- **Endpoints portfolio/trades/costs**: `GET /portfolio/snapshot`, `/portfolio/positions`, `/trades/validations` (+ `/{correlation_id}`), `/costs/summary`, `/by-agent`, `/by-task`, `/costs/daily`. ValidationRepository + 8 endpoints.

### 4.3 Sprint 2B.2: Alerts worker ✅

**Commits**: `66f52a6`, `6254188`.

Entregables:

- **AlertWorker async loop**: subscribe → router.route() per event. Shutdown sequence: stop → drain in-flight (5s timeout) → close Redis. 3 shutdown tests.  
- **Retry queue (2B.2.b)**: RetryWorker polls DB cada 30s, backoff 30s → 2min → 5min → 15min (4 attempts). Migración V016 (`given_up_at` column). Dedup bypassed by design para retries. TelegramSink shared connection.

### 4.4 Sprint 2B.3: Dashboard Slice A.1 (Home view) ✅

**Período**: 4-5 mayo 2026. 12 commits. Último: `56d6263`.

Entregables:

- **Backend**: `TRADING_MODE` config con double-confirmation token, `/system/status` y `/system/mode` endpoints, `DailyTotalsRow` Pydantic typed.  
- **Frontend infra**: AppShell con Sidebar 180px (3 secciones VIEWS / CONTROL / DATA con badges sprint) + Header 56px (brand + mode badge + system semaforo + clock + updated).  
- **Bug fix histórico**: `globals.css` línea 10 era `--font-sans: var(--font-sans)` autoreferencial → fallback a serif. Fix a `var(--font-geist-sans)`.  
- **Frontend hooks**: `useSystemStatus` (30s), `useSystemMode` (60s), `useAlerts` (30s, limit=5), `useAtlasHealth` (30s), `useCostsDaily` (30s), `usePortfolioSnapshot` (30s). `fetcher` extendido con query params opcionales backward-compatible.  
- **Frontend widgets** (6 totales en grid asimétrico):  
  - Status row (4 cols): SystemStatusCard, TradingModeCard, RiskModeCard, LLMCostCard.  
  - Data row (2x2 cols): NavPnLCard, RecentAlertsCard.  
- **Real-time clock**: `useEffect` + `setInterval(1s)` + cleanup. `Intl.DateTimeFormat` con `America/New_York` para DST automático.  
- **Stub pages**: `/portfolio` y `/risk` para evitar 404 (Slice A.2 y A.3 pendientes).  
- **Tipos OpenAPI**: `AlertItem` y `AlertsResponse` definidos en hook (workaround para schema unnamed).

### 4.5 Sprint 2B.4: Dashboard Config + Agents ✅

**Período**: 6-7 mayo 2026. Cerrado.

#### Bloques completados ✅

| Bloque | Commit | Descripción |
| :---- | :---- | :---- |
| **F.4.2 — Refactor badges** | `688e6ed` | Reemplazó badges inline en header.tsx, trading-mode-card.tsx, risk-mode-card.tsx por wrappers tipados `<ModeBadge>` y `<RiskBadge>` que envuelven el componente shadcn Badge. Type guards (sin casts) para narrowing seguro de `data.mode` y `data.risk_mode` desde string genérico al union literal. Si backend devuelve un mode/level inesperado, el widget retorna null en lugar de pintar con color undefined. |
| **B.4.1 — Endpoints agents** | `9e8da34` | `GET /agents` (lista combinada de `agents.config` + `agents.state`, LEFT JOIN, ordered by agent\_id) y `POST /agents/{agent_id}/toggle` (explicit set de `is_active`, idempotente). AgentsRepository nuevo en persistence/. 11 tests pytest, 0 regresiones (93 total tests/api/). |
| **F.4.1 — AgentsCard widget** | `ee1a12d` | Hook `use-agents` con tipos locales (Agent, AgentsResponse, ToggleAgentResponse), `useAgents()` con polling 30s y `useToggleAgent()` con useMutation + invalidateQueries. AgentsCard widget con AgentRow sub-component, dot status (idle=green, running=blue, error=red, stopped=gray, null=gray fallback), formatCost defensive, pendingAgentId para deshabilitar solo el switch in-flight, border-left gris neutro. Switch shadcn instalado. Widget agregado al Home grid full-width tercera fila (sm:col-span-2 lg:col-span-4). Verificado visual y funcionalmente. |
| **F.4.3 — Config view solo lectura** | `0d930c3` | Backend: nuevos endpoints `GET /config/limits` y `GET /config/buckets` que devuelven raw YAML parseado (passthrough dict, sin re-validación con Pydantic). Permite que la vista refleje el archivo real, incluyendo secciones placeholder como `liquidity` que `/atlas/limits` omite. 8 tests pytest, 101 total tests/api/. Frontend: hooks `useLimitsConfig`/`useBucketsConfig` con `staleTime: Infinity` (config no cambia en runtime), página `/config` con 3 secciones (Trading Mode card + Limits/Buckets como JSON pretty-printed). Sidebar: removido badge "2B.4" del item Config. |

#### Diferido a Sprint 2B.5

- Toggle de Trading Mode con safeguards (double-confirmation token).  
- Editores de limits/buckets si son realmente necesarios (probablemente NO — los limits no se editan en runtime usualmente).

#### Descubrimiento clave (6 mayo)

Verificando el backend antes de planear B.4.1, descubrimos que **la infraestructura del toggle de agents ya existía**:

- `agents.config.is_active` (boolean) ya en DB.  
- `agents.state` con `status`, `current_task`, `last_heartbeat`, `last_proposal_at`, `last_error`, `error_count_24h`, `llm_cost_today_usd`.  
- 6 agents registrados: apollo, athena, atlas, hermes, nyx, vesta — todos `active=true`.  
- `/costs/by-agent` endpoint ya existía.

**Implicación**: B.4.1 solo expuso vía API lo que ya existía. Sin trabajo de schema/migration.

#### Descubrimiento clave (7 mayo)

Verificando shapes para F.4.3, descubrimos que **`/atlas/limits` no expone todas las secciones del archivo**:

- `limits.yaml` tiene 5 secciones: `pnl`, `exposure`, `greeks`, `buying_power`, `liquidity`.  
- `Phase1Limits` Pydantic class tiene 4 sub-modelos correspondientes a las primeras 4. **No hay `LiquidityLimits`** — el loader ignora la sección.  
- `liquidity` es placeholder de scope futuro (no hay risk check que lo use todavía).

**Implicación**: para una vista "Config viewer" que muestra el archivo as-written, no podíamos reusar `/atlas/limits`. Decisión: crear endpoints `/config/limits` y `/config/buckets` que devuelven raw YAML passthrough. Mantienen al backend como fuente única de verdad sin acoplar el frontend al filesystem.

---

## 5. Sprints 3-8 (visión macro, no detalle)

### Sprint 3 — ATHENA debate-only

- ATHENA generando research / proposals.  
- Sin ejecución todavía. Las proposals se logean para review humano.  
- Conexión real con ClaudeRouter usando los hooks de Sprint 2B.1.

### Sprint 4 — APOLLO + HERMES debate-only

- APOLLO (decisor de portfolio) y HERMES (ejecutor de órdenes) generando proposals/critiques.  
- Sin ejecución.

### Sprint 5 — Schwab paper trading

- Conexión real a Schwab API.  
- Paper trades reales (no más PaperExecutor sintético).  
- Vista Market en el dashboard (lectura de market data).  
- View Backtesting en dashboard.

### Sprint 6 — APOLLO + HERMES ejecutando

- Los agentes ejecutivos generan trades reales en paper.  
- Validación con ATLAS antes de cada orden.

### Sprint 7 — NYX integration

- Agente de noticias macro / contexto de mercado.

### Sprint 8 — VESTA integration

- Agente de cobertura / hedging de portfolio.

### Mes 5-6 — Estabilización

- Validación en paper trading completo.  
- Métricas de performance vs benchmark.

### Mes 7+ — Capital real

- Transición gradual: % bajo, scaling según resultados.

---

## 6. Pendientes inmediatos (próxima sesión)

### Sprint 2B.5 (siguiente)

- **Toggle de Trading Mode con safeguards** (double-confirmation token). Prioridad alta dentro de 2B.5: es el bloque que justifica el sprint.  
- Editores de limits/buckets si son realmente necesarios (probablemente NO — los limits no se editan en runtime usualmente).  
- Cleanup chore: remover type guards muertos en `TradingModeCard` y `RiskModeCard` (ver §7 tech debt).

### Slices A.2 + A.3 (en algún momento)

- A.2: Portfolio view real (hoy stub).  
- A.3: Risk view real (hoy stub).

---

## 7. Tech debt acumulada

### Heredada de Sprint 1

- ⚠️ `run_cycle.py` sin DB obligatoria (media prioridad).  
- ⚠️ Error handling en `MessageRepository` (media prioridad).

### Generada en Sprint 2

**Backend**:

- ⚠️ `cost_usd` como `float` en `DailyTotalsRow` → migrar a `Decimal` cuando real-money trading.  
- ⚠️ `llm_cost_repository.py` importa de `api/schemas/responses.py` — dependencia inversa de capas, candidata a refactor.  
- ⚠️ `PostgresPool` wrapper no propaga timeout — bypass con `psycopg.connect()` directo + `connect_timeout`.  
- ⚠️ Backend no expone enums OpenAPI para `mode` (`paper` | `real`) ni `risk_mode` (`GREEN` | `YELLOW` | `RED` | `BLACK`). Frontend usa type guards manuales para narrowing. Si se expusieran como `Literal[...]` en Pydantic, los guards serían innecesarios.  
- ⚠️ `CostByAgentResponse` y `CostByTaskResponse` usan `list[dict[str, Any]]` en `responses.py` — untyped. Convertir a `list[AgentCostRow]` y `list[TaskCostRow]` cuando ATHENA real genere data consistente.

**Frontend**:

- ⚠️ shadcn Nova hardcodea `baseColor: neutral` — no podemos cambiar a slate por flags.  
- ⚠️ `new Date()` en render de `page.tsx` — hydration mismatch posible cerca de medianoche. Migrar a `useEffect+useState` si aparece warning.  
- ⚠️ Cache `.next` puede romper `tsc --noEmit` con duplicados de tipos. Workaround: `rm -rf .next` antes.  
- ⚠️ `RISK_BORDER` en risk-mode-card está tipado `Record<string, string>` pero podría ser `Record<RiskLevel, string>` para tipado más fuerte. Cosmético.  
- ⚠️ `API_BASE_URL` duplicado entre `api-client.ts` y `use-agents.ts`. Si aparece en un tercer archivo, extraer a un módulo `config/env.ts` o exportar desde `api-client.ts`.  
- ⚠️ `TradingModeCard` y `RiskModeCard` tienen type guards `if (data.mode !== 'paper' && data.mode !== 'real') return null` (y equivalente para risk\_mode) que son **rama muerta** — el schema OpenAPI ya tipa esos campos como literal union strict. Cuando se escribieron, el schema era `string` genérico, ahora ya no. Cleanup futuro en commit `chore: remove dead type guards in mode/risk widgets`. La convención "type guards over casts" sigue válida cuando el narrowing es necesario; acá ya no lo es.

**Testing**:

- ⚠️ Tests que requieren Docker corriendo deberían marcarse `@pytest.mark.requires_docker` para skip selectivo. Pendiente sprint de DX.

**DX**:

- ⚠️ `npx tsc` desde directorio incorrecto descarga paquete random `tsc@2.0.4`. Solución: `cd dashboard` siempre, o usar `./node_modules/.bin/tsc`.  
- ⚠️ `curl ... | python3 -m json.tool` puede fallar con artifact de IPv6/IPv4. Para smoke tests usar `curl -s -w "HTTP %{http_code}\n"` directo sin pipear a json.tool.  
- ⚠️ Pegar archivos largos a Claude Code puede truncarse silenciosamente. Para archivos \>200 líneas, partir en chunks de ~50-80 líneas desde el inicio. Para fixes quirúrgicos, usar Python con regex específicos en lugar de sed/cat.

### Cerrada en Sprint 2B.4

- ✅ shadcn `Badge` instalado pero no usado → resuelto en F.4.2 con wrappers `<ModeBadge>` y `<RiskBadge>`.

---

## 8. Convenciones de proyecto

### Stack

- **Backend**: Python 3.14, FastAPI async-first, PostgreSQL + TimescaleDB, Redis Streams, psycopg3, Pydantic v2.  
- **Frontend**: Next.js 16.2.4 (App Router), React 19.2.4, Tailwind v4 (config-less, en `globals.css` con `@theme`), shadcn/ui v4 Nova preset, React Query v5, openapi-typescript v7.

### Conexiones

- **Trading mode**: `paper` (default) o `real` (requiere env var con confirmation token).  
- **Health checks**: siempre devuelven 200, nunca lanzan. Cada subsystem reporta `status: "ok" | "error" | "unknown"` y `checks_duration_ms`.  
- **Polling intervals**: status 30s, mode 60s, alerts 30s, costs 30s, portfolio 30s, atlas-health 30s.

### UI

- **Border-left semántico**: cada widget de status tiene `border-left: 2px solid <color>` reflejando su estado primario.  
- **Card layout**: `CardTitle` uppercase tracking-wide text-white/60, primary status grande monospace, secondary info menor monospace text-white/40.  
- **Type guards over casts**: cuando el backend devuelve string genérico pero el componente espera union literal, usar runtime narrowing (`if (value !== 'a' && value !== 'b') return null`) en vez de `as` cast. **Cuando el OpenAPI schema ya tipa el campo como literal union**, el guard no es necesario y constituye rama muerta — no agregarlo.  
- **Domain-typed wrappers** sobre primitives genéricos: ej `<ModeBadge mode={...}>` y `<RiskBadge level={...}>` en lugar de `<Badge variant="...">` con className inline.  
- **JSON pretty-print para passthrough configs**: vistas read-only que muestran configs raw usan `<pre>{JSON.stringify(data, null, 2)}</pre>` en lugar de tablas/listas estructuradas. Coherente con el shape passthrough del backend; sobrevive a cambios de YAML sin tocar frontend.

### Endpoints

- **Passthrough vs proyectado**: cuando un endpoint expone una config "as-written" (ej `/config/limits`), devolver el archivo completo parseado sin re-validar con Pydantic. Cuando el endpoint expone una config "as-used" (ej `/atlas/limits`), proyectar solo los campos que el sistema realmente consume. Son dos contratos distintos para dos consumers distintos.

### Git

- **Commits atómicos**: 1 sub-bloque \= 1 commit.  
- **Heredoc para messages multi-línea**.  
- **`git status` antes y después** de cualquier cambio.

---

## 9. Cuando vuelvas

Volví. Backend: [sí/no]. Docker: [sí/no]. Retomo desde [bloque específico].

**Bloque actual**: Sprint 2B.5 → **Trading Mode toggle con safeguards** (próximo).

**Estado para retomar**:

- main up to date con origin/main (5 commits totales pusheados el 7 mayo: `157ea82`, `688e6ed`, `9e8da34`, `ee1a12d`, `0d930c3`).  
- Working tree clean.  
- Sprint 2B.4 cerrado completamente. Próximo bloque arranca limpio.  
- Para 2B.5 Trading Mode toggle: `/system/mode` ya existe (GET). Falta endpoint `POST /system/mode` con double-confirmation token. Mecanismo de confirmación a definir al arrancar (env var, header, body con token, etc.).  
- Arrancar con verificación de Docker + backend up + smoke endpoints.

---

## 10. Metodología de trabajo Juan ↔ Claude

Esta sección documenta cómo trabajamos en sesiones técnicas para que cualquier instancia futura de Claude (chat o Code) pueda seguir el mismo patrón.

### 10.1 Roles

- **Juan**: dueño de proyecto, decide scope y prioridades. Verifica visualmente todo lo que se ve en pantalla.  
- **Claude (chat)**: planificador, revisor, custodio de la metodología. NO escribe código directo al filesystem.  
- **Claude Code (PyCharm/CLI)**: ejecutor. Escribe archivos, corre comandos, devuelve outputs literales.

Flujo típico: Juan → Claude (chat) prepara prompt → Juan pega a Claude Code → Claude Code ejecuta → Juan pega output a Claude (chat) → Claude verifica y vuelve a planificar.

### 10.2 Reglas operacionales

1. **Plans antes de implementar**: cada bloque de trabajo arranca con un plan file-by-file con LOC estimado y archivos afectados.  
2. **Opciones con pros/cons honestos**: cuando hay decisión a tomar, presentar 2-3 opciones con trade-offs reales, incluyendo la que NO recomiendo.  
3. **Verificación contra realidad**: smoke tests reales (HTTP curl, `git status`, `tsc --noEmit`, `npm run build`, observación visual en browser). Nunca asumir que algo funciona porque "se ve correcto".  
4. **Contradicciones → parar y mostrar**: si algo no cierra en lo que dije o lo que hicimos, frenar antes de avanzar.  
5. **Detección de fatiga**: respuestas cortas / aprobaciones rápidas / saltarse pasos \= señal de pausa. NO preguntar explícitamente "energía 1-10" — Juan pidió quitar esa pregunta. Sí prestar atención a patrones de fatiga y proponer pausa si aparecen.  
6. **Cuestionar decisiones contradictorias**: si Juan elige una opción contraria a la recomendada, confirmarlo antes de avanzar (no sumiso).  
7. **Sin endulzar**: feedback directo. Si algo está mal o tengo dudas, lo digo. Si Juan se equivoca, lo señalo.  
8. **Código real antes de aprobar**: ver el código completo propuesto antes de escribir al filesystem. Show before write.  
9. **No tocar archivos out-of-scope**: si un cambio afecta un archivo no listado en el plan, parar y replantear.  
10. **Commits limpios y frecuentes**: 1 sub-bloque \= 1 commit. Heredoc para messages multi-línea. `git status` antes y después.

### 10.3 Pattern "show before write"

Cuando se va a crear o modificar un archivo:

1. Claude (chat) describe el cambio + propone estructura.  
2. Claude Code muestra contenido completo propuesto del archivo (no diff, archivo entero o secciones grandes).  
3. Juan revisa con Claude (chat).  
4. Juan da OK explícito.  
5. Recién entonces Claude Code escribe.

Esto previene scope creep y bugs de typo silenciosos.

### 10.4 Bloques grandes se parten

Si un bloque tiene \>5 archivos o \>200 LOC, partirlo en sub-bloques (a/b/c) con verificación intermedia. Cada sub-bloque debe tener:

- tsc clean  
- build successful  
- Smoke test si aplica  
- Decisión explícita de seguir o pausar

Commit puede ser final (1 commit cubre los 3 sub-bloques) o por sub-bloque, según el riesgo.

### 10.5 Salvavidas y rollback

Antes de cualquier deploy o commit grande:

- Anotar la revisión/commit anterior como "salvavidas".  
- Si algo rompe en producción, comando de rollback listo.  
- Working tree clean antes y después del commit.

### 10.6 Comunicación con Claude Code

Claude (chat) entrega prompts con esta estructura:

- Bloque ```` ``` ... ``` ```` con instrucciones literales para pegar.  
- Pasos numerados explícitos.  
- Outputs esperados descritos.  
- "NO commitees todavía" o "NO modifiques nada" cuando aplica.  
- "Pegame outputs literales" para revisar.

Claude Code devuelve outputs literales. Juan los pega de vuelta. Claude (chat) los lee y decide siguiente paso.

### 10.7 Cuando Claude Code se desvía

Patrones detectados de scope creep o errores de Claude Code:

- Renombrar archivos no acordados.  
- Inventar afirmaciones técnicas (ej: "'use client' evita hydration mismatch" — incorrecto).  
- Confundir scope entre fases (ej: hacer F.5 mientras dice F.4.c).  
- Tomar atajos (ej: minimizar issues como "30s suficiente" cuando son problemas reales).  
- Path issues (`npx tsc` desde directorio incorrecto).  
- Aplicar cambios no aprobados y avisar después (ej: agregar tipos locales y casts en lugar de parar y mostrar opciones).  
- Truncamiento silencioso al pegar archivos largos (necesita partir en chunks de 50-80 líneas).  
- Resumir output literal en lugar de pegarlo (necesita insistir con "output literal, no resumen").  
- Reordenar/refactor cosmético (ej: alfabetizar imports) cuando solo se piden 2 líneas nuevas. Aunque la intención sea limpiar, contamina el diff y rompe `git blame`. Cleanup cosmético va en commit aparte tipo `chore:`.

Cada desvío detectado por Juan o Claude (chat) es corregido explícitamente antes de continuar. La metodología es lo que detecta los desvíos, no la velocidad.

### 10.8 Reglas de fin de sesión

- Resumen ejecutivo de lo cerrado hoy.  
- Tech debt actualizada.  
- Próximo bloque planeado (sin ejecutar).  
- Plantilla de retorno: "Volví. Backend: [sí/no]. Docker: [sí/no]. Retomo desde [bloque]."

