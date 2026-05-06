# trading-workspace — Project Status

**Última actualización**: 6 de mayo 2026 (después de Sprint 2B.4 F.4.2)
**Branch**: `main` — 1 commit adelante de `origin/main`
**Owner**: Juan
**Repo**: github.com/juanfranciscolago-web/trading-workspace
**Local**: /Users/JUAN/Documents/trading-workspace

---

## 1. Visión

Sistema multi-agente de trading que combina varios agentes LLM especializados (ATHENA, APOLLO, HERMES, NYX, VESTA) bajo supervisión de un agente de riesgo (ATLAS). El sistema opera en paper trading hasta validación, después transición gradual a capital real. Stack: Python 3.14 + FastAPI + PostgreSQL/TimescaleDB + Redis Streams en backend, Next.js 16 + React 19 + Tailwind v4 en frontend.

El objetivo del proyecto no es solo construir el sistema de trading sino también construir la observabilidad y el riesgo **antes** de generar alpha. La filosofía es: nunca poner capital sin un dashboard que muestre qué hace el sistema, sin alertas cuando algo falla, y sin un agente de riesgo (ATLAS) que pueda parar todo.

---

## 2. Roadmap macro (8 sprints)

| # | Sprint | Objetivo | Status |
|---|---|---|---|
| 1 | Foundations | Schemas, bus Redis, migraciones, mock agents | ✅ Completo (28 abr 2026) |
| 2 | ATLAS + Dashboard | ATLAS operativo, dashboard observabilidad, alertas | 🔄 En progreso (~80%) |
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

**Período**: completado 28 abril 2026
**Métricas**: 249 tests, +5009 LOC, 43 archivos
**Último commit**: `76e6a0b` Sprint 1 COMPLETE

### Entregables
- Schemas Pydantic completos para mensajes inter-agente.
- Bus Redis Streams operativo para comunicación async.
- PostgreSQL + 9 migraciones iniciales (V001-V009).
- 5 mock agents alpha + ATLAS.
- Flujo completo proposal → critique → decision testeado end-to-end.

### Tech debt heredada a Sprint 2
- ⚠️ `run_cycle.py` sin DB obligatoria (media).
- ⚠️ Error handling en `MessageRepository` (media).

---

## 4. Sprint 2 — ATLAS + Dashboard 🔄

**Período**: arrancó después del 28 abril, en progreso.
**Métricas hasta hoy**: 35 commits, +25500 / -350 LOC aprox, 165+ archivos.
**Sub-fases**: 2A → 2B.1 → 2B.2 → 2B.3 (cerrada) → 2B.4 (en progreso).

### 4.1 — Sprint 2A: ATLAS infrastructure ✅

**Commit**: `b19919e`
**Stat**: 39 files, +4283 / -250 LOC

Entregables:
- `config/limits.yaml` + `buckets.yaml` — Phase 1 calibration: 25 tickers, 7 buckets.
- `src/multi_agent/risk/`: ATLAS core, 8 risk checks, portfolio snapshot. 96 tests.
- `src/multi_agent/consumers/`: AtlasConsumer (Redis Streams, fail-closed, DLQ). 13 tests.
- `src/multi_agent/execution/`: PaperExecutor (Level-2 slippage, partial fills). 15 tests.
- DB migraciones V010-V013.
- `scripts/seed_portfolio.py`: 10 posiciones sintéticas para testing.
- `run_async_cycle.py`: orchestrator del flujo async.

### 4.2 — Sprint 2B.1: API + LLM tracking ✅

**Commits**: `39d80b8`, `3f1a682`, `63f32cc`

Entregables:
- **LLM cost tracking**: `track_llm_cost` decorator (sync/async), `LLMCostRepository` con 5 métodos. Config en `config/llm_pricing.yaml`. Migración V014. 28 tests nuevos.
- **FastAPI foundation**: lifespan async, TTL-cached snapshot, launcher localhost-only.
- **Endpoints ATLAS**: `GET /atlas/health`, `POST /atlas/validate`, `GET /atlas/limits`, `GET /atlas/buckets`. 30 tests nuevos.
- **Endpoints portfolio/trades/costs**: `GET /portfolio/snapshot`, `/portfolio/positions`, `/trades/validations` (+ `/{correlation_id}`), `/costs/summary`, `/by-agent`, `/by-task`, `/costs/daily`. ValidationRepository + 8 endpoints.

### 4.3 — Sprint 2B.2: Alerts worker ✅

**Commits**: `66f52a6`, `6254188`

Entregables:
- **AlertWorker async loop**: subscribe → router.route() per event. Shutdown sequence: stop → drain in-flight (5s timeout) → close Redis. 3 shutdown tests.
- **Retry queue (2B.2.b)**: RetryWorker polls DB every 30s, backoff 30s → 2min → 5min → 15min (4 attempts). Migración V016 (given_up_at column). Dedup bypassed by design para retries. TelegramSink shared connection.

### 4.4 — Sprint 2B.3: Dashboard Slice A.1 (Home view) ✅

**Período**: 4-5 mayo 2026.
**Sub-bloques**: 12 commits.

Entregables (resumen):
- **Backend**: `TRADING_MODE` config con double-confirmation, `/system/status` + `/system/mode` endpoints, `DailyTotalsRow` Pydantic typed.
- **Frontend infra**: AppShell con Sidebar 180px (3 secciones: VIEWS / CONTROL / DATA con badges sprint) + Header 56px (brand + mode badge + system semaforo + clock + updated). Bug fix histórico: `globals.css` línea 10 era `--font-sans: var(--font-sans)` autoreferencial → fallback a serif. Fix a `var(--font-geist-sans)`.
- **Frontend hooks**: `useSystemStatus` (30s), `useSystemMode` (60s), `useAlerts` (30s, limit=5), `useAtlasHealth` (30s), `useCostsDaily` (con polling 30s agregado), `usePortfolioSnapshot` (con polling 30s agregado). `fetcher` extendido con query params opcionales backward-compatible.
- **Frontend widgets** (6 totales en grid asimétrico):
  - **Status row** (4 cols): SystemStatusCard, TradingModeCard, RiskModeCard, LLMCostCard.
  - **Data row** (2x2 cols): NavPnLCard, RecentAlertsCard.
- **Real-time clock**: `useEffect` + `setInterval(1s)` + cleanup. `Intl.DateTimeFormat` con `America/New_York` para DST automático.
- **Stub pages**: `/portfolio` y `/risk` para evitar 404 (Slice A.2 y A.3 pendientes).
- **Tipos OpenAPI**: `AlertItem` y `AlertsResponse` definidos en hook (workaround para schema unnamed).

Último commit: `56d6263` (F.4.c + F.5).

### 4.5 — Sprint 2B.4: Dashboard Config + Agents 🔄 — actual

**Período**: arrancó 6 mayo 2026, en progreso.

#### Bloques completados ✅

| Bloque | Commit | Descripción |
|---|---|---|
| **F.4.2 — Refactor badges** | `688e6ed` | Reemplazó badges inline en header.tsx, trading-mode-card.tsx, risk-mode-card.tsx por wrappers tipados `<ModeBadge>` y `<RiskBadge>` que envuelven el componente shadcn Badge. Type guards (sin casts) para narrowing seguro de `data.mode` y `data.risk_mode` desde string genérico al union type. Si backend devuelve un mode/level inesperado, el widget retorna null en lugar de pintar con color undefined. |

#### Bloques pendientes ⏳

| Bloque | Estimación | Descripción |
|---|---|---|
| **B.4.1 — Endpoints agents** | ~120 LOC, 1.5h | `GET /agents` (lista combinada de `agents.config` + `agents.state`), `POST /agents/{agent_id}/toggle` (flip `is_active`). AgentsRepository nuevo. 6-8 tests. |
| **F.4.1 — AgentsCard widget** | ~80 LOC, 1h | Hook `use-agents` (polling 30s). Widget con lista de los 6 agentes (apollo, athena, atlas, hermes, nyx, vesta) mostrando dot status + nombre + cost today + toggle button. |
| **F.4.3 — Config view solo lectura** | ~150 LOC, 1.5h | Crear `dashboard/src/app/config/page.tsx`. Eliminar badge "2B.4" del sidebar para Config. Secciones: Limits (de `limits.yaml`), Buckets (de `buckets.yaml`), Trading Mode (display, sin toggle todavía). Read-only en este sprint; edits van a Sprint 2B.5. |

#### Diferido a Sprint 2B.5

- Toggle de Trading Mode con safeguards (double-confirmation token).
- Editores de limits/buckets si son realmente necesarios (probablemente NO — los limits no se editan en runtime usualmente).

#### Descubrimiento clave (6 mayo)

Verificando el backend antes de planear, descubrimos que **la infraestructura del toggle de agents ya existe**:
- `agents.config.is_active` (boolean) ya en DB.
- `agents.state` con `status`, `current_task`, `last_heartbeat`, `last_proposal_at`, `last_error`, `error_count_24h`, `llm_cost_today_usd`.
- 6 agents registrados: apollo, athena, atlas, hermes, nyx, vesta — todos `active=true`.
- `/costs/by-agent` endpoint ya existe.

**Implicación**: B.4.1 solo expone via API lo que ya existe. Sin trabajo de schema/migration.

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

### Sprint 2B.4 cierre
1. **B.4.1** — Endpoints `/agents` + `POST /agents/{id}/toggle` (~1.5h).
2. **F.4.1** — AgentsCard widget en Home (~1h).
3. **F.4.3** — Config view solo lectura (~1.5h).
4. **Commit final 2B.4** — 1 commit por bloque o 1 commit grande según riesgo.

### Sprint 2B.5 (siguiente)
- Toggle de Trading Mode con safeguards.
- Posibles editores de configs (TBD).

### Slices A.2 + A.3 (en algún momento)
- A.2: Portfolio view real (hoy stub).
- A.3: Risk view real (hoy stub).

---

## 7. Tech debt acumulada

### Heredada de Sprint 1
- ⚠️ `run_cycle.py` sin DB obligatoria (media).
- ⚠️ Error handling en `MessageRepository` (media).

### Generada en Sprint 2

**Backend**:
- ⚠️ `cost_usd` como `float` en `DailyTotalsRow` → migrar a `Decimal` cuando real-money trading.
- ⚠️ `llm_cost_repository.py` importa de `api/schemas/responses.py` — dependencia inversa de capas, candidata a refactor.
- ⚠️ `PostgresPool` wrapper no propaga timeout — bypass con `psycopg.connect()` directo + `connect_timeout`.
- ⚠️ Backend no expone enums OpenAPI para `mode` (`paper` | `real`) ni `risk_mode` (`GREEN` | `YELLOW` | `RED` | `BLACK`). Frontend usa type guards manuales para narrowing. Si se expusieran como `Literal[...]` en Pydantic, los guards serían innecesarios.

**Frontend**:
- ⚠️ shadcn Nova hardcodea `baseColor: neutral` — no podemos cambiar a slate por flags.
- ⚠️ `new Date()` en render de `page.tsx` — hydration mismatch posible cerca de medianoche. Migrar a `useEffect+useState` si aparece warning.
- ⚠️ Cache `.next` puede romper `tsc --noEmit` con duplicados de tipos. Workaround: `rm -rf .next` antes.
- ⚠️ `RISK_BORDER` en risk-mode-card está tipado `Record<string, string>` pero podría ser `Record<RiskLevel, string>` para tipado más fuerte. Cosmético.

**Testing**:
- ⚠️ Tests que requieren Docker corriendo deberían marcarse `@pytest.mark.requires_docker` para skip selectivo. Pendiente sprint de DX.

**DX**:
- ⚠️ `npx tsc` desde directorio incorrecto descarga paquete random `tsc@2.0.4`. Solución: `cd dashboard` siempre, o usar `./node_modules/.bin/tsc`.
- ⚠️ `curl ... | python3 -m json.tool` puede fallar con artifact de IPv6/IPv4. Para smoke tests usar `curl -s -w "HTTP %{http_code}\n"` directo sin pipear a json.tool.

### Cerrada en Sprint 2B.4

- ✅ shadcn `Badge` instalado pero no usado → resuelto en F.4.2 con wrappers `<ModeBadge>` y `<RiskBadge>`.

---

## 8. Decisiones técnicas vivas

### Backend stack
- **Python 3.14** con type hints estrictos.
- **FastAPI** para HTTP, async-first.
- **PostgreSQL + TimescaleDB** para time-series y operacional.
- **Redis Streams** para bus inter-agente y dedup.
- **psycopg3** (no psycopg2). Connection pooling con `PostgresPool` wrapper.
- **Pydantic v2** para schemas + OpenAPI generation.

### Frontend stack
- **Next.js 16.2.4** (App Router).
- **React 19.2.4**.
- **Tailwind v4** (config-less, todo en `globals.css` con `@theme`).
- **shadcn/ui v4 Nova preset** (Card, Skeleton, Alert, Badge instalados).
- **React Query v5** (`@tanstack/react-query`) para data fetching.
- **openapi-typescript v7** para tipos automáticos desde el OpenAPI del backend.

### Convenciones de proyecto
- **Trading mode**: `paper` (default) o `real` (requiere env var con confirmation token).
- **Health checks**: siempre devuelven 200, nunca lanzan. Cada subsystem reporta `status: "ok" | "error" | "unknown"` y `checks_duration_ms`.
- **Polling intervals**: status 30s, mode 60s, alerts 30s, costs 30s, portfolio 30s, atlas-health 30s.
- **Border-left semántico**: cada widget de status tiene `border-left: 2px solid <color>` reflejando su estado primario.
- **Card layout**: `CardTitle` uppercase tracking-wide text-white/60, primary status grande monospace, secondary info menor monospace text-white/40.
- **Type guards over casts**: cuando el backend devuelve string genérico pero el componente espera union literal, usar runtime narrowing (`if (value !== 'a' && value !== 'b') return null`) en vez de `as` cast.
- **Domain-typed wrappers** sobre primitives genéricos: ej `<ModeBadge mode={...}>` y `<RiskBadge level={...}>` en lugar de `<Badge variant="...">` con className inline.
- **Commits atómicos**: 1 sub-bloque = 1 commit. Heredoc para messages multi-línea.

---

## 9. Cuando vuelvas

Plantilla de retorno para Claude Code al inicio de sesión:

```
Volví.
Backend: [sí/no — ¿está corriendo uvicorn en :8000?]
Docker: [sí/no — ¿están trading_postgres y trading_redis healthy?]
Retomo desde [bloque — ej: "Sprint 2B.4 B.4.1"].
```

Pasos de re-orientación:

1. Leer `/docs/PROJECT_STATUS.md` sección 6 (Pendientes inmediatos).
2. Verificar infra: `docker ps`, `lsof -i:8000`, `lsof -i:5432`.
3. Verificar git: `git status`, `git log --oneline | head -5`.
4. Smoke test endpoints: `curl -s -w "HTTP %{http_code}\n" http://localhost:8000/system/status`.
5. Si algo falta, arrancarlo antes de codear.
6. Confirmar bloque actual con Juan antes de implementar.

Si Juan no dice nada del estado, asumir:
- Docker: running (contenedores persistentes).
- Backend: probablemente caído (no auto-start).
- Frontend dev server: caído (no auto-start).
- Git: working tree clean (Juan hace `git stash` o commitea antes de cerrar sesión).

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
5. **Detección de fatiga**: respuestas cortas / aprobaciones rápidas / saltarse pasos = señal de pausa. NO preguntar explícitamente "energía 1-10" — Juan pidió quitar esa pregunta. Sí prestar atención a patrones de fatiga y proponer pausa si aparecen.
6. **Cuestionar decisiones contradictorias**: si Juan elige una opción contraria a la recomendada, confirmarlo antes de avanzar (no sumiso).
7. **Sin endulzar**: feedback directo. Si algo está mal o tengo dudas, lo digo. Si Juan se equivoca, lo señalo.
8. **Código real antes de aprobar**: ver el código completo propuesto antes de escribir al filesystem. Show before write.
9. **No tocar archivos out-of-scope**: si un cambio afecta un archivo no listado en el plan, parar y replantear.
10. **Commits limpios y frecuentes**: 1 sub-bloque = 1 commit. Heredoc para messages multi-línea. `git status` antes y después.

### 10.3 Pattern "show before write"

Cuando se va a crear o modificar un archivo:

1. Claude (chat) describe el cambio + propone estructura.
2. Claude Code muestra contenido completo propuesto del archivo (no diff, archivo entero o secciones grandes).
3. Juan revisa con Claude (chat).
4. Juan da OK explícito.
5. Recién entonces Claude Code escribe.

Esto previene scope creep y bugs de typo silenciosos.

### 10.4 Bloques grandes se parten

Si un bloque tiene >5 archivos o >200 LOC, partirlo en sub-bloques (a/b/c) con verificación intermedia. Cada sub-bloque debe tener:

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

- Bloque \`\`\`...\`\`\` con instrucciones literales para pegar.
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

Cada desvío detectado por Juan o Claude (chat) es corregido explícitamente antes de continuar. La metodología es lo que detecta los desvíos, no la velocidad.

### 10.8 Reglas de fin de sesión

- Resumen ejecutivo de lo cerrado hoy.
- Tech debt actualizada.
- Próximo bloque planeado (sin ejecutar).
- Plantilla de retorno: "Volví. Backend: [sí/no]. Docker: [sí/no]. Retomo desde [bloque]."
