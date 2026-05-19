# Sprint 8+ Priority Analysis — HERMES Scope ADR locked

**Fecha:** 2026-05-18
**Estado:** Decidido (Sprint 8 = HERMES Scope ADR, S.8.her-X sub-blocks pending)
**Contexto:** Sprint 7 iv_surface stage cerrado al 100% (ADR-006 Aceptado 2026-05-16, commit `bdb0106`). Sprint 8+ priority decision pending across 4 viable candidates + 4 defer candidates. Esta memo persiste el strategic scoring + recommendation + sequence proposal post Juan pain confirmation.

---

## 1. Context

### 1.1 Sprint 7 close-out state

- Tests baseline: **918 + 1 skipped** (multi-agent 823 + shared_core 95).
- ADR-006 Aceptado 2026-05-16. ADR-005 §9.3 #2 (`market.iv_surface` populating) RESOLVED Sprint 7.
- 6 candidates pending decision per ADR-006 §9.4 + 1 NEW candidate emerged (HERMES Scope ADR) + 1 incidentally surfaced (ATLAS portfolio integration) = 8 candidates total.

### 1.2 Juan pain primary confirmed: B (HERMES tactical design)

Sub-decision: **B2 path** — HERMES Scope ADR primero (design boundary), data layer enabler después.

### 1.3 Decision meta locked

**"FULL" HERMES per masterdoc §3.3** será el target (NOT scope-reduced version). Accepting:

- **Sprint 14-16+ timeline para HERMES real implementation** (data layer build-out required first).
- **Paper trading durante Sprints 9-13 con ATHENA + APOLLO + ATLAS trio** (no HERMES en debate chain).
- Foundation building era: data layer expansion + ATLAS portfolio integration + ATHENA quality enhancements antes de HERMES real.

ADR-008 HERMES Scope ADR (Sprint 8 deliverable) define qué subset de masterdoc §3.3 delivers Phase 1 vs Phase 2+ accumulating-for-future. Esta memo NO decide that boundary — defers a ADR-008.

### 1.4 Candidates inventory (8 total)

**Viable Sprint 8** (4):

- #1 ADR-007 ohlcv producer/consumer
- #2 Phase 2 consumer surface
- #7 ATLAS portfolio integration
- #8 HERMES Scope ADR (NEW, emerged 2026-05-18)

**Defer Sprint 10+** (1):

- #4 NYX sentiment (masterdoc §10.7 canonical, postponed per ADR-006 D9 — sentiment data layer ADR materialization required)

**Trigger-based defer** (3):

- #3 D5 retention (5 GB OR p99 > 500ms — triggers not met)
- #5 strike count tuning (empirical observation deferred)
- #6 F7 iv=0.0 vs None disambiguation (no concrete issue)

---

## 2. Scoring methodology

6 dimensions con weights per Juan's framework:

| Dimension | Weight | 5 means | 1 means |
|---|---|---|---|
| Paper trading impact | 25% | Direct unblock | No effect |
| Agent unlock | 20% | New agent operational | No agent change |
| Data deps (inverse) | 15% | No external deps | HUGE external deps |
| Effort (inverse) | 15% | <500 LOC | >5,000 LOC |
| Risk (inverse) | 15% | Proven pattern | Unknown territory |
| ADR prerequisite | 10% | Pure design/ADR | Pure implementation |

Weighted sum scoring (1-5 scale per dimension).

---

## 3. State per candidate (rule #15 pre-recolección, 2026-05-18)

### #8 HERMES Scope ADR

- HERMES code: `hermes_mock.py` only (BaseMockAgent, pre-canned agree/disagree/neutral summaries).
- **Tests existentes: 0 files** (find empty).
- **NO ADR previo en `docs/decisions/`**. Greenfield design.
- Masterdoc §3.3 detailed spec available — 8 data sources enumerated (L2 real-time, tape, unusual options, dark pool, GEX/vanna/charm, VIX intraday, volume profile, news real-time).

### #2 Phase 2 consumer surface

- `TickerSnapshot` actuales: 8 fields, **NO term_structure NI surface**.
- `SchwabDataLayer` NO consume iv_surface (Sprint 7 WRITE-only D6 strict).
- iv_surface populated Sprint 7, reader pending.

### #1 ADR-007 ohlcv

- V007 schema `market.ohlcv` hypertable exists (timeframes 1m|5m|1h|1d, PK ts+ticker+timeframe, 1-day chunks). UNWRITTEN.
- `SchwabClient.get_price_history` implementado Sprint 5 S.5.6c (daily only).
- Intraday timeframes (1m/5m/1h): NOT implemented en SchwabClient.

### #7 ATLAS portfolio integration

- `SchwabClient.get_positions()`: NotImplementedError stub.
- `SchwabClient.get_balances()`: NotImplementedError stub.
- `PortfolioSnapshot` + `SnapshotBuilder` complete (DB-backed via `portfolio.positions` + `portfolio.snapshots`).
- Eolo precedent: `eolo-options/execution/options_trader.py` + `eolo-crypto-dashboard/main.py`.
- NO synthetic portfolio seeder existing.

---

## 4. Scoring matrix

| Candidate | Paper trading (25%) | Agent unlock (20%) | Data deps (15%) | Effort (15%) | Risk (15%) | ADR prereq (10%) | **Weighted** |
|---|---|---|---|---|---|---|---|
| **#8 HERMES Scope ADR** | 3 | 5 | 5 | 4 | 4 | 5 | **4.20** ← Sprint 8 LOCKED |
| **#2 Phase 2 consumer surface** | 5 | 3 | 5 | 4 | 4 | 2 | **4.00** |
| **#1 ADR-007 ohlcv** | 4 | 4 | 4 | 3 | 4 | 3 | **3.75** |
| **#7 ATLAS portfolio integration** | 5 | 4 | 3 | 3 | 3 | 2 | **3.60** |

Computation example #8: 3×0.25 + 5×0.20 + 5×0.15 + 4×0.15 + 4×0.15 + 5×0.10 = 0.75 + 1.00 + 0.75 + 0.60 + 0.60 + 0.50 = **4.20**.

---

## 5. Recommendation Sprint 8 = #8 HERMES Scope ADR

Razones:

1. **Highest weighted score (4.20)** entre 4 viable candidates.
2. **Matches Juan pain B confirmed + B2 path explicit** (Scope ADR primero, data layer después).
3. **Greenfield design space**: masterdoc §3.3 detailed spec available, no prior ADR baggage, no test debt para preservar.
4. **Lowest effort tier** (~2-3 días doc-only) + lowest risk (proven ADR template ADR-005/006).
5. **Unblocks Sprint 9+ candidates**: HERMES Scope ADR clarifies which data layer subset becomes Sprint 9+ implementation target.
6. **ADR prerequisite 5/5**: pure design/planning work — IS the ADR.

Sprint 8 sub-blocks naming: S.8.her-a (ADR-008 plan firmado) → S.8.her-b/c/d/... per ADR-008 §3 sub-block breakdown (TBD per ADR content).

---

## 6. Sequence proposal Sprint 9+ (TENTATIVE)

**Caveat per rule #15**: re-score fresh at each sprint close. NOT anticipated 4-6 months ahead. Sequence below is **directional tentative**, subject to revision based on:

- ADR-008 outcome (HERMES Phase 1 boundary).
- New tech debt emerging during Sprint 8.
- Trading context changes (Juan pain re-evaluation).

### Tentative directional sequence

| Sprint | Candidate | Trigger condition |
|---|---|---|
| Sprint 9 | #1 ADR-007 ohlcv | If ADR-008 Phase 1 includes OHLCV momentum — most likely path |
| Sprint 10 | #2 Phase 2 consumer surface | ATHENA quality unlock independent del HERMES path |
| Sprint 11+ | #7 ATLAS portfolio integration | Paper trading confidence prerequisite (post-trio stabilization) |
| Sprint 12+ | #4 NYX sentiment ADR | Sentiment data layer materialization |
| Sprint 14-16+ | HERMES real implementation | Post-data layer build-out (foundation complete) |

### Branching logic Sprint 9 (post-ADR-008)

- **If ADR-008 Phase 1 = OHLCV momentum-based** → Sprint 9 = #1 ADR-007 ohlcv (intraday timeframes).
- **If ADR-008 Phase 1 = Unusual options activity** → Sprint 9 = ADR-009 supplement (Schwab unusual options ports + storage).
- **If ADR-008 Phase 1 = News reactions** → Sprint 9 = news feed integration ADR.

### Re-score pattern

Each sprint close-out doc (close-out commit, e.g., `S.8.her-d`) MUST re-validate next sprint priority via fresh rule #15 pre-recolección. Memo persistente serves como historical record, NOT as binding contract.

---

## 7. Out of scope

- **Sprint 8 implementation** — Sprint 8 deliverable es ADR-008 (HERMES Scope ADR), NO code. This memo is decision-only.
- **HERMES design content** — deferred a ADR-008 (which subset masterdoc §3.3 delivers Phase 1).
- **Specific sub-block breakdown S.8.her-X** — per ADR-008 §3 (TBD).
- **Sprint 9+ implementation commitments** — tentative per §6, subject to re-scoring.

---

## 8. References

- **ADR-006** (`docs/decisions/006-iv-surface-populating.md`): Sprint 7 close-out con §9.4 6 candidates listed.
- **Sprint 7 close-out commit**: `bdb0106` (S.7.surf-d).
- **HERMES masterdoc**: `docs/sistema_multiagente_trading.md` §3.3 (full spec).
- **NYX masterdoc**: `docs/sistema_multiagente_trading.md` §3.4 + §10.7 (Sprint 7 canonical, postponed per ADR-006 D9).
- **Memory persistente**: `~/.claude/projects/-Users-JUAN-Documents-trading-workspace/memory/project_sprint_state.md`.
- **CLAUDE.md rule #15**: verify reality before spec (re-scoring per sprint close pattern).

---

> **Sprint 8 = ADR-008 HERMES Scope ADR. Sequence Sprint 9+ tentative, re-validated each sprint close.**
