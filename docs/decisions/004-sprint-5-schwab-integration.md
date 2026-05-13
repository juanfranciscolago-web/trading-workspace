# ADR-004: Sprint 5 Plan — Schwab Integration (Read-Only Data Layer)

**Fecha:** 2026-05-13
**Estado:** Aceptado (S.5.6g, 2026-05-14)
**Contexto:** Sprint 4 cerrado (commit `f1d27ae`). Próximo bloque per ADR-003 §5 ("Schwab integration — Sprint 5").

---

## 1. Context

### 1.1 Lo que dice el roadmap

Per `docs/decisions/003-sprint-4-consensus-and-validation.md` §5 ("Out of scope Sprint 5+"):

- **Schwab integration — Sprint 5.**
- **Ejecución (paper trades reales) — Sprint 5/6.**
- HERMES / NYX / VESTA reales — Sprint 5+ **condicionados a data layer real**.
- APOLLO macro generation (proposals propias) — Sprint 5+ **cuando hay data macro real**.

Sprint 5 es el strategic unblocker: sin data real, los 4 agentes pendientes (HERMES, NYX, VESTA, APOLLO-gen) quedan bloqueados o degradan a "critics genéricos" duplicando APOLLO Sprint 4. Schwab integration cierra ese bloqueador.

Per CLAUDE.md regla #2:
> "Nunca llames a la Schwab API directamente. Usá `shared_core.brokers.SchwabClient`."

### 1.2 Estado actual del código (post Sprint 4, commit `f1d27ae`)

**Sprint 4 produjo**:
- Full debate chain operacional E2E (ATHENA → APOLLO → ConsensusEngine → ATLAS).
- 742 tests passing.
- Detail page con polling 3s.
- StubDataLayer único: 6 tickers (SPY/QQQ/IWM/NVDA/AAPL/MSFT) con OHLCV sintético + IV rank bias + correlations.

**Sprint 5 reality check (rule #15)**:

- **`shared_core/brokers/schwab_client.py` existe pero es SKELETON.** 267 LOC con estructura completa pero **todos los métodos relevantes raise `NotImplementedError("Port from Eolo: ...")`**: `_refresh_access_token`, `get_quote`, `get_quotes`, `get_options_chain`, `get_price_history`, `get_positions`, `get_balances`, `place_order`, etc. Auth via `from_env()` lee `SCHWAB_API_KEY/SECRET/REFRESH_TOKEN`, pero implementation real está TODO.

- **Eolo NO tiene un `SchwabClient` unificado.** Las llamadas a Schwab están dispersas en `eolo/marketdata.py`, `eolo/Bot/marketdata.py`, `eolo/Bot-v1.2/buffer_market_data.py`, `eolo/eolo_common/multi_tf/market_data.py`, `eolo/eolo-options/buffer_market_data.py`. 5 implementaciones independientes de `get_price_history` con variations.

  > **AMENDMENT (S.5.6c, 2026-05-14):** El conteo "5 implementaciones" era impreciso. Rule #15 finding: real inventory es **2 REST canónicos + 4 adapters/wrappers**. REST: `eolo/Bot/marketdata.py` (uso primario en S.5.6c) + `eolo/marketdata.py` (root). Adapters: `Bot-v1.2/buffer_market_data.py`, `eolo_common/multi_tf/market_data.py`, `eolo-options/buffer_market_data.py`, `eolo-crop/buffer_market_data.py` (4to no listado original).
  >
  > **AMENDMENT (S.5.6d, 2026-05-14):** Para options chain, Eolo SÍ tiene REST: `eolo-options/stream/options_chain.py::OptionChainFetcher._fetch_chain` (idéntico a `eolo-crop/stream/options_chain.py` clone). La asunción inicial "Eolo NO tiene get_options_chain named function" era literalmente correcta pero semánticamente engañosa — `_fetch_chain` cumple el rol.

- **Auth en Eolo usa GCP Secret Manager + Firestore.** `eolo/init_auth.py` invoca `retrieve_google_secret_dict(gcp_id="eolo-schwab-agent", secret_id="cs-app-key")` para api_key/secret + `retrieve_firestore_value/store_firestore_value` para refresh_token. Manual one-time OAuth dance vía `safe_init_auth_v2.py` (URL passed por argv).

- **iv_rank percentile no existe en Eolo.** Análisis IV está en `eolo-options/analysis/iv_surface.py` pero ninguno computa "iv_rank vs trailing 252 días" — pattern requerido por ATHENA prompt.

**Implicación**: Sprint 5 NO es "wire SchwabClient ya existente". Es portar implementations desde Eolo a `shared_core.SchwabClient` + envolverlas en SchwabDataLayer.

---

## 2. Decisions

### D1. Scope — P-2 Lite

**Decisión:** Sprint 5 entrega read-only data layer con Schwab. NO incluye execution.

**Entrega**:
- `SchwabDataLayer(DataLayer)` produciendo real Schwab data (OHLCV + options chain).
- `iv_rank=50.0` placeholder (computation real diferida).
- Strategy pattern: config flag (`USE_SCHWAB_DATA_LAYER: bool`) toggle StubDataLayer ↔ SchwabDataLayer en lifespan.
- Tests integration con skip-if-no-creds pattern.
- Operator handoff doc.

**NO entrega**:
- Paper trade execution (Sprint 6).
- `iv_history` table + nightly snapshots (Sprint 6).
- Real-time streaming subscriptions (Sprint 6+).
- `get_positions` / `get_balances` ports (Sprint 6, requiere por ATLAS).

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| P-1 Minimal | OHLCV-only, sin options chain | ATHENA sin skew + iv → proposals de muy baja calidad. Chain runs but proposes garbage. |
| **P-2 Lite (this)** | **OHLCV + options chain + skew real, iv_rank=50 placeholder** | **Elegida: cierra unblocker sin overscope a execution o iv_history.** |
| P-3 Mid | P-2 + paper execution Schwab | Execution adds risk surface (orders, fills, reconciliation). Defer a Sprint 6 cuando data esté estable. |

### D2. Auth — GCP Secret Manager + Firestore

**Decisión:** Reusar pattern de Eolo. Single source of truth de tokens.

- `shared_core/auth/gcp.py` (nuevo) — port helpers `retrieve_google_secret_dict`, `retrieve_firestore_value`, `store_firestore_value` desde Eolo `helpers.py`.
- `SchwabClient._refresh_access_token` lee refresh_token de Firestore, refresh, escribe back.
- `shared_core` deps agregan: `google-cloud-secret-manager`, `google-cloud-firestore`.
- Local dev requiere `GOOGLE_APPLICATION_CREDENTIALS` env var apuntando a service account JSON.
- Schwab refresh_token rota per use; single Firestore document elimina drift entre Eolo y multi-agent.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| D1-A (this) | **GCP Secret Manager + Firestore** | **Elegida: single source of truth, battle-tested en Eolo, aligned con shared_core architecture.** |
| D1-B | Env vars only (`SCHWAB_REFRESH_TOKEN` en .env) | Refresh rotates token; 2 systems con env vars distintos → silent drift, uno queda con token stale. |
| D1-C | Híbrido Firestore + env fallback | Complejidad sin valor concreto Sprint 5. |

### D3. iv_rank — placeholder Sprint 5

**Decisión:** `iv_rank=50.0` (mid-percentile) durante Sprint 5. Real computation Sprint 6+.

- `SchwabDataLayer.snapshot()` setea `iv_rank=50.0` para cada ticker.
- ATHENA prompt actualizado con caveat inline: *"Sprint 5 caveat: iv_rank is currently a placeholder (50.0). Real percentile vs trailing 252 days lands in Sprint 6+. Treat iv_rank field as advisory, weight evidence from skew + ATM straddle + realized_vol más."*
- Sprint 6 dedicated: `iv_history` table + nightly snapshot job + `iv_rank` percentile computation. ADR-005 separado.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| D2-X | Full IV history Sprint 5 | +250 LOC + DB migration + cron job + 252-day accumulation antes de ser útil. Sprint 5 ya es scope grande. |
| **D2-Y (this)** | **iv_rank=50.0 placeholder con caveat en prompt** | **Elegida: scope reducido. ATHENA produces honest proposals con conocimiento del placeholder.** |
| D2-Z | Hybrid: SchwabDataLayer usa Stub iv_rank como fallback | Mezcla real + synthetic data confusa, harder to debug. |

### D4. Port strategy — direct copy from Eolo

**Decisión:** Identificar cleanest Eolo source per método, copiar verbatim, adaptar a SchwabClient signature.

- `get_price_history`: source candidate `eolo_common/multi_tf/market_data.py` (verificar en S.5.6c).
  > **AMENDMENT (S.5.6c, 2026-05-14):** Rule #15 finding revealed `eolo_common/multi_tf/market_data.py` is a buffer-based adapter (delegates to `rest_fallback`), NOT a REST implementation. Real canonical REST source ported: `eolo/Bot/marketdata.py` (intraday minute + daily via `period_type="month"`/`frequency_type="daily"` pattern).
- `get_options_chain`: no existe en Eolo con ese nombre — buscar fetcher inline o implementar from Schwab API docs (sub-block S.5.6d evaluará).
  > **AMENDMENT (S.5.6d, 2026-05-14):** Eolo SÍ tiene REST implementation: `eolo-options/stream/options_chain.py::OptionChainFetcher._fetch_chain` (+ identical clone at `eolo-crop/stream/options_chain.py`). El method name diff (`_fetch_chain` vs `get_options_chain`) made the initial literal search miss it. 3 reusable methods ported: `_fetch_chain`, `_normalize`, `_parse_option_map`.
- `_refresh_access_token`: source candidate `eolo/safe_init_auth_v2.py` (OAuth dance + Firestore write).

Si port revela bugs en Eolo source, fix en shared_core (no en Eolo) — Eolo intocable per CLAUDE.md regla #5.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| **D3-A (this)** | **Direct port from cleanest Eolo file** | **Elegida: speed > perfection. 4 bots Eolo running productively = patterns funcionan.** |
| D3-B | Reimplement from Schwab API docs ignoring Eolo | Slower; descarta knowledge battle-tested. |
| D3-C | Read Schwab API docs + reference Eolo + distill | Intermedio. Solo para `get_options_chain` (donde Eolo no tiene named function). |

### D5. Options chain — incluido en Sprint 5

**Decisión:** Sprint 5 SchwabDataLayer fetches options chain, computa `skew` (put_iv - call_iv at delta 0.25) y ATM straddle desde el chain. Solo `iv_rank` queda placeholder.

- `get_options_chain` retorna estructura: calls[], puts[] con strike/bid/ask/last/volume/OI/IV/Greeks.
- `SchwabDataLayer` extrae ATM call IV + ATM put IV para skew, ATM straddle = call.last + put.last at strike most ≈ price.

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| **B (this)** | **Options chain included Sprint 5** | **Elegida: sin options chain, ATHENA tiene OHLCV pero usa skew=stub + iv=stub. Proposals citan signals fake. Chain runs but valida nothing semánticamente.** |
| A | Defer options chain a Sprint 6 | Rompe ATHENA quality. Sprint 5 entrega-able pero degradada. |

---

## 3. Sub-blocks (S.5.6X)

> **Nota sobre estimates:** LOC y tiempo son **upper bounds**. Delivery actual basado en Sprint 4 retrospective típicamente 60-80% del upper bound.

| Sub-bloque | Descripción | LOC est | Tiempo | Depends on |
|------------|-------------|---------|--------|------------|
| **S.5.6a** | Eolo recolección técnica + ADR-004 sign-off (this commit). NO code. | 0 (doc) | 30min | — |
| **S.5.6b** | Port GCP auth helpers (`retrieve_google_secret_dict`, Firestore CRUD) a `shared_core/auth/gcp.py`. Port OAuth refresh logic a `SchwabClient._refresh_access_token`. Tests con GCP client mocked. | 200-300 | 4-6h | S.5.6a |
| **S.5.6c** | Port `get_price_history` desde Eolo cleanest source (probable `eolo_common/multi_tf/market_data.py`). Tests con httpx mock + Schwab response fixtures. | 150-250 | 3-5h | S.5.6b |
| **S.5.6d** | Port `get_options_chain` (Eolo source TBD; fallback: implement from Schwab API docs). Tests. | 200-300 | 4-7h | S.5.6b |
| **S.5.6e** | `SchwabDataLayer(DataLayer)` impl. Schwab → MarketState mapping: OHLCV → ticker.ohlcv_daily/hourly, options chain → skew (delta 0.25 put-call) + ATM straddle, iv_rank=50.0, realized_vol from OHLCV. Unit tests con SchwabClient mocked. | 300-400 | 6-8h | S.5.6c, S.5.6d |
| **S.5.6f** | Lifespan config flag (`USE_SCHWAB_DATA_LAYER: bool`). Integration test con real Schwab (skip-if-no-creds). ATHENA prompt update con iv_rank caveat. | 150-200 | 3-5h | S.5.6e |
| **S.5.6g** | Operator handoff doc (`docs/operator/schwab-setup.md`): GCP creds setup, one-time OAuth dance, troubleshooting. ADR-004 close-out (mark Aceptado). | 0 (doc) | 1-2h | All above |

**Total estimado (upper bounds):** ~1000-1450 LOC, ~21-33h (~3-4 semanas con interrupciones, 5-7 semanas realista).

**Orden sugerido de ejecución:**

1. S.5.6a (this commit).
2. S.5.6b (auth foundation — habilita todo lo demás).
3. S.5.6c y S.5.6d son independientes entre sí; orden depende de cuál resulte más simple primero. Ambos bloquean S.5.6e.
4. S.5.6e (depende de c+d).
5. S.5.6f (depende de e).
6. S.5.6g (cierre).

---

## 4. Open questions (para resolver durante implementación)

- **Eolo `get_options_chain` source.** Sin función named en Eolo. S.5.6d primero busca implementations inline; si no, port from Schwab API docs.
- **`shared_core/auth/gcp.py` location.** ¿Auth helpers viven en `shared_core/auth/` (nuevo) o en `shared_core/config/`? Decisión durante S.5.6b.
- **Schwab rate limit headroom.** Default 5 calls/sec. Snapshot universe = 6 tickers × (1 price_history + 1 options_chain) = 12 calls ≈ 3s. Aceptable; revisar si polling Sprint 6 lo presiona.
- **Tests integration con real Schwab.** Skip-if-no-creds OK. ¿Necesitamos sandbox/paper account dedicado para CI futuro? Defer a Sprint 6 si CI llega.
- **GCP service account scope.** ¿Multi-agent service account = mismo que Eolo, o uno dedicado? Eolo wisdom: minimal scope.

---

## 5. Out of scope (Sprint 6+)

- **Paper trade execution via Schwab** (ADR-003 §5: "Sprint 5/6"). PaperExecutor port from Eolo, ATLAS integration con real orders, fill reconciliation.
- **`get_positions` / `get_balances` ports.** ATLAS portfolio snapshot uses real data — Sprint 6.
- **`iv_history` table + nightly snapshot + iv_rank percentile real.** ADR-005 separado.
- **Real-time streaming subscriptions** (Schwab WebSocket / push). Sprint 6+.
- **HERMES tactical** — needs intraday OHLCV minute-bar. Sprint 6+ ADR aparte.
- **APOLLO macro generation** (proposals propias) — needs macro data layer separado de Schwab. Sprint 6+.
- **NYX contrarian** — needs sentiment data layer. Sprint 6+ ADR-003 §5 explícito.
- **Multi-broker abstraction** (e.g., IBKR fallback). Sprint 8+.

---

## 6. Success criteria

**Concretos para Sprint 5:**

1. `USE_SCHWAB_DATA_LAYER=true` en `.env` + valid GCP creds → API arranca, ATHENA produce ProposalMessage con OHLCV/skew/ATM straddle reales desde Schwab.
2. `USE_SCHWAB_DATA_LAYER=false` → fallback a StubDataLayer (current behavior). Strategy pattern operacional.
3. Token refresh transparente: Schwab access_token expira (típicamente 30min), `SchwabClient._ensure_authenticated` refresca desde Firestore, ATHENA proposal subsequent works sin operator intervention.
4. Integration test E2E real Schwab: trigger ATHENA → proposal generado con datos Schwab → DB row → API GET /trades/pipeline returns. Test skips si no GCP creds disponibles.
5. Operator handoff doc permite rebuild clean: el operator (Juan) puede setup tokens desde cero siguiendo doc sin notas adicionales, en < 30 min.
6. 742+ tests passing post-Sprint 5 (no regresiones). Nuevos tests S.5.6: ~30-50.

**Métricas operacionales (no hard gates, observabilidad):**

- Schwab API latency P50 < 500ms per call.
- Snapshot full universe (6 tickers × 2 calls) < 5s wall-clock.
- Token refresh < 2s.

---

## 7. Risks

| ID | Risk | Likelihood | Mitigation |
|----|------|-----------|------------|
| R1 | Schwab API quirks no documentados (rate limit edge cases, error format variations) | Medium | Eolo experience (4 bots running productively) caught most. Real integration tests S.5.6f catch resto. |
| R2 | Token rotation race entre Eolo y multi-agent | Low | D2 single source of truth (Firestore). Cualquier system que refresh escribe back inmediatamente. |
| R3 | GCP creds setup friction en dev local | Medium | S.5.6g operator handoff doc dedicado. One-time setup. |
| R4 | Sprint 5 calendar mayor a estimado (5-7 semanas vs 3-4) | High | Sub-bloques independientes, cada commit standalone. No deadline fijo. |
| R5 | Schwab API changes during Sprint 5 (breaking) | Low | Schwab API stable per Eolo's 6+ meses producción. Si pasa, ADR-006 mid-sprint. |
| R6 | `get_options_chain` Eolo source no exists clean → reimplement from docs | Medium | S.5.6d primero busca, si vacío implementa con tests against Schwab response fixtures (~+50 LOC). |

---

## 8. References

- ADR-003 §5 — Sprint 5 commitments ("Schwab integration — Sprint 5").
- `docs/sistema_multiagente_trading.md` §10.5 — Sprint 5 roadmap context.
- `docs/DAILY_LOG_2026-05-11.md` — Sprint 4 close-out + Sprint 5 outline.
- CLAUDE.md regla #2 — `shared_core.brokers.SchwabClient` mandato.
- CLAUDE.md regla #3 — `shared_core.risk.atlas_client` mandato (relevante Sprint 6 cuando ATLAS use Schwab positions).
- CLAUDE.md regla #5 — Eolo intocable durante refactors.
- CLAUDE.md regla #15 — Verificar realidad antes de spec (aplicado heavy durante recolección S.5.6a).
- Eolo `init_auth.py` + `safe_init_auth_v2.py` — auth dance reference.
- Eolo `Bot/marketdata.py` — `get_price_history` canonical REST source (ported S.5.6c).
- Eolo `eolo-options/stream/options_chain.py` — `OptionChainFetcher._fetch_chain` canonical REST for options chain (ported S.5.6d).
- `docs/operator/schwab-setup.md` — operator handoff guide (Sprint 5 S.5.6g).

---

## 9. Close-out (S.5.6g, 2026-05-14)

**Status: Aceptado.** Sprint 5 cerrado en 4 días (commits 11-14 mayo).
Foundation completa para integración Schwab read-only via `SchwabDataLayer`
toggle por `USE_SCHWAB_DATA_LAYER` flag.

### 9.1 Sub-blocks delivered

| Sub-block | Commit | LOC | Tests delta | Description |
|---|---|---|---|---|
| S.5.5 | `f1d27ae` | small | — | AtlasConsumer status transition fix (Sprint 4 close-out gap) |
| S.5.6a | `bc18737` | 228 (doc) | — | ADR-004 Sprint 5 plan firmado |
| S.5.6b | `01b55c6` | +727 -9 | +33 | GCP auth helpers + Schwab OAuth refresh |
| S.5.6c | `0732baf` | +355 -6 | +13 | Port `get_price_history` from Eolo Bot/marketdata.py |
| S.5.6d | `c258005` | +597 -10 | +20 | Port `get_options_chain` + normalized chain shape |
| S.5.6e | `6ab8327` | +675 -4 | +22 | `SchwabDataLayer(DataLayer)` impl + correlations + skew 25-delta |
| S.5.6f | `c325b5e` | +572 -4 | +15 (+1 skipped gated) | Lifespan integration + `USE_SCHWAB_DATA_LAYER` flag + ATHENA caveat |
| S.5.6g | (this commit) | ~+450 (doc) | 0 | Operator handoff doc + ADR-004 amendments + close-out |
| **Total** | — | **~+3,600 net LOC** | **+103 passing, +1 skipped** | — |

Tests state final: **868 passing** (shared_core 95 + multi-agent 773) + 1 integration test skipped by design.

### 9.2 Rule #15 findings summary

Rule #15 ("verify reality before spec") fired ~30+ times across Sprint 5
sub-blocks. Distribution by sub-block:

- **S.5.6a (4)**: SchwabClient skeleton existing, Eolo battle-tested patterns inventory, dispersions count initial estimate.
- **S.5.6b (5)**: GCP project setup, Secret Manager structure, Firestore collection naming, `TOKEN_SCHWAB` dead placeholder, `gcloud firestore documents` does NOT exist.
- **S.5.6c (8)**: 2 REST + 4 adapters (not 5), `eolo_common/multi_tf` is adapter NOT REST, endpoint shape `/marketdata/v1/pricehistory` (not `/v1/{ticker}/quotes`), `httpx` already in shared_core (D-α revisited), `Bot/marketdata.py` is canonical source.
- **S.5.6d (8)**: Eolo SÍ has `_fetch_chain`, `eolo-options/stream/options_chain.py` and `eolo-crop/stream/options_chain.py` are identical clones, strike key is string (not float, Schwab native format), schema requires `_normalize_options_chain` + `_parse_option_exp_map`.
- **S.5.6e (7)**: DataLayer interface is single-method `snapshot()`, MarketState shape, TickerSnapshot 8 fields, SkewSnapshot 3 fields legacy "1σ" docstring, `ohlcv_hourly` mention in prompt is decorative not load-bearing, TICKER_UNIVERSE 6 tickers exact, lifespan injection point.
- **S.5.6f (5)**: Settings class extension pattern, lifespan branch exact line, `SchwabClient.from_env()` vestigial post-S.5.6b, ATHENA prompt single-`#` heading style, Firestore token race vs Eolo mechanism.
- **S.5.6g (3)**: `docs/operator/` directory did NOT exist (new convention), `gcloud firestore documents` invalid (Python helper alternative), `create_app()` factory function vs `app` instance.

**Pattern**: each rule #15 firing saved 10-30 min of speculative implementation that would have required rework. Recommend continuing the pattern in Sprint 6+.

### 9.3 Tech debt registered for Sprint 6+

Mirror of `docs/operator/schwab-setup.md` §7 — single source of truth:

1. **`iv_history` table + iv_rank real percentile** → ADR-005 separate. Sprint 5 placeholder 50.0.
2. **`_persisted_at` field in Firestore writes** → cleaner token expiry tracking. Currently `token_expires_at=None` initial in `from_gcp()`.
3. **Hourly OHLCV resample** (HERMES Sprint 6+) → currently `ohlcv_hourly=[]` in `SchwabDataLayer`.
4. **Date-aware correlations alignment** → required if Sprint 6+ adds VIX or cross-exchange tickers.
5. **`SchwabClient.from_env()` removal** → confirmed zero callers in S.5.6g recolección. Caller audit + separate ADR.
6. **ATHENA prompt caveat block removal** → when `iv_history` lands Sprint 6+.
7. **Token caching with TTL check** → enable concurrent operation with Eolo without race condition.
8. **`TOKEN_SCHWAB` Secret Manager cleanup** → placeholder dead value `"TU_TOKEN_AQUI"`, unused since S.5.6b discovery.
9. **`SkewSnapshot` field naming** → inline comments resolved S.5.6g; field NAMES (`put_skew_iv`/`call_skew_iv`) inherited from synthetic stub. Rename to `put_25d_iv`/`call_25d_iv` consideration Sprint 6+ (breaking change for serialized state).

### 9.4 Next steps Sprint 6+

- **ADR-005** decision: `iv_history` table architecture (column shapes, retention policy, nightly snapshot job).
- **HERMES agent** (tactical, hourly): defer until intraday data layer ready (hourly resample tech debt #3).
- **NYX agent** (per ADR-003 §5 explicit): re-evaluate after Sprint 6+ data layer growth provides sentiment inputs.
- **LlmGateway refactor (S.5.4 deferred per ADR-003 retrospective)**: re-evaluate post-NYX/HERMES landing if compounding workaround pain emerges.

Sprint 5 closes the "foundation" stage. Sprint 6+ delivers feature growth (real agents trading with real data + iv_history backfill + intraday).

---

> **Sprint 5 cerrado** (commits 11-14 mayo). Próximo: ADR-005 (`iv_history` table architecture) + Sprint 6+ planning.
