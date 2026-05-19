# Sprint 10+ Priority Analysis — Phase 2 consumer surface UNIFIED locked

**Fecha:** 2026-05-19
**Estado:** Decidido (Sprint 10 = Phase 2 consumer surface UNIFIED, S.10.cons-X sub-blocks pending)
**Contexto:** Sprint 9 ADR-007 ohlcv cerrado al 100% (commit `8305ef3`, ADR-007 Aceptado 2026-05-19). Sprint 10+ priority decision pending across 2 viable candidates per ADR-008 §9.4 + Sprint 9 §9.3 cross-ref. Esta memo persiste el strategic scoring + recommendation fresh con Frame 3 Tier B+C complete + Sprint 9 lessons F-r1 a F-r9.

---

## 1. Context

### 1.1 Sprint 9 close-out state

- ADR-007 Aceptado 2026-05-19 (commit `8305ef3`). Tier C foundation delivered.
- OhlcvWorker production-ready 21:30 UTC daily, 24 cells per run (6 tickers × 4 timeframes).
- Tests baseline: 856 multi-agent + 95 shared_core = 951 + 1 skipped.
- 9 findings rule #15 F-r1 a F-r9 (F-r9 CRITICAL pool API divergence catch ANTES de Write).
- 5 NEW tech debt items §9.3 (1m/1h/VIX-VVIX/backtest-depth/rate-limit-observability deferred).

### 1.2 Re-score trigger per S.9.plan-a + ADR-008 §9.4

- Rule #15 strict: verify reality before spec.
- TENTATIVE sequence Sprint 10+ NO locked Sprint 9.
- Sprint 10 priority must re-score con Frame 3 Tier B+C complete context.

### 1.3 Sprint 9 §9.3 cross-ref insight CRITICAL

Pre-recolección Sprint 10 reveló unification:

- ADR-007 §9.3 #4 (Backtest depth) explicit trigger: "ATHENA Phase 2 consumer surface".
- ADR-007 §5 Out of scope explicit: "Consumer-side reading patterns (Sprint 10 candidate Phase 2 consumer surface)".
- ADR-006 D6 (WRITE-only Sprint 7): "TickerSnapshot extension Phase 2".

Phase 2 consumer surface scope UNIFIED ahora incluye:

1. IvSurfaceRepository READ methods (NEW — currently 0 read methods, solo `__init__` + `write_chain_snapshot`).
2. OhlcvRepository.get_bars consumer-side wiring (delivered S.9.ohl-b, NO consumed yet).
3. TickerSnapshot extension fields (term_structure, surface, ohlcv_intraday).
4. SchwabDataLayer.snapshot() wires reads (NEW path).
5. ATHENA prompt update reflecting new data semantics.

Estimate revised ~800-1,200 LOC vs original ~700-1,200 LOC pre-Sprint 9.

### 1.4 Candidates inventory (2 viable Sprint 10)

Viable Sprint 10:

- **#2 Phase 2 consumer surface UNIFIED** (ATHENA quality unlock, independent path).
- **#7 ATLAS portfolio integration** (paper trading discipline unblocker, adjacent ADR-008).

Defer Sprint 11+ (per ADR-008 §9.4 + S.9.plan-a §6):

- ADR-009 Schwab WebSocket (Sprint 11-12 multi-sprint).
- ADR-010 GEX compute (Sprint 12+).
- ADR-011 HERMES implementation (Sprint 13-16+).

---

## 2. Scoring methodology

6 dimensions weighted (mirror S.8.plan-a + S.9.plan-a proven 2x):

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

## 3. State per candidate (rule #15 pre-recolección Sprint 10)

### #2 Phase 2 consumer surface UNIFIED

- TickerSnapshot 8 fields actuales (interfaces.py:59-83) — NO term_structure NI surface. ohlcv_hourly 24 bars placeholder, NO populated (S.5.6e deferred).
- SchwabDataLayer NO consume iv_surface (0 grep matches Sprint 7 D6 strict).
- IvSurfaceRepository: 2 methods existentes (`__init__` + `write_chain_snapshot`). NO READ.
- OhlcvRepository.get_bars (S.9.ohl-b) implemented + tested + zero consumer-side calls.
- ATHENA prompt: data caveat S.5.6f outdated post-Phase 2.

### #7 ATLAS portfolio integration

- SchwabClient.get_positions (line 682) + get_balances (line 690) = `NotImplementedError("Port from Eolo")`.
- PortfolioSnapshot infra: `multi_agent/risk/portfolio_snapshot.py` exists. Tests: test_portfolio_snapshot.py + test_atlas_consumer.py + test_atlas_core.py + test_atlas_routes.py + test_portfolio_routes.py all present.
- Eolo precedent: 3 sources (options + crop + crypto-dashboard).
- ATLAS engine: rule-based real, currently validates against synthetic PortfolioSnapshot.

---

## 4. Scoring matrix Sprint 10

| Candidate | Paper (25%) | Agent (20%) | Data (15%) | Effort (15%) | Risk (15%) | ADR (10%) | Weighted |
|-----------|--------------|--------------|--------------|---------------|-------------|------------|------------|
| **#2 Phase 2 consumer surface UNIFIED** | 4 | 3 | 5 | 3 | 5 | 3 | **3.85** ← Sprint 10 LOCKED |
| **#7 ATLAS portfolio integration** | 5 | 4 | 3 | 3 | 3 | 2 | **3.60** |

Computation #2: 4×0.25 + 3×0.20 + 5×0.15 + 3×0.15 + 5×0.15 + 3×0.10 = 1.00 + 0.60 + 0.75 + 0.45 + 0.75 + 0.30 = **3.85**.

Computation #7: 5×0.25 + 4×0.20 + 3×0.15 + 3×0.15 + 3×0.15 + 2×0.10 = 1.25 + 0.80 + 0.45 + 0.45 + 0.45 + 0.20 = **3.60**.

Gap 0.25 — close call, decisive on Data deps + Risk dimensions.

---

## 5. Recommendation Sprint 10 = Phase 2 consumer surface UNIFIED

Razones:

1. **Highest weighted score (3.85 vs 3.60)** — winning Data deps 5/5 + Risk 5/5 vs ATLAS 3/3.
2. **Natural sequencing completion**: ADR-006 + ADR-007 created WRITE-only foundations Sprint 7+9, Sprint 10 completes producer/consumer pair (canonical Foundation-First pattern).
3. **Lower risk path**: Repository read pattern proven 2x (IvHistoryRepository.get_history S.6.iv-d + OhlcvRepository.get_bars S.9.ohl-b). No new Schwab ports.
4. **No external dependencies**: All internal. Skips Schwab credential rotation + Eolo precedent comparison work.
5. **Tech debt convergence point**: ADR-005 §9.3 #2 + ADR-006 D6-1 + ADR-007 §9.3 #4 + S.9 §5 Out of scope all triggered ONLY by Sprint 10 Phase 2 consumer surface (4 inherited tech debt items resolve atomically).
6. **ATHENA quality direct enhancement** — paper trading data quality improvement, even si indirect vs ATLAS direct unblock.

ATLAS Sprint 11 adjacent — Paper 5/5 + Agent 4/5 keep it #1 Sprint 11 candidate (re-score fresh post-Sprint 10).

Sprint 10 sub-blocks naming: S.10.cons-a (ADR-009 plan firmado o priority-analysis sub-block) → S.10.cons-b/c/... per ADR-009 §3 sub-block breakdown (TBD).

---

## 6. Sequence proposal Sprint 11+ (TENTATIVE)

> **NOTA OPERACIONAL**: Esta secuencia es propuesta basada en state al cierre Sprint 9 + Sprint 10 lock. Sprint 11+ NO está locked — se debe re-scorear fresh cuando se cierre Sprint 10, dado que Sprint 10 implementation puede revelar dependencies o priorities que cambien el cálculo. Per rule #15: verify reality before spec, incluso para planning.

Tentative sequence (per ADR-008 §9.4 + Sprint 10 outputs):

- **Sprint 11**: #7 ATLAS portfolio integration (paper trading discipline unblocker, high Paper Trading 5/5 + Agent 4/5).
- **Sprint 11-12**: ADR-009 Schwab WebSocket (multi-sprint pattern per ADR-008 D6, depends on OhlcvWorker foundation S.9.ohl-b).
- **Sprint 12+**: ADR-010 GEX compute pipeline (Tier A foundation).
- **Sprint 13-16+**: ADR-011 HERMES real implementation (post-data layer build-out).

### Re-score pattern

Sprint 11 close-out doc (e.g., `S.11.[winner-prefix]-d`) MUST re-validate Sprint 12+ priority via fresh rule #15 pre-recolección. Memo persistente serves como historical record, NOT as binding contract. Pattern proven 2x Sprint 8 + 9 + ahora Sprint 10 = 3x.

---

## 7. Out of scope

- **Sprint 10 implementation details** — deferred ADR-009 (Phase 2 consumer surface) o sub-block breakdown S.10.cons-X.
- **ADR-009 number assignment** — Sprint 10 may use ADR-009 number (next sequential) OR separate scope ADR. Decision deferred Sprint 10 sub-block S.10.cons-a.
- **Sprint 11+ commit** — tentative per §6 caveat.
- **VIX/VVIX integration** — ADR-007.5 future trigger.
- **1m timeframe expansion** — ADR-007.5 trigger HERMES 0DTE SPX requires.

---

## 8. References

- **ADR-007** (commit `8305ef3`): Tier C foundation delivered, §9.3 #4 + §5 cross-ref Phase 2 consumer surface trigger.
- **ADR-008** (commit `169cef2`): Frame 3 + 4 ADRs downstream sequence + §9.4 canonical.
- **ADR-006** (commit `bdb0106`): D6 Phase 2 trigger inherited.
- **ADR-005** (commit `2ab5832` close-out S.6.iv-f): §9.3 #2 RESOLVED Sprint 7; pattern reference reader S.6.iv-d.
- **S.9.plan-a** (commit `4b54203`): Sprint 9 lock + F-r1 finding + TENTATIVE caveat doctrine.
- **S.9.ohl-a** (commit `b4bae64`): ADR-007 plan firmado.
- **S.9.ohl-b** (commit `8305ef3`): ADR-007 Aceptado + close-out + F-r9 CRITICAL pool API catch.
- **S.8.plan-a** (commit `4bd0819`): TENTATIVE caveat doctrine baseline + scoring methodology framework.
- **Sprint 9 lessons F-r1 a F-r9**: pre-recolección rigor pays substantial dividends, F-r9 prevented silent failure mode.

---

> **Sprint 10 LOCKED = Phase 2 consumer surface UNIFIED.** Sprint 11+ TENTATIVE, re-score per sprint close. Foundation building era continues — Trio ATHENA+APOLLO+ATLAS paper trading parallel durante Sprint 10-13.
