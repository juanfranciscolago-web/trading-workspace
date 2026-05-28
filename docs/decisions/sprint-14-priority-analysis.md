# Sprint 14 Priority Analysis — Bundle B1 (Operator unblock + SchwabClient F-r16) LOCKED

**Fecha:** 2026-05-28 (jueves)
**Estado:** Decidido (Sprint 14 = Bundle B1 Operator unblock #12 4.00 + SchwabClient F-r16 #11 3.25 LOCKED, bundle pattern Sprint 12 Option C precedent)
**Contexto:** Sprint 13 ADR-011 GEX CERRADO ACEPTADO 100% post S.13.gex-c (commit aa78ad5). ADRs activos foundation: 10 Aceptados (001/002/004-009/011/013). Track A telemetry-c observation gate 4 conditions ALL unmet jueves 28 → today (0 días progress). Sprint 14 LOCKED Bundle B1 per fresh re-score rule #15 strict + bundle pattern Sprint 12 precedent.

---

## 1. Context

Sprint 14 priority analysis fresh re-score post Sprint 13 ADR-011 GEX Aceptado close-out. ADRs Aceptados cumulative: 10 (foundation core 7: ADR-005/006/007/008/009/011/013). ADR-010 WebSocket part 1 + ADR-012 HERMES NO existen aún (reserved slots ADR-008 D6).

**Key signals post Sprint 13**:
- Sprint 13 GEX delivered + Aceptado (Tier A signal generation complete via shared_core extension + ADR-011 §9 close-out + 35 NEW tests + 2 D6 amendments inline math accuracy Hull canonical).
- Tech debt accumulated 10 items unresolved (5 Sprint 11 ADR-013 §9.3 + 5 Sprint 13 ADR-011 §9.3 NEW).
- Telemetry-c re-activation gate state jueves 28: 4 conditions §4 ALL unmet (operator pre-deploy NOT done + flags False/False/empty + 0 production runs + 0 telemetry events).
- Track A observation Calendar time NO progress desde S.12.telemetry-c-deferred 890d75f.

**Reality verify**:
- HEAD aa78ad5 = origin/main. Working tree clean.
- Tests baseline preserved: multi-agent 895 + 4 failed (pre-existing) + 55 skipped + shared_core 131.
- 0 commits Sprint 14 pre-plan-a.

## 2. Scoring methodology

6 dimensions weighted Sprint 13 weights probadas sustained (NO change):

| Dimension | Weight | Rationale |
|-----------|--------|-----------|
| Foundation completion narrative | 20% | ADR-008 D6 sequencing canonical (ADR-010 + ADR-012 remaining) |
| Telemetry signal readiness | 20% | Operator gate impact + Track A re-activation potential |
| Cross-sprint tech debt impact | 15% | 10+ items unresolved cumulative |
| Risk asymmetry / paper trading discipline | 15% | Fail-loud vs silent drift |
| ADR prerequisite | 10% | Pure design vs implementation |
| Operator gate dependence | 20% | Independent vs USE_LIVE_PORTFOLIO required (Sprint 12 lesson) |

Telemetry data ZERO scoring decision (per D-β-4 Sprint 13 + D-γ-3 sustained): reality verbatim jueves 28, NO speculation future signal.

## 3. Candidates inventory (12 viable post-exclusions)

**Prime ADR-008 D6 sequencing remaining (2)**:
- #1 ADR-010 Schwab WebSocket part 1 (Tier D infra multi-sprint Sprint 14-15+).
- #2 ADR-012 HERMES tactical implementation (Sprint 14-16+, depends ADR-010 ready first).

**Sprint 11 tech debt unresolved (4)**:
- #3 Greeks D-η cross-source (ADR-013 §9.3 #1).
- #4 portfolio_beta D-κ cross-source (ADR-013 §9.3 #4).
- #5 PnL history D-θ table (ADR-013 §9.3 #2).
- #6 OCC ticker parser D-ι-A (ADR-013 §9.3 #3).

**Sprint 13 NEW tech debt (4 post-fold)**:
- #7 FRED API + per-ticker dividend bundle (ADR-011 §9.3 #1+#2 folded).
- #8 ATHENA prompt GexSnapshot consumer (ADR-011 §9.3 #3).
- #9 iv_surface real-DB freshness verify (ADR-011 §9.3 #4).
- #10 CachedGexBuilder pattern (ADR-011 §9.3 #5).

**Cross-cutting tech debt (1)**:
- #11 SchwabClient F-r16 4 instances (ADR-013 §9.3 #6 + ADR-005 §9.3 #1 reaffirmed).

**Meta-sprint (1)**:
- #12 Operator unblock sprint — Sprint 13 1st 4.00 numerical (strategic override deferred Sprint 13 → 14 RE-EVALUATION).

**Excluded scope Sprint 14**:
- F-r14 Protocol → ✓ RESOLVED Sprint 12.
- Paper trading telemetry → ✓ Track A parallel observation (NOT scope).
- ATHENA prompt v2 standalone → folded into #8 GexSnapshot consumer.

## 4. Scoring matrix (12 candidates × 6 dimensions weighted)

| Rank | # | Candidate | Found 20% | Tele 20% | Debt 15% | Risk 15% | ADR 10% | OpGate 20% | Weighted |
|------|---|-----------|-----------|----------|----------|----------|---------|------------|----------|
| 🥇 | 12 | **Operator unblock sprint** | 3 | 5 | 2 | 4 | 5 | 5 | **4.00 ← LOCKED B1** |
| 🥈 | 1 | ADR-010 WebSocket part 1 | 4 | 3 | 1 | 2 | 4 | 5 | 3.25 (tie) |
| 🥈 | 11 | **SchwabClient F-r16** | 2 | 3 | 4 | 3 | 2 | 5 | **3.25 ← LOCKED B1 (tie)** |
| 4 | 10 | CachedGexBuilder pattern | 2 | 3 | 3 | 3 | 2 | 5 | 3.10 |
| 5 | 7 | FRED API + dividend bundle | 2 | 3 | 3 | 2 | 2 | 5 | 2.95 |
| 6 | 5 | PnL history D-θ | 3 | 3 | 3 | 3 | 2 | 3 | 2.90 |
| 7 | 3 | Greeks D-η | 2 | 3 | 4 | 3 | 2 | 3 | 2.85 (tie) |
| 7 | 4 | portfolio_beta D-κ | 2 | 3 | 3 | 4 | 2 | 3 | 2.85 (tie) |
| 9 | 6 | OCC parser D-ι-A | 2 | 3 | 3 | 3 | 2 | 2 | 2.50 |
| 10 | 8 | ATHENA prompt consumer | 3 | 1 | 3 | 2 | 2 | 1 | 1.95 |
| 11 | 9 | iv_surface freshness verify | 2 | 1 | 2 | 2 | 1 | 1 | 1.50 |
| 12 | 2 | ADR-012 HERMES | 2 | 1 | 2 | 1 | 2 | 1 | 1.45 |

**Gap analysis**:
- #12 Operator (4.00) → #1/#11 tie (3.25) = 0.75 gap BIG (más decisivo Sprint 14 vs Sprint 13's 0.35).
- #1 ADR-010 = #11 F-r16 TIE 3.25.
- TIE → #10 CachedGex (3.10) = 0.15 tight.

## 5. Strategic decision: LOCK Bundle B1 (#12 + #11)

**Bundle B1**: Operator unblock sprint (4.00) + SchwabClient F-r16 cross-cutting (3.25).

**Strategic rationale**:

### 5.1 #12 alone "soft sprint" risk persists

Sprint 13 strategic override #9 → #2 GEX rationale was "deferred-heavy code sprint preferred over 30-min wall-clock + passive observation 'soft sprint' identity".

Sprint 14 reality cambió post-Sprint 13:
- Sprint 13 GEX delivered ✓ (Tier A complete, NO equivalent unlock pendiente single-sprint).
- ADR-010 multi-sprint commitment (NO single-sprint deliverable).
- Tech debt 10+ accumulated.
- Track A 0 días progress (gate ALL unmet sustained).

Pure #12 Sprint 14 = "soft sprint" risk PERPETUAL (deferring otra vez sin code deliverable). Bundle B1 elimina este riesgo.

### 5.2 #11 synergistic con #12

F-r16 4 SchwabClient instances → 1 singleton refactor improves Q5/R6 telemetry aggregate quality. Una vez #12 unlock data accumulating, F-r16 maximiza signal value (aggregate counts vs per-instance fragmented). Sprint 15 telemetry-c data signal BETTER quality if F-r16 done first.

### 5.3 Bundle pattern Sprint 12 Option C precedent

Sprint 12 Bundle Option C delivered (Protocol + Telemetry + Operator memo) = validated pattern. Sprint 14 Bundle B1 mirrors: Day 1 operator setup + Day 2-5 code refactor = atomic deliverable + Track A unlock.

### 5.4 Operator gate INDEPENDENT bundle

#11 F-r16 operator gate score 5 (pure refactor). #12 ES el operator gate itself. Both independent of USE_LIVE_PORTFOLIO/SCHWAB_ACCOUNT_ID gate state. Ejecutable Sprint 14 atomic.

### 5.5 Sprint 15+ viability boost

Sprint 14 Bundle B1 outputs:
- Track A telemetry-c calendar time accumulating 2+ weeks.
- F-r16 quality data captured (aggregate vs per-instance fragmented).
- Sprint 15 priority signal data-driven (vs scoring blind sin data).

**Caveat D-γ-3 sustained**: Track A observation OPEN parallel. Sprint 15+ retrospective re-validation per S.12.plan-a §7 mandate posible.

## 6. Sprint 14 expected sub-blocks plan (~6 sub-blocks)

| Sub-block | Phase | Scope | Estimate |
|-----------|-------|-------|----------|
| S.14.plan-a | THIS commit | Priority analysis + Bundle B1 LOCK | ~250 LOC doc |
| S.14.operator-a | Day 1 | Operator pre-deploy 5 actions §10.3 + initial runs setup + memo | ~50 LOC doc + portal actions |
| S.14.operator-b | Day 2 (parallel start) | Initial production runs verification + first telemetry events captured + observation log | ~80 LOC doc |
| S.14.f-r16-a | Day 2-3 | SchwabClient DI lifespan singleton refactor design + initial impl | ~150 LOC code |
| S.14.f-r16-b | Day 3-4 | F-r16 implementation completion + 8-12 NEW tests + cross-package verify | ~150 LOC code + 8-12 tests |
| S.14.bundle-c | Day 4-5 | Bundle close-out + ADR-005 + ADR-013 §9.3 amendments + DAILY_LOG | ~150 LOC doc + ADR amendments |

**Total estimate Sprint 14**: ~830 LOC doc+code+tests + ~8-12 NEW tests + operator portal actions.

## 7. Sprint 15+ TENTATIVE (re-score fresh per rule #15)

Sprint 14 LOCKED → Sprint 15 NOT pre-committed. Rule #15 strict TENTATIVE caveat doctrine 8x proven post Sprint 13.

**Candidates Sprint 15+ (re-score required)**:
- **#1 ADR-010 Schwab WebSocket part 1** (3.25 tied Sprint 14, Tier D infra remaining canonical).
- **Telemetry-c real close-out memo** (4 conditions §4 met post Sprint 14 operator unblock + 2+ weeks observation).
- **Sprint 11 tech debt unresolved 4 items** (Greeks D-η + portfolio_beta D-κ + PnL D-θ + OCC parser).
- **Sprint 13 NEW tech debt remaining** (FRED API + ATHENA prompt + iv_surface freshness + CachedGexBuilder).
- **#3 ADR-012 HERMES** (depends ADR-010 ready first, Sprint 16+ canonical).

**Telemetry-c re-activation criteria post Sprint 14 (parallel track A)**:
- Si 4 conditions §4 telemetry-c-deferred ALL met antes Sprint 15 plan-a → telemetry-c real close-out memo execution incluido Sprint 15 plan-a re-validation per S.12.plan-a §7 mandate.
- Si NOT met → continúa Track A observation + Sprint 15 candidates above + caveat D-γ-3 sustained.

## 8. Sub-decisions firmadas (Camino 2, "-9" suffix Sprint 14 plan-a)

Convention naming Sprint 14: "-9" suffix continúa secuencia (-2 Sprint 12 telemetry-b + -3 telemetry-c-deferred + -4 Sprint 13 plan-a + -5 adr-a + -6 gex-a + -7 gex-b + -8 gex-c + -9 Sprint 14 plan-a).

- **D-α-9**: Scoring dimensions 6 weights Sprint 13 sustained Sprint 14 (NO change). Validated 1x Sprint 13 lock decision (GEX 3.65 win).
- **D-β-9**: Telemetry data ZERO scoring Sprint 14 (reality verbatim jueves 28 + caveat D-γ-3 retrospective adjustment posible Sprint 15+).
- **D-γ-9**: Candidates fold #7 FRED + dividend bundle (ADR-011 §9.3 #1+#2 similar trigger source D-ε-7). Maintain #3 Greeks + #4 portfolio_beta separate (different effort profiles).
- **D-δ-9**: ATHENA prompt v2 EXCLUDED scope Sprint 14 standalone, folded into #8 GexSnapshot consumer (data-dependent post telemetry-c).
- **D-ε-9**: Bundle B1 LOCKED strategic override numerical winner #12 alone. Pattern Sprint 12 Option C precedent validated. Avoid "soft sprint" risk perpetual + tech debt clearance ROI + synergistic Q5/R6 telemetry quality + operator gate independent.
- **D-ζ-9**: 6 sub-blocks Sprint 14 plan (plan-a + operator-a/b + f-r16-a/b + bundle-c). Mirror Sprint 11 atlas multi-package + Sprint 12 Bundle Option C atomic close-out pattern.

## 9. References

- ADR-008 D6 sequencing (Aceptado) — canonical Sprint 14+ candidates ordering.
- ADR-011 §9.4 (Aceptado, commit aa78ad5) — Sprint 14+ candidates TENTATIVE.
- ADR-013 §9.3 (Aceptado, commit 6f51efb) — Sprint 11 tech debt inventory.
- S.13.plan-a (commit ad04665) — Sprint 13 scoring methodology + bundle precedent.
- S.13.gex-c (commit aa78ad5) — Sprint 13 close-out + ADR-011 Aceptado.
- S.12.telemetry-c-deferred (commit 890d75f) — Track A observation gate + D-γ-3 caveat.
- Operator doc `docs/operator/schwab-setup.md` §10.3 — pre-deploy 5 actions.
