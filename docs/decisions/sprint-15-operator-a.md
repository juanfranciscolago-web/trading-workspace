# Sprint 15 Operator Pre-Deploy Reaffirm + Handoff (S.15.operator-a)

**Fecha:** 2026-05-29 (viernes, cross-midnight session continuation desde jueves 28)
**Sprint:** Sprint 15 Bundle C3 (#11 Operator unblock + #1 ADR-010 WebSocket part 1)
**Sub-block:** S.15.operator-a — Day 1 Operator pre-deploy reaffirm + handoff
**Estado:** Decidido (operator runbook canonical reaffirm + handoff status, NO duplicate runbook). Operator portal action async paralelo NO ejecutada jueves 28 → viernes 29 sostenido.
**Companion docs:** `docs/operator/sprint-14-pre-deploy-runbook.md` (8997fba, CANONICAL runbook S.14.operator-a) + `docs/decisions/sprint-15-priority-analysis.md` (1da261a, Bundle C3 LOCK).

---

## 1. Context

Sprint 15 Bundle C3 LOCKED via S.15.plan-a (commit 1da261a, viernes 29-may). Bundle C3 = #11 Operator unblock sprint (4.00, 3er sprint consecutivo numerical winner) + #1 ADR-010 WebSocket part 1 (3.25). 3rd-time deferral problem resolution Sprint 15.

**Runbook canonical**: `docs/operator/sprint-14-pre-deploy-runbook.md` (8997fba) entrega 7 sections completas (5 pre-deploy actions ordered + fail-fast contract D-ν validation + first boot validation + 3 telemetry events expected + daily log template + re-activation criteria checkbox). **NO duplicate runbook Sprint 15** (preserves Sprint 14 atomic + canonical single source of truth).

**S.15.operator-a scope mínimo**: reaffirm canonical runbook + handoff status documentation + sub-decisions firmadas. NO modify operator pre-deploy procedure.

## 2. Runbook canonical reaffirm

**Procedure unchanged Sprint 14 → Sprint 15**:

Reference canonical: `docs/operator/sprint-14-pre-deploy-runbook.md`

5 pre-deploy actions ordered (per runbook §2):
- Action 1: Schwab portal create paper subaccount distinct from Eolo bots.
- Action 2: Note accountNumber numerical string.
- Action 3: Edit .env add SCHWAB_ACCOUNT_ID.
- Action 4: Edit .env add USE_LIVE_PORTFOLIO=True.
- Action 5: Edit .env add USE_SCHWAB_DATA_LAYER=True.

Fail-fast contract D-ν validation (per runbook §3): code path verified existing Sprint 11 atlas-e (commit bfc297f) en `multi-agent-system/src/multi_agent/api/app.py:_build_snapshot_builder()`.

First boot validation (per runbook §4): LiveSnapshotBuilder active + account_id verified + TTL=30s + 4 Workers active + no regression.

3 first telemetry events expected (per runbook §5):
- rate_limiter_throttled (Q5 instrumentation Sprint 12 telemetry-b).
- schwab_429_throttled optional (R6 instrumentation Sprint 12 telemetry-b).
- athena_prompt_metrics (Q7 instrumentation Sprint 12 telemetry-b, Sprint 15+ explicit trigger required per F-r ant #5 S.14.operator-a).

## 3. Handoff status viernes 29 reality verify

**.env current state** (sanitized, NO secrets exposure):
- USE_LIVE_PORTFOLIO: NOT set en .env (config default False).
- USE_SCHWAB_DATA_LAYER: NOT set en .env (config default False).
- SCHWAB_ACCOUNT_ID: NOT set en .env (config default empty).

**Production logs**: `multi-agent-system/logs/` vacío (0 production runs accumulated post Sprint 14 close jueves 28 → viernes 29).

**Track A telemetry-c re-activation gate state viernes 29** (per S.12.telemetry-c-deferred §4):

| Condition | State viernes 29 |
|-----------|------------------|
| 1. Operator pre-deploy 5 steps §10.3 | NOT done |
| 2. USE_LIVE_PORTFOLIO=True + USE_SCHWAB_DATA_LAYER=True | False/False defaults |
| 3. 2+ weeks runs minimum | 0 runs |
| 4. First telemetry events captured | 0 events |

**Status**: ALL 4 conditions ALL unmet jueves 28 → viernes 29. Calendar time 0 días progress sostenido desde S.12.telemetry-c-deferred 890d75f.

## 4. S.15.operator-b dependency

S.15.operator-b real execution requires ALL 4 conditions §4 telemetry-c-deferred met (mirror Sprint 14 operator-b deferred pattern + S.12.telemetry-c-deferred §4):

1. Operator pre-deploy completed (Actions 1-5 §2 above).
2. Settings flags ON (USE_LIVE_PORTFOLIO + USE_SCHWAB_DATA_LAYER).
3. First boot validation passed (LiveSnapshotBuilder + account_id + 4 Workers).
4. First telemetry events captured (at least 1 of each type).

Si ALL 4 met → S.15.operator-b real execution viable (initial production runs verification + first telemetry events log memo).
Si NOT met (sustained current state) → continúa DEFERRED similar Sprint 14 operator-b pattern.

**Bundle C3 dual-track operational sustained Sprint 15**:
- Track A: Operator portal action async paralelo (operator responsibility, calendar time 2+ weeks observation requirement post action).
- Track B: Sprint 15 code/ADR work (S.15.adr-a ADR-010 design + S.15.ws-a Phase 1 impl + S.15.bundle-c close-out) independent operator gate.

## 5. Sub-decisions firmadas (Camino 2, -15 suffix Sprint 15 operator-a)

- **D-α-15**: NO duplicate runbook S.14.operator-a 8997fba (preserves Sprint 14 atomic, canonical reference single source of truth). S.15.operator-a = reaffirm + handoff status only.
- **D-β-15**: MINIMAL handoff memo NEW `docs/decisions/sprint-15-operator-a.md` (~70 LOC) separado de runbook canonical 8997fba (mirror Sprint 12 telemetry-c-deferred sub-block memo pattern emergent + Sprint 14 bundle-b1-deferred sub-block memo pattern sustained).
- **D-γ-15**: 4 conditions §4 telemetry-c-deferred verbatim status reaffirm (NOT change conditions, preserve canonical re-activation criteria Sprint 12 D-α-3 pattern).
- **D-δ-15**: NO operator portal action ejecutada Claude Code (operator manual async). Sprint 15 operator-b deferred similar Sprint 14 operator-b pattern (mirror "deferred sub-block" emergent pattern Sprint 12 → Sprint 14 → Sprint 15 sustained 3rd iteration).
- **D-ε-15**: Sprint 15 Bundle C3 dual-track sustained: Track A operator action async (operator responsibility) + Track B code/ADR work (S.15.adr-a ADR-010 design + S.15.ws-a Phase 1 impl + S.15.bundle-c close-out next). Sprint 15 = 5-6 sub-blocks total estimate (per S.15.plan-a §6).

---

## References

- ADR-008 D6 sequencing (Aceptado) — canonical Sprint 15+ candidates ordering ADR-010.
- S.15.plan-a (commit 1da261a, viernes 29-may) — Sprint 15 Bundle C3 LOCK strategic rationale.
- S.14.operator-a (commit 8997fba, jueves 28-may) — CANONICAL runbook pre-deploy 5 actions + fail-fast contract D-ν validation procedure.
- S.14.bundle-c (commit 4a42df5, jueves 28-may) — Sprint 14 close-out parcial 83% + Sprint 14 operator-b DEFERRED precedent.
- S.12.telemetry-c-deferred (commit 890d75f, jueves 28-may) — Track A re-activation gate 4 conditions canonical.
