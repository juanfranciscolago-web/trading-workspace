# ADR-003: Sprint 4 Plan — Consensus Phase + ATLAS Validation Integration

**Fecha:** 2026-05-11
**Estado:** Propuesto
**Contexto:** Sprint 3 cerrado (commit `998c59e`). Próximo bloque per masterdoc roadmap §10.4.

---

## 1. Context

### 1.1 Lo que dice el masterdoc

Per `docs/sistema_multiagente_trading.md`:

**§3.2 APOLLO — La Macro Discrecional:**
- Identidad: macro-driven, narrative-aware, swing trader. Tesis multi-week a meses.
- Mandato: alpha vía narrativas macro identificables antes del consenso del mercado.
- Time horizon: semanas a meses. Especialidad: LEAPs, swing equity, crypto spot.

**§3.7 ATLAS — Guardian del Portfolio:**
- NO es un agente más: es servicio de validación pre-execution.
- Rule-based, fail-closed. 8 checks deterministas.
- "Toda decisión de riesgo pasa por shared_core.risk.atlas_client" (CLAUDE.md regla #3).

**§10.4 Sprint 4 — Debate cross-agent + ATLAS auto-validación:**
- Objetivo: pasar de single-author proposals (Sprint 3) a debate genuino con votos cruzados.
- ATLAS valida cada DecisionMessage automáticamente vía bus.
- Frontend evoluciona a vista Debate (rename diferido per ADR-002 §F.2).

**Entregables del masterdoc:**
- 2+ voces produciendo cross-examination con evidence + concerns.
- ATLAS valida cada decision finalmente.
- Operador puede ver debate completo en UI con todos los mensajes correlacionados.

**Ajuste de scope vs masterdoc:**
El masterdoc §3.2 define APOLLO como agente macro discrecional con mandato propio (genera proposals macro). En Sprint 4 redefinimos APOLLO temporalmente como **contrarian / devil's advocate de ATHENA** (D7 abajo). El mandato macro completo de APOLLO (generación de proposals propias) se difiere a Sprint 5+, manteniendo el slot APOLLO ocupado pero con role-specific Sprint 4. Razón: con solo 2 agents, necesitamos un crítico explícito; la lens macro de APOLLO sirve naturalmente para desafiar la lógica cuant de ATHENA.

### 1.2 Estado actual del código (post Sprint 3, commit `998c59e`)

**Sprint 4 es wire-up, no creación de schema.** Las 4 tablas del pipeline (`proposals`, `critiques`, `decisions`, `atlas_validations`) ya existen en DB desde Sprint 1. Los schemas Pydantic existen. Sprint 4 conecta piezas existing.

**Schemas Pydantic ya existen (no requieren trabajo nuevo):**
- `communication/schemas/proposal.py` — `ProposalMessage` (Sprint 3 B.3.4).
- `communication/schemas/critique.py` — `CritiqueMessage` con `Stance`, `CritiqueArgument` (summary, evidence, concern, data_that_would_change_my_mind), `alternative_proposal: dict | None`, `veto_request: bool`, `contrarian_flag_raised: bool`.
- `communication/schemas/decision.py` — `DecisionMessage` con `ConsensusState` (agree/disagree/neutral/consensus_type), `SizeModulation`, `AtlasValidationRef`.
- `communication/schemas/atlas_validation.py` — `AtlasValidationMessage` (Sprint 2A).

**Tablas DB ya existen (V005 + V010 verificadas en DB real):**
- `trades.proposals` con status enum: `pending | under_critique | decided | atlas_validated | executing | executed | rejected | expired`. Sprint 4 transitions proposals through these states.
- `trades.critiques` con stance enum AGREE/DISAGREE/NEUTRAL/ABSTAIN, contrarian_flag, summary, full_payload JSONB, UNIQUE(correlation_id, critique_agent).
- `trades.decisions` con outcome enum APPROVED/REJECTED/APPROVED_WITH_CONDITIONS/NEEDS_MORE_DATA, consensus_type, approved_size_pct, conditions, full_payload JSONB.
- `trades.atlas_validations` (V010 schema con approved, executed_size_pct, checks_passed/failed, metrics_snapshot).

**ATLAS rule-based ya wired (Sprint 2A):**
- `risk/atlas_core.py` — `validate(proposal, decision, snapshot, limits, buckets) → AtlasValidationMessage`. 8 checks: kill_switches, pnl_halt, buying_power, beta, vega, single_name, sector_saturation, bucket_saturation. Fail-closed.
- `consumers/atlas_consumer.py` — Redis Streams consumer. Lee `agent.decisions`, llama `atlas_core.validate()`, persiste `AtlasValidationMessage` + atlas_snapshot, publica a `agent.atlas_validations`, escribe a `trades.rejected_dlq` si rechaza. Mantiene `proposal_cache` en memoria.
- `agents/atlas_mock.py` — mock (Sprint 1).

**Bus de mensajes:**
- `communication/message_bus.py` — `AgentChannels.PROPOSALS = "agent.proposals"`, `AgentChannels.CRITIQUES`, `AgentChannels.DECISIONS`, `AgentChannels.ATLAS_VALIDATIONS`. Método `bus.publish(channel, msg)` hace `XADD` al stream.

**Persistencia:**
- `persistence/message_repository.py` tiene métodos `save_proposal`, `save_critique`, `save_decision`, `save_atlas_validation`, `save_atlas_snapshot`, `save_rejected_dlq`, `log_llm_cost`.

**Gaps críticos identificados:**
1. **`save_proposal` NO publica al bus Redis.** El parameter `channel="agent.proposals"` se usa solo para naming en `_insert_agent_message` (DB log), no para `bus.publish()`. AtlasConsumer no se entera cuando se guarda una proposal nueva.
2. **No hay productor de `DecisionMessage`.** AtlasConsumer espera leer de `agent.decisions`, pero hoy nada publica ahí en el trigger flow del Sprint 3.
3. **No hay ConsensusEngine.** El pipeline proposal → decision NO existe.
4. **No hay APOLLO real.** Solo mock (Sprint 1).

**Sprint 3 baseline:**
- 667 tests passing.
- Backend running PID 43290 (port 8000).
- Frontend running PID 46716 (port 3000).

---

## 2. Decisions

Siete decisiones arquitectónicas para Sprint 4.

### D1. Critique mechanism shape

**Decisión:** Sequential critique de 1 ronda. APOLLO critica una vez, sin refinement loop.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| D1.1 | Multi-round refinement (ATHENA revisa después de APOLLO) | Latency 2x + cost LLM 2x. Sin evidencia que mejora calidad en 2-agent setting. Sprint 6+ si se demuestra valor. |
| **D1.2** | **Sequential 1 ronda** | **Elegida: simple, predecible, latency contenida (~10-15s extra sobre Sprint 3). Refinement como evolución futura.** |
| D1.3 | Parallel critique (N críticos simultáneos) | Premature optimization — Sprint 4 tiene 1 crítico solamente. |

### D2. ATLAS validation timing

**Decisión:** Async via Redis Streams (existing AtlasConsumer wiring).

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| D2.1 | Sync inline call `atlas_core.validate()` después de consensus | Bloquea trigger endpoint por ~1-5s. Refactor de consumer pattern existente sin ganancia. |
| **D2.2** | **Async via existing AtlasConsumer** | **Elegida: wiring ya existe (lee `agent.decisions`), trigger retorna fast, polling cubre el gap UI.** |
| D2.3 | Hybrid (sync si proposal urgente, async otherwise) | Complejidad sin caso claro de "urgente" en Sprint 4 (paper mode). |

### D3. Frontend update mechanism

**Decisión:** Polling 3s en detail page cuando hay phases pendientes. Stop polling cuando completed.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| D3.1 | SSE / WebSocket push | Backend SSE infra no existe. Sprint propio. |
| **D3.2** | **Polling 3s, conditional stop** | **Elegida: simple, fits React Query refetchInterval. 3s aceptable UX para pipeline 10-30s.** |
| D3.3 | Manual refresh button only | UX pobre para pipeline async. Operador querría refresh constante. |

### D4. Trigger UX

**Decisión:** 1 botón "Trigger ATHENA" orquesta todo el pipeline. Mismo nombre que F.3.2.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| D4.1 | Botón separado por fase (Trigger ATHENA, Trigger APOLLO, etc.) | UX confuso — operador no piensa en fases, piensa en "generar 1 proposal completa". |
| **D4.2** | **1 botón unificado** | **Elegida: mismo botón Sprint 3, semántica extendida internamente. Backend orquesta.** |
| D4.3 | Auto-trigger (cron) | Out of scope per ADR-002 §5. Sprint 5+. |

### D5. ConsensusEngine type

**Decisión:** ConsensusEngine algorítmica determinística. Sin LLM.

**Lógica concreta:**
- `outcome = APPROVED` si todos `agree` o `neutral`. `size_modulation = None`.
- `outcome = APPROVED_WITH_CONDITIONS` si ≥1 `disagree` sin `veto_request`. `size_modulation.approved_size = original × 0.5` (reducción defensiva).
- `outcome = REJECTED` si ≥1 `veto_request=True`. `size_modulation = None`.
- Si ≥1 `contrarian_flag_raised=True` sin veto: pasa a ATLAS con flag visible en `conditions`.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| D5.1 | LLM meta-agent ("ConsensusBot" lee proposal + critiques, decide) | Costo LLM adicional + non-determinismo + sin claro upside con solo 2 voces. |
| **D5.2** | **Algorithmic determinístico** | **Elegida: predecible, testeable, sin costo LLM. Reglas explícitas auditables.** |
| D5.3 | Human-in-the-loop (operador decide cada vez) | Friction operativa; opone "trigger 1 botón" de D4. |

**Updated 2026-05-11 (B.4.3 reconciliation):**

Cuando B.4.3 empezó, `src/multi_agent/agents/consensus.py` ya implementaba
un ruleset más rico que los 4 bullets de "Lógica concreta" arriba (heredado
de Sprint 1-3). Dos gaps reales quedaban:

1. **`veto_request` se ignoraba.** Una crítica con `(stance=DISAGREE,
   veto_request=True)` fluía a la rama de plain majority dissent y aprobaba
   el trade a tamaño completo.
2. **`contrarian_flag_raised` no se exponía en `DecisionMessage`.** El
   bullet 4 de D5 decía que el flag debía ser visible para ATLAS; la
   implementación solo lo embebía en strings de `conditions` en la rama
   de productive dissent.

Este update cierra ambos gaps sin downgrade del ruleset rico ya shipping.

**Cambios:**
- Veto branch agregada al inicio de la priority chain de `evaluate()`.
  Schema: nuevo miembro `ConsensusType.VETOED`; conditions con formato
  `["vetoed_by:{agent_id}", ...]`.
- Field nuevo `DecisionMessage.contrarian_flag_raised: bool = False`.
  Se popula como `any(c.contrarian_flag_raised for c in critiques)` en
  TODAS las ramas (ATLAS ve la señal incluso cuando reglas consensus-level
  absorben el dissent).

Las 8 branches efectivas en orden de prioridad están documentadas en el
docstring de `consensus.evaluate` en `src/multi_agent/agents/consensus.py`.
Ese docstring es la referencia canónica; este ADR captura solo el rationale.

**Tests:**
- `tests/agents/test_consensus.py::TestVetoRequest` (3 tests: single veto,
  multiple vetos, veto overrides majority).
- `tests/agents/test_consensus.py::TestContrarianFlagPropagation` (3 tests:
  flag propagates when raised, default-False when none, veto+contrarian
  edge case).

### D6. ATLAS implementation

**Decisión:** Mantener ATLAS rule-based existente. NO reemplazar con LLM.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| D6.1 | Reemplazar `atlas_core` con LLM-driven risk validator | Violación principio "fail closed por default" (CLAUDE.md). LLM hallucination en risk path = pérdida real. |
| **D6.2** | **Mantener rule-based existing** | **Elegida: 8 checks deterministas, auditable, fail-closed. Cumple CLAUDE.md regla #4.** |
| D6.3 | Hybrid (rule-based + LLM advisor que agrega contexto) | Sprint propio. Sin caso de uso claro en Sprint 4. |

### D7. APOLLO role en Sprint 4

**Decisión:** APOLLO como contrarian / devil's advocate de ATHENA con lens macro. Role-specific Sprint 4.

**Prompt highlights:**
- "Tu mandato Sprint 4 es desafiar las proposals de ATHENA aplicando lens macro."
- Output: `CritiqueMessage` con `stance ∈ {AGREE, DISAGREE, NEUTRAL}`, `veto_request` si invalidante grave, `contrarian_flag_raised` si insight no obvio.
- Evidencia esperada: factores macro (Fed, geopolítico, narrativa, sector flows) que afecten la tesis de ATHENA.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| D7.1 | APOLLO full role per masterdoc §3.2 (genera proposals macro propias) | Sprint propio (200-500 LOC adicionales para generation). Sprint 5+ tiene scope para macro generation. |
| **D7.2** | **Contrarian/devil's advocate con lens macro** | **Elegida: scope contenido, deja generation para Sprint 5+, da debate genuino con role explícito.** |
| D7.3 | APOLLO genérico (sin lens macro) | Pierde personalidad — sería "critico genérico", duplicaría una crítica futura. |

---

## 3. Sub-blocks (B.4.X / F.4.X)

> **Nota sobre estimates:** LOC y tiempo son **upper bounds**. Delivery actual típicamente 60-80% del upper bound based on Sprint 3 retrospective.

| Sub-bloque | Descripción | LOC est | Tiempo | Depends on |
|------------|-------------|---------|--------|------------|
| **B.4.1** | Verificar `MessageRepository.save_critique` y `save_decision` aceptan los Pydantic schemas existing y persisten `full_payload` correctamente (incluido `veto_request`, `contrarian_flag_raised`, `alternative_proposal`). NO migration nueva — schema completo desde Sprint 1. Si hay drift, fix con cambios mínimos. | 5-15 | 30min | — |
| **B.4.2** | APOLLO prompt module + `AgentApolloAgent` (extends `BaseAgent`). Mirror ATHENA pattern. Input: `ProposalMessage` + market_state. Output: `CritiqueMessage` validado contra Pydantic. | 300-500 | 6-10h | B.3.1, B.3.2 |
| **B.4.3** | `ConsensusEngine` algorithmic. Input: `ProposalMessage` + `list[CritiqueMessage]`. Output: `DecisionMessage`. Reglas D5 hardcoded explícitas. Tests unitarios exhaustivos. | 200-350 | 3-5h | — |
| **B.4.4** | Trigger orchestration. Modificar `POST /agents/athena/trigger`: persiste `ProposalMessage` → publish a `agent.proposals` bus → return correlation_id rápido. Worker chain procesa el resto async. | 150-250 | 3-5h | B.4.2, B.4.3 |
| **B.4.5** | APOLLO worker + ConsensusEngine worker (consumers). **Primer deliverable: ASCII sequence diagram del worker chain (ver §3.1) ANTES de implementar.** Mirror pattern de `atlas_consumer.py`. Status transitions de `trades.proposals.status` en cada paso. | 250-400 | 4-6h | B.4.2, B.4.3, B.4.4 |
| **B.4.6** | Read endpoints. `GET /trades/critiques/{correlation_id}` (list por correlation_id), `GET /trades/decisions/{correlation_id}` (single). Probable agregator `GET /trades/pipeline/{cid}` que devuelve `{proposal, critiques, decision, validation, status}`. | 200-300 | 3-4h | B.4.1 |
| **B.4.7** | Tests: unit (engine D5 rules), integration (workers contra mock LLM + DB), E2E (trigger → poll → all 4 messages persisted con same correlation_id). Snapshot tests del `CritiqueMessage` + `DecisionMessage` shape. | 500-700 | 8-12h | All above |
| **F.4.1** | Detail page sections + polling. Mostrar: `ProposalMessage` (existing), `CritiqueMessage` section (stance + evidence + concern + veto badge), `DecisionMessage` section (outcome + consensus state + size modulation if any), `AtlasValidationMessage` section (approved + checks + reason). Polling 3s mientras phases pending; stop polling cuando `status='atlas_validated'` o `rejected`. | 350-550 | 6-10h | B.4.6 |

**Total estimado (upper bounds):** ~1955-3065 LOC, ~30-50h (~1.5-2 semanas full-time).

**Orden sugerido de ejecución:**
1. B.4.1 (verificación schemas — 30 min).
2. B.4.2 + B.4.3 en paralelo (prompt independiente, engine independiente).
3. B.4.6 (read endpoints — desbloquea frontend).
4. B.4.4 (trigger orchestration).
5. B.4.5 (worker chain — primero diagrama §3.1, luego implementación).
6. F.4.1 (frontend — depende de B.4.6 ready).
7. B.4.7 (tests al cierre).

### 3.1 Worker chain sequence (for B.4.5)

```
trigger endpoint (POST /agents/athena/trigger)
  ├─ ATHENA generates ProposalMessage (existing Sprint 3)
  ├─ persists in trades.proposals (status='pending')
  ├─ publishes to bus stream "agent.proposals"
  └─ returns {correlation_id, status: 'pending'} (fast, async from here)

APOLLO worker (NEW, consumer of "agent.proposals")
  ├─ reads ProposalMessage from stream
  ├─ UPDATE trades.proposals SET status='under_critique'
  ├─ invokes AgentApolloAgent.generate_critique(proposal) → CritiqueMessage
  ├─ persists CritiqueMessage in trades.critiques (via save_critique)
  └─ publishes to bus stream "agent.critiques"

ConsensusEngine worker (NEW, consumer of "agent.critiques")
  ├─ reads CritiqueMessage from stream
  ├─ retrieves ProposalMessage from DB by correlation_id
  ├─ applies D5 rules → DecisionMessage
  ├─ UPDATE trades.proposals SET status='decided'
  ├─ persists DecisionMessage in trades.decisions (via save_decision)
  └─ publishes to bus stream "agent.decisions"

AtlasConsumer (EXISTING Sprint 2A, consumer of "agent.decisions")
  ├─ reads DecisionMessage from stream
  ├─ builds PortfolioSnapshot (TTL 5s cache)
  ├─ atlas_core.validate(proposal, decision, snapshot, limits, buckets)
  ├─ UPDATE trades.proposals SET status='atlas_validated' (or 'rejected' if blocked)
  ├─ persists AtlasValidationMessage in trades.atlas_validations
  ├─ publishes to bus stream "agent.atlas_validations"
  └─ if approved=false → also writes to trades.rejected_dlq

Frontend detail page (polling 3s while phases pending)
  ├─ GET /trades/pipeline/{cid} → {proposal, critiques, decision, validation, status}
  └─ stop polling when status in {atlas_validated, rejected, expired}
```

---

## 4. Open questions (para resolver durante implementación)

- **Status transitions de `trades.proposals.status`:** ¿quién hace los UPDATE? Probable: APOLLO worker → `under_critique`, ConsensusEngine → `decided`, AtlasConsumer → `atlas_validated`/`rejected`. Decisión en B.4.5.
- **APOLLO model:** ¿Sonnet 4.6 (default) o Opus para análisis macro más profundo? Decisión en B.4.2 — probable Sonnet con escalación a Opus si quality insufficient.
- **Costo por ciclo:** ATHENA (~$0.02-0.05) + APOLLO (~$0.02-0.05) + ATLAS (rule-based, $0) = ~$0.04-0.10 por trigger. Necesita confirmación con corridas reales.
- **Timeout per phase:** ¿cuánto antes de dar APOLLO por timeout? Probable 60s.
- **DLQ behavior si APOLLO falla:** ¿proposal va a ATLAS sin critique o se queda en DLQ? Probable: registrar critique vacío con stance=NEUTRAL + flag de failure, continuar pipeline. Decisión en B.4.5.
- **Polling stop condition exacta:** ¿polling stops cuando `status='atlas_validated'` (sea aprobado o no) o solo en outcome final? Probable: cualquier estado terminal (`atlas_validated`, `rejected`, `expired`). Decisión en F.4.1.
- **TriggerAthenaResponse shape:** ¿mantener mismo o renombrar a `TriggerPipelineResponse`? Decisión en B.4.4 — probable mantener nombre, agregar field `pipeline_started: bool`.
- **Multiple triggers en paralelo:** ¿el bus + consumers manejan o serializa? Redis Streams es multi-consumer-safe — probable no problema, pero verificar.
- **ATLAS PortfolioSnapshot:** Sprint 4 hereda PortfolioSnapshot real (Sprint 2A) o stub? Probable mantener real (ya existe via `SnapshotBuilder`).
- **APOLLO ve ATHENA full payload o summary:** probable full `ProposalMessage` para que pueda criticar específicos. Decisión en B.4.2.
- **Consensus reglas calibration:** ¿reducción 50% por disagree es correcta o muy agresiva? Probable empezar con 50%, ajustar tras observación.

---

## 5. Out of scope (Sprint 5+)

- **HERMES (Tactical flow / 0DTE)** — Sprint 5 con data layer real (intraday OHLCV).
- **NYX (Contrarian independiente)** — Sprint 6+.
- **VESTA (Rotación sectorial)** — Sprint 6+.
- **APOLLO macro generation (proposals propias)** — Sprint 5+ cuando hay data macro real.
- **Trust scores / calibración por agent** — Sprint 5+ cuando hay datos.
- **Rename "Proposals view" → "Debate view"** — Sprint 5 (cuando hay 3+ voces, naming honesto).
- **Cron / scheduled triggering** — Sprint 5+.
- **Refinement loop ATHENA → APOLLO → ATHENA revision** — Sprint 6+ si se demuestra valor.
- **Multi-round consensus (N rondas)** — Sprint 6+.
- **LLM meta-agent (ConsensusBot)** — Sprint 6+.
- **Schwab integration** — Sprint 5.
- **Ejecución (paper trades reales)** — Sprint 5/6.
- **SSE/WebSocket push** — Sprint 6+.
- **ATLAS LLM advisor layer** — Sprint 7+.
- **Postmortems automáticos** — Sprint 5+.
- **Cost optimization (cache hit rate)** — Sprint 5+.

---

## 6. Success criteria

**Del masterdoc §10.4:**
- 2 voces produciendo debate cross-examination con evidence + concerns.
- ATLAS valida cada decision finalmente.
- Operador puede ver debate completo en UI.

**Concretos para este Sprint:**

1. Disparar 1 trigger button → `ProposalMessage` + `CritiqueMessage` + `DecisionMessage` + `AtlasValidationMessage` (o `rejected_dlq`) todos persistidos en DB con el mismo `correlation_id`.
2. Pipeline P50 latency end-to-end < 30s (paper mode aceptable).
3. `CritiqueMessage` tiene `evidence: list[EvidenceItem]` con ≥1 item con `claim` + `data_source` + `value` (no critique vacío).
4. `DecisionMessage` refleja correctamente las reglas de ConsensusEngine (D5).
5. `trades.proposals.status` transitions correctamente a través de `pending → under_critique → decided → atlas_validated` (o `rejected`).
6. Detail page muestra los 4 mensajes en sections diferenciadas con polling 3s mientras phases pending.
7. `pytest tests/` pasa: 667 actuales + ~80-120 nuevos.
8. `tsc --noEmit` + `npm run build` clean en frontend.
9. Operador (Juan) puede juzgar "este debate produce información de valor sobre la proposal sola" — proxy del criterio "validación contra juicio humano" del masterdoc.

**No son criterios de Sprint 4 (los dejamos a sprints futuros):**

- Win-rate alto en backtests de proposals con debate vs sin debate.
- Costo LLM por ciclo optimizado.
- Multi-agent (3+) cross-examination.
- HERMES / NYX / VESTA real.
- Trades ejecutados.
- Calibración de trust scores.

---

**Próxima sesión:** arranca **B.4.1** (verificación schemas — 30 min).
