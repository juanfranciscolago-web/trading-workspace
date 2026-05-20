# ADR-013: ATLAS Portfolio Integration — SchwabClient ports + LiveSnapshotBuilder + flag

**Fecha:** 2026-05-20
**Estado:** Propuesto
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

## 9. Close-out (S.11.atlas-f, pending)

> Sección se completa en S.11.atlas-f. Estructura prevista (mirror ADR-005/006/007/009 §9):
> - §9.1 Sub-blocks delivered (S.11.atlas-a/b/c/d/e/f con commits + LOC + tests + sign-off dates).
> - §9.2 Rule #15 findings summary (F-r1 a F-r5 + implementation findings).
> - §9.3 Tech debt registered (deferred Q1-Q5 + emergent).
> - §9.4 Next steps Sprint 12+ (ADR-010 Schwab WebSocket + ADR-011 GEX + ADR-012 HERMES tentative).
> - Status: Propuesto → Aceptado.

---

> **Próximo sub-bloque:** S.11.atlas-b (SchwabClient.get_positions port + account_id discovery + ~10 tests). Inicia tras Juan sign-off plan firmado actual.
