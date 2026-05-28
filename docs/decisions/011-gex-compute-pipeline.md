# ADR-011: GEX/Vanna/Charm Compute Pipeline — Tier A Signal Generation

**Fecha:** 2026-05-28
**Estado:** Propuesto
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

**Decisión**: Vanna + Charm computed from delta + gamma + IV + DTE + spot via Black-Scholes derivative formulas Sprint 13 (NO defer Sprint 14+).

**Formulas canonical**:
- Vanna = ∂Delta/∂IV = -gamma × d1 × sqrt(T) (per-strike, weighted by OI for aggregate)
- Charm = ∂Delta/∂T = -gamma × [r - q + (d1 × σ) / (2 × sqrt(T))] (per-strike, weighted by OI)

**Justificación**: D-ε-5. +50 LOC trivial vs scope-cohesion benefit. Vanna NOT en iv_surface schema → derived from existing fields (gamma + IV + DTE).

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

## 9. Close-out (S.13.gex-c, pending)

Sección a completar en S.13.gex-c. Estructura prevista (mirror ADR-005/006/007/009/013 §9):
- §9.1 Sub-blocks delivered (adr-a + gex-a + gex-b + gex-c con commits + LOC + tests + sign-off dates).
- §9.2 Rule #15 findings summary (F-r catches Sprint 13 cumulative).
- §9.3 Tech debt registered (deferred Sprint 14+ items).
- §9.4 Next steps Sprint 14+ (ADR-010 WebSocket + ADR-012 HERMES + Operator unblock #9 + tech debt remaining).
- Status: Propuesto → Aceptado.

---

> **Próximo sub-bloque**: S.13.gex-a (GEX core compute pipeline + 4 aggregation levels + ~10-15 unit tests). Inicia tras Juan sign-off plan firmado actual.
