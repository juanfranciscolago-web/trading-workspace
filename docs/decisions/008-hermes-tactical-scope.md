# ADR-008: HERMES Tactical Flow Trader Scope

**Fecha:** 2026-05-19
**Estado:** Propuesto
**Contexto:** Sprint 8 LOCKED via Sprint 8+ priority analysis (commit `4bd0819`, 2026-05-18). Pain primary B confirmed (HERMES tactical design) + B2 path (Scope ADR primero, data layer después). Decision meta: "FULL" HERMES per masterdoc §3.3, accepting Sprint 14-16+ timeline. Esta ADR define Phase 1 scope (Schwab-native data tiers A-D, Sprint 9-13) vs Phase 2 deferred (external vendors Tier E, Sprint 16+).

---

## 1. Context

### 1.1 Sprint 8 lock per priority analysis

Sprint 7 iv_surface stage cerrado al 100% (commit `bdb0106`, ADR-006 Aceptado 2026-05-16). Sprint 8+ priority decision locked Sprint 8 = HERMES Scope ADR per scoring matrix (#8 won 4.20/5):

- `docs/decisions/sprint-8-priority-analysis.md` (commit `4bd0819`, 2026-05-18).
- 4 viable candidates scored (#8 HERMES Scope ADR, #2 Phase 2 consumer surface, #1 ADR-007 ohlcv, #7 ATLAS portfolio integration).
- Sprint 9+ tentative sequence (re-score fresh per sprint close, rule #15 caveat explicit).

### 1.2 Pain primario B (HERMES tactical design unblock)

Sub-decision: **B2 path** — HERMES Scope ADR primero (esta ADR), data layer enabler después (Sprint 9+ implementation ADRs).

### 1.3 Decision meta locked: FULL HERMES per masterdoc §3.3

Sprint 8+ priority analysis §1.3 locked:

- **"FULL" HERMES** target (NOT scope-reduced version).
- **Sprint 14-16+ timeline** para HERMES real implementation.
- **Paper trading durante Sprints 9-13 con ATHENA + APOLLO + ATLAS trio** (no HERMES en debate chain).

### 1.4 Frame 3 locked: Phase 1 = Schwab REST + WebSocket (Tiers A+B+C+D)

Phase 1 scope draws boundary at **Schwab-native data** (REST API + WebSocket port). External vendors deferred a Phase 2.

Tier classification (see D5 for full per-tier infra requirements):

- **Tier A**: Compute-side (no external data fetch).
- **Tier B**: Daily Schwab REST (existing Sprint 5).
- **Tier C**: Intraday Schwab REST (NEW Sprint 9+).
- **Tier D**: Schwab WebSocket (NEW Sprint 11+, real-time streaming).

### 1.5 Phase 2 deferred: external vendors (Tier E) Sprint 16+

External feeds (dark pool prints, real-time news) explicitly out-of-scope Phase 1. Trigger condition: HERMES Phase 1 delivers paper trading positive ROI sin dark pool/news, OR vendor cost justified by alpha signal incremental.

---

## 2. Decisions

### D1. Phase 1 scope — 4 tier classification (A+B+C+D, Sprint 9-13)

**Decisión:** HERMES Phase 1 incluye data sources clasificadas en Tiers A-D (Schwab-native). Tier E (external vendors) deferred Phase 2 (Sprint 16+).

Mapping 8 HERMES data sources (masterdoc §3.3) → tiers:

| Source masterdoc | Tier | Phase | Notes |
|---|---|---|---|
| L2 / Order book real-time | D | 1 | Schwab WebSocket (NEW port) |
| Tape / volumen agresor | D | 1 | Schwab WebSocket |
| Unusual options activity | C/D | 1 | Detection logic over chain snapshots (intraday) |
| Dark pool prints intraday | E | 2 | Third-party vendor (Sprint 16+) |
| GEX/vanna/charm flows | A | 1 | Compute from iv_surface (S.7.surf-b ready) |
| VIX intraday, VVIX | C | 1 | Schwab REST quotes (intraday) |
| Volume profile intraday | A/C | 1 | Compute from intraday OHLCV (Tier C bars + Tier A aggregation) |
| News real-time | E | 2 | Third-party vendor (Sprint 16+) |

**Phase 1 covers 6 of 8 sources. Phase 2 covers remaining 2 (dark pool + news).**

| Opción | Descripción | Descartada porque |
|---|---|---|
| **A (this)** | Tiers A-D Phase 1, Tier E Phase 2 | Schwab-native scope reasonable Sprint 13-14 delivery. Phase 2 trigger on empirical Phase 1 ROI. |
| B | All 8 sources Phase 1 | Massive scope, Sprint 20+ timeline. Postpones paper trading discipline. |
| C | Only Tiers A+B Phase 1 (compute + daily) | Insufficient tactical edge. HERMES masterdoc §3.3 time horizon "minutos a horas" requires Tier C minimum. |

### D2. HERMES rol consensus chain — critic primario, proposer secundario condicional

**Decisión:** HERMES integrates en debate chain como:
- **Critic primario** (similar to APOLLO Sprint 4 role) for ATHENA/APOLLO proposals.
- **Proposer secundario condicional** — generates own proposals only when tactical signal strong (e.g., GEX flip + tape divergence). Default no_setup escape hatch frequent.

Razón: HERMES intraday time horizon doesn't always align con ATHENA 15-45 días / APOLLO weeks-months. Most days HERMES has no tactical setup. Critic role provides value every cycle; proposer role episodic.

### D3. Time horizon operacional — intraday (5m-60m bars + WebSocket events)

**Decisión:** HERMES operational granularity:
- **5m-60m intraday bars** (Tier C) para momentum + volume profile.
- **WebSocket events** (Tier D) para tactical setups en real-time (L2 imbalance, tape acceleration).
- **Daily snapshot** (Tier B) para context (gap from prior close, overnight news catch-up).

Cycle cadence: HERMES proposer evaluates intraday on-demand (event-driven). Critic evaluates con normal debate cycle.

### D4. Output schema — ProposalMessage + CritiqueMessage extended

**Decisión:**
- HERMES proposer output: `ProposalMessage` shape (same as ATHENA) con `time_horizon_days` field overloaded para fractional days (e.g., `0.5` = 12 hours).
- HERMES critic output: `CritiqueMessage` shape extended con field `tactical_flag_raised: bool` (similar to `contrarian_flag_raised` APOLLO).
- ClaudeRouter `task_type`: NEW `tactical_proposal` (proposer) + NEW `tactical_critique` (critic). Both Sonnet 4.6 default (per LLM delegation §8.6).

### D5. Data layer requirements per tier

**Tier A (Compute-side):**
- GEX/vanna/charm aggregation from existing `market.iv_surface` (per-strike OI ✓, gamma ✓).
- Volume profile aggregation from intraday OHLCV (requires Tier C first).
- Effort: ~200-400 LOC compute module (Sprint 12+).

**Tier B (Daily Schwab REST):**
- ALREADY IMPLEMENTED (Sprint 5 S.5.6c).

**Tier C (Intraday Schwab REST):**
- `SchwabClient.get_price_history` extension para 5m/15m/30m/60m timeframes.
- VIX/VVIX intraday quote endpoint (NEW).
- Unusual options activity detection over chain snapshots (NEW compute on Sprint 7 iv_surface base).
- Storage: `market.ohlcv` hypertable V007 (UNWRITTEN) populated by NEW worker.
- **ADR-007 prerequisite (drives Sprint 9).**

**Tier D (Schwab WebSocket NEW infra):**
- `SchwabClient.subscribe_quotes/level2/tape` ports (NEW, no Eolo precedent — Eolo uses REST only).
- WebSocket client + connection management + reconnect policy.
- Streaming → event bus integration (Redis stream NEW topic `tactical_events`).
- **ADR-009 candidate (drives Sprint 11+).**

**Tier E (External vendors, Phase 2):**
- Dark pool feed: TBD vendor.
- Real-time news: TBD vendor.
- Out of scope Phase 1.

### D6. ADR sequencing downstream

**Decisión:** Phase 1 implementation requires sequenced ADRs:

1. **ADR-007** (market.ohlcv producer/consumer) — Sprint 9. Tier C intraday bars + Tier A volume profile foundation.
2. **ADR-009** (Schwab WebSocket port) — Sprint 11+. Tier D real-time L2/tape.
3. **ADR-010** (GEX compute pipeline) — Sprint 12+. Tier A dealer flows.
4. **ADR-011** (HERMES implementation) — Sprint 13-14+. Integrates Tiers A+B+C+D + prompt + agent class + debate chain.

Each downstream ADR follows ADR-005/006 pattern.

### D7. Sub-sprint breakdown per data tier (incremental delivery)

**Decisión:** HERMES build-out spans ~6 sprints (9-14) with incremental tier delivery:

- Sprint 9: Tier C foundation (ohlcv intraday via ADR-007).
- Sprint 10: Phase 2 consumer surface (ATHENA quality + Tier A base for HERMES later).
- Sprint 11: Tier D infra (WebSocket via ADR-009 part 1).
- Sprint 12: Tier A compute pipeline (GEX via ADR-010) + WebSocket completion (ADR-009 part 2).
- Sprint 13-14: HERMES agent class + prompt + debate integration (ADR-011).

Incremental delivery permits paper trading durante build-out (foundation building era).

### D8. Out of scope Phase 1: Tier E (vendors)

**Decisión:** Phase 1 NO incluye:
- Dark pool feeds (third-party vendor).
- Real-time news (NLP vendor + pipeline).
- AAII/NAAIM sentiment surveys (NYX-adjacent, separate ADR).

Trigger Phase 2 (Sprint 16+):
- Phase 1 HERMES delivered + paper trading positive ROI sin Tier E.
- Vendor cost justified by alpha signal incremental.
- NYX integration provides reusable sentiment data layer (shared infra opportunity).

### D9. Open questions list (preserve para Phase 2 trigger decisions)

**Decisión:** Phase 2 decisions deferred a empirical Phase 1 data:
- Vendor selection (dark pool source, news source).
- Latency tolerance Tier E feeds.
- HERMES Phase 2 prompt extension.

§4 Open Questions enumera Q1-Q7 con triggers.

---

## 3. Sub-blocks (S.8.her-X)

| Sub-block | Date | Description | LOC est | Time est |
|---|---|---|---|---|
| **S.8.her-a** | 2026-05-19 | ADR-008 plan firmado (this commit) | ~300 (doc) | 2-3h |
| **S.8.her-b** | TBD | Refinement strategic discussion + decisions D1-D9 lock | ~50-100 (doc edits) | 1-2h |
| **S.8.her-c** | TBD | ADR-008 close-out + Aceptado + commit message comprehensive | ~80-130 (doc) | 1-2h |

**Total estimado:** ~430-530 LOC doc-only, ~4-7h.

ADR-008 Aceptado triggers Sprint 9 planning re-score (per rule #15 caveat memo S.8.plan-a §6).

---

## 4. Open questions

- **Q1: Latency tolerable HERMES** — sub-second (Tier D real-time tactical) vs few-seconds (Tier C intraday bars sufficient)? Decision factor: tactical setup time horizon. 0DTE SPX may need sub-second; weeklies tolerable few-seconds.
- **Q2: GEX compute frequency** — real-time per chain update (Tier D streaming) vs intraday snapshot (Tier C 15m/60m)? Compute cost vs signal freshness trade-off.
- **Q3: Schwab WebSocket reconnect policy** — disconnect frequency unknown. Affects ADR-009 design (idempotency + back-fill).
- **Q4: HERMES debate cadence con ATHENA** — per proposal cycle (synchronous) vs continuous event-driven (asynchronous)? Architecture impact on agent chain.
- **Q5: HERMES Phase 1 ROI threshold** — paper trading metric to gate Phase 2 (e.g., Sharpe > 1.5 over 3 months paper).
- **Q6: GEX validation** — iv_surface OI + greeks sufficient for GEX/vanna/charm compute accuracy? Math validation against external GEX feeds (SpotGamma comparison) en ADR-010.
- **Q7: ATHENA prompt extension** — should ATHENA prompt mention HERMES tactical output for awareness, or HERMES isolated until consensus engine reconciles?

---

## 5. Out of scope

- **HERMES implementation Phase 1** (Sprint 13-14+). Deferred a ADR-011.
- **Phase 2 vendors integration** (Sprint 16+ trigger-based).
- **ATHENA prompt extension to consume HERMES output** — post Phase 1 ADR-011 close-out.
- **VESTA long-term memory integration** — Sprint 10+ separate ADR.
- **NYX sentiment data layer overlap** — separate ADR Sprint 11+ candidate.
- **Consensus engine HERMES integration** — Sprint 14+ post-ADR-011.

---

## 6. Success criteria

1. **ADR-008 Aceptado** by end of Sprint 8 (S.8.her-c close-out).
2. **D1-D9 locked** con Juan sign-off + sub-decisions refined (S.8.her-b).
3. **Tier classification A/B/C/D/E** explicit en D5 per data source.
4. **Downstream ADRs (007, 009, 010, 011) scope informed** by ADR-008 D6 sequencing.
5. **Sprint 9 priority analysis re-scored** con ADR-008 context.
6. **Open questions Q1-Q7** preserved para Phase 2 / sub-decisions trigger.
7. **HERMES voz spec en masterdoc §3.3** preserved verbatim (no scope reduction).

---

## 7. Risks

| ID | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R1 | Phase 1 underscoped — HERMES "no tactical" suficiente, redirection mid-sprint | Medium | D1 4-tier framework comprehensive (6/8 sources); Sprint 13-14 re-validation gate |
| R2 | Phase 1 overscoped — Sprint 13-14 timeline slips | Medium-High | Incremental tier delivery D7; foundation building tolerable; trio paper trading parallel |
| R3 | Schwab WebSocket port more difficult (Sprint 11-12 expand) | Medium | ADR-009 dedicated scope; Eolo NO precedent; budget +1 sprint contingency |
| R4 | GEX compute mathematically incorrect — iv_surface data sufficient? | Low-Medium | Q6 open question; external GEX feed validation (SpotGamma) en ADR-010 |
| R5 | HERMES + ATHENA debate semantics — consensus dilution | Medium | D2 critic primario role (additive not contradictory); D4 tactical_flag separate from contrarian_flag |
| R6 | Empirical Phase 2 trigger not met — Tier E never delivered | Low (intentional) | Phase 2 defer doctrine: positive ROI gates investment, NO speculation |
| R7 | Tier D WebSocket Schwab API change/deprecation | Low | Schwab stable API contract; mitigate via abstraction SchwabClient |

---

## 8. References

- **Masterdoc** (`docs/sistema_multiagente_trading.md`) §3.3: HERMES detailed spec (8 data sources, time horizon, marco analítico).
- **Masterdoc §10.6/10.7**: Sprint roadmap (HERMES Sprint 7 canonical original, postponed via ADR-006 D9 + S.8.plan-a → Sprint 13-14+ realistic).
- **`docs/decisions/sprint-8-priority-analysis.md`** (commit `4bd0819`): Sprint 8 lock, scoring, sequence Sprint 9+ tentative.
- **ADR-006** (`docs/decisions/006-iv-surface-populating.md`): iv_surface populated Sprint 7, ready para Tier A GEX compute.
- **ADR-005** (`docs/decisions/005-iv-history-and-iv-rank-compute.md`): pattern reusable for tactical agents.
- **ADR-004** (`docs/decisions/004-sprint-5-schwab-integration.md`): Schwab REST baseline.
- **`multi-agent-system/src/multi_agent/agents/athena_prompt.py`**: prompt pattern para HERMES prompt mirror.
- **`multi-agent-system/src/multi_agent/agents/apollo_prompt.py`**: critic prompt pattern para HERMES critic role (D2).
- **`multi-agent-system/src/multi_agent/agents/hermes_mock.py`**: current mock, replaced Sprint 13-14+.
- **Eolo precedent NOT directly applicable** — multi-bot stand-alone strategies vs single LLM-agent multi-strategy. Pre-recolección finding S.8.her-a.

---

## 9. Close-out (S.8.her-c, pending)

> Sección se completa en S.8.her-c. Estructura prevista (mirror ADR-005/006):
> - §9.1 Sub-blocks delivered (S.8.her-a/b/c con commits + LOC + sign-off dates).
> - §9.2 Rule #15 findings summary.
> - §9.3 Tech debt registered for Sprint 9-14+.
> - §9.4 Next steps Sprint 9+ (ADR-007 ohlcv priority + sequence re-score).
> - Status: Propuesto → Aceptado.

---

> **Próximo sub-bloque:** S.8.her-b (refinement strategic discussion + D1-D9 lock). Inicia tras Juan sign-off del plan firmado actual.
