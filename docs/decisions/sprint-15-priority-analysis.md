# Sprint 15 Priority Analysis — Bundle C3 (Operator unblock + ADR-010 WebSocket part 1) LOCKED

**Fecha:** 2026-05-29 (viernes)
**Estado:** Decidido (Sprint 15 = Bundle C3 Operator unblock #11 4.00 + ADR-010 WebSocket part 1 #1 3.25 LOCKED, bundle pattern Sprint 12 + 14 precedent validated 2x)
**Contexto:** Sprint 14 Bundle B1 CERRADO PARCIALMENTE 83% post S.14.bundle-c (commit 4a42df5, jueves 28 May 2026). ADRs activos foundation: 10 Aceptados (001/002/004-009/011/013). Track A telemetry-c observation gate 4 conditions ALL unmet jueves 28 → viernes 29 (1 día calendar, 0 días observation progress post Sprint 14 close). Sprint 15 LOCKED Bundle C3 per fresh re-score rule #15 strict + bundle pattern Sprint 12 + 14 precedent + 3rd-time deferral problem resolution.

---

## 1. Context

Sprint 15 priority analysis fresh re-score post Sprint 14 Bundle B1 close-out parcial. ADRs Aceptados cumulative: 10 (foundation core 7: ADR-005/006/007/008/009/011/013). ADR-010 WebSocket part 1 + ADR-012 HERMES NO existen aún (reserved slots ADR-008 D6).

**Key signals post Sprint 14**:
- Sprint 14 Bundle B1 F-r16 RESOLVED (2 items cluster-resolved ADR-013 §9.3 #6 + ADR-005 §9.3 #1).
- Tech debt cumulative 9 items unresolved (4 Sprint 11 ADR-013 §9.3 + 5 Sprint 13 ADR-011 §9.3).
- Telemetry-c re-activation gate state viernes 29: 4 conditions §4 ALL unmet (operator pre-deploy NOT done + flags False/False/empty + 0 production runs + 0 telemetry events).
- Track A observation Calendar time NO progress desde S.12.telemetry-c-deferred 890d75f.
- #11 Operator unblock 3er sprint consecutivo numerical winner (Sprint 13 + Sprint 14 deferred).

**Reality verify**:
- HEAD 4a42df5 = origin/main. Working tree clean.
- Tests baseline preserved: multi-agent 904 + 4 failed (pre-existing) + 55 skipped + shared_core 131.
- 0 commits Sprint 15 pre-plan-a.

## 2. Scoring methodology

6 dimensions weighted Sprint 13+14 weights probadas sustained (validated 2x):

| Dimension | Weight | Rationale |
|-----------|--------|-----------|
| Foundation completion narrative | 20% | ADR-008 D6 sequencing canonical (ADR-010 + ADR-012 remaining) |
| Telemetry signal readiness | 20% | Operator gate impact + Track A re-activation potential |
| Cross-sprint tech debt impact | 15% | 9 items cumulative unresolved (down from 10 post Sprint 14) |
| Risk asymmetry / paper trading discipline | 15% | Fail-loud vs silent drift |
| ADR prerequisite | 10% | Pure design vs implementation |
| Operator gate dependence | 20% | Independent vs USE_LIVE_PORTFOLIO required (Sprint 12 lesson) |

Telemetry data ZERO scoring decision sustained (per D-β-4 Sprint 13 + D-γ-3 + D-β-9 Sprint 14): reality verbatim Sprint 15 = Sprint 14 (0 días observation progress).

## 3. Candidates inventory (11 viable post-F-r16 RESOLVED removed)

**Prime ADR-008 D6 sequencing remaining (2)**:
- #1 ADR-010 Schwab WebSocket part 1 (Tier D infra multi-sprint Sprint 15-16+).
- #2 ADR-012 HERMES tactical implementation (Sprint 15-16+, depends ADR-010 ready first).

**Sprint 11 tech debt unresolved (4)**:
- #3 Greeks D-η cross-source (ADR-013 §9.3 #1).
- #4 portfolio_beta D-κ cross-source (ADR-013 §9.3 #4).
- #5 PnL history D-θ table (ADR-013 §9.3 #2).
- #6 OCC ticker parser D-ι-A (ADR-013 §9.3 #3).

**Sprint 13 NEW tech debt (4 post-fold sustained)**:
- #7 FRED API + per-ticker dividend bundle (ADR-011 §9.3 #1+#2 folded D-γ-9 Sprint 14).
- #8 ATHENA prompt GexSnapshot consumer (ADR-011 §9.3 #3).
- #9 iv_surface real-DB freshness verify (ADR-011 §9.3 #4).
- #10 CachedGexBuilder pattern (ADR-011 §9.3 #5).

**Meta-sprint (1)**:
- #11 Operator unblock sprint — Sprint 13 + Sprint 14 numerical winner 4.00 (deferred 2 sprints, Sprint 15 = "now or never" pattern).

**Excluded scope Sprint 15**:
- F-r14 Protocol → ✓ RESOLVED Sprint 12.
- F-r16 SchwabClient → ✓ RESOLVED Sprint 14 Bundle B1.
- Paper trading telemetry → ✓ Track A parallel observation (NOT scope).
- ATHENA prompt v2 standalone → folded into #8 GexSnapshot consumer.

## 4. Scoring matrix (11 candidates × 6 dimensions weighted)

| Rank | # | Candidate | Found 20% | Tele 20% | Debt 15% | Risk 15% | ADR 10% | OpGate 20% | Weighted |
|------|---|-----------|-----------|----------|----------|----------|---------|------------|----------|
| 🥇 | 11 | **Operator unblock sprint** | 3 | 5 | 2 | 4 | 5 | 5 | **4.00 ← LOCKED C3 (3rd consecutive)** |
| 🥈 | 1 | **ADR-010 WebSocket part 1** | 4 | 3 | 1 | 2 | 4 | 5 | **3.25 ← LOCKED C3** |
| 🥉 | 10 | CachedGexBuilder pattern | 2 | 3 | 3 | 3 | 2 | 5 | 3.10 |
| 4 | 7 | FRED API + dividend bundle | 2 | 3 | 3 | 2 | 2 | 5 | 2.95 |
| 5 | 5 | PnL history D-θ | 3 | 3 | 3 | 3 | 2 | 3 | 2.90 |
| 6 | 3 | Greeks D-η | 2 | 3 | 4 | 3 | 2 | 3 | 2.85 (tie) |
| 6 | 4 | portfolio_beta D-κ | 2 | 3 | 3 | 4 | 2 | 3 | 2.85 (tie) |
| 8 | 6 | OCC parser D-ι-A | 2 | 3 | 3 | 3 | 2 | 2 | 2.50 |
| 9 | 8 | ATHENA prompt consumer | 3 | 1 | 3 | 2 | 2 | 1 | 1.95 |
| 10 | 9 | iv_surface freshness verify | 2 | 1 | 2 | 2 | 1 | 1 | 1.50 |
| 11 | 2 | ADR-012 HERMES | 2 | 1 | 2 | 1 | 2 | 1 | 1.45 |

**Gap analysis**:
- #11 Operator (4.00) → #1 ADR-010 (3.25) = 0.75 SAME Sprint 14 (sustained decisive gap).
- #1 (3.25) → #10 (3.10) = 0.15 tight.

## 5. Strategic decision: LOCK Bundle C3 (#11 + #1)

**Bundle C3**: Operator unblock sprint (4.00) + ADR-010 WebSocket part 1 (3.25).

**Strategic rationale**:

### 5.1 #11 Operator unblock 3rd-time deferral problem resolution

Sprint 13 + Sprint 14 strategic override #11 → code work bundles (GEX + F-r16 Bundle B1). Sprint 15 reality:
- Sprint 13 GEX delivered ✓ (Tier A signal complete).
- Sprint 14 F-r16 RESOLVED ✓ (cross-cutting tech debt cluster).
- Tech debt 9 items remaining (paper trading + operator-dependent mayoría).
- Track A 0 días progress sustained (operator portal action async paralelo NO ejecutada).

**3rd-time deferral problem**: Si Sprint 15 deferimos #11 OTRA vez = rule #15 numerical scoring permanently overridden = doctrine credibility erosion.

**Sprint 15 = "now or never" para #11 Operator unblock**: pattern restored numerical winner respected.

### 5.2 ADR-010 foundation completion narrative

#1 ADR-010 WebSocket part 1 = last remaining Tier D ADR ADR-008 D6 canonical:
- ADRs Aceptados activos hoy 10 (007 + 009 + 011 + 4 Sprint 11+ + foundation core 005/006/008/013).
- ADR-010 Aceptado Sprint 16+ → 11 ADRs Aceptados milestone.
- HERMES Sprint 16-18 viable post ADR-010 (depends ADR-010 ready first).
- Tier D real-time L2/tape REST → WebSocket migration narrative.

**Foundation completion narrative restored Sprint 15** = strategic value mayor vs CachedGexBuilder closure polish.

### 5.3 Bundle pattern Sprint 12 + 14 precedent validated 2x

Sprint 12 Bundle Option C delivered (Protocol + Telemetry + Operator memo) = validated pattern.
Sprint 14 Bundle B1 delivered (Operator + F-r16) = validated pattern.
Sprint 15 Bundle C3 (Operator + ADR-010) = pattern continuation 3rd time.

**Dual-track value sustained**: Day 1 operator setup + Day 2-5 code/ADR design = atomic deliverable + Track A unlock + code work avance.

### 5.4 Operator gate INDEPENDENT bundle

#11 ES el operator gate itself (score 5). #1 ADR-010 operator gate INDEPENDENT (score 5, Schwab WebSocket auth no subaccount required). Both independent of USE_LIVE_PORTFOLIO/SCHWAB_ACCOUNT_ID gate state. Ejecutable Sprint 15 atomic.

### 5.5 Multi-sprint ADR-010 commitment honest acknowledged

ADR-010 NO single-sprint deliverable. Sprint 15 Bundle C3 = ADR-010 Phase 1:
- ADR-010 design plan firmed (Propuesto ADR document ~250-300 LOC).
- Initial WebSocket infra setup (~50% Phase 1).
- Tests basic auth + connection (~5-8 NEW tests).

Sprint 16+ ADR-010 Phase 2 completion + ADR-012 HERMES design start.

**Caveat D-γ-3 sustained**: Track A observation OPEN parallel Sprint 15 → Sprint 16+. Sprint 16+ retrospective re-validation per S.12.plan-a §7 mandate posible cuando data exists.

## 6. Sprint 15 expected sub-blocks plan (~5-6 sub-blocks)

| Sub-block | Phase | Scope | Estimate |
|-----------|-------|-------|----------|
| S.15.plan-a | THIS commit | Priority analysis + Bundle C3 LOCK | ~280 LOC doc |
| S.15.operator-a | Day 1 | Operator pre-deploy 5 actions §10.3 reaffirm + handoff | ~50 LOC doc + portal actions |
| S.15.adr-a | Day 2-3 | ADR-010 Propuesto design plan firmed | ~280 LOC doc ADR |
| S.15.ws-a | Day 3-4 | ADR-010 Phase 1 initial impl WebSocket auth + connection + 5-8 NEW tests | ~200 LOC code + 5-8 tests |
| S.15.operator-b | Day 4 (parallel) | Operator portal action complete verify + first telemetry events log | ~80 LOC doc |
| S.15.bundle-c | Day 5 | Bundle close-out + ADR-010 status confirm + DAILY_LOG amend | ~180 LOC doc |

**Total estimate Sprint 15**: ~1,070 LOC doc+code+tests + ~5-8 NEW tests + operator portal actions.

## 7. Sprint 16+ TENTATIVE (re-score fresh per rule #15)

Sprint 15 LOCKED → Sprint 16 NOT pre-committed. Rule #15 strict TENTATIVE caveat doctrine 9x proven post Sprint 14.

**Candidates Sprint 16+ (re-score required)**:
- **ADR-010 Phase 2 completion** (Sprint 15 Phase 1 → Sprint 16 Phase 2 multi-sprint continuation).
- **ADR-012 HERMES tactical design** (depends ADR-010 Phase 2 ready first).
- **Telemetry-c real close-out memo** (4 conditions §4 met post Sprint 15 operator unblock + 2+ weeks observation).
- **Sprint 11 tech debt unresolved 4 items** (Greeks D-η + portfolio_beta D-κ + PnL D-θ + OCC parser).
- **Sprint 13 NEW tech debt remaining** (FRED API + ATHENA prompt + iv_surface freshness + CachedGexBuilder).

**Telemetry-c re-activation criteria post Sprint 15 (parallel track A)**:
- Si 4 conditions §4 telemetry-c-deferred ALL met antes Sprint 16 plan-a → telemetry-c real close-out memo execution incluido Sprint 16 plan-a re-validation per S.12.plan-a §7 mandate.
- Si NOT met → continúa Track A observation + Sprint 16 candidates above + caveat D-γ-3 sustained.

## 8. Sub-decisions firmadas (Camino 2, "-14" suffix Sprint 15 plan-a)

Convention naming Sprint 15: "-14" suffix continúa secuencia (-9 a -13 Sprint 14).

- **D-α-14**: Scoring dimensions 6 weights Sprint 13+14 sustained Sprint 15 (NO change). Validated 2x previous sprints (GEX 3.65 Sprint 13 + Bundle B1 wins Sprint 14).
- **D-β-14**: Telemetry data ZERO scoring Sprint 15 (reality verbatim Sprint 15 = Sprint 14 + caveat D-γ-3 retrospective adjustment posible Sprint 16+).
- **D-γ-14**: Candidates 11 viable post-F-r16 RESOLVED removed. Sprint 11 tech debt 4 items maintain separate (different effort profiles).
- **D-δ-14**: Bundle C3 LOCKED strategic 3rd-time deferral problem resolution + foundation completion narrative + bundle pattern Sprint 12+14 precedent validated 2x.
- **D-ε-14**: 5-6 sub-blocks Sprint 15 plan (plan-a + operator-a/b + adr-a + ws-a + bundle-c). Multi-sprint ADR-010 commitment Sprint 15-16+ honest acknowledged (Sprint 15 = Phase 1 only).
- **D-ζ-14**: ADR-010 status Sprint 15 = Propuesto (NOT Aceptado). Sprint 16+ Phase 2 completion + Aceptado milestone.

## 9. References

- ADR-008 D6 sequencing (Aceptado) — canonical Sprint 15+ candidates ordering.
- ADR-011 §9.4 (Aceptado, commit aa78ad5) — Sprint 14+ candidates TENTATIVE.
- ADR-013 §9.3 (Aceptado, commit 6f51efb + Sprint 14 #6 RESOLVED amendment 4a42df5) — Sprint 11 tech debt inventory.
- ADR-005 §9.3 (Aceptado, Sprint 14 #1 RESOLVED amendment 4a42df5) — SchwabClient F-r16 cross-cutting cluster-resolved.
- S.14.plan-a (commit 5536940) — Sprint 14 Bundle B1 priority analysis + bundle pattern.
- S.14.bundle-c (commit 4a42df5) — Sprint 14 close-out parcial 83% + Sprint 15+ TENTATIVE.
- S.13.plan-a (commit ad04665) — Sprint 13 scoring methodology + bundle precedent.
- S.12.telemetry-c-deferred (commit 890d75f) — Track A observation gate + D-γ-3 caveat.
- Operator doc `docs/operator/sprint-14-pre-deploy-runbook.md` — pre-deploy 5 actions canonical.
