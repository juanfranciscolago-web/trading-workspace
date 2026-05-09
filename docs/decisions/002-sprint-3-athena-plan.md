# ADR-002: Sprint 3 Plan — ATHENA Debate-Only Mode

**Fecha:** 2026-05-09  
**Estado:** Aceptado  
**Contexto:** Sprint 2B.5 cerrado (commit `0b6f7dd`). Próximo bloque per masterdoc roadmap §10.3.

---

## 1. Context

### 1.1 Lo que dice el masterdoc

Per `docs/sistema_multiagente_trading.md`:

**§3.1 ATHENA — La Cuantitativa Sistemática:**
- Identidad: skeptical, data-driven, paciente. Arquetipo Renaissance / Jim Simons.
- Mandato: alpha vía edge estadística verificable con muchas ocurrencias.
- Especialidad: mean reversion, statistical arbitrage, options selling sistemático (CSP, credit spreads, iron condors). Strategies con N≥100 + POP > 70%.
- Time horizon: 15-45 días.
- Datos prioritarios: OHLCV multi-timeframe, IV rank/percentile/term structure/skew, vol surface, correlations rolling, backtests propios.
- Marco analítico: Kelly fraccionado 0.25x, cierre mecánico al 50% max profit, cero discrecionalidad post-entrada.
- Sesgos auto-reconocidos: subestima cola, opera regímenes que cambiaron, ciega a catalizadores narrativos.

**§10.3 Sprint 3 — ATHENA en Debate-Only Mode:**
- Objetivo: primer agente generando proposals reales.
- ATHENA con prompt completo y data layer conectado.
- Genera propuestas que pasan por protocolo completo.
- ATLAS valida pero NO se ejecutan trades.
- Dashboard muestra debates en vista Debate.

**Entregables:**
- ATHENA produciendo proposals válidos.
- Logging completo de todas las decisiones.
- Validación de calidad de proposals contra juicio humano.

### 1.2 Estado actual del código (post Sprint 2B.5 + 3 chores 2026-05-09)

- `multi-agent-system/src/multi_agent/agents/athena_mock.py` existe — `class AthenaMock(BaseMockAgent)` con lógica hardcoded.
- `multi-agent-system/src/multi_agent/agents/base.py` — `class BaseMockAgent(ABC)`.
- 6 agents mock implementados: Athena, Apollo, Hermes, Nyx, Vesta, Atlas.
- `communication/schemas/proposal.py:61` — `class ProposalMessage(BaseMessage)` schema completo.
- `multi-agent-system/claude_router/` — paquete con `ClaudeRouter` operativo (Sprint 1).
- `shared_core.brokers.SchwabClient` existe pero no se usa todavía (reservado para Sprint 5).
- 6 agents en DB (`agents.config`), todos `is_active=true`.
- Tabla `trades.proposals` ya existe (schema rich: proposing_agent, ticker, asset_class, strategy_type, conviction_score, sizing, time_horizon_days, status, full_payload JSONB).
- API: 20 endpoints. NO existen endpoints de proposals/debate. `/atlas/validate` es síncrono one-shot (synthetic proposal → validation, no persiste como proposal real).
- Frontend: 4 rutas (`/`, `/config`, `/portfolio`, `/risk`). NO existe vista de proposals/debate.
- Tests: 599 passing. `test_mock_agents.py::TestAthenaMock` con 10+ tests sobre AthenaMock.

---

## 2. Decisions

Seis decisiones arquitectónicas para Sprint 3.

### A. Data layer source

**Decisión:** Stub data layer en Sprint 3. Schwab integration diferida a Sprint 5.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| A1 | Schwab paper data desde Sprint 3 | Sprint 5 (per masterdoc §10.5) tiene "Conexión a Schwab Paper Trading" como scope principal — usarlo en Sprint 3 invade ese scope con auth/rate-limits/error handling que distraen del foco LLM/prompt |
| **A2** | **Stub data layer** | **Elegida: aísla Sprint 3 al loop ATHENA-prompt-output, deja Schwab limpio para Sprint 5** |
| A3 | Pre-cargar histórico en DB | Mismo problema que A1 a otro nivel; complejidad sin beneficio para debate-only |

### B. Agent base class

**Decisión:** Crear `BaseAgent` abstract nuevo. AthenaAgent extiende BaseAgent. Mocks intactos extendiendo BaseMockAgent.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| B1 | AthenaAgent extiende BaseMockAgent + override | Rompe la separación mock/real; tests que mockean cualquier "Agent" empiezan a confundir contratos |
| **B2** | **BaseAgent nuevo (abstract real)** | **Elegida: separación clara, mocks siguen sirviendo a tests, reales a producción** |
| B3 | Refactor a un único Base post-Sprint 3 | Empuja la decisión a sub-bloque futuro sin rationale; mejor decidir ahora que hay solo 1 agente real |

### C. Pipeline trigger

**Decisión:** Manual via `POST /agents/athena/trigger`. Cron diferido a Sprint 5+.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| C1 | Cron en Sprint 3 | Requiere infra de scheduling (no hay hoy); fuera del scope foco-LLM |
| **C2** | **Manual API trigger** | **Elegida: dev-mode, simple, debugeable. Cron va en Sprint 5+ cuando sea ejecutivo** |
| C3 | Bus event automático | Misma fricción que C1 sin beneficio en debate-only |

### D. Stub data layer scope

**Decisión:** Stub "rich-enough": OHLCV multi-timeframe + IV rank/percentile dinámico + skew simplificado (3 strikes ATM ± 1σ) + correlations entre 3-5 tickers. Apunta a ~300-500 LOC.

**Razón:** ATHENA necesita inputs realistas para que el output sea evaluable contra juicio humano (criterio del masterdoc §10.3). Un stub demasiado pobre genera proposals vacías o irrelevantes; uno demasiado rico se vuelve Sprint propio.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| D1 | Solo OHLCV (~100 LOC) | Insuficiente — ATHENA prioriza IV/skew/vol surface, sin eso no produce CSP/credit spreads creíbles |
| **D2** | **Stub rich-enough** | **Elegida: cubre los inputs del marco analítico de §3.1 sin escalar a layer real** |
| D3 | Stub completo (vol surface multi-expiry + opciones chain real) | Sprint propio; Sprint 5 conecta Schwab que provee esto real |

### E. Test scope

**Decisión:** Unit con LLM stub determinístico + snapshot tests del proposal shape. Integration con ClaudeRouter real DIFERIDO.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| E1 | Solo unit con LLM stub | Insuficiente — falta cobertura del shape de output |
| **E2** | **Unit + snapshot tests** | **Elegida: stub determina inputs, snapshot fija output shape, sin cost real** |
| E3 | Unit + integration con ClaudeRouter real | Cost por test run (~$0.001/test × N corridas/día). Defer hasta haber estabilidad de prompt |

### F. Frontend view naming + scope

**Decisión:** "Proposals view" (lista + detalle) en Sprint 3 — naming honesto a lo entregado. Sprint 4 evoluciona a "Debate view".

**Razón:** con 1 agente, no hay debate (no hay críticas cruzadas, no hay votos contra). Llamar "Debate" a una lista de proposals sole-author es naming pretencioso. Sprint 4 (APOLLO + HERMES) es donde aparecen votos y conflictos — ahí el rename a "Debate" se gana.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| F1 | "Debate view" desde Sprint 3 | Nombre adelantado; con 1 agente la vista es de proposals, no de debate |
| **F2** | **"Proposals view" en S3, evolución a Debate en S4** | **Elegida: naming honesto, evolución natural cuando hay 3+ voces** |
| F3 | Diferir frontend a Sprint 4 | Pierde "Validación de calidad contra juicio humano" del masterdoc — sin UI, el operador no puede juzgar |

---

## 3. Sub-blocks (B.3.X / F.3.X)

| Sub-bloque | Descripción | LOC est | Tiempo | Depends on |
|------------|-------------|---------|--------|------------|
| **B.3.1** | `BaseAgent` abstract + scaffolding (interface común para agents reales: input contract, output contract, ClaudeRouter wiring) | 100-200 | 2-3h | — |
| **B.3.2** | Stub data layer (OHLCV multi-timeframe + IV rank/percentile + skew simplificado + correlations) | 300-500 | 4-6h | — |
| **B.3.3** | ATHENA system prompt module (identidad + datos + marco analítico + format JSON) | 100-300 | 4-8h (mucha iteración LLM) | B.3.1 |
| **B.3.4** | `AthenaAgent` (ClaudeRouter call + parse output → `ProposalMessage` validado) | 200-400 | 4-6h | B.3.1, B.3.2, B.3.3 |
| **B.3.5** | `POST /agents/athena/trigger` endpoint (manual trigger via API) | 100-200 | 2-3h | B.3.4 |
| **B.3.6** | `GET /trades/proposals` (list + detail) o adaptación de `/trades/validations` | 150-250 | 2-3h | — (paralelo a B.3.4+) |
| **B.3.7** | Tests (unit con LLM stub + snapshot tests del proposal shape) | 400-600 | 6-10h | B.3.1, B.3.2, B.3.3, B.3.4, B.3.5, B.3.6 |
| **F.3.1** | Vista Proposals (lista) — `/proposals` route, hooks, table component | 300-500 | 4-8h | B.3.6 |
| **F.3.2** | Vista detalle Proposal — single proposal con metadata, ATLAS validation embed | 200-300 | 2-4h | B.3.6, F.3.1 |

**Total estimado:** ~1850-3250 LOC, ~30-50h (~1-2 semanas full-time).

**Orden sugerido de ejecución:**
1. B.3.1 + B.3.2 (paralelizables — distintas áreas).
2. B.3.6 (endpoint, antes que frontend pueda consumir).
3. B.3.3 (prompt — independiente, mucha iteración).
4. B.3.4 (agente — junta B.3.1 + B.3.2 + B.3.3).
5. B.3.5 (trigger endpoint).
6. F.3.1 + F.3.2 (frontend, depende de B.3.6).
7. B.3.7 (tests al cierre).

---

## 4. Open questions (para resolver durante implementación)

- **Tickers exactos del stub:** ¿qué 5-10 tickers? Probable: SPY, QQQ, IWM, NVDA, AAPL, MSFT — alta liquidez de opciones, cubre tech + indices + small-cap. Decisión en B.3.2.
- **IV ranges realistas:** ¿qué percentiles usar para que ATHENA encuentre setups? Necesita variedad — si todo IV rank > 80, ATHENA selling sistemático va siempre. Si todo < 30, nada. Distribución sintética balanceada. Decisión en B.3.2.
- **Structure de prompt:** ¿single-turn o multi-turn? ¿few-shot examples? ¿chain-of-thought explícito? Decisión iterativa en B.3.3 — probable arrancar single-turn con format JSON estricto + 1-2 few-shot examples.
- **Output validation:** si el LLM produce JSON que no parsea o que no matchea `ProposalMessage` Pydantic, ¿retry con feedback al LLM o failure inmediato? Decisión en B.3.4 — probable max 2 retries con error message como input al LLM, después fallar.
- **Proposal persistence:** ¿guardar todas las proposals incluso las que ATLAS rechaza? Sí — el masterdoc menciona "Logging completo de todas las decisiones". Tabla `trades.proposals` ya existe per V005 migration.
- **Frontend pagination:** si después de varias semanas hay 100+ proposals, ¿paginación o infinite scroll? Decisión en F.3.1 — probable paginación simple con `?limit=20&offset=N`.
- **`/trades/proposals` vs adaptar `/trades/validations`:** decisión en B.3.6. La lista probablemente quiere paginar por proposals (padre), no por validations (hijo). Probable construir endpoint nuevo + reusar response shape de validations para el detalle.

---

## 5. Out of scope (Sprint 5+)

- **Schwab integration** — auth, rate-limits, real OHLCV/IV data. Sprint 5.
- **Cron / scheduled triggering** — ATHENA scan diario al inicio del día. Sprint 5+.
- **Ejecución de trades** — paper trades reales contra el broker. Sprint 5 (ejecución), Sprint 6 (en producción).
- **Full options chain real** — multi-expiry vol surface, todas las strikes. Sprint 5 con Schwab.
- **APOLLO / HERMES / NYX / VESTA reales** — Sprint 4-8.
- **Cross-examination entre agents** — requires 2+ voces. Sprint 4 con APOLLO + HERMES.
- **Trust scores y calibración** — Sprint 4+ cuando hay datos para calibrar.
- **Dashboard "vista Debate" con votos/conflictos** — Sprint 4+ rename de "Proposals view".
- **Postmortems automáticos** — Sprint 5+ post-ejecución.
- **Integration tests con ClaudeRouter real** — diferido hasta estabilidad de prompt.

---

## 6. Success criteria

**Del masterdoc §10.3:**
- ATHENA produciendo proposals válidos.
- Logging completo de todas las decisiones.
- Validación de calidad de proposals contra juicio humano.

**Concretos para este Sprint:**

1. Disparar `POST /agents/athena/trigger` retorna 200 con un `correlation_id` y persiste un `ProposalMessage` válido en `trades.proposals`.
2. La proposal persistida pasa Pydantic validation contra `ProposalMessage` schema sin retries.
3. La proposal cumple con los marcos analíticos de ATHENA del masterdoc §3.1: ticker en universo del stub, `strategy_type ∈ {CSP, CREDIT_SPREAD, IRON_CONDOR}`, time horizon 15-45 días, `conviction_score ≥` algún threshold básico.
4. ATLAS recibe la proposal por el pipeline (consensus + atlas validation), persiste el `AtlasValidationMessage`, no rechaza por bug de schema.
5. La vista Proposals frontend muestra la proposal recién creada con sus campos clave (ticker, strategy, size_pct, reason, conviction).
6. Operador (Juan) puede leer 1+ proposal generada y juzgar "esto es razonable / esto es ridículo" — proxy del criterio "validación contra juicio humano".
7. `pytest tests/` pasa: 599 actuales + ~30-50 tests nuevos para B.3.X.
8. Sin regresiones en chequeos cross-stack (`tsc --noEmit + npm run build` clean).

**No son criterios de Sprint 3 (los dejamos a sprints futuros):**
- Win-rate alto en backtests de las proposals (necesita data real + período histórico).
- Costo LLM optimizado (Sprint 5+ con cache hit rate medible).
- Debate cross-agent (Sprint 4).
- Trades ejecutados (Sprint 5+).

---

**Próxima sesión:** arranca **B.3.1** (BaseAgent abstract).
