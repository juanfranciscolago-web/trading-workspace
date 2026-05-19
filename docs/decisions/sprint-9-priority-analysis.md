# Sprint 9+ Priority Analysis — ADR-007 ohlcv locked

**Fecha:** 2026-05-19
**Estado:** Decidido (Sprint 9 = ADR-007 market.ohlcv, S.9.ohl-X sub-blocks pending)
**Contexto:** Sprint 8 HERMES Scope ADR cerrado al 100% (ADR-008 Aceptado 2026-05-19, commit `169cef2`). Frame 3 Phase 1 boundary locked. Sprint 9+ priority decision per S.8.plan-a TENTATIVE caveat (re-score fresh, NO anticipated). Esta memo persiste el strategic scoring + recommendation fresh con ADR-008 context + F-r1 finding (SchwabClient intraday signature ya ready).

---

## 1. Context

### 1.1 Sprint 8 close-out state

- ADR-008 Aceptado (2026-05-19, commit `169cef2`). Frame 3 locked.
- 4 ADRs downstream sequenced informed: ADR-007 → ADR-009 → ADR-010 → ADR-011.
- Trio ATHENA+APOLLO+ATLAS paper trading parallel durante foundation building Sprints 9-13.
- Tests baseline preserved: 918 + 1 skipped.

### 1.2 Re-score trigger per S.8.plan-a + ADR-008 §9.4

- Rule #15 strict: verify reality before spec.
- TENTATIVE sequence Sprint 9+ NO locked Sprint 8.
- Sprint 9 priority must re-score con Frame 3 context.

### 1.3 F-r1 finding — SchwabClient intraday ready

- Pre-recolección revealed `SchwabClient.get_price_history` already supports `frequency_type="minute"` from Sprint 5 S.5.6c.
- ADR-008 D5 wording said "extension needed" — outdated. NO new SchwabClient port required.
- Implication: ADR-007 effort estimate revised **3-5 días → 2-3 días**.
- Pattern mirror S.6.iv-b/c (Repository + Worker + lifespan, no novel architectural decisions).

### 1.4 Candidates inventory (5 viable Sprint 9 + 3 defer)

Viable Sprint 9:

- **#1 ADR-007 ohlcv** (market.ohlcv producer/consumer).
- **#2 Phase 2 consumer surface** (ATHENA quality unlock).
- **#7 ATLAS portfolio integration**.

Defer Sprint 9 (timing trigger):

- ADR-009 Schwab WebSocket: depends on ADR-007 ohlcv consumer pattern foundation.
- ADR-010 GEX compute: depends on Sprint 11-12 WebSocket + Tier A foundation Sprint 12+.
- ADR-011 HERMES real: requires Tiers A+B+C+D delivered first (Sprint 13-16+).

---

## 2. Scoring methodology

(Reusable framework Sprint 8: 6 dimensions weighted)

| Dimension | Weight |
|-----------|--------|
| Paper trading impact | 25% |
| Agent unlock | 20% |
| Data deps (inverse) | 15% |
| Effort (inverse) | 15% |
| Risk (inverse) | 15% |
| ADR prerequisite | 10% |

---

## 3. State per candidate (rule #15 pre-recolección Sprint 9)

### #1 ADR-007 ohlcv (Sprint 9 candidate fuerte)

- V007 schema exists `market.ohlcv` hypertable (Apr 28, UNWRITTEN).
- `SchwabClient.get_price_history` ready (F-r1 finding — `frequency_type="minute"` supported).
- NO ohlcv Repository / Worker / tests existentes.
- Pattern mirror: S.6.iv-b/c proven 2x.

### #2 Phase 2 consumer surface

- `TickerSnapshot` 8 fields actuales (NO term_structure ni surface field).
- `ohlcv_hourly` empty (deferred S.5.6e).
- iv_surface populated Sprint 7 (write-side complete, read-side missing).
- `SchwabDataLayer` NO consume iv_surface (Sprint 7 D6 strict).

### #7 ATLAS portfolio integration

- `SchwabClient.get_positions` + `get_balances` stubs `NotImplementedError`.
- `PortfolioSnapshot` infra complete (V011 + repository + tests).
- Eolo precedent: 3 sources (options + crop + crypto-dashboard).

---

## 4. Scoring matrix Sprint 9

| Candidate | Paper (25%) | Agent (20%) | Data (15%) | Effort (15%) | Risk (15%) | ADR (10%) | Weighted |
|-----------|--------------|--------------|--------------|---------------|-------------|------------|------------|
| **#1 ADR-007 ohlcv** | 4 | 4 | 5 | 5 | 5 | 3 | **4.40** ← Sprint 9 LOCKED |
| **#2 Phase 2 consumer surface** | 5 | 3 | 5 | 4 | 4 | 2 | **4.00** |
| **#7 ATLAS portfolio integration** | 5 | 4 | 3 | 3 | 3 | 2 | **3.60** |

ADR-007 ohlcv **4.40** — highest. F-r1 finding boosts Effort + Risk scores (Sprint 5 SchwabClient + S.6.iv pattern combine).

---

## 5. Recommendation Sprint 9 = ADR-007 ohlcv

Razones:

1. Highest weighted score (**4.40** up from 3.75 Sprint 8 thanks to F-r1).
2. Matches ADR-008 §9.4 canonical sequence.
3. F-r1 finding reveals SchwabClient ready + pattern S.6.iv-b/c proven 2x.
4. Estimate **2-3 días** (revised from 3-5 días).
5. Tier C foundation unblocks HERMES Phase 1 data layer downstream.
6. Tier A volume profile aggregation foundation (Sprint 12+ ADR-010 prereq).

---

## 6. Sequence proposal Sprint 10+ (TENTATIVE)

> **NOTA OPERACIONAL**: Esta secuencia es propuesta basada en state al cierre Sprint 8 + Sprint 9 lock. Sprint 10+ NO está locked — se debe re-scorear fresh cuando se cierre Sprint 9, dado que Sprint 9 implementation puede revelar dependencies o priorities que cambien el cálculo. Per rule #15: verify reality before spec, incluso para planning.

Tentative sequence (per ADR-008 §9.4 + Sprint 9 outputs):

- **Sprint 10**: Phase 2 consumer surface OR ATLAS portfolio integration (re-score post-Sprint 9).
- **Sprint 11-12**: ADR-009 Schwab WebSocket (multi-sprint).
- **Sprint 12+**: ADR-010 GEX compute pipeline.
- **Sprint 13-16+**: ADR-011 HERMES implementation.

Adjacent candidate: ATLAS portfolio integration (Sprint 10/11+ probable depending on Sprint 9 close — paper trading discipline unblocker, highest Paper Trading Impact 5/5).

---

## 7. Out of scope

- Sprint 9 implementation details (deferred ADR-007 dentro de S.9.ohl-X).
- ADR-007 sub-block breakdown final (estimate compact pattern: S.9.ohl-a plan + S.9.ohl-b implementation+close-out).
- Sprint 10+ commit (tentative per §6 caveat).

---

## 8. References

- **ADR-008** (commit `169cef2`): Frame 3 + 4 ADRs downstream sequence.
- **ADR-008 §9.4**: Sprint 9+ canonical sequence + ATLAS adjacent.
- **S.8.plan-a** (commit `4bd0819`): TENTATIVE caveat doctrine.
- **ADR-005** (Sprint 6 iv_history): pattern reference S.6.iv-b/c.
- **ADR-006** (Sprint 7 iv_surface): pattern reference + tech debt cross-ref.
- **F-r1 finding**: SchwabClient intraday signature ready S.5.6c.

---

> **Sprint 9 LOCKED = ADR-007 ohlcv.** Sprint 10+ TENTATIVE, re-score per sprint close.
