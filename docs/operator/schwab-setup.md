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

## Section 7 — Future Work (Sprint 6+)

Registered tech debt from S.5.6 commits for Sprint 6+ resolution:

- **`iv_history` table + nightly snapshots** → real `iv_rank` percentile
  vs trailing 252 days. ADR-005 separate decision.
- **`_persisted_at` field** in Firestore writes → cleaner token expiry
  tracking (currently `token_expires_at=None` initial state in `from_gcp`,
  relies on 401 retry path).
- **Hourly OHLCV resample** (HERMES Sprint 6+) → currently
  `ohlcv_hourly=[]` empty in `SchwabDataLayer`.
- **Date-aware correlations alignment** → currently naive (same-index
  log returns). Required if Sprint 6+ adds VIX or cross-exchange tickers.
- **`SchwabClient.from_env()` removal** → confirmed zero callers; safe to
  remove pending caller audit (S.5.6f Show 1).
- **ATHENA prompt caveat block removal** → when `iv_history` lands and
  `iv_rank` becomes real (Sprint 6+).
- **Token caching with TTL check** → enable concurrent operation with
  Eolo without race condition (currently mitigated by mutual exclusion
  during market hours, see Section 4).
- **`TOKEN_SCHWAB` Secret Manager cleanup** → placeholder dead value
  (`"TU_TOKEN_AQUI"`), unused. Cleanup when GCP Console reviewed.

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
