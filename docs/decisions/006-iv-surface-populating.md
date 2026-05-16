# ADR-006: market.iv_surface populating

**Fecha:** 2026-05-15
**Estado:** Aceptado (2026-05-16)
**Contexto:** Sprint 6 iv-history stage cerrado (commits 14-15 mayo 2026). `market.iv_history` table writes ATM IV scalar daily for iv_rank compute. `market.iv_surface` hypertable EXISTS desde V007 pero unwritten — ADR-005 §9.3 tech debt #2. Esta ADR define producer wire-up para populating iv_surface aprovechando chain ya fetched por IvHistoryWorker.

---

## 1. Context

### 1.1 Lo que Sprint 6 difirió

Per ADR-005:
- **§5 Out of scope**: "per-strike IV history (delta-25 put_iv history, etc.). Out of scope; iv_history es single ATM scalar only."
- **§9.3 tech debt #2**: `market.iv_surface` populating — hypertable EXISTS desde V007 pero NO producer/consumer wired. Future ADR-006 candidate.
- **§9.4 Next steps**: ADR-006 candidate trigger: "cuando HERMES Sprint 6+ needs richer per-contract IV, OR when ATHENA / APOLLO benefit from term structure data beyond daily ATM scalar."

Estado actual del código:
- `market.iv_surface` schema V007:30-56 — 12 fields (`ts, underlying, expiration, strike, option_type, iv, delta, gamma, theta, vega, open_interest, volume`).
- `IvHistoryWorker` (S.6.iv-c) fetches `chain = self._client.get_options_chain(ticker)` per ticker at 21:15 UTC daily. Currently consumes only ATM IV scalar via `compute_atm_iv()`.
- Zero existing consumers of `market.iv_surface`.
- ATHENA prompt mentions "term structure, vol surface" en data priorities pero TickerSnapshot.skew solo expone ATM + 25-delta scalars (3 fields).

### 1.2 Por qué iv_surface ahora

Three drivers:

1. **Foundation completion** — V007 hypertable existe pero unwritten desde hace ~Sprint 2. Closes ADR-005 §9.3 tech debt #2.
2. **Producer side ~free** — chain ya fetched per IvHistoryWorker, contains all 12 V007 fields per-contract. Extension cost minimal (~50-100 LOC).
3. **Forward-compatible data accumulation** — paper trading mission requires accurate IV history for ATHENA/APOLLO retrospective backtests + tactical agents Sprint 8+. Start accumulating now per D9 firm "forward only" pattern.

### 1.3 Masterdoc deviation rationale

Per CLAUDE.md rule #13 ("Mantenete fiel al documento maestro. Si vas a desviarte, justificalo y preguntá"):

**Masterdoc §10.7 explicit:** Sprint 7 = NYX Integration.

**Deviation:** ADR-006 pivots Sprint 7 to iv_surface populating.

**Justificación operator-validated:**

- **NYX scope is massive** — net-new sentiment data layer (AAII, NAAIM, NLP titulares, COT, retail flow). Per masterdoc §3.4 priority data list: 6+ external data sources required, zero implemented currently.
- **iv_surface scope is minimal** — V007 schema reuse, producer pattern proven (S.6.iv-c), ~150-250 LOC code.
- **Paper trading roadmap** (CLAUDE.md mission core) — IV surface data accumulation forward-only takes ~1 año bootstrap (per D9 consistency). Starting Sprint 7 unblocks future tactical/retrospective work without blocking paper trading itself.
- **Sprint labeling has drifted** from masterdoc §10. Real Sprint 5 ≠ masterdoc §10.5; real Sprint 6 ≠ masterdoc §10.6. Strict §10.7 adherence over-constrains given prior drift.

Decision operator-explicit 2026-05-15: pivot accepted. NYX remains future candidate (Sprint 8+ when sentiment data layer ADR materializes).

---

## 2. Decisions

### D1. Schema — Reuse V007 as-is (no V019 migration)

**Decisión:** Use `market.iv_surface` V007 schema sin modification.

12 fields cover IV + greeks (5) + liquidity (2) + identifier keys (5). Microstructure fields missing (`bid/ask/mark/last/dte`) NOT blocking for iv_surface primary use cases (term structure, skew evolution, surface analytics).

| Opción | Descripción | Descartada porque |
|---|---|---|
| **A (this)** | V007 as-is, 12 fields. | Sufficient para anticipated consumers ATHENA/APOLLO. Bid/ask spreads = microstructure separate concern. |
| B | V019 migration agregar bid/ask/mark/last/dte. | Premature. Add when concrete consumer needs surfaced (Sprint 8+ if pain). |
| C | Subset V007 (only iv/delta/oi/volume initially). | Schema rigidity for marginal write savings. NUMERIC columns NULL-safe in PG anyway. |

### D2. Volume strategy — Full chain (no sampling)

**Decisión:** Persist all contracts returned por Schwab `get_options_chain(ticker, strike_count=DEFAULT_STRIKE_COUNT)` — both calls + puts, all expirations, all strikes.

| Opción | Descripción | Descartada porque |
|---|---|---|
| **A (this)** | Full chain ~800-960 rows/ticker/snapshot. | Defeats purpose to sample iv_surface — surface = "all the surface". |
| B | Sampled ATM ± N strikes only. | Loses term structure breadth. iv_history already covers ATM scalar. |
| C | 25-delta strikes only. | Loses information density at wings. |

Volume estimate: 6 tickers × ~900 rows × daily = ~5,400 rows/day = ~1.5-1.8M rows/year. Within TimescaleDB capacity (default 1-day chunks per V007).

### D3. Worker strategy — Extend IvHistoryWorker (no new worker)

**Decisión:** Extend `IvHistoryWorker._snapshot_one_ticker` to call `IvSurfaceRepository.write_chain_snapshot(chain, ticker, ts)` after the existing `compute_atm_iv` + `write_snapshot` calls.

One Schwab fetch per ticker → both `market.iv_history` (ATM scalar) AND `market.iv_surface` (full chain) populated. Atomic intent per-ticker.

| Opción | Descripción | Descartada porque |
|---|---|---|
| **A (this)** | Extend IvHistoryWorker. | Same chain already fetched. Atomic write both tables. 1 Schwab call vs 2. |
| B | NEW IvSurfaceWorker independent. | Doubles Schwab calls (12 → 24/snapshot). Coordination overhead. |
| C | Background async worker triggered post-iv_history. | Async complexity para minimal gain. |

#### D3-1. Sub-decision: Surface write failure isolation

**Decisión:** Surface write failure must NOT block iv_history write success. Per-table try/except inside `_snapshot_one_ticker`:

```python
# Always attempt iv_history (canonical, Sprint 6)
self._repo.write_snapshot(ticker, ts, atm_iv, underlying_close)

# Attempt iv_surface (Sprint 7+, isolated failure mode)
try:
    self._surface_repo.write_chain_snapshot(chain, ticker, ts)
except Exception:
    logger.warning("iv_surface write failed for %s, iv_history succeeded", ticker, exc_info=True)
```

Razón: iv_history es production-critical (iv_rank compute path). iv_surface es accumulating-for-future. Failure mode asymmetry — iv_history must succeed even if iv_surface DB write fails (column type mismatch, transaction conflict, etc.).

### D4. Chunk interval — 1 day per V007 default

**Decisión:** Mantener `chunk_time_interval => INTERVAL '1 day'` per V007 line 50. NO migration adjustment.

Justificación: iv_surface is high-volume (~5.4K rows/day) — V007 ya anticipó esto vs iv_history low-volume (~6 rows/day) usando 1-month chunks (V018). V007 decision validated.

### D5. Retention policy — Defer Sprint 9+ con trigger condition documented

**Decisión:** No active retention policy Sprint 7-8. Documented trigger condition for Sprint 9+ re-evaluation:

- **Trigger A**: hypertable size > 5 GB.
- **Trigger B**: query latency p99 > 500ms on typical iv_surface lookups.
- **First action**: TimescaleDB native compression on chunks > 90 days (preserves query semantics, ~10-20x compression typical).
- **Fallback action**: drop chunks > 365 days if compression insufficient.

| Opción | Descripción | Descartada porque |
|---|---|---|
| A1 | Pure defer, no documented trigger. | Silent ambiguity — future operator doesn't know when to act. |
| **A2 (this)** | Defer + documented trigger conditions. | Operator-friendly, no premature optimization, future-self honest. |
| B | Drop chunks > N days now. | Premature. Volume manageable Sprint 7-8. |
| C | Compression policies activated now. | Premature optimization. |

### D6. Consumer surface — WRITE only Sprint 7

**Decisión:** Sprint 7 scope = persist iv_surface (producer side). NO TickerSnapshot extension. NO ATHENA/APOLLO prompt updates referencing term structure data.

Pattern mirror S.6.iv-b/c (write) → S.6.iv-d (read) two-phase delivery. Future S.7.surf-e/f (or Sprint 8 sub-blocks) add consumer surface when concrete need surfaces.

| Opción | Descripción | Descartada porque |
|---|---|---|
| **A (this)** | WRITE only. No TickerSnapshot extension. | Matches S.6.iv pattern. Minimal scope. Producer accumulates data forward; consumer landed when need concrete. |
| B | WRITE + thin TermStructureSnapshot field (30d/60d ATM IV slope). | Premature — no concrete consumer yet. ATHENA prompt mentions term structure but no actual signal extraction logic. |
| C | WRITE + full surface to ATHENA. | Big scope creep. Out of S.7.surf bounds. |

#### D6-1. Sub-decision: ATHENA prompt drift tech debt registered

**Decisión:** ATHENA prompt línea 50-51 menciona "term structure, vol surface" en data priorities, pero TickerSnapshot NOT exposes ni term structure ni surface. Drift entre prompt aspirations + data reality.

**Tech debt registered (ADR-006 §9.3 future):** ATHENA prompt should be reconciled cuando consumer surface land (Phase 2). Either:
- (a) Remove "term structure, vol surface" from priorities until exposed.
- (b) Extend TickerSnapshot con term structure/surface fields cuando se materialize.

NOT addressed Sprint 7. Tech debt visible para futuro.

### D7. Backfill — Forward accumulation only, NEVER (consistency con D9 ADR-005)

**Decisión:** Mirror ADR-005 D9 firm. Forward accumulation only. NO backfill paid feeds, NO synthetic imputation.

Note semantic difference vs iv_history: iv_surface use cases are mostly **current state** (today's surface) + **time-series for one strike** (forward evolution). Percentile compute (que justificaba D9 strict en iv_history) no es primary use case aquí. Pero firm policy mantained para consistency + complexity avoidance.

### D8. Sub-block naming — S.7.surf-X

**Decisión:** Naming convention `S.7.surf-X` (a/b/c/d) Sprint 7 surface stage. Mirror ADR-005 `S.6.iv-X` pattern.

Sprint label "7" reflects calendar-sequential numbering, NOT masterdoc §10.7 (which is NYX per D9 deviation).

### D9. Masterdoc deviation rationale — Documented §1.3

**Decisión:** Per CLAUDE.md rule #13, deviation from masterdoc §10.7 (Sprint 7 = NYX) is documented explicitly en §1.3 con operator approval rationale.

NYX remains valid future candidate (Sprint 8+) when sentiment data layer ADR materializes.

---

## 3. Sub-blocks (S.7.surf-X)

| Sub-block | Description | LOC est | Time est | Dependencies |
|-----------|-------------|---------|----------|--------------|
| **S.7.surf-a** | ADR-006 plan firmado (this document) | 0 (doc) | 1-2h | — |
| **S.7.surf-b** | `IvSurfaceRepository` + tests (NO migration — V007 reuse) | 100-150 | 2-3h | S.7.surf-a |
| **S.7.surf-c** | `IvHistoryWorker` extension (write surface alongside ATM) + tests | 50-100 | 1-2h | S.7.surf-b |
| **S.7.surf-d** | Operator doc update (`schwab-setup.md` §7 lifecycle extension) + ADR-006 close-out + status Aceptado | 0 (code), ~100-200 (doc) | 1-2h | All above |

**Total estimado:** ~150-250 LOC code + ~100-200 LOC doc, ~5-9h.

**Orden ejecución sugerido:**
1. S.7.surf-a (this).
2. S.7.surf-b (foundation Repository).
3. S.7.surf-c (Worker extension).
4. S.7.surf-d (close-out).

Smaller scope vs Sprint 6 iv-stage (~1,752 LOC) por: V007 schema reuse + Worker extension vs new worker + WRITE-only scope.

---

## 4. Open questions

- **Phase 2 consumer surface trigger** — cuándo materializar TickerSnapshot extension con term structure/surface fields. Decision factors: ATHENA proposal quality regressions sin surface data, APOLLO macro critique signal richness, ATLAS portfolio greek exposure analysis.
- **Strike count tuning** — currently Schwab `strike_count=20` default (~40 strikes/exp). Sprint 8+ revisit si tail strikes (>3σ moves) provide value vs storage cost.
- **Per-expiration retention** vs uniform retention — Sprint 9+ if D5 trigger conditions hit, evaluate whether 0DTE strikes (high volume) need different policy than LEAPs (low volume).
- **D6-1 ATHENA prompt reconciliation timing** — Phase 2 when consumer surface lands, OR earlier if prompt drift causes proposal quality issues.

---

## 5. Out of scope

- **Microstructure fields** (`bid/ask/mark/last/dte`) — out of V007 schema. V019 migration Sprint 8+ if concrete consumer needs surfaced.
- **ATHENA term structure consumer surface** — Phase 2 sub-block o Sprint 8.
- **APOLLO/ATLAS surface consumers** — Phase 2 when proposal generation roles expand.
- **Real-time intraday surface updates** — only daily snapshot per IvHistoryWorker 21:15 UTC schedule. Intraday persistence requires ADR-007 ohlcv + streaming infra.
- **Multi-source aggregation** — only Schwab. CBOE direct feed o ORATS subscription out of scope.
- **Greek interpolation / IV smile fitting** — raw values only. Analytical models Sprint 8+ if needed.
- **TickerSnapshot extension exposing surface to LLM agents** — Phase 2 (D6).

---

## 6. Success criteria

**Concretos para Sprint 7 surface sub-stage:**

1. **IvSurfaceRepository class** implemented con `write_chain_snapshot(chain, ticker, ts) -> int` (returns rows inserted). Mock pool/cursor unit tests verde.
2. **IvHistoryWorker extension** persists iv_surface alongside iv_history. Both tables populated por single chain fetch.
3. **Failure isolation D3-1** verified — surface write exception NOT blocks iv_history write success. Unit test con mocked exception in surface_repo.
4. **Day 1 post-deployment**: `market.iv_surface` contains ~5,400 rows (6 tickers × ~900 contracts/ticker average).
5. **Day 7 post-deployment**: ~38,000 rows accumulated forward-only. Hypertable chunks visible en `timescaledb_information.chunks`.
6. **Tests baseline**: 902 passing + 1 skipped maintained. New tests `IvSurfaceRepository` (~10) + `IvHistoryWorker` extension (~5) = ~15 new tests. Target 917 passing post-S.7.surf-c.
7. **Operator doc updated**: `docs/operator/schwab-setup.md` §7 iv_rank Lifecycle extended con iv_surface lifecycle notes (storage growth, monitoring queries).
8. **ADR-006 status Aceptado** post-S.7.surf-d.

---

## 7. Risks

| ID | Risk | Likelihood | Mitigation |
|----|------|-----------|------------|
| R1 | Schwab chain shape drift breaks producer | Low | S.5.6d test fixtures lock shape; integration test detects regression |
| R2 | DB write latency increase (~1000× rows/snapshot vs iv_history only) | Medium | Batch INSERT (single executemany call per ticker); per-ticker timing logged for visibility |
| R3 | Hypertable size growth faster than projected | Low | D5 trigger conditions monitored; compression activation Sprint 9+ if needed |
| R4 | Surface write failure cascades to iv_history (breaks production path) | Critical | D3-1 isolated try/except in Worker; iv_history write succeeds even if surface raises |
| R5 | NUMERIC overflow on extreme greeks values | Low | V007 NUMERIC(10,8) gamma supports up to 99.99999999; Schwab returns rarely > 1.0 |
| R6 | Failed migration if schema drift unnoticed | NONE | No migration needed (V007 reuse) — risk eliminated |
| R7 | Concurrent write conflicts iv_history + iv_surface | Low | Separate tables, separate INSERT statements; PostgreSQL handles concurrent INSERTs per-table |

---

## 8. References

- **ADR-005** (`docs/decisions/005-iv-history-and-iv-rank-compute.md`): Direct precedent. §9.3 tech debt #2 = this ADR resolves. §9.4 trigger conditions met.
- **`multi-agent-system/db/migrations/V007__market_tables.sql:30-56`**: `market.iv_surface` schema (12 fields, 1-day chunks, idx_iv_surface_underlying_time).
- **`multi-agent-system/src/multi_agent/workers/iv_history_worker.py`**: IvHistoryWorker pattern to extend (S.6.iv-c).
- **`multi-agent-system/src/multi_agent/persistence/iv_history_repository.py`**: IvHistoryRepository pattern to mirror (S.6.iv-b).
- **`shared_core/src/shared_core/brokers/schwab_client.py:get_options_chain`**: chain shape source (S.5.6d normalized).
- **`docs/sistema_multiagente_trading.md` §10.7**: NYX Integration — deviation source per D9.
- **`docs/operator/schwab-setup.md`**: Updated S.7.surf-d — new §8 "iv_surface Lifecycle" added; Future Work renumbered to §9 with iv_surface tech debt IDs registered. Cross-references canonical tech debt IDs en §9.3 below.

---

## 9. Close-out (S.7.surf-d, 2026-05-16)

Sprint 7 iv_surface stage cerrado. ADR-006 status: Propuesto → Aceptado.
WRITE-only path operational: `IvHistoryWorker._snapshot_one_ticker` extension
calls `IvSurfaceRepository.write_chain_snapshot` per ticker per snapshot,
con D3-1 isolation (surface failure NOT blocks iv_history success). Phase 2
consumer surface (TickerSnapshot extension) deferred per D6.

### 9.1 Sub-blocks delivered

| Sub-block | Date | Commit | LOC delta | Tests delta | Description |
|-----------|------|--------|-----------|-------------|-------------|
| S.7.surf-a | 2026-05-15 | `de82465` | +263 (doc) | 0 | ADR-006 plan firmado (this document) |
| S.7.surf-b | 2026-05-16 | `84ab8c3` | +368 | +11 | `IvSurfaceRepository` + tests (NEW executemany batch pattern D-γ) |
| S.7.surf-c | 2026-05-16 | `7ac1ee5` | +147 | +5 | `IvHistoryWorker` extension + lifespan wire-up + D3-1 isolation tests |
| S.7.surf-d | 2026-05-16 | (this commit) | ~+300 (doc) | 0 | Operator doc §8 iv_surface Lifecycle + ADR close-out + daily log |
| **Total** | — | — | **~1,078** | **+16** | — |

Test baseline final: **918 passing** (multi-agent 823 + shared_core 95) + 1
integration test skipped by design (baseline pre-Sprint-7 era 902 +
1 skipped). Net +16 tests for iv_surface components.

### 9.2 Rule #15 findings summary

Pre-recolección rule #15 disciplinada disparó ~32 findings across sub-blocks. Distribución:

- **S.7.surf-a (8)**: ADR-006 plan recolección — V007 schema reuse confirmation, chunk_time_interval 1 day (high-volume), Schwab chain shape per S.5.6d, IvHistoryWorker reuse opportunity, consumer surface scope, D9 backfill firm consistency, retention deferred, masterdoc §10.7 NYX deviation rationale.
- **S.7.surf-b (9)**: findings F1-F9 — migration registry already includes iv_surface (F1 RELIEF), executemany no precedent (F2 NEW pattern), mock pool/cursor reusable (F3), strike string→float cast (F4 CRITICAL), oi→open_interest mapping (F5 CRITICAL), calls/puts→CALL/PUT normalization (F6 CRITICAL), iv NOT NULL guard (F7), volume sparse vs production (F8), psycopg3 NUMERIC float input (F9).
- **S.7.surf-c (9 + 1 mid-flight)**: Worker structure, lifespan wire-up pattern, TYPE_CHECKING precedent variance (app.py TYPE_CHECKING vs Worker direct imports — mid-flight correction D-α-1), D3-1 implementation code example, exception scope, fixture extension, 17 existing tests `_make_worker` invocations.
- **S.7.surf-d (~6)**: ADR-006 §9 placeholder structure, operator doc §7 ya populated (iv_rank Lifecycle desde S.6.iv-f), daily log convention `DAILY_LOG_YYYY-MM-DD.md`, Sprint 7 commits stats, findings real count (~32 vs initial estimate ~10-15), tech debt 5 new items.

Most impactful catches across stage:

- **F4 (S.7.surf-b) CRITICAL**: Schwab chain strike key es STRING ("450.0"), V007 column `strike NUMERIC(14,4)`. Repository casts `float(strike_str)` en write path. Without catch: psycopg3 type error en INSERT.
- **F5 (S.7.surf-b) CRITICAL**: Schwab `contract["oi"]` vs V007 column `open_interest`. Pre-emptive mapping en row tuple builder. Silent data loss without catch.
- **F6 (S.7.surf-b) CRITICAL**: Schwab `"calls"`/`"puts"` plural lowercase vs V007 `option_type "CALL"/"PUT"` singular uppercase. Module-level `_OPTION_TYPE_MAP` constant.
- **F1 (S.7.surf-c) STATE GAP**: Memory claimed S.7.surf-b committed, reality untracked. Pattern repetido también en S.7.surf-d (S.7.surf-c uncommitted at session resume). Atomic commit-per-sub-block hygiene critical.
- **D-α-1 (S.7.surf-c) MID-FLIGHT**: Pre-recolección F5 memory inaccurate — Worker uses direct imports, not TYPE_CHECKING. Adopted direct import pattern per file convention. App.py mantain TYPE_CHECKING precedent separate.

**Pattern observado:** rule #15 ahorró 10-30 min de speculative implementation per finding. Sprint 7 introduced new state-gap catch pattern (commit lag between sessions) — atomic commits + memory updates required Sprint 8+.

### 9.3 Tech debt registered for Sprint 8+

NEW Sprint 7 items (5 new):

1. **F7 iv=0.0 vs iv=None disambiguation** (S.7.surf-b): `IvSurfaceRepository.write_chain_snapshot` uses `if not iv:` to skip falsy — both None (missing) and 0.0 (legit deep OTM theoretical) get filtered. Future Sprint may need distinguish missing data vs valid zero IV. Edge case for ADR-006 §4 open question.

2. **executemany pattern canonical convention** (S.7.surf-b): NEW pattern introduced — previously single-row execute() in S.6.iv-b. Document Sprint 8+ as canonical for high-volume Repository INSERTs (~900 rows/ticker/snapshot for iv_surface). Future Repositories follow.

3. **D-α-3 MagicMock plain (no spec=IvSurfaceRepository)** (S.7.surf-c): Tests use plain MagicMock for surface_repo. API drift (signature changes) NOT auto-caught. Trade-off accepted: less coupling, faster tests. Sprint 8+ revisit si concrete API drift bugs emerge.

4. **Test 5 positional args check vs kwargs** (S.7.surf-c): `test_surface_called_with_correct_chain_ticker_ts` validates positional args via `call_args[0]`. Intentional drift catch — if Worker code switches to kwargs, test breaks. Documents API contract via test. Future code MUST keep positional `write_chain_snapshot(chain, ticker, ts)`.

5. **D6-1 ATHENA prompt drift** (inherited from ADR-006): ATHENA prompt línea 50-51 mentions "term structure, vol surface" en data priorities pero TickerSnapshot NOT exposes ni term structure ni surface. Reconciliation cuando consumer surface lands Phase 2 (D6 trigger).

**Inherited from ADR-005 §9.3 (cross-ref)**: SchwabClient doble construcción (#1), market.iv_surface populating (#2 RESOLVED Sprint 7), market.ohlcv populating (#3 → ADR-007 candidate), _persisted_at field (#4), date-aware correlations (#5), SchwabClient.from_env() removal (#6), ATHENA prompt caveat (#7 RESOLVED S.6.iv-e), token TTL caching (#8), TOKEN_SCHWAB cleanup (#9), SkewSnapshot field naming (#10), Historical IV backfill (#11).

ADR-005 §9.3 #2 (`market.iv_surface` populating) **CLOSED en Sprint 7** (S.7.surf-b/c). Operator doc §9 references both ADR-005 §9.3 (Sprint 6 inherited) and ADR-006 §9.3 (Sprint 7 new) canonical IDs.

### 9.4 Next steps Sprint 8+

ADR-006 §4 open questions + Sprint 8+ candidates:

- **ADR-007 candidate** — `market.ohlcv` producer/consumer (tech debt ADR-005 §9.3 #3). HERMES historical data prerequisite. Sprint 8+ trigger when HERMES tactical agent design lands o intraday OHLCV needs emerge.
- **Phase 2 consumer surface** (ADR-006 §4 first open question + D6 trigger). TickerSnapshot extension with TermStructureSnapshot field (30d/60d ATM IV slope) o full surface exposure. Decision factors: ATHENA proposal quality regressions sin surface data, APOLLO macro critique signal richness.
- **D5 retention triggers** (ADR-006 §4 + D5). Monitor hypertable size + p99 query latency. Activate TimescaleDB native compression > 90d when triggers hit (5 GB OR p99 > 500ms). Sprint 9+ likely.
- **NYX Sprint 8+ candidate** — masterdoc §10.7 NYX Integration postponed per ADR-006 D9. Sentiment data layer ADR materialization required. Trigger when AAII/NAAIM/COT/NLP titulares data sources scoped.
- **Strike count tuning** (ADR-006 §4). Currently Schwab `strike_count=20` default. Sprint 8+ revisit si tail strikes (>3σ moves) provide value vs storage cost.
- **F7 iv=0.0 vs None disambiguation** (tech debt #1 new). Decide Sprint 8+ if concrete data quality issue emerges.

Sprint 7 iv_surface stage successfully closed. Foundation iv_surface accumulating forward (~1 año bootstrap per D9 consistency). Phase 2 consumer surface lands cuando concrete need surfaces.

---

> **Sprint 7 iv_surface stage cerrado** (commits 15-16 mayo 2026). Próximo: Sprint 8+ planning — HERMES + ADR-007 ohlcv candidate o Phase 2 consumer surface decision.
