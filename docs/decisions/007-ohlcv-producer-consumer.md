# ADR-007: market.ohlcv Producer + Consumer Foundation

**Fecha:** 2026-05-19
**Estado:** Aceptado (2026-05-19)
**Contexto:** Sprint 9 LOCKED via Sprint 9+ priority analysis (commit `4b54203`, 2026-05-19).
ADR-008 Frame 3 Phase 1 (Schwab-native Tiers A+B+C+D) requires Tier C foundation = intraday
OHLCV persistence. F-r1 finding: SchwabClient.get_price_history ya soporta frequency_type="minute"
desde Sprint 5 S.5.6c — NO new port required, solo Repository + Worker + lifespan integration
mirror S.6.iv-b/c pattern proven 2x. Esta ADR define market.ohlcv populating Sprint 9, 4 timeframes
{5m, 15m, 30m, 1d}, 6 tickers TICKER_UNIVERSE, bootstrap 10 días + forward daily 21:30 UTC.

---

## 1. Context

### 1.1 Sprint 9 lock per priority analysis
- ADR-008 Aceptado 2026-05-19 (commit 169cef2). Frame 3 locked.
- S.9.plan-a (commit 4b54203): Sprint 9 = ADR-007 ohlcv, 4.40 weighted highest.
- F-r1 finding: SchwabClient ya intraday ready, effort revised 2-3 días.

### 1.2 ADR-008 D5 Tier C requirements
- Intraday OHLCV via Schwab REST.
- Storage: market.ohlcv hypertable V007.
- Worker pattern mirror IvHistoryWorker.
- Tier A volume profile aggregation foundation downstream (Sprint 12+).

### 1.3 Pre-recolección findings rule #15 (7 NEW)
- **F-r1**: SchwabClient.get_price_history ya intraday-ready S.5.6c.
- **F-r2 CRITICAL**: V007 schema comment "1m | 5m | 1h | 1d" outdated vs Schwab native
  {1, 5, 10, 15, 30}. 1h NO native Schwab.
- **F-r3 CRITICAL**: Schwab period_type="day" cap 1-10 días → bootstrap paginated.
- **F-r4**: V007 volume BIGINT correct (full market volume scale).
- **F-r5**: SchwabDataLayer.snapshot() ya fetches daily OHLCV ephemeral; persistence layer separate.
- **F-r6**: Timezone epoch_ms → TIMESTAMPTZ UTC pattern Sprint 5 reusable.
- **F-r7**: Worker time overlap IvHistoryWorker 21:15 UTC + OhlcvWorker → stagger required.
- **F-r8**: VIX/VVIX intraday architectural diff (indices, no TICKER_UNIVERSE) → split ADR-007.5.

### 1.4 Scope boundary Sprint 9
- INCLUDED: 6 tickers TICKER_UNIVERSE × 4 timeframes × bootstrap 10 días + forward daily.
- EXCLUDED: 1m timeframe (defer Q1), 1h compute (defer Q2), VIX/VVIX (defer ADR-007.5).

---

## 2. Decisions

### D1. Scope: market.ohlcv ONLY (NO VIX/VVIX bundle)

**Decisión:** ADR-007 = market.ohlcv populating para TICKER_UNIVERSE actual (6 tickers).
VIX/VVIX intraday path separate (ADR-007.5 follow-up future Sprint).

**Razón:** Scope boundary clean. F-r8 arquitectural diff — VIX/VVIX indices NOT optionable,
NOT en TICKER_UNIVERSE. Bundle Sprint 9 = scope creep risk.

### D2. Phase 1 timeframes = {5m, 15m, 30m, 1d}

**Decisión:** 4 timeframes Sprint 9 populated:
- 5m, 15m, 30m: HERMES-relevant intraday momentum (ADR-008 D3 horizon 5m-60m).
- 1d: persistent canonical daily source (overlap SchwabDataLayer ephemeral OK — diff use cases:
  ATHENA reads MarketState daily live; ADR-007 persists for backtest/historical).

**Razón:** Schwab native frequency_type="minute" + frequency ∈ {1, 5, 10, 15, 30}; 1d = daily
mode. Excludes 1m + 1h.

#### D2-1. Sub-decision: 1m timeframe defer (Q1)

1m timeframe excluded Phase 1. Razón: high volume (~390 bars/day per ticker × 6 = 2,340/day),
Schwab API cap pain bootstrap, low marginal value HERMES (5m sufficient para tactical momentum
4-hour windows). Defer trigger ADR-007.5 si HERMES 0DTE SPX paper trading requires.

#### D2-2. Sub-decision: 1h timeframe defer (Q2)

1h NOT native Schwab REST. Compute from 30m bars en consumer-side aggregation (deferred). Razón:
F-r2 — schema VARCHAR(5) acepta "1h" string, pero populating requires aggregation logic NOT
in Sprint 9 scope. Defer trigger ADR-007.5 o ADR-010 (GEX compute pipeline same Sprint 12+).

### D3. Worker cadence: end-of-day batch 21:30 UTC (stagger from IvHistoryWorker 21:15 UTC)

**Decisión:** OhlcvWorker scheduled 21:30 UTC daily (post-IvHistoryWorker). Sprint 9 = batch
persistence post-close. Real-time intraday → Sprint 11-12 ADR-009 WebSocket.

**Razón:** F-r7 catch — concurrent 21:15 UTC two workers risk Schwab API rate limit hit bootstrap
phase (24-100+ calls primera run). 15-min stagger trivial deviation, debugging-friendly, conservative.

### D4. Repository methods

**OhlcvRepository:**
- `write_bars(ticker: str, timeframe: str, bars: list[dict])` — batch INSERT idempotent.
- `get_bars(ticker: str, timeframe: str, since: datetime, limit: int = 1000)` — historical query.
- `count_for_ticker(ticker: str, timeframe: str) -> int` — validation/threshold checks.

Mirror IvHistoryRepository pattern Sprint 6.

### D5. Idempotency: ON CONFLICT (ts, ticker, timeframe) DO NOTHING

**Decisión:** Standard pattern S.6.iv-b/S.7.surf-b. Idempotent re-runs safe.

**Razón:** Worker re-fire on failure (retry queue), bootstrap re-execute on schema change.
PK (ts, ticker, timeframe) ensures dedup.

### D6. Bootstrap: 10 días paginated, one-time at deployment

**Decisión:** Bootstrap fetch 10 días history per ticker × timeframe at Worker first run.
Subsequent runs forward-only daily increment.

**Razón:** F-r3 Schwab cap period_type="day" ∈ 1-10 días → 10 días = single API call per ticker ×
timeframe = **24 API calls one-time** (6 tickers × 4 timeframes). Safe under rate limit.

**Defer:** Backtest-ready depth (30+/90+ días) future ADR-007.5 si ATHENA backtests require.

### D7. Universe: current TICKER_UNIVERSE (6 tickers)

**Decisión:** No expansion Sprint 9. Tickers: per `multi_agent.config.universe.TICKER_UNIVERSE`.

**Razón:** Consistency S.6.iv-c + S.7.surf-c precedent. Expansion = separate sub-decision future ADR.

### D8. SchwabDataLayer.snapshot() NO side-effect write

**Decisión:** snapshot() remains ephemeral (current Sprint 5 behavior preserved). OhlcvWorker
= single source of persistence truth.

**Razón:** F-r5 catch — separation of concerns. snapshot() reads for live agent decisions (ATHENA),
Worker writes for backtest/historical/aggregation consumers. NO dual-write race conditions.

---

## 3. Sub-blocks (S.9.ohl-X)

| Sub-block | Date | Description | LOC est |
|-----------|------|-------------|---------|
| **S.9.ohl-a** | 2026-05-19 | ADR-007 plan firmado (this commit) | ~280 LOC doc |
| **S.9.ohl-b** | TBD | Implementation: Repository + Worker + lifespan + tests + close-out + Status Aceptado | ~600-1,000 LOC code + ~30 tests + ~80 LOC doc close-out |

**Total Sprint 9 estimate:** ~3-4 horas combined.

---

## 4. Open questions

- **Q1**: 1m timeframe Phase 1.5 trigger? HERMES 0DTE SPX requires 1m bars? Deferred ADR-007.5.
- **Q2**: 1h compute pipeline location? Consumer-side aggregation (5m × 12 → 1h) o ADR-010 Tier A
  compute? Deferred ADR-010 scope discussion.
- **Q3**: VIX/VVIX intraday integration path? Same OHLCV pipeline (ADR-007.5) o separate volatility
  table? Deferred Sprint 10+ planning.
- **Q4**: Backtest depth requirements? 30/90/360 días historial sufficient? Trigger ATHENA Phase 2
  consumer surface (Sprint 10 candidate).
- **Q5**: Worker monitoring + alerting reuse Telegram bot? Eolo precedent existing.

---

## 5. Out of scope

- 1m timeframe (defer Q1, future ADR-007.5 trigger).
- 1h timeframe compute (defer Q2, ADR-010 Tier A scope).
- VIX/VVIX intraday (defer Q3, ADR-007.5).
- Real-time intraday streaming (Sprint 11-12 ADR-009 WebSocket scope).
- Backtest depth >10 días bootstrap (defer Q4 trigger).
- Consumer-side reading patterns (Sprint 10 candidate Phase 2 consumer surface).
- Volume profile aggregation (Sprint 12+ ADR-010 Tier A scope).

---

## 6. Success criteria

1. V007 `market.ohlcv` hypertable populated 6 tickers × 4 timeframes × 10 días bootstrap.
2. OhlcvWorker scheduled 21:30 UTC daily forward-only.
3. Repository methods (write_bars + get_bars + count_for_ticker) tested.
4. Idempotency ON CONFLICT verified test.
5. Lifespan integration (FastAPI startup register Worker).
6. ~30 new tests passing (mirror S.6.iv-b/c pattern: ~15 Repository + ~15 Worker).
7. Tests baseline preserved: 918 + ~30 = 948 + 1 skipped post-Sprint 9.
8. ADR-007 Status: Propuesto → Aceptado en S.9.ohl-b close-out.

---

## 7. Risks

| ID | Risk | Likelihood | Mitigation |
|----|------|-----------|------------|
| R1 | Schwab rate limit hit bootstrap (24 calls concentrated) | Low | Sequential calls + retry logic existing |
| R2 | F-r2 schema comment confusion (1h not native) | Low | D2-2 explicit defer + comment update Worker init |
| R3 | F-r3 paginated bootstrap edge case (history > 10 días) | Low | D6 caps 10 días simple, no pagination needed |
| R4 | F-r5 snapshot() dual-write race condition | Low | D8 explicit NO side-effect, Worker dedicated |
| R5 | F-r7 worker stagger insufficient (15 min gap small) | Low | Monitor Sprint 9 first runs; expand stagger if needed |
| R6 | Bootstrap timezone offset bug (epoch_ms misalignment) | Low | F-r6 pattern Sprint 5 reusable |
| R7 | Test regression from Worker scheduling overlap | Low | Independent test classes, mock scheduler |

---

## 8. References

- **ADR-008** (commit 169cef2): Frame 3 Tier C requirements + D5 + D7 sequencing.
- **ADR-006** (commit bdb0106): iv_surface populating pattern S.7.surf-b/c precedent.
- **ADR-005**: iv_history pattern S.6.iv-b/c reusable Repository + Worker template.
- **S.9.plan-a** (commit 4b54203): Sprint 9 lock + F-r1 finding.
- **V007 schema** (Apr 28): `db/migrations/V007__market_tables.sql` market.ohlcv hypertable.
- **SchwabClient.get_price_history** (S.5.6c): intraday signature ready, frequency_type ∈ {minute,
  daily, weekly, monthly}.
- **TICKER_UNIVERSE**: 6 tickers per `multi_agent.config.universe`.
- **IvHistoryWorker** (S.6.iv-c): 21:15 UTC pattern.
- **IvHistoryRepository** (S.6.iv-b): batch INSERT idempotent pattern.

---

## 9. Close-out (S.9.ohl-b, 2026-05-19)

Sprint 9 ADR-007 ohlcv cerrado al 100% (2/2 sub-bloques compact pattern).
ADR-007 status: Propuesto → Aceptado. market.ohlcv hypertable populated infra
ready, OhlcvWorker schedule 21:30 UTC daily, 4 timeframes × 6 tickers = 24
cells per run. Tier C foundation Frame 3 delivered.

### 9.1 Sub-blocks delivered

| Sub-block | Date | Commit | LOC delta | Tests delta | Description |
|-----------|------|--------|-----------|-------------|-------------|
| S.9.plan-a | 2026-05-19 | `4b54203` | +145 (doc) | 0 | Sprint 9+ priority analysis, ADR-007 locked |
| S.9.ohl-a | 2026-05-19 | `b4bae64` | +215 (doc) | 0 | ADR-007 plan firmado, Status Propuesto |
| S.9.ohl-b | 2026-05-19 | (this) | +~1,043 (code+tests+doc) | +33 | OhlcvRepository + OhlcvWorker + lifespan + tests + close-out Aceptado |
| **Total** | — | — | **~1,403 LOC** | **+33** | — |

Tests baseline: 918 → 951 + 1 skipped post-Sprint 9 (multi-agent 856 + shared_core 95).

### 9.2 Rule #15 findings summary

Pre-recolección + implementation disparó 9 findings críticos NUEVOS:

- **F-r1** (S.9.plan-a): SchwabClient.get_price_history ya intraday-ready Sprint 5 S.5.6c.
  NO new port required → effort 3-5 días → 2-3 días.
- **F-r2 CRITICAL** (S.9.ohl-a): V007 schema comment "1m | 5m | 1h | 1d" outdated vs
  Schwab native {1, 5, 10, 15, 30} + daily. 1h NOT native, defer Q2.
- **F-r3 CRITICAL** (S.9.ohl-a): Schwab period_type="day" cap 1-10 días → D6 simplification.
- **F-r4** (S.9.ohl-a): V007 volume BIGINT correct (full market scale).
- **F-r5** (S.9.ohl-a): SchwabDataLayer.snapshot() ephemeral; Worker dedicated persistence
  truth (D8).
- **F-r6** (S.9.ohl-a): Timezone epoch_ms → TIMESTAMPTZ UTC pattern Sprint 5 reusable.
- **F-r7** (S.9.ohl-a): Two workers 21:15 UTC concurrent → D3 stagger 21:30 UTC.
- **F-r8** (S.9.ohl-a): VIX/VVIX intraday architectural diff → split ADR-007.5 future.
- **F-r9 CRITICAL** (S.9.ohl-b PARTE 2 pre-Write): Pool API divergence — spec asumió
  psycopg_pool.ConnectionPool, reality es PostgresPool wrapper con auto-commit.
  Sin fix, INSERTs silently no persisten (silent failure mode). Catch ANTES de Write
  via verify reality. Pattern mirror IvHistoryRepository/IvSurfaceRepository proven.

Most impactful catches:

- **F-r9 CRITICAL** prevented silent failure mode (peor que crash visible). Catch ANTES
  de Write demuestra rule #15 strict + Camino 3 protocol working at peak quality.
- **F-r3 CRITICAL** drove D6 KISS simplification (10-day window uniform vs
  bootstrap-vs-incremental branching).
- **F-r7** drove D3 stagger mitigation (21:30 vs concurrent 21:15).

**Pattern observed**: 2 catches críticos pre-Write hoy martes (c0cf3d6 filename + F-r9
pool API). Sin auto-mode interpretación aggressive O rule #15 pause + verify, ambos
shipped broken. Quality discipline pays substantial dividends.

### 9.3 Tech debt registered for Sprint 10+

NEW Sprint 9 items (5 new):

1. **1m timeframe deferred** (D2-1) → ADR-007.5 trigger si HERMES 0DTE SPX requires.
2. **1h compute pipeline deferred** (D2-2) → ADR-010 Tier A scope o ADR-007.5.
3. **VIX/VVIX intraday path deferred** (D1) → ADR-007.5 (separate from market.ohlcv).
4. **Backtest depth >10 días** (D6) → ADR-007.5 trigger si ATHENA Phase 2 surface needs.
5. **Schwab rate limit observability** → monitor first OhlcvWorker runs, validate D3
   stagger 15-min sufficient (R5 mitigation).

Inherited cross-ref:

- **ADR-005 §9.3**: 11 items (#2 + #7 RESOLVED Sprint 7/6, 9 pending).
- **ADR-006 §9.3**: 5 NEW items pending (F7 disambig, etc.).
- **ADR-008 §9.3**: 5 NEW items pending (V0XX migration, ADR-009/010/011 scope informed).

### 9.4 Next steps Sprint 10+

ADR-007 Aceptado triggers Sprint 10 priority re-score per S.9.plan-a TENTATIVE caveat.

Sprint 10 candidates (per ADR-008 §9.4 + Sprint 9 lessons):

- Phase 2 consumer surface (ATHENA quality unlock, independent path).
- ATLAS portfolio integration (paper trading discipline unblocker, adjacent).

Re-score fresh post-Sprint 9 reflect lessons:

- F-r9 pattern catch demuestra valor de pre-recolección strict.
- D6 KISS simplification pattern reusable downstream ADRs.
- Worker stagger pattern (D3) reusable Sprint 11+ ADR-009.

Sprint 11+ adjacent: ATLAS portfolio integration probable Sprint 10/11.
Sprint 11-12: ADR-009 Schwab WebSocket multi-sprint.
Sprint 12+: ADR-010 GEX compute.
Sprint 13-16+: ADR-011 HERMES real implementation.

Foundation building era continues. Trio ATHENA+APOLLO+ATLAS paper trading parallel
durante Sprint 10-13 build-out.

---

> **Sprint 9 ADR-007 ohlcv cerrado al 100%** (2/2 sub-blocks compact pattern:
> S.9.ohl-a + S.9.ohl-b). Próximo: Sprint 10 priority analysis re-score con
> ADR-007 context. Foundation building Sprint 10-13 continues.
