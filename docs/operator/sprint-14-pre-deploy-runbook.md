# Sprint 14 Pre-Deploy Runbook — Bundle B1 Operator Actions

**Fecha:** 2026-05-28 (jueves)
**Sprint:** Sprint 14 Bundle B1 (#12 Operator unblock + #11 SchwabClient F-r16)
**Sub-block:** S.14.operator-a — Day 1 pre-deploy 5 actions + fail-fast contract D-ν validation
**Companion docs:** `docs/operator/schwab-setup.md` §10.3 (canonical pre-deploy) + §11 (telemetry observation) + `docs/decisions/sprint-12-telemetry-c-deferred.md` §4 (re-activation criteria) + `docs/decisions/sprint-14-priority-analysis.md` (Bundle B1 strategic rationale).

---

## 1. Context

Sprint 14 Bundle B1 LOCKED (commit `5536940`, S.14.plan-a) per fresh re-score rule #15. #12 Operator unblock sprint = único path Track A telemetry-c re-activation progress (gate 4 conditions ALL unmet jueves 28 sostenido). #11 SchwabClient F-r16 cross-cutting = synergistic Q5/R6 telemetry quality post-unblock.

**Track A telemetry-c re-activation gate state jueves 28** (per S.12.telemetry-c-deferred §4):
- ⏳ Condition 1: Operator pre-deploy 5 actions (this runbook).
- ⏳ Condition 2: USE_LIVE_PORTFOLIO=True + USE_SCHWAB_DATA_LAYER=True deployed.
- ⏳ Condition 3: 2+ weeks runs accumulating (calendar time post-deploy).
- ⏳ Condition 4: First telemetry events captured (3 types per §5 abajo).

Esta runbook ejecuta Condition 1 + Condition 2. Condition 3 = calendar time (2+ weeks post-deploy). Condition 4 = post-trigger ATHENA cycles + Schwab API calls.

## 2. Pre-deploy 5 actions ordered checklist

**REQUIRED orden secuencial**. NO skip steps.

### Action 1: Schwab portal — create paper subaccount

**Manual operator (Claude Code NO ejecuta)**:
1. Login Schwab portal (operator credentials).
2. Verificar subaccounts existentes Eolo bots (NOT modificar — preservar).
3. **Create NEW paper subaccount** distinct de Eolo bots:
   - Name suggestion: `multi-agent-paper` o `eolo-multiagent-paper`.
   - Type: paper trading (NOT live capital).
   - Owner: same parent account (operator).

### Action 2: Note accountNumber

**Manual operator**:
1. Open NEW subaccount details.
2. Copy `accountNumber` (numerical string, formato típico `123456789`).
3. **NO commit accountNumber a git** — sensitive identifier.

### Action 3: Edit `.env` — add SCHWAB_ACCOUNT_ID

**Manual operator** (Claude Code NO modifica `.env` secrets):
1. Open `trading-workspace/.env` (workspace root, single source para Eolo + multi-agent).
2. Add line (después de Schwab API section):
   ```
   SCHWAB_ACCOUNT_ID="<accountNumber del Action 2>"
   ```
3. Save + verify NO commit a git (`.env` already in `.gitignore`).

### Action 4: Edit `.env` — add USE_LIVE_PORTFOLIO=True

**Manual operator**:
1. Open `.env`.
2. Add line (después de SCHWAB_ACCOUNT_ID):
   ```
   USE_LIVE_PORTFOLIO=True
   ```
3. Save.

### Action 5: Edit `.env` — add USE_SCHWAB_DATA_LAYER=True

**Manual operator**:
1. Open `.env`.
2. Add line (después de USE_LIVE_PORTFOLIO):
   ```
   USE_SCHWAB_DATA_LAYER=True
   ```
3. Save.

**Template reference**: `trading-workspace/.env.example` actualizado Sprint 14 operator-a contiene 3 NEW flags Multi-agent ATLAS section. Copy values, replace defaults con real subaccount + True.

## 3. Fail-fast contract D-ν validation procedure

**Code path canónico** (existing implementation Sprint 11 atlas-e commit `bfc297f`):

**Location**: `multi-agent-system/src/multi_agent/api/app.py:_build_snapshot_builder()` (NOT Pydantic model_validator config.py).

**Contract verbatim**:
```python
if settings_obj.USE_LIVE_PORTFOLIO:
    if not settings_obj.SCHWAB_ACCOUNT_ID:
        raise ValueError(
            "USE_LIVE_PORTFOLIO=True requires SCHWAB_ACCOUNT_ID explicit "
            "(ADR-013 D9 subaccount isolation). Auto-discovery would "
            "silently use Eolo's subaccount, causing position conflation. ..."
        )
```

**NEGATIVE test (intentional fail-fast verify)**:
1. Temporalmente comentar SCHWAB_ACCOUNT_ID en `.env` (preserve USE_LIVE_PORTFOLIO=True).
2. Start FastAPI: `cd multi-agent-system && uvicorn multi_agent.api.app:app` (sin --reload, freshness verify).
3. **Expected**: app refuses to start con `ValueError: USE_LIVE_PORTFOLIO=True requires SCHWAB_ACCOUNT_ID explicit ...`.
4. Stop app. Restore SCHWAB_ACCOUNT_ID en `.env`.

**POSITIVE test (normal startup verify)**:
1. `.env` correcto post-Actions 1-5 (USE_LIVE_PORTFOLIO=True + SCHWAB_ACCOUNT_ID=numerical + USE_SCHWAB_DATA_LAYER=True).
2. Start FastAPI: `cd multi-agent-system && uvicorn multi_agent.api.app:app`.
3. **Expected**: app starts successfully + lifespan logs ATLAS LiveSnapshotBuilder active.

## 4. First boot validation checklist

Post Action 5 + FastAPI startup, verify lifespan logs en orden:

- [ ] `✓ DB pool ready (min=2 max=10)` (postgres connection).
- [ ] `✓ AgentMessageBus ready (REDIS_URL=...)` (redis connection).
- [ ] `ATLAS LiveSnapshotBuilder active (account_id=<accountNumber>, TTL=30s)` ← **KEY**: confirma live mode + account_id correct.
- [ ] `✓ Worker chain started: Apollo + Consensus + Atlas consumers`.
- [ ] `✓ AlertWorker + RetryWorker started`.
- [ ] `✓ IvHistoryWorker active (snapshot 21:15 UTC daily)`.
- [ ] `✓ OhlcvWorker active (snapshot 21:30 UTC daily, 4 timeframes)`.

**Si NO ve `ATLAS LiveSnapshotBuilder active`** → fail-fast contract triggered OR config error. Re-verify Actions 3-5 + restart.

**Regression check**: tests baseline `cd multi-agent-system && pytest tests/ --tb=line -q` debe seguir mostrando `895 passed + 4 failed (pre-existing telegram env) + 55 skipped`.

## 5. First telemetry events expected (Sprint 12 telemetry-b instrumentation active)

Per `S.12.telemetry-c-deferred §4 condition 4` — 3 event types capturables post-deploy:

### 5.1 `rate_limiter_throttled` (Q5 + R6 source)
**Source**: `shared_core/brokers/schwab_client.py:RateLimiter.wait_if_needed()`.
**Trigger**: cuando rate limiter sleep_time > 0 (5+ req/sec sustained).
**Expected first capture**: post-deploy first OhlcvWorker daily run (21:30 UTC) + IvHistoryWorker (21:15 UTC) — multi-ticker fan-out → likely 1+ throttle events.

### 5.2 `schwab_429_throttled` (R6 source, OPTIONAL)
**Source**: 3 ATLAS endpoints (`get_positions`, `get_balances`, `get_options_chain`) cuando Schwab API responde 429.
**Trigger**: rate limit exceeded SchwabAPIError 429 status.
**Expected first capture**: OPCIONAL — si rate_limiter prevents successfully, 429 NO fires. NO mandatory para condition 4.

### 5.3 `athena_prompt_metrics` (Q7 + F-r6.5 source)
**Source**: `multi-agent-system/src/multi_agent/agents/athena_agent.py:generate_proposal()`.
**Trigger**: cada llamada a `AthenaAgent.generate_proposal()`.
**Expected first capture**: 🚨 **F-r ant #5 IMPORTANTE**: ATHENA generate_proposal NO scheduled (on-demand via API routes). Capture requires explicit ATHENA cycle trigger Sprint 15+ (POST /api/v1/agents/athena/propose o equivalente). Sin trigger, este event type NO fires.

**Implicación re-activation gate**: Conditions 1 + 2 ejecutables Sprint 14 operator-a. Conditions 3 + 4 require Sprint 15+ trigger + calendar time accumulation.

## 6. Daily log entry template (post completion)

**File**: `docs/DAILY_LOG_2026-05-XX.md` (operator pattern §11.4).

Template suggested:

```markdown
## Operator pre-deploy completion (Sprint 14 operator-a)

**Fecha:** 2026-05-XX
**Sub-block:** S.14.operator-a Day 1 completion

### Actions ejecutadas
- [x] Action 1: Schwab portal paper subaccount created (name: `<name>`).
- [x] Action 2: accountNumber noted (NO committed git).
- [x] Action 3: SCHWAB_ACCOUNT_ID en .env (verified).
- [x] Action 4: USE_LIVE_PORTFOLIO=True en .env (verified).
- [x] Action 5: USE_SCHWAB_DATA_LAYER=True en .env (verified).

### Fail-fast contract D-ν validation
- [x] NEGATIVE test: app refuses start sin SCHWAB_ACCOUNT_ID (ValueError verified).
- [x] POSITIVE test: app starts successful con .env completo.

### First boot logs verified
- [x] ATLAS LiveSnapshotBuilder active (account_id=<masked>, TTL=30s).
- [x] 4 Workers started (Alert + Retry + IvHistory + Ohlcv).

### Track A re-activation criteria progress
- [x] Condition 1: Pre-deploy 5 actions completed.
- [x] Condition 2: Flags ON deployed.
- [ ] Condition 3: 2+ weeks runs accumulating (calendar time pending).
- [ ] Condition 4: First telemetry events captured (Sprint 15+ trigger required).
```

## 7. Re-activation criteria checkbox + sign-off

**Post-completion operator sign-off** (per S.12.telemetry-c-deferred §4 4 conditions):

- [ ] **Condition 1**: Operator pre-deploy 5 actions completed.
- [ ] **Condition 2**: USE_LIVE_PORTFOLIO=True + USE_SCHWAB_DATA_LAYER=True deployed production.
- [ ] **Condition 3**: 2+ weeks calendar time accumulating production runs (Sprint 14+ post-deploy).
- [ ] **Condition 4**: First telemetry events captured (rate_limiter_throttled + athena_prompt_metrics minimum; schwab_429_throttled optional).

**Sign-off**: ___________________ **Fecha**: ___________________

Conditions 1+2 → S.14.operator-a completion.
Conditions 3+4 → S.14.operator-b (Day 2+ observation) o Sprint 15+ continuation.

Cuando ALL 4 conditions met → telemetry-c real close-out memo execution viable per S.12.plan-a §7 mandate.
