# ADR-013: ATLAS Portfolio Integration — SchwabClient ports + LiveSnapshotBuilder + flag

**Fecha:** 2026-05-20
**Estado:** Aceptado (2026-05-26)
**Contexto:** Sprint 11 LOCKED via S.11.plan-a (commit `e66ed45`, 2026-05-20, scoring 3.60/5 vs WebSocket 2.35, gap 1.25 decisive). Esta ADR define ATLAS portfolio integration completion — SchwabClient.get_positions + get_balances ports + LiveSnapshotBuilder NEW class + ATLAS engine wiring + lifespan swap + USE_LIVE_PORTFOLIO flag. ADR-013 NEW number (no renumber required — ATLAS portfolio NOT en ADR-008 D6 sequencing).

---

## 1. Context

### 1.1 Sprint 11 lock per S.11.plan-a

- S.11.plan-a (commit `e66ed45`): Sprint 11 = #7 ATLAS portfolio integration, 3.60/5 weighted dominant vs ADR-010 WebSocket part 1 2.35/5 (gap 1.25 decisive).
- Foundation completion narrative: Sprint 5/7/9 producer + Sprint 10 consumer + Sprint 11 validator = trio operational foundation completed.
- ADR-008 §9.4 reference: ATLAS portfolio integration NOT en D6 canonical sequencing (ADR-009/010/011/012). NEW ADR number assignment ADR-013.

### 1.2 ADR number decision

ADR-013 NEW slot. No renumber required (vs Sprint 10 S.10.cons-a full renumber pattern). ATLAS portfolio integration emerged adjacent to ADR-008 Frame 3 sequencing — clean number assignment.

### 1.3 Eolo precedent state (verified pre-recolección)

- `~/PycharmProjects/eolo/eolo-options/execution/options_trader.py` + `eolo-crop/execution/options_trader.py`: `get_account_id()` sync + `async def get_positions()` con `?fields=positions` Eolo pattern.
- **NO direct `get_balances()` function en Eolo Schwab path** (F-r2 catch). Schwab API docs source required.
- `eolo-crypto-dashboard` + `eolo-crypto`: Binance/CCXT `balance_usdt` pattern. NOT applicable Schwab port.

### 1.4 Pre-recolección findings F-r1 a F-r5

- **F-r1**: `TRADER_BASE_URL` constant MISSING SchwabClient — D4 adds.
- **F-r2**: Eolo NO has `get_balances` precedent — D5-C Schwab API docs source.
- **F-r3**: `portfolio_routes.py` does NOT exist en api/ — D1 out of scope Sprint 11.
- **F-r4**: `USE_LIVE_PORTFOLIO` flag independence from `USE_SCHWAB_DATA_LAYER` important — D10 separate flag.
- **F-r5 NEW**: Operator pre-deploy subaccount creation required (D9 + D9-1). Schwab portal manual action, not API automation. Lifespan startup warning if account_id empty + USE_LIVE_PORTFOLIO=true.

---

## 2. Decisions

### D1. Scope

**IN Sprint 11:**
- SchwabClient.get_positions + get_balances ports.
- LiveSnapshotBuilder NEW class.
- ATLAS engine integration (validate against live snapshot).
- Lifespan swap (USE_LIVE_PORTFOLIO branch).
- 2 NEW Settings fields: USE_LIVE_PORTFOLIO + SCHWAB_ACCOUNT_ID.

**OUT (Sprint 12+):**
- portfolio_routes.py API surface (F-r3 catch).
- Position deduplication logic (D9 isolated naturally).
- Advanced caching strategy.
- Order management (place_order, cancel_order — Sprint 13+).

### D2. Sync port style

SchwabClient.get_positions + get_balances methods SYNC (mirror existing `get_price_history` + `get_options_chain` pattern). Consumers wrap via `asyncio.to_thread` para async paths.

**Razón:** Pattern consistency con existing SchwabClient surface. Async via wrapping en consumer (mirror OhlcvWorker S.9.ohl-b pattern).

### D3. Account discovery (runtime + cache)

Runtime via `GET /trader/v1/accounts` first call. Cache `self._account_id` instance attribute (mirror Eolo `get_account_id()` pattern proven 3x).

**Razón:** No Settings field needed for default behavior (empty SCHWAB_ACCOUNT_ID → auto-discovery pick-first). Mirror Eolo proven 3x.

### D4. TRADER_BASE_URL constant

NEW: `TRADER_BASE_URL = "https://api.schwabapi.com/trader/v1"` added to SchwabClient class constants (alongside PRICE_HISTORY_URL + CHAINS_URL).

**Razón:** F-r1 catch pre-Write — Eolo precedent has SCHWAB_TRADER_BASE constant, multi-agent SchwabClient missing.

### D5. get_balances endpoint pattern (D5-C)

**Separate endpoints (D5-C path)** per pre-recolección verify-grep multi-source:

- **get_positions**: `GET /trader/v1/accounts/{account_id}?fields=positions` (Eolo port verbatim).
- **get_balances**: `GET /trader/v1/accounts/{account_id}` (no fields, default balances) — NEW fresh implementation Schwab API docs source.

Schwab response parsing get_balances:

```python
data = response.json()
sa = data.get("securitiesAccount", {})
balances = sa.get("currentBalances", {})
return {
    "cash": float(balances.get("cashBalance", 0)),
    "buying_power": float(balances.get("buyingPower", 0)),
    "total_value": float(balances.get("liquidationValue", 0)),
    "margin_used": float(balances.get("marginBalance", 0)),
    "day_trading_buying_power": float(balances.get("dayTradingBuyingPower", 0)),
}
```

**Razón F-r2 catch:** Eolo NO has get_balances precedent (verified multi-source grep eolo-options + eolo-crop + eolo-crypto). Schwab API docs source. Field names verification en S.11.atlas-c implementation. Alternatives evaluated:
- D5-A single endpoint no fields (rejected: couples positions + balances).
- D5-B single endpoint con fields=positions,orders,balances (rejected: 3 fetches one call, harder testing).
- D5-C separate endpoints (SELECTED: separation of concerns, Eolo verbatim port preserved).

### D6. LiveSnapshotBuilder NEW class

NEW `LiveSnapshotBuilder` class alongside existing DB-backed `SnapshotBuilder`. Lifespan selector branch:

```python
if settings.USE_LIVE_PORTFOLIO:
    snapshot_builder = LiveSnapshotBuilder(schwab_client)
else:
    snapshot_builder = SnapshotBuilder(pool)  # existing DB-backed
```

`LiveSnapshotBuilder.build()` calls SchwabClient.get_positions + get_balances, maps to PortfolioSnapshot fields, computes hash.

**Razón:** Mirror SchwabDataLayer vs StubDataLayer proven pattern. Preserves existing 8 SnapshotBuilder tests + DB-backed path backward compat (D7 mirror, Sprint 5 D7 pattern).

### D7. Cadence (CachedSnapshotBuilder TTL 30s live)

CachedSnapshotBuilder TTL **30 seconds live mode** (vs 5 seconds synthetic). Per-proposal hits cache. Schwab rate limit 5/sec OK at this cadence.

**Razón:** Live broker calls slower than DB reads + Schwab rate limit consideration. 30s = max 2 portfolio refreshes/minute = ~120/hour vs Schwab limit 5/sec sustained = trivial. Sprint 12+ telemetry inform refinement.

### D8. Paper mode (Schwab paper subaccount)

Schwab paper trading uses **real Schwab API + paper subaccount_id**. NOT synthetic DB.

- Multi-agent paper trading = Schwab paper subaccount reads (real API, paper subaccount).
- Synthetic mode (USE_LIVE_PORTFOLIO=False) = StubDataLayer + DB-backed SnapshotBuilder (current behavior preserved).

**Razón:** Paper trading discipline requires real API contract experience. Synthetic DB-backed mode preserved for tests + development.

### D9. Subaccount isolation strategy

Multi-agent operates en **separate Schwab subaccount** distinct from Eolo bots' subaccount. Both share same Schwab parent account + same API key authentication. Distinct accountNumber per subaccount.

**Implications:**
- ATLAS reads exclusively multi-agent subaccount positions (no Eolo conflation).
- NO position deduplication logic needed Phase 1 (naturally isolated).
- buying_power independent per subaccount.

**Operator pre-deploy action required (F-r5 NEW catch):**
- Schwab portal: create new paper subaccount distinct from Eolo's existing.
- Note accountNumber returned by Schwab.
- Set `SCHWAB_ACCOUNT_ID` env var antes de Sprint 11 deploy.

#### D9-1. Settings field SCHWAB_ACCOUNT_ID NEW

NEW Settings field: `SCHWAB_ACCOUNT_ID: str = ""`.

- **Empty default** = auto-discovery pick-first (Eolo behavior preserved for backward compat).
- **Set explicit** = multi-agent uses specified subaccount; SchwabClient constructor accepts optional `account_id` parameter; overrides auto-discovery if provided.

**Rationale alternatives evaluated Camino 2:**
- (a) Explicit Settings field — SELECTED: robust, env-var configurable, mirrors deployment patterns.
- (b) Nickname-based discovery — rejected: fragile, depends on Schwab account display name returns.
- (c) Indexed discovery (e.g., second account in list) — rejected: fragile, depends on list ordering.

### D10. USE_LIVE_PORTFOLIO flag

NEW Settings field: `USE_LIVE_PORTFOLIO: bool = False`.

Independent from `USE_SCHWAB_DATA_LAYER`:
- `USE_SCHWAB_DATA_LAYER` = ATHENA market data reads.
- `USE_LIVE_PORTFOLIO` = ATLAS portfolio reads.

4 combinations possible (testing flexibility):
| USE_SCHWAB_DATA_LAYER | USE_LIVE_PORTFOLIO | Mode |
|-----------------------|--------------------|------|
| False | False | Pure synthetic (current) |
| True | False | Schwab data + DB portfolio |
| False | True | Stub data + Schwab portfolio (degenerate) |
| True | True | Full live (production target Sprint 11+) |

**Razón:** F-r4 catch — flags conceptually distinct, independent toggles enable progressive deployment + testing combinations.

---

## 3. Sub-blocks (S.11.atlas-X)

| Sub-block | Date | Description | LOC est | Tests est |
|-----------|------|-------------|---------|-----------|
| **S.11.atlas-a** | 2026-05-20 | ADR-013 plan firmado (this commit) | ~280 doc | 0 |
| **S.11.atlas-b** | TBD | SchwabClient.get_positions port + account_id discovery + tests | ~200 | ~10 |
| **S.11.atlas-c** | TBD | SchwabClient.get_balances port + tests | ~150 | ~10 |
| **S.11.atlas-d** | TBD | LiveSnapshotBuilder NEW class + USE_LIVE_PORTFOLIO flag + tests | ~250 | ~15 |
| **S.11.atlas-e** | TBD | ATLAS lifespan integration (live builder swap) + tests | ~150 | ~5 |
| **S.11.atlas-f** | TBD | Operator doc + ADR-013 close-out + daily log | ~200 doc | 0 |

**Total Sprint 11 estimate:** ~1,000-1,200 LOC code + ~40-50 tests + ~450 LOC doc.

---

## 4. Open questions

- **Q1**: Subaccount creation operator workflow — manual Schwab portal Phase 1 vs API automation Sprint 12+. Trigger: scaling beyond 1 subaccount.
- **Q2**: Stale data fallback strategy if Schwab API down — use last known snapshot vs halt ATLAS. Trigger: production outage observed Sprint 11+.
- **Q3**: Position metadata richness — Greek breakdown via Schwab response vs derive from market data layer. Trigger: ATLAS Greek-based validation needs.
- **Q4**: ATLAS validation behavior when portfolio empty — bootstrap state vs error. Phase 1: bootstrap state with $0 NAV $0 positions tuple.
- **Q5**: Multi-account future extensibility — multiple subaccounts aggregate vs strict 1:1. Trigger: cross-strategy capital allocation Sprint 13+.

---

## 5. Out of scope

- **portfolio_routes.py API surface** — Sprint 12+ (F-r3 catch).
- **Position deduplication logic** — D9 isolated naturally via subaccount.
- **Order management endpoints** (place_order, cancel_order, get_order_status) — Sprint 13+ scope.
- **Real-time position WebSocket streaming** — Sprint 12-13+ ADR-010 scope.
- **Greek aggregation analytics** — post Sprint 11 enhancement (Q3 trigger).
- **Multi-account aggregation** — Q5 trigger Sprint 13+.

---

## 6. Success criteria

1. 6 sub-blocks S.11.atlas-a/b/c/d/e/f delivered atomic per Sprint 10 compact pattern.
2. ~40-50 NEW tests, 0 regresiones from 996 + 1 skipped baseline.
3. ATLAS validates real Schwab portfolio snapshot vs synthetic DB-backed.
4. `USE_LIVE_PORTFOLIO=True` → LiveSnapshotBuilder + SchwabClient ports active.
5. `USE_LIVE_PORTFOLIO=False` → existing DB-backed SnapshotBuilder behavior preserved.
6. Operator pre-deploy checklist documented (subaccount creation + env vars).
7. Lifespan startup warning logged si `USE_LIVE_PORTFOLIO=True` + `SCHWAB_ACCOUNT_ID=""`.
8. ADR-013 Status: Propuesto → Aceptado en S.11.atlas-f close-out.

---

## 7. Risks

| ID | Risk | Likelihood | Mitigation |
|----|------|-----------|------------|
| R1 | Schwab API field names diverge from D5 spec | Medium | D5 verification pre-Write S.11.atlas-c + integration test gated |
| R2 | Account discovery failure if 0 paper subaccounts exist | Low | Clear error message + operator pre-deploy docs |
| R3 | Concurrent Eolo + multi-agent same parent account auth conflicts | Low | D9 subaccount isolation + same OAuth credentials shared (single refresh token) |
| R4 | ATLAS validation lag vs polled cadence 30s | Low | CachedSnapshotBuilder TTL configurable Sprint 12+ if needed |
| R5 | LiveSnapshotBuilder vs DB-backed behavior divergence | Low | D6 swap pattern preserves DB tests, parallel impl |
| R6 | Schwab paper trading API throttling Sprint 11 production | Low | rate_limiter existing + monitoring D-γ isolation pattern S.7.surf-c |
| R7 | Operator forgets pre-deploy subaccount creation | Medium | F-r5 catch documented + operator doc §11 explicit + lifespan startup warning |

---

## 8. References

- **ADR-007** (commit `8305ef3`): market.ohlcv producer/consumer Aceptado. Tier C foundation precedent.
- **ADR-008** (commit `169cef2`): HERMES Tactical Scope Aceptado. D6 sequencing (ADR-013 NOT en D6, NEW slot).
- **ADR-009** (commit `dea7ee9`): Phase 2 consumer surface UNIFIED Aceptado. Foundation completion narrative.
- **S.11.plan-a** (commit `e66ed45`): Sprint 11 priority analysis ATLAS LOCKED + scoring matrix 3.60 vs 2.35.
- **Eolo precedent**: `~/PycharmProjects/eolo/eolo-options/execution/options_trader.py` (get_positions + get_account_id sync pattern, SCHWAB_TRADER_BASE constant line 62).
- **SchwabClient current**: `shared_core/src/shared_core/brokers/schwab_client.py` (get_positions + get_balances stubs lines 682 + 690).
- **PortfolioSnapshot infra**: `multi-agent-system/src/multi_agent/risk/portfolio_snapshot.py` (4 classes: PositionView + PortfolioSnapshot + SnapshotBuilder + CachedSnapshotBuilder).
- **ATLAS engine**: `multi-agent-system/src/multi_agent/risk/atlas_core.py` (validate + get_current_risk_mode functions accept PortfolioSnapshot).
- **Schwab Trader API docs**: https://developer.schwab.com/products/trader-api--individual.

---

## 9. Close-out (S.11.atlas-f, 2026-05-26)

Sprint 11 ATLAS portfolio integration completado. ADR-013 Aceptado.

**Sprint 11 work period**: 2026-05-20 (Sprint plan-a + atlas-a a atlas-e, ~4 horas
intense Camino 2 protocol) + 2026-05-26 (atlas-f close-out post 6-day operator
break).

### 9.1 Sub-blocks delivered

| Commit | Sub-block | LOC delta | Tests delta | Descripción |
|--------|-----------|-----------|-------------|-------------|
| `e66ed45` | S.11.plan-a | +182 doc | 0 | Sprint 11 priority analysis ATLAS LOCKED |
| `d33d8fe` | S.11.atlas-a | +263 doc | 0 | ADR-013 plan firmado (10 decisions D1-D10 + D9-1) |
| `5873cd0` | S.11.atlas-b | +407 code+tests | +10 | SchwabClient.get_positions + get_account_id port from Eolo |
| `6f28c66` | S.11.atlas-c | +295 code+tests | +11 | SchwabClient.get_balances port from Schwab API docs |
| `c4b3c14` | S.11.atlas-d | +333 code+tests | +14 | LiveSnapshotBuilder + USE_LIVE_PORTFOLIO + SCHWAB_ACCOUNT_ID |
| `bfc297f` | S.11.atlas-e | +188 code+tests | +6 | ATLAS lifespan integration _build_snapshot_builder helper |
| _S.11.atlas-f_ | _this commit_ | _~+385 doc_ | _0_ | _Close-out + ADR Aceptado + operator §10 + daily log_ |
| **Total** | — | **~+2,053** | **+41** | — |

### 9.2 Findings rule #15 summary

**18 catches cumulative Sprint 11** (vs Sprint 10's 8 record). Pre-Write
discipline working sustained. Pattern observable: F-r catches concentrate
en first-touch sub-blocks (atlas-a 5, atlas-b 3, atlas-d 2, atlas-e 4),
decay as patterns proven (atlas-c 0).

| ID | Sub-block | Type | Descripción |
|----|-----------|------|-------------|
| F-r1 | atlas-a | Missing | TRADER_BASE_URL constant MISSING SchwabClient |
| F-r2 | atlas-a | Source | Eolo NO has get_balances precedent (Schwab docs source) |
| F-r3 | atlas-a | Scope | portfolio_routes.py does NOT exist (out of scope Sprint 11) |
| F-r4 | atlas-a | Independence | USE_LIVE_PORTFOLIO ≠ USE_SCHWAB_DATA_LAYER importance |
| F-r5 | atlas-a | Operator | Pre-deploy subaccount creation required (manual Schwab portal) |
| F-r9 | atlas-b | Naming | spec self._credentials underscored vs reality self.credentials public |
| F-r10 | atlas-b | Naming | spec client_id/client_secret vs reality api_key/api_secret |
| F-r11 | atlas-b | Pattern | spec module-level TRADER_BASE_URL vs reality class-level |
| F-r12 | atlas-d | Path | spec settings.py vs reality config.py |
| F-r13 | atlas-d | Signature | snapshot_hash(positions, cash_usd, pnl_daily_usd, snapshot_at) vs spec assumption |
| F-r14 | atlas-e | Type | CachedSnapshotBuilder type hint SnapshotBuilder vs LiveSnapshotBuilder duck-typing |
| F-r15 | atlas-e | Path | spec atlas_engine.py vs reality atlas_core.py |
| F-r16 | atlas-e | Pattern | SchwabClient 4th instance construction (tech debt ADR-005 §9.3 #1) |
| F-r17 | atlas-e | Attribute | spec result._ttl_seconds vs reality result._ttl |
| F-r18 | atlas-f | Path | spec docs/daily-logs/ vs reality docs/ workspace root convention |

**Patterns observados**:
- Cross-package work (shared_core ↔ multi-agent) yields catches concentradas atlas-b/d/e.
- Camino 2 protocol value sustained: 18 catches pre-Write = ~3-4 horas debugging
  saved post-implementation.
- ADR canonical re-read discipline (F-r5 Sprint 10 lesson) successful Sprint 11:
  multiple `awk '/### DX/,/### DY/'` re-reads pre-Write.

### 9.3 Tech debt registered

**Sprint 11 NEW tech debt items** (5 Phase 1 simplifications + 1 cross-cutting):

1. **Greeks cross-source** (D-η defer Sprint 12+): PositionView delta/vega/theta
   default Decimal(0) Phase 1. Trigger: ATHENA→ATLAS proposals requiring
   Greeks-based validation. Source candidate: iv_surface (Sprint 7) or options
   chain on-demand.

2. **PnL history table** (D-θ defer Sprint 12+): pnl_weekly_pct + pnl_monthly_pct
   + drawdown_from_peak_pct default 0.0 Phase 1. Trigger: trio paper trading
   accumulates daily snapshots. Schema: `daily_pnl_history` table.

3. **OCC ticker parser** (D-ι-A defer Sprint 12+): PositionView ticker = Schwab
   symbol raw (full OCC for OPTION). Trigger: ATHENA→ATLAS proposals requiring
   ticker-based lookups OPTION positions. Implementation: OCC regex + Schwab
   instrument.underlyingSymbol fallback.

4. **portfolio_beta cross-source** (D-κ defer Sprint 12+): Default 0.0 Phase 1.
   Trigger: ATLAS validation rules requiring portfolio_beta vs SPX. Source:
   compute from historical daily returns vs SPX benchmark.

5. **CachedSnapshotBuilder Protocol refactor** (F-r14 defer Sprint 12+): Type
   hint `builder: SnapshotBuilder` accepts LiveSnapshotBuilder duck-typed.
   mypy may warn. Resolution: `SupportsBuild` Protocol.

6. **SchwabClient instance accumulation** (F-r16 cross-cutting): 4 instances
   (_select_data_layer + IvHistoryWorker + OhlcvWorker + LiveSnapshotBuilder).
   Already registered ADR-005 §9.3 #1. Reaffirmed Sprint 11.

   **✓ RESOLVED Sprint 14 Bundle B1** (commits `0c8c59f` S.14.f-r16-a +
   `119a077` S.14.f-r16-b): 4 instances → 1 singleton via
   `app.state.schwab_client` lifespan pattern + `_build_schwab_client(settings)`
   helper conditional + 9 NEW tests coverage (TestBuildSchwabClient 7 +
   TestHelperBackwardCompat 2). Fail-fast contract D-ν preserved. See
   `docs/decisions/sprint-14-bundle-b1-deferred.md` close-out memo.

**Inherited tech debt resolved Sprint 11**: 0 (Sprint 11 standalone ADR-013
NEW, no cross-sprint dependencies resolved).

### 9.4 Next steps Sprint 12+ (TENTATIVE)

**Sprint 11 LOCKED → Sprint 12 re-score fresh per rule #15 strict** (per
S.11.plan-a + ADR-008 §9.4 + TENTATIVE caveat 4x proven Sprints 8/9/10/11).

**Candidates Sprint 12 (re-score required)**:

- **ADR-010 Schwab WebSocket part 1** (Tier D infra per ADR-008 D5). Sprint 11
  second-place candidate (2.35 weighted). Multi-sprint pattern Sprint 12-13.
- **Paper trading observation telemetry**: Sprint 11 ATLAS live integration
  ready. Trigger: production runs accumulate telemetry → F-r6.5 budget
  trajectory monitoring (Sprint 10 lesson) + R6 throttling validation.
- **Greeks cross-source D-η** (tech debt #1): si ATLAS Greeks validation rules
  require non-zero delta/vega/theta.

**Sprint 13-16+ TENTATIVE**:
- ADR-011 GEX compute pipeline (Tier A).
- ADR-012 HERMES implementation (Sprint 13-16+ ADR-008 timeline).

**Rule #15 reminder**: Sprint 12+ NOT pre-committed. Re-score fresh per
sprint close. Pre-recolección strict per Camino 2 protocol. ADR canonical
re-read pre-Write discipline (F-r5 lesson). Path verification pre-Write
(F-r12 + F-r15 + F-r18 pattern across Sprint 10/11).

---

> **Sprint 11 ATLAS portfolio integration cerrado al 100%** (7 commits 20-26 May 2026).
> Próximo: Sprint 12 priority analysis re-score fresh per rule #15.
