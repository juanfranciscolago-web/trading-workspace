# Sprint 11+ Priority Analysis — ATLAS portfolio integration locked

**Fecha:** 2026-05-20
**Estado:** Decidido (Sprint 11 = #7 ATLAS portfolio integration LOCKED, S.11.atlas-X sub-blocks pending)
**Contexto:** Sprint 10 Phase 2 consumer surface UNIFIED cerrado al 100% (commit `dea7ee9`, ADR-009 Aceptado 2026-05-19). Sprint 11+ priority decision pending across 2 viable candidates per ADR-008 §9.4 + Sprint 10 §9.4 cross-ref. Esta memo persiste el strategic scoring + recommendation fresh con Foundation completion narrative + Sprint 10 lessons.

---

## 1. Context

### 1.1 Sprint 10 close-out state

- ADR-009 Aceptado 2026-05-19 (commit `dea7ee9`). Phase 2 consumer surface UNIFIED operational.
- ATHENA quality unlock delivered: term_structure + surface + ohlcv_intraday wired.
- Tests baseline: 901 multi-agent + 95 shared_core = 996 + 1 skipped.
- 8 findings rule #15 catches (F-r1 a F-r6.5 + F-r8) — Sprint 10 record cumulative single sprint.
- 4 inherited tech debt items RESOLVED Sprint 10 (ADR-005 §9.3 #2 + ADR-006 D6-1 + ADR-007 §9.3 #4 + S.9 §5).

### 1.2 Re-score trigger per S.10.plan-a + ADR-008 §9.4

- Rule #15 strict: verify reality before spec.
- TENTATIVE sequence Sprint 11+ NO locked Sprint 10.
- Sprint 11 priority must re-score con Foundation building era + Sprint 10 lessons context.

### 1.3 Sprint 10 lessons applied Sprint 11 workflow

- Camino 2 protocol Juan deliberate sign-off (no auto-Write after scoring "decisive").
- ADR canonical verbatim re-read en cada sub-block touching cemented decisions (F-r5 lesson).
- Estimate + reality measurement pair para budget-sensitive ops (F-r6/F-r6.5 lesson).
- Path verification pre-Write para file references (F-r1 + F-r8 pattern).
- Pre-recolección rule #15 strict mandatory antes de scoring.

### 1.4 Candidates inventory (2 viable Sprint 11)

Viable Sprint 11:

- **#7 ATLAS portfolio integration** (S.10.plan-a §6 #1 adjacent candidate + S.10.cons-f §9.4 likely LOCK).
- **ADR-010 Schwab WebSocket part 1** (per ADR-008 D6 multi-sprint Sprint 11-12).

Defer Sprint 12+ (per ADR-008 §9.4 + Sprint 10 lessons):

- ADR-011 GEX compute pipeline (Sprint 12-13+ Tier A).
- ADR-012 HERMES implementation (Sprint 13-16+).
- Phase 2 telemetry observation (waiting period, no actionable code Sprint 11).

---

## 2. Scoring methodology

6 dimensions weighted (mirror S.8.plan-a + S.9.plan-a + S.10.plan-a proven 3x → 4x con Sprint 11):

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

## 3. State per candidate (rule #15 pre-recolección Sprint 11)

### #7 ATLAS portfolio integration

- `SchwabClient.get_positions` (line 682) + `get_balances` (line 690) = `raise NotImplementedError("Port from Eolo")`. Sin cambio Sprint 10.
- PortfolioSnapshot infra ready: `multi_agent/risk/portfolio_snapshot.py` 269 LOC. Classes PositionView + PortfolioSnapshot + SnapshotBuilder + CachedSnapshotBuilder.
- ATLAS engine usa PortfolioSnapshot extensively (validate_proposal + get_current_risk_mode + 3 helpers).
- Tests existentes: test_atlas_core.py (10,885 bytes) + test_portfolio_snapshot.py (5,221 bytes). Well-tested infra ready for live source wiring.
- Eolo precedent 3 sources: eolo-options/execution/options_trader.py + eolo-crop/execution/options_trader.py + eolo-crypto-dashboard/main.py.

### ADR-010 Schwab WebSocket part 1

- ADR-008 D6 verbatim: "ADR-010 (Schwab WebSocket port) scope informed by Frame 3 Tier D — multi-sprint pattern part 1 Sprint 11 + part 2 Sprint 12."
- OhlcvWorker foundation S.9.ohl-b ✓ ready (no DB blocker).
- No agent currently consumes Tier D real-time data. HERMES (Sprint 13+ ADR-012) primary downstream consumer.
- Eolo WebSocket precedent likely available (options bot real-time streaming).

### Emergent candidates check

- 0 emergent candidates from Sprint 10 review.
- Sprint 10 §9.3 tech debt items (Q1-Q5 + 2 emergent) all trigger-based deferred.
- F-r5/F-r6.5 lessons = workflow improvements, NO sprint scope.
- Phase 2 telemetry: 0 production runs Sprint 10, telemetry-driven decisions properly deferred.

---

## 4. Scoring matrix Sprint 11

| Candidate | Paper 25% | Agent 20% | Data 15% | Effort 15% | Risk 15% | ADR 10% | **Weighted** |
|-----------|-----------|-----------|----------|------------|----------|---------|--------------|
| **#7 ATLAS portfolio integration** | 5 | 4 | 3 | 3 | 3 | 2 | **3.60** ← Sprint 11 LOCKED |
| **ADR-010 Schwab WebSocket part 1** | 2 | 2 | 3 | 2 | 2 | 4 | **2.35** |

Computation #7: 5×0.25 + 4×0.20 + 3×0.15 + 3×0.15 + 3×0.15 + 2×0.10 = 1.25 + 0.80 + 0.45 + 0.45 + 0.45 + 0.20 = **3.60**.

Computation ADR-010 part 1: 2×0.25 + 2×0.20 + 3×0.15 + 2×0.15 + 2×0.15 + 4×0.10 = 0.50 + 0.40 + 0.45 + 0.30 + 0.30 + 0.40 = **2.35**.

Gap: **1.25** (decisive vs Sprint 10's 0.25 close gap).

ATLAS dominant dimensions: Paper trading 5/5 + Agent unlock 4/5 + Effort 3/5.
WebSocket dominant dimension: ADR prereq 4/10 only (design-heavy).

---

## 5. Recommendation Sprint 11 = #7 ATLAS portfolio integration

Razones:

1. **Decisive weighted score (3.60 vs 2.35, gap 1.25)** — dominant ATLAS por Paper Trading + Agent Unlock dimensions.
2. **Direct paper trading impact 5/5**: ATLAS reality-check gate transitions synthetic → real portfolio validation. Sin ATLAS, paper trading discipline illusory (proposals run sin meaningful risk gate).
3. **Foundation completion narrative**: Sprint 5/7/9 producer (Schwab data layer + iv_surface WRITE + ohlcv WRITE) + Sprint 10 consumer (Phase 2 reads) + Sprint 11 validator (ATLAS real portfolio) = trio operational foundation completed.
4. **Eolo precedent reusable** (3 source files locating get_positions/get_balances). Pattern proven 3x prior ports (S.5.6c price_history + S.5.6d options_chain + ADR-005 iv compute formula port).
5. **ATHENA Phase 2 quality unlock (Sprint 10 ADR-009 Aceptado) now meaningful** — proposals con term_structure + surface + ohlcv_intraday validated by ATLAS against real portfolio.
6. **WebSocket opportunity cost low** — Sprint 12+ re-score fresh per rule #15. ADR-010 Tier D primary consumer is HERMES (Sprint 13+ ADR-012), no rush.

ADR number: **ADR-013 NEW** (no renumber required — ATLAS portfolio integration NO en ADR-008 D6 sequencing). Clean number assignment vs Sprint 10 S.10.cons-a full renumber pattern.

Sub-blocks plan Sprint 11 (compact 6 sub-blocks mirror Sprint 10):

- S.11.atlas-a: ADR-013 plan firmado (~250 LOC doc).
- S.11.atlas-b: SchwabClient.get_positions port + tests (~200 LOC + ~10 tests).
- S.11.atlas-c: SchwabClient.get_balances port + tests (~150 LOC + ~10 tests).
- S.11.atlas-d: PortfolioSnapshot live source wiring + SnapshotBuilder ext (~250 LOC + ~15 tests).
- S.11.atlas-e: ATLAS engine integration con real PortfolioSnapshot + lifespan (~150 LOC + ~5 tests).
- S.11.atlas-f: Operator doc + ADR-013 close-out + daily log (~200 LOC doc).

**Total Sprint 11 estimate: ~1,000-1,200 LOC code + ~40-50 tests + ~450 LOC doc.**

---

## 6. Sequence proposal Sprint 12+ TENTATIVE

> **NOTA OPERACIONAL**: Esta secuencia es propuesta basada en state al cierre Sprint 10 + Sprint 11 lock. Sprint 12+ NO está locked — se debe re-scorear fresh cuando se cierre Sprint 11, dado que Sprint 11 implementation puede revelar dependencies o priorities que cambien el cálculo. Per rule #15: verify reality before spec, incluso para planning.

Tentative sequence (per ADR-008 §9.4 + Sprint 11 outputs):

- **Sprint 12**: ADR-010 Schwab WebSocket part 1 (Tier D infra). Multi-sprint pattern per ADR-008 D6 + D7.
- **Sprint 13**: ADR-010 Schwab WebSocket part 2 (completion) — could parallelize ADR-011 GEX compute start.
- **Sprint 12-13+**: ADR-011 GEX compute pipeline (Tier A). Depends on iv_surface Sprint 7 + OI ✓.
- **Sprint 13-16+**: ADR-012 HERMES implementation (per ADR-008 timeline).

### TENTATIVE caveat doctrine (4x proven Sprints 8/9/10/11)

- Sprint 12+ NOT locked Sprint 11.
- Re-score fresh per sprint close per rule #15 strict.
- ADR canonical re-read pre-Write discipline (F-r5 lesson Sprint 10).
- Budget management pre-Write + post-Write both required (F-r6/F-r6.5 lesson Sprint 10).
- Path verification pre-Write (F-r1 + F-r8 pattern Sprint 10).

Sprint 11 close-out doc (e.g., `S.11.atlas-f`) MUST re-validate Sprint 12+ priority via fresh rule #15 pre-recolección. Memo persistente serves como historical record, NOT as binding contract.

---

## 7. Out of scope (NOT Sprint 11)

- **Phase 2 telemetry observation** — waiting period, no actionable code Sprint 11. First paper trading data available post-ATLAS integration Sprint 11+.
- **Sprint 10 §9.3 tech debt items** (Q1-Q5 + 2 emergent) — all trigger-based deferred (surface full grid + ohlcv timeframe configurability + multi-snapshot aggregation + cache TTL + Schwab rate limit + ATM-exact resolution + prompt budget trajectory monitoring).
- **ATHENA prompt budget trajectory monitoring** — Sprint 11+ telemetry-driven.
- **ADR-010 Schwab WebSocket part 1** — Sprint 12 candidate.
- **ADR-011 GEX compute pipeline** — Sprint 12-13+ TENTATIVE.
- **ADR-012 HERMES implementation** — Sprint 13-16+ TENTATIVE.

---

## 8. References

- **ADR-007** (commit `8305ef3`): market.ohlcv producer/consumer Aceptado. Tier C foundation.
- **ADR-008** (commit `169cef2`): HERMES Tactical Scope Aceptado. D6 sequencing + §9.4 cross-ref.
- **ADR-009** (commit `dea7ee9`): Phase 2 consumer surface UNIFIED Aceptado. ATHENA quality unlock.
- **S.10.plan-a** (commit `40fadca`): Sprint 10 priority analysis precedent + scoring methodology framework.
- **S.10.cons-f** (commit `dea7ee9`): Sprint 10 close-out con §9.4 Sprint 11+ tentative + 7 findings catalog.
- **Sprint 10 lessons F-r1 a F-r6.5 + F-r8**: Camino 2 protocol catches, ADR canonical re-read discipline, budget management pre+post, path verification pre-Write.
- **Eolo precedent**: `~/PycharmProjects/eolo/eolo-options/execution/options_trader.py` + `eolo-crop/execution/options_trader.py` + `eolo-crypto-dashboard/main.py` (3 sources locating get_positions/get_balances).
- **PortfolioSnapshot infra**: `multi-agent-system/src/multi_agent/risk/portfolio_snapshot.py` (269 LOC, 4 classes) + tests.

---

> **Sprint 11 LOCKED = #7 ATLAS portfolio integration.** ADR-013 NEW (no renumber). Sprint 12+ TENTATIVE per S.10.plan-a/S.11.plan-a TENTATIVE caveat doctrine 4x proven. Foundation building era Sprints 9-13 continues. Trio ATHENA+APOLLO+ATLAS paper trading parallel during Sprint 11+ build-out.
