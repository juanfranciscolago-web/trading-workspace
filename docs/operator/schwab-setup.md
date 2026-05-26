# Schwab Integration — Operator Setup Guide

Sprint 5 deliverable (S.5.6g). Cold-start procedure for activating real
Schwab broker data in the multi-agent trading workspace. Written so the
operator (Juan) can rebuild from zero without reading source.

---

## Overview

The trading-workspace ships two `DataLayer` implementations:

- **`StubDataLayer`** (default): synthetic seeded OHLCV / IV / skew /
  correlations. No network calls. Used for development and tests.
- **`SchwabDataLayer`** (this guide): real broker data via Schwab's REST
  API. Read-only Sprint 5 — fetches OHLCV (price history) + options chain
  for the 6-ticker universe (SPY, QQQ, IWM, NVDA, AAPL, MSFT). NO order
  execution. `iv_rank` and `iv_percentile` are placeholders (50.0) until
  Sprint 6+ adds the `iv_history` table (ADR-005).

Activation is gated by the `USE_SCHWAB_DATA_LAYER` env var. Default `false`.

---

## Prerequisites

- GCP project access: `eolo-schwab-agent` (shared with Eolo).
- `gcloud` CLI installed and authenticated as `juanfranciscolago@gmail.com`.
- `trading-workspace` cloned at `/Users/JUAN/Documents/trading-workspace`.
- Python 3.14 venv at `/Users/JUAN/Documents/trading-workspace/venv`.
- Eolo repo accessible at `/Users/JUAN/PycharmProjects/eolo` (read-only,
  per `CLAUDE.md` rule #5).

---

## Section 1 — GCP Credentials Setup

Two paths, pick one. Local dev typically uses Option A; CI / production
uses Option B.

### Option A: Local development (ADC user creds)

```bash
gcloud auth application-default login
```

Browser opens, log in as `juanfranciscolago@gmail.com`. Credentials written
to `~/.config/gcloud/application_default_credentials.json`.

Verify:

```bash
gcloud auth application-default print-access-token   # should print token
gcloud secrets list --project=eolo-schwab-agent      # should list cs-app-key + others
```

If `gcloud secrets list` succeeds, the account has the `secretmanager.versions.access`
permission. Firestore access is also required — verify:

```bash
gcloud firestore databases list --project=eolo-schwab-agent
# should print: appEngineIntegrationMode, concurrencyMode, etc.
```

### Option B: CI / Production (Service Account JSON)

1. In GCP Console (`eolo-schwab-agent` project), create a Service Account
   with these roles:
   - `roles/secretmanager.secretAccessor` (read `cs-app-key`)
   - `roles/datastore.user` (read/write Firestore `schwab-tokens`)
2. Generate a JSON key, download to `$HOME/.config/gcloud/sa.json`.
3. Export:

   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/gcloud/sa.json"
   ```

4. Verify same as Option A.

---

## Section 2 — Firestore Tokens Bootstrap

The Schwab OAuth tokens live in Firestore at:
- Project: `eolo-schwab-agent`
- Collection: `schwab-tokens`
- Document: `schwab-tokens-auth`

This document is **shared with Eolo running bots**. The one-time OAuth
dance below populates it. After that, both Eolo and trading-workspace
refresh the tokens in place (see Section 4 for safety).

### One-time OAuth dance

If `schwab-tokens-auth` does not exist (fresh setup) or refresh_token has
expired (>7 days idle), run Eolo's bootstrap script:

```bash
cd /Users/JUAN/PycharmProjects/eolo
python3 safe_init_auth_v2.py
```

The script:
1. Prints a Schwab OAuth authorization URL.
2. Opens the URL in your browser (or copy-paste into browser).
3. Schwab login → consent → redirects to `https://127.0.0.1/?code=...`.
4. Copy the full redirect URL from the browser address bar.
5. Paste it back into the terminal.
6. Script exchanges the auth code for `{access_token, refresh_token, expires_in, ...}`.
7. Writes the dict to Firestore `schwab-tokens/schwab-tokens-auth`.

### Verify tokens written

```bash
cd /Users/JUAN/Documents/trading-workspace
python3 -c "
import sys
sys.path.insert(0, 'shared_core/src')
from shared_core.auth import retrieve_firestore_dict
tokens = retrieve_firestore_dict(
    collection_id='schwab-tokens',
    document_id='schwab-tokens-auth',
    project_id='eolo-schwab-agent',
)
print('Has access_token:', 'access_token' in (tokens or {}))
print('Has refresh_token:', 'refresh_token' in (tokens or {}))
print('expires_in:', (tokens or {}).get('expires_in'))
"
```

Expected: both `True`, `expires_in` around 1800 (~30 min).

### Token refresh lifecycle

- **access_token TTL**: ~30 minutes. SchwabClient refreshes automatically
  on 401 retry inside `get_price_history` / `get_options_chain`.
- **refresh_token TTL**: 7 days. If nothing refreshes for 7 days, the
  refresh_token expires → re-run `safe_init_auth_v2.py` to bootstrap.
- **Eolo's refresh cadence**: a Cloud Function named `refresh_tokens`
  runs ~every 25 min in production. So if Eolo is running, the tokens
  in Firestore stay fresh.

---

## Section 3 — Activating SchwabDataLayer

### Default behavior (StubDataLayer)

If `USE_SCHWAB_DATA_LAYER` is unset or `false`, the lifespan instantiates
`StubDataLayer()` and ATHENA receives synthetic data. Startup log:

```
✓ StubDataLayer active (synthetic data, default for Sprint 5)
```

### Enabling real Schwab data

```bash
export USE_SCHWAB_DATA_LAYER=true
# Ensure Section 1 GCP creds are set and Section 2 Firestore tokens exist.
cd /Users/JUAN/Documents/trading-workspace
uvicorn multi_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

On successful startup, log message:

```
✓ SchwabDataLayer active (real broker data, iv_rank=50.0 placeholder per ADR-004 D3)
```

### Fail-fast contract

If `USE_SCHWAB_DATA_LAYER=true` but GCP credentials are missing or the
Firestore tokens are not bootstrapped, the API **refuses to start**. The
logged exception includes the remedy:

```
USE_SCHWAB_DATA_LAYER=true but SchwabDataLayer construction failed.
Refusing to start. Set USE_SCHWAB_DATA_LAYER=false to fall back to
StubDataLayer, or fix the underlying GCP / Firestore configuration.
```

NO silent fallback to StubDataLayer (would mislead the operator into
thinking real data was active).

---

## Section 4 — ⚠️ Firestore Token Rotation Safety with Eolo

**Critical reading before activating Schwab data layer during market hours.**

### The race condition

- trading-workspace and Eolo share the same Firestore token document.
- Schwab **rotates BOTH `access_token` AND `refresh_token`** on each
  successful refresh.
- Each refresh **invalidates the prior `refresh_token`**.
- If trading-workspace triggers a refresh while Eolo is mid-cycle,
  Eolo's next refresh attempt will fail (it holds a now-invalid
  refresh_token).
- Eolo recovers via its scheduled `refresh_tokens` Cloud Function (~25
  min cadence), but the gap may cause missed Eolo trading cycles.

### Mitigation rules

- **DO NOT** start trading-workspace with `USE_SCHWAB_DATA_LAYER=true`
  during market hours while Eolo is actively trading (09:30–16:00 ET
  weekdays).
- **DO NOT** run the integration test (Section 5) during market hours.
- Run real-Schwab activations during **market closed periods only**:
  - Weekdays after 16:00 ET.
  - Weekends.
  - US market holidays.
- If concurrent operation is required in the future, implement token
  caching with TTL check before refresh (Sprint 6+ tech debt — see
  ADR-004 close-out).

### Recovery if Eolo breaks

If Eolo's bot stops trading because its refresh_token was invalidated:
1. Wait up to 25 min — Eolo's Cloud Function will re-read Firestore and
   refresh successfully on its next scheduled run.
2. If urgent: manually trigger Eolo's refresh:

   ```bash
   gcloud functions call refresh_tokens \
     --region=us-east1 \
     --project=eolo-schwab-agent
   ```

3. Verify Firestore has fresh tokens via Section 2 verify command.

---

## Section 5 — Integration Test (Real Schwab API)

A single end-to-end test exercises the full data fetch trio:
`from_gcp()` → `SchwabClient` → 6×`get_price_history` + 6×`get_options_chain`
→ `SchwabDataLayer.snapshot()` → `MarketState`. 12 Schwab API calls total.

### Default behavior

The test is **gated** and skips automatically in normal pytest runs:

```bash
cd /Users/JUAN/Documents/trading-workspace/multi-agent-system
pytest tests/data_layer/test_schwab_data_layer_integration.py -v
# → 1 skipped (gating: RUN_REAL_SCHWAB_TESTS env var not set)
```

### Manual invocation (market closed only)

```bash
RUN_REAL_SCHWAB_TESTS=1 pytest \
  tests/data_layer/test_schwab_data_layer_integration.py -v
```

The test asserts structural validity only (instance type, ticker set,
correlation pairs count, SPY sanity). NO assertions on specific IV / skew
values — Schwab data state-dependent, off-hours / holidays can return
empty chains.

Re-running is safe during market closed periods.

---

## Section 6 — Troubleshooting

### `SchwabAuthError: No tokens in Firestore schwab-tokens/schwab-tokens-auth`

- **Cause**: One-time OAuth dance not yet performed, OR refresh_token
  expired (>7 days idle) and someone deleted the document.
- **Remedy**: Run `safe_init_auth_v2.py` (Section 2).

### `google.api_core.exceptions.NotFound: Secret [cs-app-key] not found`

- **Cause**: Secret Manager secret missing in `eolo-schwab-agent`, OR
  the active SA / user lacks `secretmanager.versions.access`.
- **Remedy**:
  - Verify `gcloud secrets list --project=eolo-schwab-agent` includes
    `cs-app-key`.
  - If missing: re-create it in GCP Console (consult Eolo handoff doc
    for the JSON shape — `{"app-key": "...", "app-secret": "..."}`).
  - If permission issue: grant `roles/secretmanager.secretAccessor` to
    the SA / user.

### API refuses to start, log shows `logger.exception("USE_SCHWAB_DATA_LAYER=true but ...")`

- **Cause**: Flag is true but `SchwabClient.from_gcp()` or
  `SchwabDataLayer()` construction failed.
- **Remedy**: Read the logged traceback — the inner exception identifies
  the specific failure (GCP creds missing, Firestore doc absent, Secret
  Manager NotFound, etc.). Fix the root cause OR set
  `USE_SCHWAB_DATA_LAYER=false` to fall back to stub.

### `SchwabAPIError: Schwab /pricehistory returned 401` after retry

- **Cause**: refresh_token in Firestore is expired (>7 days since last
  successful refresh). First 401 triggered `_refresh_access_token`,
  but the refresh itself failed with another 401.
- **Remedy**: Re-run `safe_init_auth_v2.py` to bootstrap fresh tokens.

### Eolo bot stops trading after running trading-workspace with Schwab

- **Cause**: Concurrent token rotation invalidated Eolo's cached
  refresh_token (Section 4 race condition).
- **Remedy**: Wait ~25 min for Eolo's Cloud Function recovery, OR
  manually trigger `gcloud functions call refresh_tokens` (Section 4).
- **Prevention**: Section 4 mitigation rules.

### `SchwabDataLayer.snapshot()` raises `ValueError: No daily candles for SPY`

- **Cause**: Schwab returned empty candles array (rare — most common in
  pre-market or market data outage).
- **Remedy**: Retry after market open. If persistent, check Schwab API
  status. Fail-fast is intentional — ATHENA cannot operate on empty data.

---

## Section 7 — iv_rank Lifecycle (Sprint 6 iv-stage onwards)

`SchwabDataLayer.iv_rank` y `iv_percentile` use ADR-005 D5 progressive
disclosure semantics post-S.6.iv-d. Operator guidance below covers the
bootstrap timeline, threshold transitions, and monitoring.

### 7.1 Overview: forward accumulation + bootstrap timeline

iv_history populates **forward only** (ADR-005 D9 firm — NO backfill).
Each market day at **21:15 UTC**, `IvHistoryWorker` snapshots ATM IV for
all 6 TICKER_UNIVERSE tickers via `IvHistoryRepository.write_snapshot`.

**Timeline expectations** (Day 0 = process first launch with
`USE_SCHWAB_DATA_LAYER=true`):

- **Day 0**: iv_history empty. iv_rank returns 50.0 fallback (N=0 < 10).
- **Days 1-9**: bootstrap phase. iv_rank stays 50.0 (per D5 N<10 threshold).
- **Day 10**: first real percentile compute. WARNING log emitted (10≤N<30).
- **Day 30**: WARNING → INFO log transition (30≤N<252).
- **Day ~252** (~1 trading year): full percentile, DEBUG-silent steady state.

Bootstrap delay (~1 year) is **intentional** per D9 — accepted trade-off
for clean forward-accumulated history (no synthetic/imputed values).

### 7.2 D5 progressive disclosure 4 thresholds

| N range | iv_rank value | Log level | Confidence |
|---------|---------------|-----------|------------|
| N < 10 | 50.0 (fallback) | DEBUG silent | None (bootstrap) |
| 10 ≤ N < 30 | percentile (limited history) | **WARNING** | Low — operator-visible transition |
| 30 ≤ N < 252 | percentile (partial year) | INFO | Medium — useful signal |
| N ≥ 252 | percentile (full year) | DEBUG silent | High — steady state |

Per-call logic resides en `SchwabDataLayer._compute_iv_rank_progressive`
(see `multi-agent-system/src/multi_agent/data_layer/schwab_data_layer.py`).
Compute uses `shared_core.utils.indicators.iv_rank` canonical formula
(`(current - min) / (max - min) * 100`) when N ≥ 10.

D6 mirror: `iv_percentile = iv_rank` literal Phase 1 (same value, semantic
reserve).

### 7.3 Monitoring: log signals at startup + runtime

**Startup logs** (lifespan):

- `✓ SchwabDataLayer active (real broker data, iv_rank=real (ADR-005 D5))`
  when `iv_history_repo` wired correctly. If logs `iv_rank=50.0 fallback`
  instead, repo NOT wired (verify lifespan + `USE_SCHWAB_DATA_LAYER=true`).
- `✓ IvHistoryWorker active (snapshot 21:15 UTC daily)` confirms Worker
  scheduled. Missing → Worker NOT running, no daily writes.

**Runtime logs** (per-snapshot, per-ticker):

- `DEBUG iv_rank bootstrap (N<10), returning 50.0 placeholder` — bootstrap.
- `WARNING iv_rank computed on N=15 days only (target 252)` — transition out
  of bootstrap. **First WARNING en operator timeline → milestone Day 10**.
- `INFO iv_rank computed on N=100 days (target 252)` — partial-year operation.
- `DEBUG iv_rank computed on full N=300 days` — steady state, silent at INFO level.

Structured logging uses `extra={"ticker", "n_samples", "iv_rank"}` for
JSON handler consumption. Plain stdout shows the format string with
positional N substitution.

**Nightly worker run logs:**

- `INFO Starting IV snapshot run for ts=2026-05-15T21:15:00+00:00`
- `INFO IV snapshot run completed: 6/6 tickers ok` (success).
- `WARNING IV snapshot run completed: 5/6 tickers succeeded` (per-ticker
  isolation D-γ — 1 ticker failed, worker proceeds).
- `ERROR IV snapshot run completed: 0/6 tickers succeeded` (worker degraded
  — Schwab API down or auth lapsed; investigate).

Watch for: missing 21:15 UTC nightly log → IvHistoryWorker not running (check `app.state.iv_worker`).

### 7.4 Troubleshooting: iv_rank stuck at 50.0

If iv_rank returns 50.0 consistently across multiple snapshots:

1. **Bootstrap phase (expected)**: First ~10 days operation. Verify via `count_for_ticker` SQL query below.
2. **IvHistoryWorker not running**: Check lifespan logs at startup for "✓ IvHistoryWorker active". If missing, verify `USE_SCHWAB_DATA_LAYER=true` + `isinstance(app.state.data_layer, SchwabDataLayer)`.
3. **Schwab API failure during snapshot**: Check log for per-ticker WARNING lines ("Snapshot failed for ticker=X, skipping"). Per-ticker error isolation D-γ preserva worker stability pero pierde 1 datapoint.
4. **Holiday/weekend skip (expected)**: Worker skips Saturday/Sunday + empty chain responses (holiday detection D10).
5. **No `iv_history_repo` wired**: SchwabDataLayer constructed con `iv_history_repo=None` (test path or misconfiguration). Verify lifespan wire-up.

### 7.5 SQL monitoring queries

Verificar iv_history population status:

```sql
-- Count datapoints per ticker
SELECT ticker, COUNT(*) AS n_samples, MIN(ts) AS oldest, MAX(ts) AS newest
FROM market.iv_history
GROUP BY ticker
ORDER BY ticker;

-- Verify last 7 days writes
SELECT ts::date AS day, COUNT(DISTINCT ticker) AS tickers_snapshotted
FROM market.iv_history
WHERE ts > NOW() - INTERVAL '7 days'
GROUP BY ts::date
ORDER BY day DESC;

-- Check current iv values for steady-state tickers
SELECT DISTINCT ON (ticker) ticker, atm_iv, ts
FROM market.iv_history
ORDER BY ticker, ts DESC;
```

Hypertable inspection (TimescaleDB):

```sql
SELECT * FROM timescaledb_information.hypertables WHERE hypertable_name = 'iv_history';
SELECT * FROM timescaledb_information.chunks WHERE hypertable_name = 'iv_history' ORDER BY range_start DESC LIMIT 5;
```

---

## Section 8 — iv_surface Lifecycle (Sprint 7 surface-stage onwards)

`market.iv_surface` accumulates per-contract IV + greeks + liquidity per
snapshot, written alongside `iv_history` ATM scalar by `IvHistoryWorker`
extension (S.7.surf-c). WRITE-only Sprint 7 per ADR-006 D6 — no consumer
surface (TickerSnapshot extension) until Phase 2.

### 8.1 Overview: per-snapshot accumulation + volume estimate

Per ADR-006 D2 (full chain) + D4 (1-day chunks) + D9 (forward only):

- **Snapshot trigger**: same 21:15 UTC daily como iv_history (D3 Worker extension).
- **Volume per snapshot**: ~800-960 contracts/ticker × 6 tickers = ~5,400 rows/day.
- **Volume per year**: ~1.5-1.8M rows. Within TimescaleDB capacity easily.
- **Storage chunks**: 1-day chunks per V007 (high-volume vs iv_history 1-month).
- **Bootstrap timeline**: forward accumulation per D9 — NO backfill. Day 0
  iv_surface empty. Day N has N days × ~5,400 rows accumulated.

Schwab chain `strike_count=20` default = ~40 strikes × ~10-12 expirations
× 2 (call+put) per ticker. Real volume depends on liquid expirations per
ticker (SPY denser than NVDA).

### 8.2 D3-1 isolation contract

iv_history (canonical, production-critical) + iv_surface (accumulating-for-future)
write order per `IvHistoryWorker._snapshot_one_ticker`:

1. `IvHistoryRepository.write_snapshot` — ALWAYS first (Sprint 6 canonical).
2. `IvSurfaceRepository.write_chain_snapshot` — INSIDE try/except.
3. Surface failure → WARNING log + continue (NOT raised).
4. iv_history success NOT blocked by surface exceptions.

Operator implications:

- WARNING logs `"iv_surface write failed for X"` are **NOT critical** —
  iv_rank compute (iv_history-based) unaffected.
- ERROR-level alerts NOT triggered for surface failures.
- ER pager / oncall NOT engaged for D3-1 isolation events.
- Surface accumulating-for-future — missing N rows for 1 ticker on 1 day
  is acceptable.

If surface failure rate exceeds 10% across N days OR specific ticker
fails consistently → investigate (likely Schwab chain shape drift or
V007 schema mismatch).

### 8.3 Monitoring: log signals at startup + runtime

**Startup logs (lifespan):**

- `✓ IvHistoryWorker active (snapshot 21:15 UTC daily)` — iv_history confirmed.
- `✓ iv_surface populating enabled (per snapshot, D3-1 isolated)` — surface
  populating confirmed. Missing → `iv_surface_repo` NOT wired (verify
  lifespan + `USE_SCHWAB_DATA_LAYER=true`).

**Runtime logs (per snapshot, per ticker):**

- `DEBUG iv_surface wrote N rows for TICKER` — success (D-γ refinement
  S.7.surf-c). Operational signal: N typically 800-960 per ticker.
- `WARNING iv_surface write failed for TICKER, iv_history succeeded
  (D3-1 isolation)` — surface failure isolated. Includes `exc_info=True`
  stack trace for diagnostic.

**Operator alert filtering**: grep `"D3-1 isolation"` to filter
operationally-tolerable surface failures from critical errors.

**Per-snapshot run aggregates** (same as Sprint 6 iv_history Worker
logging): `INFO Starting IV snapshot run for ts=...` + `INFO IV snapshot
run completed: N/6 tickers ok`.

### 8.4 Troubleshooting: iv_surface NOT populating

1. **`iv_surface_repo` None (expected `USE_SCHWAB_DATA_LAYER=False`)**: lifespan
   construct conditional. No surface writes if flag False.
2. **Surface write D3-1 isolation triggered repeatedly**: investigate
   WARNING logs. Common causes:
   - Schwab chain shape drift (column missing in contract dict).
   - V007 schema mismatch (column type, NULL constraint).
   - DB connection pool exhaustion (separate from iv_history pool).
3. **executemany failure for entire ticker**: per-ticker isolation D-γ at
   Worker level catches before D3-1 isolation. Worker continues other tickers.
4. **iv NOT NULL violation skipping rows**: F7 guard `if not iv:` skips
   contracts where iv falsy (None or 0). Expected; check Schwab returning
   valid IV per contract.

### 8.5 SQL monitoring queries

Verificar iv_surface population:

```sql
-- Row count per ticker per day (last 7 days)
SELECT underlying, ts::date AS day, COUNT(*) AS contracts
FROM market.iv_surface
WHERE ts > NOW() - INTERVAL '7 days'
GROUP BY underlying, ts::date
ORDER BY day DESC, underlying;

-- Total rows + hypertable size (TimescaleDB public API)
SELECT
    'iv_surface' AS table_name,
    pg_size_pretty(hypertable_size('market.iv_surface')) AS total_size,
    (SELECT COUNT(*) FROM market.iv_surface) AS total_rows;

-- Term structure snapshot for single ticker (today's surface)
SELECT expiration, strike, option_type, iv, delta, volume
FROM market.iv_surface
WHERE underlying = 'SPY'
  AND ts = (SELECT MAX(ts) FROM market.iv_surface WHERE underlying = 'SPY')
ORDER BY expiration, strike, option_type;

-- D5 retention trigger monitoring (ADR-006 §4)
-- Trigger A: hypertable_size > 5 GB → activate compression chunks > 90 days
-- Trigger B: monitor query p99 latency separately
SELECT
    pg_size_pretty(hypertable_size('market.iv_surface')) AS current_size,
    (SELECT COUNT(*) FROM timescaledb_information.chunks
     WHERE hypertable_name = 'iv_surface') AS chunk_count;
```

---

## Section 9 — Phase 2 Consumer Surface Reads (Sprint 10 onwards)

Phase 2 consumer surface UNIFIED (ADR-009, S.10.cons-X) extends ATHENA's
MarketState with term_structure + surface + ohlcv_intraday fields. SchwabDataLayer
reads from IvSurfaceRepository + OhlcvRepository per snapshot, assembles
extended TickerSnapshot, ATHENA prompt interprets fields per D5 semantics.

### 9.1 Overview: producer/consumer pair completion

Sprint 7 iv_surface WRITE (S.7.surf-c) + Sprint 9 market.ohlcv WRITE (S.9.ohl-b)
created accumulation foundation. Sprint 10 (this) completes producer/consumer
pair adding READ-side wiring + ATHENA prompt semantics.

Per ADR-009 D4 + sub-decisions D4-1/D4-2/D4-3:

- **Reads per snapshot**: ~30 reads/snapshot (6 tickers × (1 surface + 4 timeframes)
  + 12 existing API calls = 18 DB reads + 12 Schwab API).
- **D4-1 delta bucketing**: ATM |delta| ∈ [45, 55], put_25d |delta| ∈ [20, 30] PUT,
  call_25d delta ∈ [20, 30] CALL. Avg IV per bucket.
- **D4-2 timeframe lookbacks**: TIMEFRAME_LOOKBACK_BARS = {5m: 78, 15m: 96,
  30m: 48, 1d: 30}.
- **D4-3 D-γ isolation**: per-cell errors logged WARNING + skip (mirror S.7.surf-c).

### 9.2 Repository wiring + lifespan

Lifespan (`app.py`) constructs OhlcvRepository early (line ~180) alongside
IvHistoryRepository + IvSurfaceRepository. Shared instances passed to:
- SchwabDataLayer constructor (iv_surface_repo + ohlcv_repo per Sprint 10).
- IvHistoryWorker (S.7.surf-c, iv_surface_repo Phase 1 write-only).
- OhlcvWorker (S.9.ohl-b, ohlcv_repo write).

Repository sharing eliminates doble construcción tech debt (ADR-005 §9.3 #1
partial — Schwab client still doble per worker).

### 9.3 TickerSnapshot Phase 2 fields

3 new fields per ADR-009 D2-1/D2-2/D2-3 (mirror iv_rank D5 progressive disclosure):

```python
@dataclass(frozen=True)
class TickerSnapshot:
    # ... existing 8 fields ...
    term_structure: list[tuple[int, float]] = field(default_factory=list)
    surface: dict[int, list[float]] = field(default_factory=dict)
    ohlcv_intraday: dict[str, list[OHLCV]] = field(default_factory=dict)
```

- `term_structure`: list[(DTE, atm_iv_proxy)] ordered front-to-back.
- `surface`: dict[DTE → [atm_iv, put_25d_iv, call_25d_iv]] per expiration.
- `ohlcv_intraday`: dict["5m"/"15m"/"30m"/"1d" → list[OHLCV]].

Backward compat (D7): existing TickerSnapshot constructors unchanged (defaults
factory). 6 existing test files referencing TickerSnapshot pass sin migration.

### 9.4 ATHENA prompt budget

SYSTEM_PROMPT grew Sprint 10: 3955 → 5228 chars (+32.5% single sub-block).
Budget guard: 5300 chars (F-r6/F-r6.5 catches Sprint 10 S.10.cons-e).

Token cost: +319 tokens vs original. ATHENA user_prompt JSON 10-30k tokens
dominates cost (SYSTEM_PROMPT delta = noise). Sprint 11+ telemetry inform
compression decisions.

### 9.5 Monitoring: SchwabDataLayer Phase 2 logs

**Runtime logs (per snapshot, per ticker, on errors):**

- `WARNING SchwabDataLayer Phase 2: no iv_surface data for TICKER (D4-3 isolation)` —
  bootstrap phase, surface NOT populated yet.
- `WARNING SchwabDataLayer Phase 2: iv_surface read failed for TICKER (D4-3 isolation),
  continuing` — DB error isolated, ATHENA continues con empty defaults.
- `WARNING SchwabDataLayer Phase 2: ohlcv read failed for TICKER TIMEFRAME
  (D4-3 isolation), continuing` — per-timeframe error isolated.

**Operator alert filtering**: grep `"D4-3 isolation"` to filter Phase 2 read
failures from critical errors.

### 9.6 SQL monitoring queries

Verificar Phase 2 reads health:

```sql
-- Latest surface per ticker (D3 get_latest_surface canonical query)
SELECT underlying, MAX(ts) AS latest_surface_ts
FROM market.iv_surface
GROUP BY underlying;

-- Surface row count per ticker latest snapshot (D3 get_surface_for_ticker)
SELECT underlying, COUNT(*) AS contracts
FROM market.iv_surface
WHERE ts = (SELECT MAX(ts) FROM market.iv_surface WHERE underlying = 'SPY')
  AND underlying = 'SPY';

-- ohlcv_intraday lookback verification (D4-2 TIMEFRAME_LOOKBACK_BARS)
SELECT ticker, timeframe, COUNT(*) AS bars,
       MIN(ts) AS oldest, MAX(ts) AS newest
FROM market.ohlcv
WHERE ticker = 'SPY'
GROUP BY ticker, timeframe
ORDER BY timeframe;
```

---

## Section 10 — ATLAS Portfolio Integration (Sprint 11 onwards)

ADR-013 Aceptado (2026-05-26). Live broker portfolio reads via SchwabClient
for ATLAS validation. Mirror Phase 2 Consumer Surface §9 documentation
pattern.

### 10.1 Overview

ATLAS validates trading proposals against real-time portfolio state. Two
modes operational:

- **Synthetic** (default, `USE_LIVE_PORTFOLIO=False`): DB-backed
  SnapshotBuilder reads from `portfolio.snapshots` + `portfolio.positions`
  tables. Existing behavior since Sprint 6. CachedSnapshotBuilder TTL 5s.
- **Live** (`USE_LIVE_PORTFOLIO=True`): LiveSnapshotBuilder reads via
  SchwabClient.get_positions() + get_balances(). Real broker portfolio state.
  CachedSnapshotBuilder TTL 30s.

### 10.2 USE_LIVE_PORTFOLIO Settings flag (D10)

- **Default**: `False` (synthetic DB-backed mode).
- **Production**: `True` post pre-deploy Schwab subaccount setup (§10.3 below).
- **Independence**: NOT coupled with `USE_SCHWAB_DATA_LAYER`. ATHENA market
  data reads (Sprint 5+) vs ATLAS portfolio reads (Sprint 11+) flag separately.

### 10.3 SCHWAB_ACCOUNT_ID subaccount isolation (D9 + D9-1)

**Pre-deploy operator action REQUIRED before setting USE_LIVE_PORTFOLIO=True**:

1. **Schwab portal**: Verify subaccounts. Create new paper subaccount distinct
   from Eolo bots'. Note `accountNumber`.
2. **Set env var**: `SCHWAB_ACCOUNT_ID="123456789"` (your new multi-agent
   subaccount).
3. **Validate**: Same API key authentication; isolation via accountNumber.

**Why subaccount isolation**: Multi-agent + Eolo share same Schwab parent
account + same API key. Distinct `accountNumber` per subaccount → naturally
isolated. ATLAS reads exclusively multi-agent positions, no Eolo conflation.

**Fail-fast contract (D-ν STRENGTHENED + D-ο)**: If `USE_LIVE_PORTFOLIO=True`
+ `SCHWAB_ACCOUNT_ID=""` → app refuses to start (ValueError). Silent
auto-discovery would use Eolo's first account = wrong positions = silent
bug. Better fail loudly at startup.

### 10.4 LiveSnapshotBuilder + CachedSnapshotBuilder (D6 + D7)

`_build_snapshot_builder(settings, pool)` helper en `multi_agent/api/app.py`:
- USE_LIVE_PORTFOLIO=True path: `CachedSnapshotBuilder(LiveSnapshotBuilder(SchwabClient.from_gcp(account_id=...)), ttl_seconds=30.0)`.
- USE_LIVE_PORTFOLIO=False path: `CachedSnapshotBuilder(SnapshotBuilder(pool), ttl_seconds=5.0)`.

ATLAS engine consumption: `validate(proposal, decision, snapshot, limits, buckets)`
contract preserved. Same PortfolioSnapshot type, agnostic to source.

### 10.5 Phase 1 simplifications (sub-decisions D-η a D-λ)

5 Phase 1 simplifications cementadas (tech debt Sprint 12+):
- **Greeks default Decimal(0)** (D-η): Schwab positions no returns greeks.
  Tech debt #1: cross-source iv_surface or options chain on-demand.
- **PnL weekly/monthly/drawdown default 0.0** (D-θ): historical snapshots
  table not yet populated. Tech debt #2.
- **ticker = symbol raw (no OCC parser)** (D-ι-A): OPTION positions use full
  OCC string Phase 1. ATLAS validates per asset_class. Tech debt #3.
- **portfolio_beta default 0.0** (D-κ): no benchmark source Phase 1. Tech
  debt #4.
- **pnl_daily_usd = sum positions[].unrealized_pnl** (D-λ): Schwab
  currentDayProfitLoss per position aggregate. Approximate but better than 0.

### 10.6 Monitoring + operator workflow

**Startup logs** (info level):
- `ATLAS LiveSnapshotBuilder active (account_id=<id>, TTL=30s)` → confirm
  live mode + account_id correct.
- Error logs: `USE_LIVE_PORTFOLIO=True but LiveSnapshotBuilder construction
  failed` → GCP credentials or Schwab API issue.

**Validation procedure post-deploy**:
1. Verify lifespan startup log shows LiveSnapshotBuilder active.
2. Check ATLAS validation request: `snapshot_id` should change every ~30s
   (CachedSnapshotBuilder TTL).
3. Cross-verify positions count vs Schwab portal UI.
4. Monitor `_ttl` cache hit ratio (Sprint 12+ telemetry).

---

## Section 11 — Future Work / Tech debt

Items canonical numbered. Cross-reference sources:
- ADR-005 §9.3 IDs #1-#11 (Sprint 6 tech debt, inherited).
- ADR-006 §9.3 IDs (Sprint 7 tech debt, new).

### ADR-005 §9.3 inherited items (Sprint 6+)

- **#1 SchwabClient doble construcción** — Sprint 7+ refactor candidate.
  Lifespan + worker each call `SchwabClient.from_gcp()` independently.
- **#2 `market.iv_surface` populating** — **✓ RESOLVED Sprint 7** (commits
  `de82465` ADR-006 plan + `84ab8c3` Repository + `7ac1ee5` Worker extension).
  See ADR-006 §9.1 sub-blocks delivered.
- **#3 `market.ohlcv` populating** — **ADR-007 candidate** HERMES prerequisite.
- **#4 `_persisted_at` field**: cleaner Schwab Firestore token expiry tracking.
- **#5 Date-aware correlations alignment**: required if VIX or cross-exchange
  tickers added to universe.
- **#6 `SchwabClient.from_env()` removal**: zero callers confirmed S.5.6g
  recolección, deprecated path safe to remove.
- **#7 ATHENA prompt caveat** — **✓ RESOLVED en S.6.iv-e** (commit `d22f573`).
  Caveat NOT removed, UPDATED accurate D5 progressive disclosure semantics.
- **#8 Token caching con TTL check**: Sprint 7+ concurrent Eolo coexistence
  improvement.
- **#9 `TOKEN_SCHWAB` Secret Manager cleanup**: dead `"TU_TOKEN_AQUI"`
  placeholder, unused desde S.5.6b.
- **#10 `SkewSnapshot` field naming `put_25d_iv`/`call_25d_iv`**: breaking
  change Sprint 7+ (serialized state migration required).
- **#11 Historical IV backfill**: D9 firm "NEVER" Phase 1; Sprint 8+ open
  question, paid CBOE feed evaluation if priorities shift.

### ADR-006 §9.3 NEW items (Sprint 7)

1. **F7 iv=0.0 vs iv=None disambiguation** — `IvSurfaceRepository` skips both
   via `if not iv:`. Future Sprint may distinguish missing data vs legit
   zero IV (deep OTM theoretical).
2. **executemany pattern canonical convention** — NEW Sprint 7 pattern.
   Document Sprint 8+ as canonical for high-volume Repository INSERTs.
3. **D-α-3 MagicMock plain (no spec=IvSurfaceRepository)** — Tests use
   plain MagicMock. API drift not auto-caught. Trade-off accepted.
4. **Test 5 positional args check vs kwargs** — Intentional drift catch
   via `call_args[0]` positional verification.
5. **D6-1 ATHENA prompt drift** — Prompt mentions term structure/vol
   surface but TickerSnapshot NOT exposes. Phase 2 reconciliation.

**Previously listed (S.5.6g) — now resolved:**

- **`iv_history` table + nightly snapshots** — **✓ RESOLVED Sprint 6 iv-stage**
  (commits `462d1bf` V018+Repository, `4372033` Worker+lifespan, `82cbe10`
  SchwabDataLayer real compute). See ADR-005 §9.1 sub-blocks delivered.
- **Hourly OHLCV resample** — deferred to HERMES Sprint 7+ per tech debt #3
  (ohlcv populating via ADR-007 candidate).

---

## References

- **ADR-004** (`docs/decisions/004-sprint-5-schwab-integration.md`):
  Sprint 5 plan — Schwab integration. Contains D1–D5 decisions and
  S.5.6g close-out tech debt registry.
- **ADR-003** (`docs/decisions/003-sprint-4-consensus-and-validation.md`):
  Sprint 4 plan. Data layer commitments in §5.
- **Eolo handoff** (`/Users/JUAN/PycharmProjects/eolo/EOLO_HANDOFF.md`):
  battle-tested OAuth patterns referenced during S.5.6b port.
- **`shared_core.brokers.schwab_client`**: `from_gcp()` classmethod is
  the canonical construction path. `from_env()` retained for backward
  compat only.
- **`multi_agent.data_layer.schwab_data_layer`**: `SchwabDataLayer`
  wraps the client + maps to `MarketState`.
- **`CLAUDE.md`** rule #5: Eolo intocable — read-only reference, no
  modifications during port work.
