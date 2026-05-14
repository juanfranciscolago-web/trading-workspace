# ADR-005: iv_history table and iv_rank percentile compute

**Fecha:** 2026-05-14
**Estado:** Propuesto
**Contexto:** Sprint 5 cerrado (commit `c46c463`) con `iv_rank=50.0` placeholder (ADR-004 D3 + §9.3 tech debt #1). Sprint 6+ debe entregar real percentile. Esta ADR define la table architecture + nightly snapshot job + compute path.

---

## 1. Context

### 1.1 Lo que Sprint 5 difirió

Per ADR-004:
- **D3**: `iv_rank=50.0 placeholder` durante Sprint 5. Real computation diferida con ADR-005.
- **§5 Out of scope**: "`iv_history` table + nightly snapshot + iv_rank percentile real. ADR-005 separado."
- **§9.3 tech debt #1**: ADR-005 promised — table + nightly job + percentile compute.

Estado actual del código:
- `TickerSnapshot.iv_rank: float` y `iv_percentile: float` en `interfaces.py:65-66`.
- `SchwabDataLayer.__init__(..., iv_rank_default=50.0, iv_percentile_default=50.0)` hardcodea defaults.
- ATHENA prompt tiene caveat block (S.5.6f) documentando placeholder.
- Tests assert `iv_rank == 50.0` / `iv_percentile == 50.0` en SchwabDataLayer tests.

### 1.2 Reality check (rule #15 findings pre-ADR)

10 findings A-J durante recolección:

- **A**: ADRs siguen convention `###-topic.md`. Este ADR es `005-iv-history-and-iv-rank-compute.md`.
- **B**: `iv_rank` y `iv_percentile` son **dos conceptos diferentes** según docstring (rank vs trailing 252d, percentile vs absolute scale). Stub los conflate.
- **C**: TimescaleDB precedent fuerte — 17 migrations V001-V017, 4+ hypertables, schema `market.*` namespace. Próxima migration: **V018**.
- **D**: `market.ohlcv` hypertable existe (V007) pero **unwritten**. Out of scope ADR-005.
- **E**: Eolo `_compute_iv_rank(pd.Series, current) → 50.0 if N<10` en `eolo-options/theta_harvest/earnings_iv_harvest_strategy.py:72-94`. Formula a portar.
- **F**: ADR-004 promete ADR-005 deliverable: table + nightly job + percentile compute.
- **G**: NO market calendar dep (`pandas_market_calendars` / `holidays` NOT en pyproject). Detección runtime.
- **H**: NO APScheduler. Existing pattern es custom asyncio worker (`alert_worker`, `retry_worker`).
- **I**: Repository pattern es 6 plain classes (sin ABC base). Match estilo.
- **J**: 🚨 MAJOR — `market.iv_surface` hypertable existe (V007:30-56) pero **unwritten**. ADR-005 crea NEW `market.iv_history`; populating de iv_surface registered como tech debt Sprint 7+.

---

## 2. Decisions

### D1. Schema — NEW `market.iv_history` (no reuse iv_surface)

**Decisión:** Crear nueva table `market.iv_history` con 1 row per (ticker, day) — single ATM IV scalar.

NO reusar `market.iv_surface` (V007) que es per-contract per-strike granular.

| Opción | Descripción | Descartada porque |
|---|---|---|
| **A (this)** | **NEW `market.iv_history` minimal (1 row/ticker/day)** | **Elegida: matches ADR-004 D3 promise. Cheap (~1500 rows/year). iv_surface puede populating Sprint 7+ separado.** |
| B | Reuse iv_surface + continuous aggregate sobre ATM strikes | iv_surface unwritten currently; populating es separate scope. Requires HERMES (Sprint 7+). |
| C | Wider iv_history con multiple strikes (ATM ± 25-delta) | Over-spec Sprint 6+. iv_rank only needs single ATM scalar. |

Tech debt registrar: iv_surface populating como ADR-006 o sub-block Sprint 7+ separado.

V018 migration target: `chunk_time_interval => INTERVAL '1 month'` (low-volume table, match V008 analytics convention).

### D2. Granularidad — 1 row per (ticker, day) ATM IV

**Decisión:** Tabla key = (ts, ticker). Una entry per ticker per trading day.

Trivially correct: iv_rank semantically es daily metric (NO intraday). 6 tickers × 252 trading days/year = 1,512 rows/year. Negligible volume.

### D3. ATM IV definition — avg(call.iv, put.iv) at ATM strike, fallback non-zero side

**Decisión:** ATM IV = average de call IV y put IV at strike closest to spot. Si solo uno disponible (otro 0 / missing), usar el non-zero side.

Lógica:
```python
call_iv = call_strikes[atm_strike].get("iv", 0.0)
put_iv  = put_strikes[atm_strike].get("iv", 0.0)
if call_iv > 0 and put_iv > 0:
    atm_iv = (call_iv + put_iv) / 2
elif call_iv > 0:
    atm_iv = call_iv
elif put_iv > 0:
    atm_iv = put_iv
else:
    atm_iv = None  # skip insert this day
```

Robust to asymmetric quotes (rare pero observed).

### D4. Snapshot timing — 21:15 UTC daily (16:15 ET)

**Decisión:** Nightly worker runs at 21:15 UTC. Snapshot post-close con 15-min safety margin (Schwab session ends 16:00 ET, allow propagation).

Considerado: 21:00 UTC exact. Rechazado: pre-close edge cases (last-minute quotes pending). 21:15 es conservative + idempotent (operator can re-run if needed).

### D5. Bootstrap strategy — Progressive 4 thresholds

**Decisión:** iv_rank progressive disclosure según N (count of historical datapoints en table):

| N range | Behavior | Log level |
|---|---|---|
| N < 10 | `iv_rank = 50.0` (placeholder, Eolo pattern) | DEBUG (silent) |
| 10 ≤ N < 30 | percentile vs available + advisory warning | WARNING ("iv_rank computed on N days only") |
| 30 ≤ N < 252 | percentile vs available + transition info | INFO ("iv_rank computed on N days, full at 252") |
| N ≥ 252 | full 252-day percentile | DEBUG (silent) |

Bootstrap completo toma ~1 año (per D9 forward accumulation).

### D6. iv_percentile field — Phase 1 = iv_rank (semantic reserve)

**Decisión:** Phase 1 (Sprint 6+): `iv_percentile = iv_rank` (same value). NO deprecation alias. Field se mantiene en TickerSnapshot para semantic reserve.

Phase 2+ (Sprint 7+): si se materializa "absolute scale percentile" semantic distinto (e.g., percentile of theoretical max IV), diverge entonces.

Razón: backward compat con tests + ATHENA prompt + Stub. Cambio breaking field-removal posponible.

### D7. Job mechanism — Custom asyncio worker (no APScheduler)

**Decisión:** `IvHistoryWorker` clase custom asyncio matching `alert_worker` / `retry_worker` pattern. NO APScheduler dependency.

| Opción | Descripción | Descartada porque |
|---|---|---|
| **A (this)** | **Custom asyncio worker** | **Elegida: match existing pattern (app.py:211-220), no new dep, in-process lifespan-managed.** |
| B | APScheduler library | +1 dep ~MB. Reinvent semantic ya cubierto por existing alert_worker pattern. |
| C | External cron (system-level) | No in-process visibility. Operator needs separate setup. |

Worker sleeps until next 21:15 UTC, invokes snapshot, sleeps until next day. Startup recovery check: si proceso reinició y ya pasó 21:15 hoy AND no hay row for today's date, snapshot inmediato.

### D8. Compute path — Python in-memory percentile

**Decisión:** `IvHistoryRepository.get_history(ticker, days=252)` returns list of atm_iv values. `SchwabDataLayer._compute_iv_rank(history, current_atm_iv)` does Python percentile.

| Opción | Descripción | Descartada porque |
|---|---|---|
| **A (this)** | **Python in-memory percentile** | **Elegida: ~1500 rows trivial. Match Eolo formula port. Tests easier (no DB mock for compute).** |
| B | DB-side `percent_rank()` query | Single query overkill for small dataset. Couples compute to DB. |
| C | TimescaleDB continuous aggregate | iv_history es small; cont. agg adds infra complexity sin payoff. |

Eolo formula:
```python
def _compute_iv_rank(history: list[float], current: float) -> float:
    if len(history) < 10:
        return 50.0
    below = sum(1 for v in history if v < current)
    return 100.0 * below / len(history)
```

### D9. Backfill — Forward accumulation only, NEVER

**Decisión:** NO historical IV backfill. iv_history populates forward from S.6.iv-c deployment.

Operator implication: full iv_rank toma ~1 año desde activation.

| Opción | Descripción | Descartada porque |
|---|---|---|
| **A (this)** | **Forward accumulation only** | **Elegida: simple, honest. Schwab API no provee historical IV.** |
| B | Backfill via CBOE paid feed | New paid dependency. Defer hasta priority emerges Sprint 8+. |
| C | Backfill via realized_vol proxy | Inaccurate (IV ≠ realized vol). Misleads progressive disclosure. |

### D10. Calendar — Runtime detection (Schwab empty chain → skip)

**Decisión:** NO calendar library dependency. Worker runs daily 21:15 UTC. Si Schwab returns empty chain (holiday / no trades), worker logs warning + skips insert for that day.

| Opción | Descripción | Descartada porque |
|---|---|---|
| **A (this)** | **Runtime detection via empty chain** | **Elegida: zero new deps. Schwab itself is the calendar authority.** |
| B | `holidays` package | New dep. US-focused only. |
| C | `pandas_market_calendars` | Heavier dep. Overkill for "skip days" requirement. |
| D | Hardcoded NYSE holidays list | Manual maintenance burden. |

Worker also skips weekends (Saturday/Sunday) via Python `datetime.weekday() in (5, 6)` check before invoking Schwab — saves API call.

### D11. Threshold transitions — Crisp (no hysteresis)

**Decisión:** iv_rank transitions across N thresholds (10, 30, 252) son crisp. NO hysteresis logic, NO smoothing factor.

| Opción | Descripción | Descartada porque |
|---|---|---|
| **A (this)** | **Crisp transition at N=10, 30, 252** | **Elegida: honest data-driven behavior. Adds zero complexity. Observability via log message on transition.** |
| B | Hysteresis buffer (e.g., stay placeholder until N=12) | Adds state tracking. Just delays inevitable transition without changing data quality. |
| C | Smooth interpolation between thresholds | Mathematically arbitrary. iv_rank semantic is "percentile", not blended value. |

Reasoning detalle: si N oscila around 10 (ej. weekend gap, then new datapoint), iv_rank may transition 50.0 ↔ real percentile en consecutive snapshots. Esto es **honest signal**: con N=9 NO tenemos sufficient data; con N=10 SÍ. Hysteresis just delays revealing this state.

Observability: cuando N transitions across a threshold (10, 30, 252), `IvHistoryRepository` logs INFO line para audit trail. Operator can grep "iv_rank threshold crossed" para correlate ATHENA behavior changes.

---

## 3. Sub-blocks (S.6.iv-X)

> LOC y tiempo son **upper bounds**. Sprint 5 retrospective: typical delivery 60-80% del upper bound.

| Sub-block | Description | LOC est | Tiempo | Depends on |
|---|---|---|---|---|
| **S.6.iv-a** | ADR-005 plan + decisions firmado (this commit). NO code. | 0 (doc) | 1h | — |
| **S.6.iv-b** | V018 migration (`market.iv_history` hypertable + index) + `IvHistoryRepository` (write_snapshot, get_history, count_for_ticker). Unit tests con DB mocked. | 100-150 | 2-3h | S.6.iv-a |
| **S.6.iv-c** | `IvHistoryWorker` async loop + nightly snapshot logic (D4 timing, D10 calendar runtime). Lifespan integration. | 150-200 | 3-4h | S.6.iv-b |
| **S.6.iv-d** | `SchwabDataLayer.iv_rank` real compute via D5 thresholds + D8 Python percentile. Replace 50.0 placeholder with progressive disclosure. | 100-150 | 2-3h | S.6.iv-b |
| **S.6.iv-e** | ATHENA prompt update — caveat block transitions to conditional: mention progressive disclosure stages explicitly. | 30-50 | 1h | S.6.iv-d |
| **S.6.iv-f** | Operator doc update (`schwab-setup.md` §7 + new section on iv_rank lifecycle) + ADR-005 close-out + status Aceptado. | 0 (doc) | 1-2h | All above |

**Total estimado**: ~380-550 LOC, ~10-15h.

**Orden ejecución sugerido**:
1. S.6.iv-a (this).
2. S.6.iv-b (foundation).
3. S.6.iv-c y S.6.iv-d en paralelo (independent post-b).
4. S.6.iv-e (depends on d).
5. S.6.iv-f (close-out).

---

## 4. Open questions

- **iv_surface populating** — separate ADR (ADR-006?) o tech debt held. Pending mid-Sprint-6 decisión cuando se vea cómo iv_history operates en producción. Decision factors: ¿HERMES Sprint 6 needs richer per-contract IV? ¿iv_surface adds value beyond iv_rank for ATHENA / APOLLO?
- **Backfill revisit** — D9 firm "never", pero si Sprint 8+ priority shifts to historical IV richness, ¿paid CBOE feed integration?
- **iv_percentile divergence trigger** — D6 reserves semantic. ¿Cuál signal indicaría "actually we need absolute scale"? (e.g., cross-symbol comparisons, theoretical max IV bound).
- **Hysteresis revisit** — D11 firm "no hysteresis", pero si Sprint 7+ produces ATHENA proposals donde N=10 boundary causa whipsaw observable, revisit con concrete data.

---

## 5. Out of scope

- **iv_surface populating** (out of THIS ADR scope; may land en separate ADR per §4).
- **`market.ohlcv` populating** (HERMES Sprint 7+).
- **30-day constant maturity IV interpolation** (advanced volatility surface modeling).
- **Term structure history** (front/back month spread).
- **Per-strike IV history** (delta-25 put_iv history, etc.). Out of scope; iv_history es single ATM scalar only.
- **Real-time IV stream** (Schwab WebSocket). Snapshot-only Sprint 6+.

---

## 6. Success criteria

**Concretos para Sprint 6 iv sub-stage:**

1. **V018 migration applies clean** en dev + staging. `market.iv_history` hypertable visible en `timescaledb_information.hypertables`.
2. **IvHistoryWorker arranca** con lifespan startup. Logs "✓ IvHistoryWorker active (next snapshot at YYYY-MM-DD 21:15 UTC)".
3. **Day 0 (first launch)**: SchwabDataLayer.iv_rank == 50.0 (placeholder per D5).
4. **Day 1 post-launch**: 1 row inserted en iv_history per ticker (6 rows total).
5. **Day 10**: SchwabDataLayer.iv_rank computa real percentile from 10 datapoints + WARNING log "iv_rank computed on 10 days only".
6. **Day 252+**: full iv_rank, no warning.
7. **Holiday detection**: Schwab returns empty chain → worker logs warning, skips insert, no error.
8. **Weekend skip**: Saturday/Sunday → worker NO invoca Schwab API.
9. **Process restart**: si proceso restarts past 21:15 UTC AND no row for today, snapshot inmediato (recovery check D7).
10. **Tests post-deployment**: existing 868 passing remain green + ~30-50 new tests for iv_history components.
11. **Operator doc updated**: `docs/operator/schwab-setup.md` includes section on iv_rank lifecycle + threshold transitions.

---

## 7. Risks

| ID | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R1 | Worker missed snapshot (process down at 21:15 UTC) | Medium | D7 startup recovery check; idempotent insert via PK |
| R2 | Idempotency — duplicate writes if recovery + new schedule overlap | Low | PK (ts, ticker) + `ON CONFLICT DO NOTHING` |
| R3 | iv_rank flapping at N=10 boundary (D11 no hysteresis) | Low | Observability log on threshold transitions; revisit only if concrete whipsaw observed |
| R4 | Holiday detection false positive (Schwab returns partial chain mid-holiday) | Low | Empty chain check + log warning; operator review if patterns emerge |
| R5 | Bootstrap delay (~1 year forward accumulation per D9) | High (intentional) | Documented in operator doc + ATHENA prompt; progressive disclosure mitigates |
| R6 | Workers race condition with Eolo Firestore refresh (S.5.6f finding) | Medium | iv_history snapshot doesn't touch Schwab auth state; reads cached data from SchwabClient already-active session |
| R7 | Hypertable size growth (long-term) | Low | ~1500 rows/year × indefinite retention = ~15K rows/decade. Negligible. |

---

## 8. References

- **ADR-004** (`docs/decisions/004-sprint-5-schwab-integration.md`): D3 iv_rank placeholder + §5 out of scope + §9.3 tech debt #1. Direct predecessor.
- **ADR-003** (`docs/decisions/003-sprint-4-consensus-and-validation.md`): Sprint 4 plan that delivered the DataLayer abstraction consumed by ATHENA.
- **`multi-agent-system/db/migrations/V007__market_tables.sql`**: pattern reference (hypertable + index + namespace `market.*`).
- **`multi-agent-system/src/multi_agent/data_layer/schwab_data_layer.py`**: post-S.5.6e impl with `iv_rank_default=50.0`. To be modified S.6.iv-d.
- **`multi-agent-system/src/multi_agent/data_layer/interfaces.py:65-66`**: `iv_rank` / `iv_percentile` field definitions on TickerSnapshot.
- **`multi-agent-system/src/multi_agent/agents/athena_prompt.py:55-65`**: Sprint 5 caveat block. To be updated S.6.iv-e.
- **`multi-agent-system/src/multi_agent/api/app.py:211-220`**: alert_worker + retry_worker existing pattern for IvHistoryWorker.
- **`/Users/JUAN/PycharmProjects/eolo/eolo-options/theta_harvest/earnings_iv_harvest_strategy.py:72-94`**: Eolo `_compute_iv_rank` formula reference.
- **`docs/operator/schwab-setup.md`**: §7 Future work item #1 (this ADR resolves). Will be updated S.6.iv-f.

---

## 9. Close-out (S.6.iv-f, pending)

> Sección se completa en S.6.iv-f. Estructura prevista:
> - §9.1 Sub-blocks delivered (table con commits + LOC + tests).
> - §9.2 Rule #15 findings summary (counts per sub-block).
> - §9.3 Tech debt registered for Sprint 7+.
> - §9.4 Next steps (ADR-006 si iv_surface populating, HERMES, etc.).

---

> **Próximo sub-bloque:** S.6.iv-b (V018 migration + IvHistoryRepository). Inicia tras Juan sign-off de este ADR.
