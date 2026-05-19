# ADR-009: Phase 2 Consumer Surface UNIFIED — TickerSnapshot Extension + Repository READ Path

**Fecha:** 2026-05-19
**Estado:** Propuesto
**Contexto:** Sprint 10 LOCKED via S.10.plan-a (commit `40fadca`, 2026-05-19, scoring 3.85/5
highest). ADR-008 D6 sequencing previously reserved ADR-009 for Schwab WebSocket port —
**renumber applied atomic en este commit (S.10.cons-a)**: ADR-009 supersedes prior reservation
(Phase 2 consumer surface UNIFIED takes ADR-009 slot), downstream ADR-010 = Schwab WebSocket,
ADR-011 = GEX compute, ADR-012 = HERMES implementation. Esta ADR define READ-side completion
del producer/consumer pair Sprint 7 (iv_surface WRITE) + Sprint 9 (ohlcv WRITE).

---

## 1. Context

### 1.1 Sprint 10 lock per S.10.plan-a

- S.10.plan-a (commit `40fadca`): Sprint 10 = Phase 2 consumer surface UNIFIED, 3.85/5 weighted highest vs ATLAS 3.60/5.
- Foundation completion narrative: Sprint 7 + Sprint 9 created WRITE-only foundations; Sprint 10 completes producer/consumer pair.
- 4 inherited tech debt items resolve atomically (ADR-005 §9.3 #2 + ADR-006 D6-1 + ADR-007 §9.3 #4 + S.9 §5 Out of scope).

### 1.2 ADR number decision — renumber supersedes ADR-008 D6 sequencing

ADR-009 supersedes prior ADR-008 D6 sequencing (ADR-009 was reserved for Schwab WebSocket).
Renumber applied atomic en este commit (S.10.cons-a):

- **ADR-009** (NEW Sprint 10): Phase 2 consumer surface UNIFIED.
- **ADR-010** (was ADR-009): Schwab WebSocket port (Sprint 11-12).
- **ADR-011** (was ADR-010): GEX compute pipeline (Sprint 12+).
- **ADR-012** (was ADR-011): HERMES implementation (Sprint 13-16+).

Rationale: chronological numbering = standard pattern + cleaner audit trail long-term. Renumber NOW < renumber LATER cuando more downstream ADRs reference.

### 1.3 Sprint 7/9 WRITE-only state inherited

Pre-recolección S.10.cons-a confirmed rule #15 strict:

- IvSurfaceRepository: 2 methods only (`__init__` + `write_chain_snapshot`). NO read methods.
- OhlcvRepository: 5 methods incluyendo `get_bars` (S.9.ohl-b), pero 0 consumer callers fuera de tests.
- TickerSnapshot: 8 fields actuales (ticker, last_price, ohlcv_daily, ohlcv_hourly, iv_rank, iv_percentile, skew, realized_vol_30d). NO term_structure NI surface field. `ohlcv_hourly: []` placeholder S.5.6e deferred.
- SchwabDataLayer.snapshot(): 12 API calls/snapshot (6 tickers × 2 endpoints). NO iv_surface read, NO market.ohlcv read.
- ATHENA prompt: line 50 "Data priorities" ALREADY menciona "term structure" + "vol surface" (forward-looking copy, sin data backing).

### 1.4 ADR-008 D5 Sprint 10 boundary explicit

ADR-008 D5 explicit: "Sprint 10: Phase 2 consumer surface (ATHENA quality unlock + Tier A consumer pattern foundation, NOT HERMES Tier A compute which is Sprint 12+ per D5)".

Scope strict: establish read pattern, NOT compute pipeline. Tier A compute (GEX/vanna/charm) = Sprint 12+ ADR-011. Volume profile aggregation = Sprint 12+ Tier A (downstream Sprint 10 foundation).

---

## 2. Decisions

### D1. Scope UNIFIED Sprint 10

**Decisión:** Phase 2 consumer surface UNIFIED scope incluye:

1. IvSurfaceRepository READ methods (NEW).
2. TickerSnapshot extension (3 NEW fields: term_structure + surface + ohlcv_intraday).
3. SchwabDataLayer.snapshot() reads iv_surface + market.ohlcv post-fetch.
4. ATHENA prompt update mandatory (term_structure + surface semantics sections).

NOT in scope:
- Compute pipeline (Tier A GEX/vanna/charm → Sprint 12+ ADR-011).
- Aggregation logic (volume profile → Sprint 12+ Tier A).
- New Schwab API ports (read-only, internal reads).

**Razón:** UNIFIED scope unlocks ATHENA quality + Tier A consumer pattern foundation atomic. Partial scope = incomplete deliverable.

### D2. TickerSnapshot extension shape

**Decisión:** 3 NEW fields added to `TickerSnapshot` dataclass (frozen=True), backward-compatible con defaults.

#### D2-1. term_structure: list of tuples ordered

`term_structure: list[tuple[int, float]] = field(default_factory=list)` — ordered front-to-back (dte, atm_iv).

**Razón:** Prompt-friendly serialization, shape semantics (contango/backwardation) immediately visible to ATHENA. List preserves ordering (key for contango detection). Tuple is JSON-serializable as 2-element arrays.

Example: `[(7, 0.18), (35, 0.22), (90, 0.25)]` → front-to-back contango.

#### D2-2. surface: dict delta-sampled

`surface: dict[int, list[float]] = field(default_factory=dict)` — keyed by dte, values = list of (atm_iv, put_25d_iv, call_25d_iv) sampled at delta strikes.

**Razón:** Balance detail vs token budget. Full surface grid = thousands of strike×expiration points (token bloat). Delta-sampled (25/50/75) = ATHENA actionable skew info en ~30 values per ticker.

Example: `{7: [0.20, 0.18, 0.22], 35: [0.22, 0.20, 0.24]}` → near-term + medium-term delta surface.

#### D2-3. ohlcv_intraday: dict 4 timeframes

`ohlcv_intraday: dict[str, list[OHLCV]] = field(default_factory=dict)` — keyed by timeframe string ("5m", "15m", "30m", "1d").

**Razón:** ATHENA decides timeframe contextually. Multi-timeframe access Phase 2 unlock requirement. Existing `ohlcv_daily` + `ohlcv_hourly` (deferred placeholder) coexist for backward compat.

Note: `ohlcv_hourly` field NO populated Sprint 10 (D-η deferred), `ohlcv_intraday["1d"]` is the canonical persistent daily. Sprint 11+ deprecation candidate ohlcv_hourly.

### D3. NEW IvSurfaceRepository READ methods scope

**Decisión:** 3 new read methods:

- `get_surface_for_ticker(ticker: str, ts: datetime) → list[dict]` — returns full surface rows for (ticker, ts) snapshot.
- `get_term_structure(ticker: str, ts: datetime) → list[tuple[int, float]]` — returns ordered (dte, atm_iv) tuples for (ticker, ts).
- `get_latest_surface(ticker: str) → datetime | None` — returns latest ts persistent for ticker.

**Razón:** Match SchwabDataLayer.snapshot() consumption shape. Repository owns SQL + serialization; DataLayer wires + assembles TickerSnapshot fields.

### D4. SchwabDataLayer.snapshot() extension pattern

**Decisión:** Extension reads iv_surface + ohlcv post-fetch (per-ticker):

```
for ticker in TICKER_UNIVERSE:
    daily = fetch_daily_ohlcv(ticker)
    chain = client.get_options_chain(ticker)
    # NEW per Sprint 10:
    latest_surface_ts = iv_surface_repo.get_latest_surface(ticker)
    if latest_surface_ts:
        term_structure = iv_surface_repo.get_term_structure(ticker, latest_surface_ts)
        surface = build_delta_sampled_surface(iv_surface_repo.get_surface_for_ticker(ticker, latest_surface_ts))
    ohlcv_intraday = {tf: ohlcv_repo.get_bars(ticker, tf, since=...) for tf in ["5m", "15m", "30m", "1d"]}
    ticker_snapshot = TickerSnapshot(..., term_structure=..., surface=..., ohlcv_intraday=...)
```

~30 reads/snapshot (6 tickers × (1 surface + 4 timeframes) + 12 existing API calls = 18 DB + 12 API).

**Razón:** Atomic per-ticker extension. Single snapshot() call. Repository instances injected via __init__.

### D5. ATHENA prompt update MANDATORY

**Decisión:** ATHENA prompt extension required Sprint 10:

- ADD "term_structure semantics" section (mirror iv_rank D5 progressive disclosure pattern S.6.iv-d).
- ADD "surface semantics" section (delta-sampling explanation, skew interpretation guidance).
- UPDATE existing "Data priorities" line 50 — make explicit field-backed vs forward-looking.

**Razón:** Without prompt update, ATHENA cannot interpret new fields. Data without semantics = data unused.

### D6. Caching read-side Phase 1 = none

**Decisión:** No caching read-side Phase 1. Reads stateless, deterministic given (ticker, ts).

**Razón:** Mirror snapshot pattern (no cache existing fetches). Cache TTL deferred Q4 trigger empirical performance measurement.

### D7. Backward compatibility — optional fields con defaults

**Decisión:** 3 NEW TickerSnapshot fields have `field(default_factory=...)` defaults. Existing 8 fields unchanged. Existing tests preserve (823 → 823 baseline mantenido pre-Sprint 10).

**Razón:** Forward-compat: legacy callers/tests pass `TickerSnapshot(ticker=..., last_price=..., ohlcv_daily=...)` continue to work. New fields = empty defaults.

### D8. Sub-block breakdown 6 sub-blocks (compact pattern)

**Decisión:** Sprint 10 sub-blocks S.10.cons-a/b/c/d/e/f mirror ADR-005/006/007 9-section ADR + multi-block delivery patterns.

Total estimate: ~800 LOC code + ~40 tests + ~400 LOC doc.

---

## 3. Sub-blocks (S.10.cons-X)

| Sub-block | Date | Description | LOC est |
|-----------|------|-------------|---------|
| **S.10.cons-a** | 2026-05-19 | ADR-009 plan firmado + ADR-008 full renumber atomic (this commit) | ~290 LOC doc |
| **S.10.cons-b** | TBD | IvSurfaceRepository READ methods + tests | ~200 LOC + ~15 tests |
| **S.10.cons-c** | TBD | TickerSnapshot extension + serializer + MarketState.to_dict() | ~150 LOC + ~10 tests |
| **S.10.cons-d** | TBD | SchwabDataLayer.snapshot() extension + Repository wiring + lifespan | ~250 LOC + ~10 tests |
| **S.10.cons-e** | TBD | ATHENA prompt update (term_structure + surface semantics sections) | ~50 LOC + ~5 tests |
| **S.10.cons-f** | TBD | Operator doc + ADR-009 close-out + Status Aceptado | ~150 LOC doc |

**Total Sprint 10 estimate:** ~800 LOC code + ~40 tests + ~400 LOC doc, ~6-10 horas combined.

---

## 4. Open questions

- **Q1**: surface representation tradeoff — delta-sampled (D2-2) vs full grid future. Phase 1 = delta-sampled. Trigger Phase 2 expansion: ATHENA GEX compute requires full grid (ADR-011 scope intersection).
- **Q2**: ohlcv_intraday timeframe selection — all 4 (D2-3) vs ATHENA-configurable subset. Phase 1 = all 4 atomic. Trigger configurability: token budget pressure observed.
- **Q3**: Surface aggregation if multiple snapshots same day — which ts to read? D3 uses `get_latest_surface` → returns max ts. Trigger refinement: multi-snapshot intraday divergence detection useful.
- **Q4**: Cache TTL para 30-read snapshot impact — measure first Sprint 10 baseline. Trigger Phase 1.5 caching: latency >500ms p99 observed.
- **Q5**: Schwab API rate limit interaction with worker snapshots — reads are DB-only, NO Schwab calls. Should be safe. Trigger validation: monitor first Sprint 10 runs.

---

## 5. Out of scope

- **Tier A compute pipeline** (GEX/vanna/charm aggregation) — Sprint 12+ ADR-011.
- **Volume profile aggregation** (ohlcv-based) — Sprint 12+ Tier A.
- **NYX sentiment integration** — Sprint 12+ separate ADR.
- **WebSocket real-time consumer** — Sprint 11-12 ADR-010.
- **Full surface grid representation** — defer Q1 trigger.
- **ATHENA backtest depth ATL changes** — Q4 trigger ADR-007.5 future.
- **HERMES integration** — Sprint 13-16+ ADR-012.

---

## 6. Success criteria

1. IvSurfaceRepository tiene 3 new read methods (`get_surface_for_ticker` + `get_term_structure` + `get_latest_surface`) tested.
2. TickerSnapshot has 3 NEW fields (term_structure + surface + ohlcv_intraday) backward-compatible defaults.
3. SchwabDataLayer.snapshot() reads iv_surface + market.ohlcv post-fetch, assembles extended TickerSnapshot.
4. ATHENA prompt updated con term_structure + surface semantics sections.
5. ~40 new tests passing (mirror ADR-005/006/007 patterns).
6. Tests baseline preserved: 856 + ~40 = 896 + 1 skipped post-Sprint 10.
7. ADR-009 Status: Propuesto → Aceptado en S.10.cons-f close-out.
8. ADR-008 renumber consistency verified (zero leftover ADR-009 WebSocket refs).
9. 4 inherited tech debt items resolved atomically (ADR-005 §9.3 #2 + ADR-006 D6-1 + ADR-007 §9.3 #4 + S.9 §5).

---

## 7. Risks

| ID | Risk | Likelihood | Mitigation |
|----|------|-----------|------------|
| R1 | Schema breaking change frozen=True TickerSnapshot | Low | D7 optional defaults preserve existing callers |
| R2 | Performance impact 30 reads/snapshot | Medium | D6 measure baseline + Q4 cache trigger |
| R3 | ATHENA prompt token bloat (3 new fields) | Medium | D2-2 delta-sampled keeps surface compact + D5 progressive disclosure |
| R4 | Surface representation forces ADR-011 GEX compute compatibility | Low | Q1 trigger explicit defer Phase 2 expansion if needed |
| R5 | Bootstrap path — iv_surface/ohlcv repo empty pre-Sprint 7/9 | Low | D3 returns None/empty; DataLayer handles defaults |
| R6 | Repository SQL N+1 anti-pattern (per-ticker calls) | Low | Acceptable Phase 1 6 tickers; batch query refactor future |
| R7 | ADR-008 renumber inconsistency post-S.10.cons-a (downstream docs) | Medium | Full atomic renumber 15 refs verified; future docs use new numbering |

---

## 8. References

- **ADR-008** (commit `169cef2`): D6 sequencing pre-renumber; D5 Sprint 10 boundary explicit; §9.4 cross-ref.
- **ADR-007** (commit `8305ef3`): OhlcvRepository.get_bars consumer-ready; §9.3 #4 Backtest depth trigger Phase 2.
- **ADR-006** (commit `bdb0106`): D6 WRITE-only Sprint 7; D6-1 ATHENA prompt drift inherited; §9.3 #2 RESOLVED Sprint 7.
- **ADR-005**: D5 progressive disclosure pattern reference; §9.3 #2 + #7 RESOLVED inherited.
- **S.10.plan-a** (commit `40fadca`): Sprint 10 lock + scoring matrix 3.85 vs 3.60.
- **S.9.plan-a** (commit `4b54203`): TENTATIVE caveat doctrine + F-r1 pattern.
- **Sprint 7 + Sprint 9 close-outs**: WRITE-only foundations producer/consumer pair completion narrative.

---

## 9. Close-out (S.10.cons-f, pending)

> Sección se completa en S.10.cons-f. Estructura prevista (mirror ADR-005/006/007 §9):
> - §9.1 Sub-blocks delivered (S.10.cons-a/b/c/d/e/f con commits + LOC + tests + sign-off dates).
> - §9.2 Rule #15 findings summary (F-r1 a F-rN + implementation findings).
> - §9.3 Tech debt registered (deferred Q1-Q5 + 4 inherited RESOLVED).
> - §9.4 Next steps Sprint 11+ (ADR-010 Schwab WebSocket + ATLAS portfolio adjacent).
> - Status: Propuesto → Aceptado.

---

> **Próximo sub-bloque:** S.10.cons-b (IvSurfaceRepository READ methods + tests). Inicia tras Juan sign-off plan firmado actual.
