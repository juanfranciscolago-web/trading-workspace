# Sprint 12 Priority Analysis — Bundle Protocol + Telemetry hybrid locked

**Fecha:** 2026-05-26
**Estado:** Decidido (Sprint 12 = Bundle Protocol + Telemetry hybrid LOCKED, S.12.protocol-a + S.12.telemetry-X sub-blocks pending)
**Contexto:** Sprint 11 ATLAS portfolio integration cerrado al 100% (commit `6f51efb`, ADR-013 Aceptado 2026-05-26). Sprint 12+ priority decision pending across 7 viable candidates per ADR-008 §9.4 + ADR-013 §9.4 + accumulated cross-sprint tech debt. Esta memo persiste el strategic scoring + Bundle Option C (Strategic override numerical winner) sign-off fresh con Trio foundation operational + telemetry-viable operator pre-deploy confirmado.

---

## 1. Context

### 1.1 Sprint 11 close-out state

- ADR-013 Aceptado 2026-05-26 (commit `6f51efb`). ATLAS portfolio integration operational.
- Trio ATHENA+APOLLO+ATLAS foundation operational (Sprint 5/7/9 producer + Sprint 10 consumer + Sprint 11 validator).
- 6 ADRs Aceptados activos: ADR-005/006/007/008/009/013.
- Tests baseline: 1037 + 1 skipped (921 multi-agent + 116 shared_core).
- 18 findings rule #15 cumulative Sprint 11 record (vs Sprint 10's 8).
- 6 NEW tech debt items §9.3 (5 Phase 1 simplifications D-η a D-λ + F-r14 Protocol refactor + F-r16 cross-cutting).

### 1.2 Re-score trigger per S.11.plan-a + ADR-008 §9.4 + ADR-013 §9.4

- Rule #15 strict: verify reality before spec.
- TENTATIVE caveat 5x proven (Sprints 8/9/10/11/12).
- Sprint 12 priority must re-score con Trio foundation operational context + accumulated tech debt + telemetry-viable confirmation.

### 1.3 Operator pre-deploy "telemetry-viable" confirmado

Juan confirmation pre-scoring: Paper trading observation telemetry candidate **viable Sprint 12** (operator pre-deploy Schwab subaccount + env vars plannable mid-sprint). Sin confirmation, telemetry candidate defer Sprint 13+.

### 1.4 6-day pause healthy precedent

Sprint 11 atlas-e (2026-05-20) → atlas-f (2026-05-26): 6-day operator break documented daily log §8 (cognitive load awareness post-intense work day). Memory rehydration clean post-break. Pattern reusable Sprint 12+ si needed.

### 1.5 Candidates inventory (7 viable Sprint 12)

**Prime canonical (3)**:
- #1 ADR-010 Schwab WebSocket part 1 (ADR-008 D6 + ADR-013 §9.4, Tier D multi-sprint).
- #2 ADR-011 GEX compute pipeline (ADR-008 D6 + ADR-013 §9.4, Tier A signals).
- #3 Paper trading observation telemetry (ADR-013 §9.4, TELEMETRY-VIABLE confirmed).

**Tech debt resolution (4)**:
- #4 Greeks D-η cross-source (ADR-013 §9.3 #1).
- #5 portfolio_beta D-κ cross-source (ADR-013 §9.3 #4).
- #6 CachedSnapshotBuilder Protocol refactor (ADR-013 §9.3 #5 + F-r14).
- #7 PnL history table D-θ (ADR-013 §9.3 #2).

**Defer Sprint 13+** (per ADR-008 timeline):
- ADR-012 HERMES implementation (Sprint 13-16+).

**Emergent candidates**: 0 (ADR-009/006/005 §9.3 inherited items all telemetry-driven, mismo trigger Q1).

---

## 2. Scoring methodology

6 dimensions weighted (5x proven Sprints 8/9/10/11/12):

| Dimension | Weight | 5 means | 1 means |
|-----------|--------|---------|---------|
| Paper trading impact | 25% | Direct unblock | No effect |
| Agent unlock | 20% | New agent operational | No agent change |
| Data deps (inverse) | 15% | No external deps | HUGE external deps |
| Effort (inverse) | 15% | <500 LOC | >5,000 LOC |
| Risk (inverse) | 15% | Proven pattern | Unknown territory |
| ADR prerequisite | 10% | Pure design/ADR | Pure implementation |

Weighted sum scoring (1-5 scale per dimension).

---

## 3. State per candidate (rule #15 pre-recolección Sprint 12)

### #1 ADR-010 Schwab WebSocket part 1
- Per ADR-008 D6 + D7: multi-sprint pattern part 1 + part 2 (Sprint 11 went ATLAS, defers Sprint 12+).
- OhlcvWorker S.9.ohl-b foundation ready (no DB blocker).
- HERMES (Sprint 13+ ADR-012) primary downstream consumer.

### #2 ADR-011 GEX compute pipeline
- Per ADR-008 D6: Sprint 12+ (Tier A dealer flows).
- iv_surface Sprint 7 + OI ready. Greeks computation library standard.
- ATHENA + HERMES Sprint 13+ both benefit (signal regime detection).

### #3 Paper trading observation telemetry
- ADR-013 §9.4: Sprint 11 LiveSnapshotBuilder code-ready BUT NOT activated production.
- USE_LIVE_PORTFOLIO + USE_SCHWAB_DATA_LAYER both False default. 0 production runs accumulated.
- Operator pre-deploy actions required (Schwab subaccount + env vars).
- Multi-trigger unlock: Q5 (Schwab throttling) + Q7 (ATHENA prompt budget) + R6 (ATLAS throttling) + F-r6.5 (budget reality).

### #4 Greeks D-η cross-source
- ADR-013 §9.3 #1 tech debt. PositionView delta/vega/theta default Decimal(0).
- Sources candidate: iv_surface Sprint 7 ✓ + options chain on-demand.
- Phase 1 currently functional sin Greeks (ATLAS cash/margin/exposure work).

### #5 portfolio_beta D-κ cross-source
- ADR-013 §9.3 #4 tech debt. Default 0.0 Phase 1.
- Source: SPX historical OHLC (Sprint 9 market.ohlcv ready) + multi-agent positions returns history (Sprint 11 atlas-d ready).
- ATLAS beta-based rules unlock.

### #6 CachedSnapshotBuilder Protocol refactor
- ADR-013 §9.3 #5 + F-r14 tech debt. mypy type hint generalization.
- Define `SupportsBuild` Protocol con `build() -> PortfolioSnapshot`.
- Update CachedSnapshotBuilder type hint `builder: SupportsBuild`.

### #7 PnL history table D-θ
- ADR-013 §9.3 #2 tech debt. pnl_weekly/monthly/drawdown default 0.0.
- NEW schema `daily_pnl_history` + populating worker + LiveSnapshotBuilder reads.

---

## 4. Scoring matrix Sprint 12

| Rank | # | Candidate | Paper 25% | Agent 20% | Data 15% | Effort 15% | Risk 15% | ADR 10% | **Weighted** |
|------|---|-----------|-----------|-----------|----------|------------|----------|---------|--------------|
| 🥇 | 3 | Paper trading telemetry | 5 | 3 | 3 | 4 | 2.5 | 2 | **3.48** |
| 🥈 | 2 | ADR-011 GEX compute | 3.5 | 4 | 3 | 3 | 3 | 3 | **3.33** |
| 🥉 | 6 | CachedSnapshotBuilder Protocol | 1 | 1 | 5 | 5 | 5 | 5 | **3.20** (methodology artifact) |
| 4 | 5 | portfolio_beta D-κ | 2 | 2 | 4 | 4 | 4 | 2 | **2.90** |
| 5 | 7 | PnL history D-θ | 3 | 3 | 2 | 3 | 3 | 2 | **2.75** |
| 6 | 4 | Greeks D-η | 3 | 2 | 3 | 3 | 3 | 2 | **2.70** |
| 7 | 1 | ADR-010 WebSocket part 1 | 2.5 | 2 | 3 | 2 | 2 | 4 | **2.48** |

Computation example #3: 5×0.25 + 3×0.20 + 3×0.15 + 4×0.15 + 2.5×0.15 + 2×0.10 = 1.25 + 0.60 + 0.45 + 0.60 + 0.375 + 0.20 = **3.475**.

**Scoring gap analysis**:
- #3 vs #2: **0.15** (TIGHT, NOT decisive — strategic identity decision needed per Camino 2 protocol Sprint 10 cons-a lesson).
- #2 vs #6: 0.13 (also tight).
- #6 methodology artifact: small candidates inflate via inverse dimensions 5/5/5 (effort + risk + deps). NOT genuine 3rd-place standalone candidate.
- **Real Sprint 12 contest**: #3 Telemetry vs #2 GEX.

**Strategic identity options** (NOT pure scoring):
- Option A: Telemetry sprint (#3 pure numerical winner, 3.48).
- Option B: GEX compute strategic override (#2, 3.33).
- Option C: Bundle hybrid (#6 Protocol quick win + #3 Telemetry).

---

## 5. Recommendation Sprint 12 = Bundle Protocol + Telemetry (Option C LOCKED)

Sprint 12 scope hybrid LOCKED per Juan explicit "bundle-lock" sign-off override numerical winner.

**Phase 1 (Day 1-2): #6 CachedSnapshotBuilder Protocol refactor**:
- Resolve F-r14 ADR-013 §9.3 #5 tech debt.
- Define `SupportsBuild` Protocol con `build() -> PortfolioSnapshot` signature.
- Update CachedSnapshotBuilder type hint `builder: SupportsBuild`.
- Update tests para verify Protocol compliance (SnapshotBuilder + LiveSnapshotBuilder).
- Estimate ~50-100 LOC code + ~5 tests + commit S.12.protocol-a.

**Phase 2 (Day 3+): #3 Paper trading observation telemetry**:
- Operator pre-deploy actions execute (Schwab subaccount + SCHWAB_ACCOUNT_ID env var + USE_LIVE_PORTFOLIO=True + USE_SCHWAB_DATA_LAYER=True).
- Telemetry setup: logs structured + alerts + metrics dashboard (Prometheus/Grafana or simple log analysis).
- Multi-trigger observation: Q5 + Q7 + R6 + F-r6.5 simultaneously.
- Ongoing observation 4-8 weeks (low-touch background).
- Estimate ~150-200 LOC setup + ongoing reports.

**6 rationales explícitas Bundle Option C**:

1. **Tight scoring gap (0.15)** between #3 Telemetry (3.48) y #2 GEX (3.33) NOT decisive numerically. Strategic identity choice needed per Camino 2 protocol Sprint 10 cons-a lesson (NO auto-Write decisive scoring).

2. **Validates Sprint 5-11 foundation BEFORE building MORE (GEX)**. Sprint 11 cerrado claimed "Trio operational" — telemetry verifies that claim con production runs. Building GEX (Sprint 12) sin validating ATLAS production (Sprint 11 outputs) = continuamos building blind.

3. **Multi-trigger unlock Sprint 12**: telemetry unlocks Q5 + Q7 + R6 + F-r6.5 simultaneously (ADR-009 + ADR-013 cross-sprint tech debt). Single sprint resolves 4 telemetry-driven triggers.

4. **Protocol refactor quick win** balances "soft sprint" feel of pure telemetry. Day 1-2 concrete deliverable (F-r14 tech debt #5 closed) + Day 3+ telemetry started = ROI maximizado.

5. **Operator pre-deploy ready** ("telemetry-viable confirmado"). Schwab subaccount creatable + env vars plannable + tiempo Sprint 12 disponible.

6. **GEX (#2) defer Sprint 13+**: HERMES Sprint 13+ ADR-012 primary consumer downstream. Without paper trading validation Sprint 12, GEX signals built blind. Sprint 13 fresh re-score per rule #15.

ADR number: **NO new ADR Sprint 12**.
- Protocol refactor = amendment ADR-013 §9.3 #5.
- Telemetry setup = operator doc §11 extension + light memo (no formal ADR).

---

## 6. Sub-blocks plan Sprint 12 (5 sub-blocks)

| Sub-block | Phase | Scope | Estimate |
|-----------|-------|-------|----------|
| S.12.plan-a | THIS commit | Priority analysis | ~200 LOC doc |
| S.12.protocol-a | Phase 1 (Day 1-2) | SupportsBuild Protocol + CachedSnapshotBuilder refactor + tests | ~75 LOC code + 5 tests |
| S.12.telemetry-a | Phase 2 (Day 3) | Telemetry setup memo + operator doc §11 ext | ~150 LOC doc |
| S.12.telemetry-b | Phase 2 (Day 4-5) | Structured logs + metrics scaffold | ~200 LOC code |
| S.12.telemetry-c | Phase 2 (ongoing) | Observation report + close-out | ~200 LOC doc |

**Total Sprint 12 estimate**: ~825 LOC code+tests+doc + ~5 tests + ongoing observation 4-8 semanas.

---

## 7. Sequence proposal Sprint 13+ TENTATIVE

> **NOTA OPERACIONAL**: Esta secuencia es propuesta basada en state al cierre Sprint 11 + Sprint 12 lock. Sprint 13+ NO está locked — se debe re-scorear fresh cuando se cierre Sprint 12, dado que telemetry observations Sprint 12 pueden revelar dependencies o priorities que cambien el cálculo. Per rule #15: verify reality before spec, incluso para planning.

Per ADR-008 §9.4 + Sprint 12 LOCK assumption + rule #15 strict TENTATIVE caveat:
- **Sprint 13**: ADR-011 GEX compute pipeline (Tier A, post-telemetry validation Sprint 12).
- **Sprint 13-14**: ADR-010 Schwab WebSocket part 1 (Tier D infra, multi-sprint).
- **Sprint 14-16+**: ADR-010 WebSocket part 2 + ADR-012 HERMES implementation.
- **Sprint 12+ Tech debt remaining**: #4 Greeks D-η + #5 portfolio_beta D-κ + #7 PnL history D-θ (trigger-based per telemetry observations).

### TENTATIVE caveat doctrine (5x proven Sprints 8/9/10/11/12)

- Sprint 13+ NOT locked Sprint 12.
- Re-score fresh per sprint close per rule #15 strict.
- ADR canonical re-read pre-Write discipline (F-r5 lesson Sprint 10).
- Budget management pre-Write + post-Write both required (F-r6/F-r6.5 lesson Sprint 10).
- Path verification pre-Write (F-r1 + F-r8 + F-r12 + F-r15 + F-r18 pattern Sprint 10/11).

Sprint 12 close-out doc (e.g., `S.12.telemetry-c`) MUST re-validate Sprint 13+ priority via fresh rule #15 pre-recolección + telemetry observation outcomes.

---

## 8. Out of scope (NOT Sprint 12)

- **#2 ADR-011 GEX compute pipeline** — Sprint 13 candidate (post-telemetry).
- **#1 ADR-010 Schwab WebSocket part 1** — Sprint 13-14 candidate.
- **#4 Greeks D-η + #5 portfolio_beta D-κ + #7 PnL history D-θ** — trigger-based, Sprint 13+ per telemetry observations.
- **ADR-012 HERMES implementation** — Sprint 14-16+ ADR-008 timeline.

---

## 9. References

- **ADR-005** Aceptado (Sprint 6 iv_rank).
- **ADR-006** Aceptado (Sprint 7 iv_surface).
- **ADR-007** Aceptado (Sprint 9 market.ohlcv).
- **ADR-008** Aceptado (Sprint 8 HERMES Tactical Scope, D6 sequencing).
- **ADR-009** Aceptado (Sprint 10 Phase 2 Consumer Surface UNIFIED, §9.3 Q5+Q7 telemetry triggers).
- **ADR-013** Aceptado (commit `6f51efb`, Sprint 11 ATLAS portfolio integration, §9.3 6 tech debt items + §9.4 Sprint 12+ candidates).
- **S.11.plan-a** (commit `e66ed45`): Sprint 11 priority analysis precedent + scoring methodology framework.
- **S.11.atlas-f** (commit `6f51efb`): Sprint 11 close-out + §9.4 Sprint 12+ TENTATIVE list.

---

> **Sprint 12 LOCKED = Bundle Protocol + Telemetry hybrid Option C.** NO new ADR. Sprint 13+ TENTATIVE per rule #15 strict + 5x proven caveat doctrine. Foundation building era continues Sprint 12-16+. Trio ATHENA+APOLLO+ATLAS production validation begins Sprint 12 atlas-telemetry Phase 2.
