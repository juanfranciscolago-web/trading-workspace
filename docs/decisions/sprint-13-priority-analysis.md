# Sprint 13 Priority Analysis — ADR-011 GEX Compute Pipeline LOCKED

**Fecha:** 2026-05-28 (jueves)
**Estado:** Decidido (Sprint 13 = ADR-011 GEX compute pipeline LOCKED, strategic override numerical winner #9 Operator unblock 4.00 vs #2 GEX 3.65 gap 0.35)
**Contexto:** Sprint 12 Bundle Option C cerrado parcialmente 80% post S.12.telemetry-c-deferred (commit 890d75f). Track A telemetry-c observation OPEN parallel. Sprint 13 arrancable per D-γ-3 caveat operator override jueves 28 (caveat: retrospective adjustment posible cuando telemetry-c data exists). Re-score fresh per rule #15 strict ejecutado.

---

## 1. Context

Sprint 13 priority analysis fresh re-score post Sprint 12 close-out parcial. ADR-008 D6 sequencing canonical Sprint 13+ candidates: ADR-010/011/012 ALL undelivered Sprint 11-12 (ATLAS + Bundle Option C took precedence). Sprint 12 telemetry-c observation window OPEN (Track A) — Sprint 13 arrancable independent track (Track B per D-γ-3 dual track operational pattern).

Re-score fresh per rule #15 strict TENTATIVE caveat doctrine 6x proven (Sprints 8/9/10/11/12 close + jueves 28). NO pre-committed Sprint 13. Verify reality + score fresh + LOCK explicit operator sign-off.

## 2. Scoring methodology

6 dimensions weighted (revisadas Sprint 13, Sprint 12 lesson aplicado):

| Dimension | Weight | Rationale |
|-----------|--------|-----------|
| Foundation completion narrative | 20% | ADR-008 D6 sequencing canonical (was 25%, decreased balance) |
| Telemetry signal readiness | 20% | Operator gate impact (Sprint 12 lesson) |
| Cross-sprint tech debt impact | 15% | Resolved debt clears Sprint 14+ blockers (was 20%, decreased balance) |
| Risk asymmetry / paper trading discipline | 15% | Fail-loud vs silent drift |
| ADR prerequisite | 10% | Pure design/ADR vs implementation |
| **Operator gate dependence (NEW)** | **20%** | Independent vs USE_LIVE_PORTFOLIO required (Sprint 12 reveal) |

Telemetry data ZERO scoring decision (per D-γ-3 caveat): score con reality verbatim jueves 28 (production runs accumulated = 0), NO speculation future telemetry signal. Retrospective adjustment posible Sprint 14+ cuando data exists.

## 3. Candidates inventory (9 viable post-exclusions)

**Prime ADR-008 D6 sequencing (3)**:
- #1 ADR-010 Schwab WebSocket part 1 (Tier D infra, multi-sprint Sprint 13-14).
- #2 ADR-011 GEX compute pipeline (Tier A dealer flows).
- #3 ADR-012 HERMES tactical implementation (Sprint 13-16+ canonical timeline).

**Tech debt resolution (4)**:
- #5 Greeks D-η cross-source (ADR-013 §9.3 #1).
- #6 portfolio_beta D-κ cross-source (ADR-013 §9.3 #4).
- #7 PnL history D-θ table (ADR-013 §9.3 #2).
- #8 SchwabClient 4 instances F-r16 cross-cutting (ADR-013 §9.3 #6 + ADR-005 §9.3 #1 reaffirmed).

**Meta-sprint (1)**:
- #9 Operator unblock sprint (NEW): pre-deploy 5 actions §10.3 + initial production runs ramp-up + accelerate Track A re-activation.

**Excluded (post-Sprint 12)**:
- #4 ATHENA prompt v2 → premature sin telemetry-c data signal.
- F-r14 Protocol refactor → ✓ RESOLVED S.12.protocol-a e76e879.
- Paper trading telemetry → ✓ OPEN Track A observation (NOT Sprint 13 scope).

## 4. Scoring matrix (9 candidates × 6 dimensions weighted)

| Rank | # | Candidate | Found 20% | Tele 20% | Debt 15% | Risk 15% | ADR 10% | OpGate 20% | Weighted |
|------|---|-----------|-----------|----------|----------|----------|---------|------------|----------|
| 🥇 | 9 | Operator unblock sprint | 3 | 5 | 2 | 4 | 5 | 5 | 4.00 |
| 🥈 | 2 | **ADR-011 GEX compute** | **4** | **4** | **2** | **3** | **3** | **5** | **3.65 ← LOCKED** |
| 🥉 | 8 | SchwabClient F-r16 | 2 | 3 | 4 | 3 | 2 | 5 | 3.25 |
| 4 | 1 | ADR-010 WebSocket part 1 | 3 | 3 | 1 | 2 | 4 | 5 | 3.05 |
| 5 | 7 | PnL history D-θ | 3 | 3 | 3 | 3 | 2 | 3 | 2.90 |
| 6 | 5 | Greeks D-η | 2 | 3 | 4 | 3 | 2 | 3 | 2.85 |
| 6 | 6 | portfolio_beta D-κ | 2 | 3 | 3 | 4 | 2 | 3 | 2.85 |
| 8 | 3 | ADR-012 HERMES | 2 | 1 | 2 | 1 | 2 | 1 | 1.45 |

Gap top 3: #9 (4.00) → #2 (3.65) = 0.35 decisive numerically. #2 → #8 (3.25) = 0.40 decisive. #8 → #1 (3.05) = 0.20 tight.

## 5. Strategic decision: LOCK #2 ADR-011 GEX (override numerical winner #9)

**Numerical winner**: #9 Operator unblock sprint (4.00).
**LOCKED**: #2 ADR-011 GEX compute pipeline (3.65).

**Strategic override rationale**:
- #9 Operator unblock = meta-sprint "soft sprint" identity risk (no code deliverable, ~30 min wall-clock execution + passive monitoring).
- #2 ADR-011 GEX = deliverable-heavy code sprint con Tier A signal generation unlock (ATHENA dealer flow regime).
- iv_surface (Sprint 7 ✓) + OI (Sprint 9 ✓) data deps ready → NO blockers.
- Operator gate INDEPENDENT (score 5) → ejecutable jueves 28 sin operator pre-deploy.
- Sprint 12 lesson "building blind" caveat: GEX signals sin paper trading validation = unverifiable claim. **Mitigation**: GEX compute pipeline validates against known SpotGamma/Vanna patterns offline (Sprint 13 scope) + paper trading validation Sprint 14+ post telemetry-c data signal.

**Caveat D-γ-3 sustained**: Track A telemetry-c observation OPEN parallel. Cuando data exists (4 conditions §4 telemetry-c-deferred), Sprint 14+ priority re-validation puede ajustar retrospectively. GEX Sprint 13 NO bloqueado por this.

## 6. Sprint 13 expected sub-blocks plan (~5 sub-blocks)

| Sub-block | Phase | Scope | Estimate |
|-----------|-------|-------|----------|
| S.13.plan-a | THIS commit | Priority analysis + GEX lock | ~250 LOC doc |
| S.13.adr-a | Day 1 | ADR-011 design plan firmed (D1-D10 GEX decisions) | ~250-300 LOC doc ADR-011 |
| S.13.gex-a | Day 2-3 | GEX core compute pipeline (gamma exposure formula + aggregation) | ~300-400 LOC code + 10-15 tests |
| S.13.gex-b | Day 3-4 | Vanna/Charm compute (second-order Greeks aggregation) | ~200-300 LOC code + 8-12 tests |
| S.13.gex-c | Day 4-5 | Integration tests + benchmark vs SpotGamma reference data + close-out | ~150 LOC tests + doc |

**Total estimate Sprint 13**: ~1,150-1,400 LOC doc+code+tests + ~25-35 tests.
**Total tests Sprint 13 esperado**: ~25-35 NEW (mirror Sprint 11 atlas-b/c/d/e +41 cumulative).

## 7. Sprint 14+ TENTATIVE (re-score fresh per rule #15)

Sprint 13 LOCKED → Sprint 14 NOT pre-committed. Rule #15 strict TENTATIVE caveat doctrine 7x proven post jueves 28.

**Candidates Sprint 14+ (re-score required)**:
- ADR-010 Schwab WebSocket part 1 (Tier D infra, Sprint 13 last-place 3.05 + multi-sprint pattern Sprint 14-15).
- #9 Operator unblock sprint (numerical winner Sprint 13 deferred + accelerates Track A re-activation).
- #8 SchwabClient F-r16 cross-cutting (3.25 third-place Sprint 13).
- ADR-012 HERMES Sprint 14-16+ (depends on ADR-010 ready first).

**Telemetry-c re-activation criteria (parallel track A)**:
- Si 4 conditions §4 telemetry-c-deferred ALL met antes Sprint 14 plan-a → telemetry-c real close-out memo execution incluido en Sprint 14 plan-a re-validation per plan-a §7 mandate.
- Si NOT met → Sprint 14 continúa con candidates above + Track A observation continues calendar time accumulation.

## 8. Sub-decisions firmadas (Camino 2, -4 suffix Sprint 13 plan-a)

Convention naming Sprint 13: "-4" suffix continúa Greek letters (-2 Sprint 12 telemetry-b + -3 Sprint 12 telemetry-c-deferred + -4 Sprint 13 plan-a).

- **D-α-4**: Scoring weights revisadas Sprint 13 (Foundation 20% + Operator gate NEW 20%). Sprint 12 lesson aplicado: operator gate dependence merece weight major (was 10% propuesto → 20% adoptado).
- **D-β-4**: Telemetry data ZERO scoring decision (NO speculation future signal). Reality verbatim jueves 28 + caveat D-γ-3 retrospective adjustment posible Sprint 14+.
- **D-γ-4**: #4 ATHENA prompt v2 EXCLUDED scope (premature sin telemetry data). Sprint 14+ post telemetry-c viable.
- **D-δ-4**: #9 Operator unblock sprint INCLUDED as NEW candidate (meta-sprint pattern emergent). Numerical winner pero strategic override por "soft sprint" risk.
- **D-ε-4**: Strategic LOCK #2 ADR-011 GEX override numerical winner #9. Justification: Tier A signal unlock + deliverable code sprint + operator gate independent + data deps ready.

## 9. References

- ADR-008 D6 sequencing (Aceptado) — canonical Sprint 13+ candidates ordering source.
- ADR-013 §9.4 (Aceptado, commit 6f51efb) — Sprint 12+ candidates propuesto.
- S.12.plan-a (commit af0ee36) — Bundle Option C precedent + §7 Sprint 13 mandate.
- S.12.telemetry-c-deferred (commit 890d75f) — Track A observation gate + Sprint 13 caveat D-γ-3.
- Sprint 11 ADR-013 §9.3 — tech debt 6 items (1 resolved Sprint 12, 5 unresolved candidates).
- Sprint 10 ADR-009 §9.4 Q1-Q7 — telemetry-driven items deferred telemetry-c.
