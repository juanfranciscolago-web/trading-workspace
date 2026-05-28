# ADR-011: GEX/Vanna/Charm Compute Pipeline — Tier A Signal Generation

**Fecha:** 2026-05-28
**Estado:** Aceptado (2026-05-28)
**Contexto:** Sprint 13 LOCKED via S.13.plan-a (commit `ad04665`, 2026-05-28, scoring 3.65 weighted, strategic override numerical winner #9 Operator unblock 4.00 gap 0.35). Esta ADR define GEX + Vanna + Charm compute pipeline = Tier A dealer flow signal generation aggregating per-strike Greeks from `market.iv_surface` (ADR-006 producer S.7.surf-b ACEPTADO). ADR-011 NEW canonical per ADR-008 D6 #4 sequencing.

---

## 1. Context

### 1.1 Sprint 13 lock per S.13.plan-a

- S.12.telemetry-c-deferred ✓ Sprint 12 close-out parcial (commit `890d75f`, 2026-05-28). Track A telemetry-c observation OPEN parallel.
- S.13.plan-a ✓ Sprint 13 priority analysis fresh re-score (commit `ad04665`, 2026-05-28). #2 ADR-011 GEX compute LOCKED 3.65 weighted.
- Strategic override #9 Operator unblock (4.00 numerical winner): "soft sprint" risk + GEX deliverable code Tier A signal unlock + operator gate INDEPENDENT score 5/5.
- Caveat D-γ-3 sustained: Track A telemetry-c observation OPEN. Sprint 14+ retrospective adjustment posible cuando data exists.

### 1.2 ADR number decision

ADR-011 NEW canonical per ADR-008 D6 #4 sequencing ("ADR-011 (GEX compute pipeline) — Sprint 12+. Tier A dealer flows. Renumber: was ADR-010 prior ADR-008."). NO renumber required jueves 28.

Current ADR list: 001-009 + 013. ADR-010 (WebSocket Tier D) + ADR-012 (HERMES) reserved per ADR-008 D6 #3 + #5. ADR-011 slot canonical disponible.

### 1.3 Pre-recolección findings F-r1 a F-r5 (rule #15 strict)

- **F-r1**: iv_surface producer ACEPTADO S.7.surf-b/c (commits `84ab8c3` + `7ac1ee5`, 2026-05-16). `IvSurfaceRepository.write_chain_snapshot` executemany pattern + `IvHistoryWorker.run_daily_snapshot` @ 21:15 UTC active. Write path code verified jueves 28 reality. Row count NO verifiable (Docker daemon down jueves 28 session, psql not installed) → Sprint 13 gex-a integration tests must verify data freshness pre-compute. R1 catalog mitigation.
- **F-r2**: Eolo precedent check — `gamma_scalp_0dte_strategy.py` exists Eolo (strategy, NOT GEX compute pipeline aggregation). ADR-011 greenfield design jueves 28.
- **F-r3**: ADR Estado "Propuesto" en S.13.adr-a → "Aceptado" en S.13.gex-c close-out (mirror ADR-013 pattern).
- **F-r4**: contract_multiplier=100 standard equity universe SPX/SPY/QQQ TICKER_UNIVERSE. Futures out-of-scope D10.
- **F-r5**: ADR-011 NEW canonical per ADR-008 D6 #4 (no renumber required).

---

## 2. Decisions

### D1. Scope = GEX + Vanna + Charm all Sprint 13

**Decisión**: Sprint 13 ADR-011 implementación incluye GEX + Vanna + Charm en mismo sprint per S.13.plan-a §6 (gex-a Day 2-3 GEX core + gex-b Day 3-4 Vanna/Charm BS derivatives + gex-c Day 4-5 integration + benchmark + close-out).

**Justificación**: Scope cohesion. Vanna/Charm = second-order Greeks derivatives de gamma/delta + IV/DTE (computable Sprint 13 vs defer Sprint 14+, +50 LOC trivial). Single deliverable atomic. D-β-5 firmado.

### D2. Data source = market.iv_surface ONLY

**Decisión**: GEX compute reads `market.iv_surface` exclusivamente. NO on-demand `SchwabClient.get_options_chain` fetch.

**Justificación**:
- iv_surface producer ACEPTADO Sprint 7 (ADR-006). 12 fields per contract per strike per expiration: ts, underlying, expiration, strike, option_type, iv, delta, gamma, theta, vega, open_interest, volume.
- Single source canonical eliminates dual-path consistency burden.
- Read-only consumer (NO new producer wiring needed Sprint 13).
- D-γ-5 firmado.

### D3. Compute architecture = stateless functions module

**Decisión**: `multi_agent/risk/gex_compute.py` exporta stateless pure functions (NOT new Repository class — no DB writes).

**Justificación**:
- GEX = pure compute (NO state, NO DB writes). Repository pattern over-engineering Sprint 13.
- Mirror `multi_agent/risk/` organization (ATLAS-adjacent module per D-δ-5).
- Stateless = trivially testable + future CachedGexBuilder Sprint 14+ Q2 deferred wrap-around opcional.

### D4. GEX formula canonical

**Decisión**:
- **Formula per-strike**: `GEX_per_strike = (call_gamma × call_OI − put_gamma × put_OI) × spot² × 0.01 × contract_multiplier`.
- **Net GEX**: sum across all strikes (per expiration o aggregate).
- **Units**: $ per 1% move standard SpotGamma convention. Contract multiplier = 100 standard equity options.

**Justificación**: Standard market practice SpotGamma + GammaLab. Self-validating against benchmarks. F-r4: hardcode contract_multiplier=100 Sprint 13 (SPX/SPY/QQQ standard equity universe, no futures).

### D5. Aggregation strategy

**Decisión**: 4 aggregation levels:
1. **Per-strike GEX**: individual strike contribution.
2. **Per-expiration GEX curve**: DTE-bucketed (0DTE, 1-7DTE, 8-30DTE, 31-60DTE, >60DTE).
3. **Total GEX**: sum across all strikes/expirations.
4. **Gamma flip point**: zero-crossing strike (positive ↔ negative gamma regime boundary).

**Justificación**: SpotGamma/GammaLab convention. Per-expiration curve enables term structure analysis (Sprint 14+ ATHENA regime detection).

### D6. Vanna/Charm via Black-Scholes derivatives

**Decisión**: Vanna + Charm computed via `shared_core.utils.greeks_calculator` extension Sprint 13 gex-b (NEW functions `calculate_vanna()` + `calculate_charm()` added to existing module, leveraging existing `calculate_d1_d2()` helper). Multi-agent `gex_compute.py` imports + aggregates per-strike Vanna/Charm weighted by OI.

**Formulas canonical** (Hull canonical Black-Scholes derivatives, Sprint 13 gex-b math accuracy amendment):
- Vanna = ∂Delta/∂σ = -e^(-qT) × N'(d1) × d2 / σ (per unit σ change, per-strike, weighted by OI × CONTRACT_MULTIPLIER)
- Charm_call = q × e^(-qT) × N(d1) - e^(-qT) × N'(d1) × [2(r-q)T - d2×σ√T] / (2T×σ√T) (per-year)
- Charm_put = -q × e^(-qT) × N(-d1) - e^(-qT) × N'(d1) × [2(r-q)T - d2×σ√T] / (2T×σ√T) (per-year)
- Multi-agent layer divides Charm by 365 for per-day convention (mirror existing theta pattern).

**Justificación D-α-7 amendment Sprint 13 gex-b math accuracy**: Original spec "-gamma × d1 × √T" (Sprint 13 adr-a) was simplified approximation, mathematically off vs Hull canonical (missing N'(d1) × e^(-qT) factors + incorrect dimensionality vs spot S). Pre-Write math verify catched accuracy bug F-r ant #4. Hull canonical implemented Sprint 13 gex-b via `shared_core.utils.greeks_calculator` NEW functions `calculate_vanna()` + `calculate_charm()` leveraging existing `calculate_d1_d2()` + `_norm_pdf()` + `_norm_cdf()` helpers. Finite-difference numerical validation D-ζ-7 (NO py_vollib dep).

**Justificación D-ε-5 + D-ε-6 amendment Sprint 13 gex-a**: Vanna NOT en iv_surface schema → derived from existing fields (gamma + IV + DTE). Implementation location `shared_core.utils.greeks_calculator` (vs `multi_agent/risk/gex_compute.py`) preserves separation of concerns + reuses `calculate_d1_d2` helper. +50 LOC shared_core + ~30 LOC multi_agent integration (vs +80 LOC isolated multi_agent duplicating logic). D6 amendment inline S.13.gex-a per ADR-011 Propuesto modifiable pre-close-out.

### D7. Tests strategy

**Decisión**: 3-tier tests Sprint 13:
1. **Unit tests** (~15-20): synthetic input → known output formula validation. Edge cases (zero gamma, extreme DTE, ATM vs OTM strikes).
2. **Integration tests** (~5-8): real iv_surface read → compute → shape verify (NO benchmark vs external reference).
3. **Benchmark tests** (~2-3): cross-validate Vanna/Charm via py_vollib reference library OR manual SpotGamma sample (operator-provided si available).

**Total tests estimate**: ~25-30 NEW Sprint 13 gex-a + gex-b.

### D8. Downstream consumer interface

**Decisión**: NEW `GexSnapshot` dataclass exported `multi_agent/risk/gex_compute.py`:

```python
@dataclass(frozen=True)
class GexSnapshot:
    underlying: str
    snapshot_at: datetime
    spot: float
    gex_total: float                          # $ per 1% move
    gex_per_expiration: dict[str, float]      # DTE bucket → GEX
    gex_per_strike: dict[float, float]        # strike → GEX
    gamma_flip_point: float | None            # zero-crossing strike
    vanna_total: float
    charm_total: float
```

**ATHENA prompt integration EXCLUDED Sprint 13**: D-ζ-5 + D-γ-4 sustained. Sprint 14+ post telemetry-c data signal viable.

### D9. Operator gate independence verify

**Decisión**: GEX compute reads market.iv_surface (DB-backed Sprint 7 producer). NO USE_LIVE_PORTFOLIO required. NO USE_SCHWAB_DATA_LAYER required. NO SCHWAB_ACCOUNT_ID required.

**Justificación**: ADR-011 LOCK rationale (S.13.plan-a §5 strategic override) operator gate independent score 5/5. Validated D9 explicit.

### D10. Out of scope Sprint 13

**Explicit OUT of scope**:
- ATHENA prompt integration (Sprint 14+ telemetry-c trigger).
- Real-time GEX streaming (depends Tier D WebSocket ADR-010).
- Historical GEX time-series storage (Sprint 14+ telemetry trigger).
- Gamma cubed / exotic Greeks.
- Cross-asset GEX correlation (SPX vs SPY vs QQQ).
- Dark pool flow integration.

---

## 3. Sub-blocks Sprint 13 (canonical S.13.plan-a §6)

| Sub-block | Phase | Scope | Estimate |
|-----------|-------|-------|----------|
| S.13.plan-a | ✓ DONE | Priority analysis + GEX LOCK | ~124 LOC doc (commit ad04665) |
| S.13.adr-a | THIS commit | ADR-011 design plan firmado D1-D10 | ~250-300 LOC doc |
| S.13.gex-a | Day 2-3 | GEX core compute (formula + aggregation + 4 levels) | ~300-400 LOC code + 10-15 tests |
| S.13.gex-b | Day 3-4 | Vanna/Charm BS derivatives + tests | ~200-300 LOC code + 8-12 tests |
| S.13.gex-c | Day 4-5 | Integration tests + benchmark + close-out | ~150 LOC + ADR-011 Aceptado |

**Total estimate Sprint 13**: ~1,150-1,400 LOC + ~25-35 tests.

---

## 4. Open questions (Sprint 13 gex-a/b/c TBD)

- **Q1**: Vanna/Charm benchmark source — py_vollib library (Python option pricing reference) preferred OR operator-provided SpotGamma sample data file?
- **Q2**: GexSnapshot caching strategy — gex_compute.py stateless per call, OR CachedGexBuilder Sprint 13+ mirror CachedSnapshotBuilder pattern?
- **Q3**: 0DTE handling — Black-Scholes derivatives breakdown near expiration. Special-case 0DTE separately or include in 1-7DTE bucket?
- **Q4**: Universe scope Sprint 13 — SPX + SPY + QQQ + IWM (standard market makers tickers) OR per-ticker config?

Defer to S.13.gex-a/b/c sub-blocks.

---

## 5. Out of scope (this ADR)

- ATHENA prompt integration (Sprint 14+ telemetry-c trigger per D-γ-4 + D-ζ-5).
- Real-time GEX streaming (depends ADR-010 WebSocket).
- Historical GEX time-series storage (Sprint 14+).
- Cross-asset correlation analysis.
- Dark pool / exotic flows.

---

## 6. Success criteria

- D1-D10 implemented across S.13.gex-a + gex-b + gex-c.
- ~25-35 NEW tests passing (unit + integration + benchmark).
- GEX compute reads iv_surface successfully (no schema migration needed).
- Vanna/Charm BS derivatives validated against py_vollib OR SpotGamma sample.
- GexSnapshot dataclass exported, ready future ATHENA Sprint 14+ integration.
- ADR-011 Status: Propuesto → Aceptado at S.13.gex-c close-out.

---

## 7. Risks + mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| R1: iv_surface NOT populated (producer Sprint 7 not running OR row count 0 jueves 28) | High | F-r1 pre-Write verify: Docker daemon down jueves 28 → row count NO verifiable. Code path ACEPTADO Sprint 7 verified. Sprint 13 gex-a integration tests must verify data freshness pre-compute. R1 active mitigation gex-a phase |
| R2: Vanna/Charm BS derivative accuracy | Medium | D7 benchmark tests py_vollib + SpotGamma sample cross-validation |
| R3: contract_multiplier convention (100 vs futures) | Low | F-r4: Sprint 13 universe SPX/SPY/QQQ standard equity = 100. Futures out-of-scope D10 |
| R4: Sprint 14+ ATHENA integration scope creep | Low | D-ζ-5 + D-γ-4 sustained scope discipline. GexSnapshot dataclass ready, integration deferred |
| R5: Performance (compute over full iv_surface per call) | Medium | Sprint 13 stateless per call. CachedGexBuilder Sprint 13+ Q2 deferred decision |

---

## 8. Sub-decisions firmadas (Camino 2, -5 suffix Sprint 13 adr-a)

- **D-α-5**: ADR-011 NEW canonical (per ADR-008 D6 #4 sequencing). Mirror ADR-013 9 sections structure pattern.
- **D-β-5**: D1 scope GEX + Vanna + Charm all Sprint 13 (per S.13.plan-a §6 gex-b explicit).
- **D-γ-5**: D2 data source market.iv_surface ONLY (NO on-demand chain). Single source canonical.
- **D-δ-5**: D3 module location multi_agent/risk/gex_compute.py (mirror risk/ organization, ATLAS-adjacent).
- **D-ε-5**: D6 Vanna/Charm compute from BS derivatives Sprint 13 (NO defer Sprint 14+). +50 LOC trivial vs scope-cohesion.
- **D-ζ-5**: D8 ATHENA prompt integration EXCLUDED Sprint 13 (D-γ-4 sustained, Sprint 14+ telemetry-c trigger).

---

## 9. Close-out (S.13.gex-c, 2026-05-28)

### 9.1 Sub-blocks delivered

| Sub-block | Commit | LOC | Tests | Description |
|-----------|--------|-----|-------|-------------|
| S.13.plan-a | `ad04665` | +124 doc | 0 | Sprint 13 priority analysis + GEX LOCKED (scoring 3.65 weighted, strategic override #9 Operator unblock 4.00 gap 0.35) |
| S.13.adr-a | `1298177` | +217 doc | 0 | ADR-011 design plan firmado D1-D10 (NEW Propuesto, 9 sections mirror ADR-013) |
| S.13.gex-a | `fd37555` | +398/-3 | +17 | GEX core compute pipeline (4 aggregation levels + GexSnapshot scaffold) + ADR-011 D6 amendment #1 (shared_core extension D-ε-6) |
| S.13.gex-b | `6135607` | +325/-14 | +13 | Vanna/Charm Hull canonical (greeks_calculator extension) + ADR-011 D6 amendment #2 math accuracy + finite-diff benchmarks (D-α-7 CRITICAL catch pre-Write) |
| S.13.gex-c | _this commit_ | ~+280 | +5 | §9 close-out + 5 integration tests + DAILY_LOG amend + ADR-011 Aceptado |

**Sprint 13 totals**: 5 commits + ~1,344 LOC (doc + code + tests) + 35 NEW tests (gex-a 17 + gex-b 13 + gex-c 5).

### 9.2 Findings rule #15 summary

**12 F-r catches Sprint 13 cumulative** (record alto vs Sprint 11 record 18 + Sprint 12 record 8):

| F-r # | Sub-block | Type | Resolution |
|-------|-----------|------|------------|
| F-r ant #1-#7 | gex-a (catalogued) | Signature divergence cross-module + 0DTE + spot=0 + iv_surface populated | All inline mitigated pre-Write |
| F-r ant #1-#5 | gex-b (catalogued) | Case translation + py_vollib NO + 0DTE + math accuracy + test rename | All inline mitigated pre-Write |
| F-r28 | gex-b (post-Write) | OTM call Vanna sign convention (d2<0 → positive) | Test expectation corrected 1 iteration |
| F-r29 | gex-b (post-Write) | Charm Hull elapsed-time convention sign | Numerical formula sign flipped 1 iteration |

**Patterns observed Sprint 13**:
- Pre-recolección math verify CATCHED CRITICAL accuracy bug pre-Write (D-α-7 ADR-011 D6 spec was simplified approximation). Catched pre-Write = exactly value sustained Camino 2 protocol 6+ sprints.
- ADR Propuesto modifiable inline pattern reusable (2x D6 amendments same sprint sin re-litigation).
- Cross-package work (multi-agent + shared_core) yields concentrated F-r catches mirror atlas-b Sprint 11 lesson.
- Hand-computed + finite-difference numerical benchmark validation (NO py_vollib dep, pure stdlib preserved) — math accuracy provable via dual independent methods.

**Tech debt resolved Sprint 13**: 0 (Sprint 13 was NEW feature delivery, NOT debt resolution sprint).

**Tech debt NEW Sprint 13** (deferred §9.3):
- DEFAULT_RISK_FREE_RATE=0.05 hardcoded constant (vs FRED API real-time fetch).
- DEFAULT_DIVIDEND_YIELD=0.0 hardcoded constant (vs per-ticker config).
- ATHENA prompt integration deferred Sprint 14+ (per D-ζ-5 + D-γ-4 sustained).
- iv_surface freshness verify deferred (R1 mocked tests, operator pre-deploy + telemetry-c unlocks real-DB validation).

### 9.3 Tech debt registered

**NEW Sprint 13** (Sprint 14+ candidates):

| # | Item | Source | Trigger |
|---|------|--------|---------|
| 1 | DEFAULT_RISK_FREE_RATE FRED API integration | gex-b D-ε-7 | Sprint 14+ data accuracy concern |
| 2 | DEFAULT_DIVIDEND_YIELD per-ticker config | gex-b D-ε-7 | Sprint 14+ data accuracy concern |
| 3 | ATHENA prompt integration GexSnapshot consumer | adr-a D-ζ-5 + plan-a D-γ-4 | Post telemetry-c data signal Sprint 14+ |
| 4 | iv_surface real-DB freshness verify | adr-a R1 | Operator pre-deploy + Track A telemetry-c re-activation |
| 5 | CachedGexBuilder pattern (mirror CachedSnapshotBuilder) | Q2 deferred | Sprint 14+ performance optimization trigger |

**Inherited tech debt (Sprint 11 + Sprint 12, NOT addressed Sprint 13)**:
- Greeks D-η cross-source (ADR-013 §9.3 #1) — UNRESOLVED.
- PnL history D-θ table (ADR-013 §9.3 #2) — UNRESOLVED.
- OCC ticker parser D-ι-A (ADR-013 §9.3 #3) — UNRESOLVED.
- portfolio_beta D-κ cross-source (ADR-013 §9.3 #4) — UNRESOLVED.
- SchwabClient 4 instances F-r16 cross-cutting (ADR-013 §9.3 #6) — UNRESOLVED.
- Telemetry-c real close-out memo (S.12.telemetry-c-deferred §4 4 conditions) — DEFERRED observation window.

### 9.4 Next steps Sprint 14+ (TENTATIVE)

**Rule #15 strict**: Sprint 14 priority RE-VALIDATION required. NO pre-commit Sprint 14 priority.

**Caveat D-γ-3 sustained**: Track A telemetry-c observation window OPEN parallel. Cuando data exists (per telemetry-c-deferred §4 4 conditions met), Sprint 14+ re-validation MAY adjust priorities retrospectively per S.12.plan-a §7 mandate.

**Sprint 14+ candidates ranked Sprint 13 (3.05-4.00 range)**:
- #9 Operator unblock sprint (numerical winner Sprint 13 deferred 4.00 weighted) — accelerates Track A telemetry-c re-activation + validates fail-fast contract D-ν live.
- #8 SchwabClient F-r16 cross-cutting (3.25 third-place Sprint 13) — RESOLVES ADR-013 §9.3 #6 + ADR-005 §9.3 #1 reaffirmed.
- #1 ADR-010 Schwab WebSocket part 1 (3.05 fourth-place Sprint 13) — Tier D infra HERMES Sprint 14+ dependency multi-sprint pattern.
- Sprint 11 tech debt unresolved (Greeks D-η + portfolio_beta D-κ + PnL D-θ + SchwabClient F-r16).
- #3 ADR-012 HERMES Sprint 14-16+ canonical timeline (depends ADR-010 ready first).

**Re-score per rule #15 Sprint 14 plan-a**: pre-recolección outputs fresh + scoring matrix N candidates × 6 dimensions weighted + LOCK explicit operator sign-off. NO carry-over assumptions.
