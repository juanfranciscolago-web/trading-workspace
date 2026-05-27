# Sprint 12 Telemetry Setup Memo — Phase 1 Observation

**Fecha:** 2026-05-26
**Estado:** Decidido (Bundle Option C Day 3 telemetry stage, S.12.telemetry-b + telemetry-c pending)
**Contexto:** Sprint 11 ATLAS portfolio integration cerrado (commit `6f51efb`, ADR-013 Aceptado 2026-05-26). Sprint 12 LOCKED Bundle Option C Protocol + Telemetry hybrid (commit `af0ee36`). Day 1-2 Protocol refactor cerrado (commit `e76e879`, F-r14 ADR-013 §9.3 #5 resolved). Day 3 telemetry setup memo establece scope + observation procedure pre-deploy.

---

## 1. Context

Sprint 12 Bundle Option C Day 3 phase. Telemetry stage activa observation procedures post-deploy USE_LIVE_PORTFOLIO=True + USE_SCHWAB_DATA_LAYER=True. 4 triggers Q5/Q7/R6/F-r6.5 observados simultaneously per S.12.plan-a multi-trigger unlock rationale.

NO formal ADR (per S.12.plan-a "no formal ADR" — telemetry-a es memo + operator doc extension only). Memo + operator §11 = canonical reference para Phase 1 observation.

## 2. Observation triggers (4)

### 2.1 Q5: Schwab API rate limit validation (ADR-009 §9.4 #5)

**Status amendment Sprint 11**: ver §2.5 cross-ADR drift catches.

**Observation approach**:
- RateLimiter wait_if_needed() invocations logged.
- 429 HTTP responses captured.
- Aggregate req/sec across 4 SchwabClient instances (#6 cross-cutting tech debt ADR-013 §9.3).
- Decision threshold: si aggregate > 5 req/sec sustained → mitigate (S.12.telemetry-c).

### 2.2 Q7: ATHENA prompt budget trajectory monitoring (ADR-009 §9.4 #7)

**Context**: Budget grew Sprint 6→10: 4000→5300 chars (+32.5% single sub-block per F-r6.5). Sprint 11 atlas-d added context terms (mapping descriptions) — increment unmeasured. Sprint 12+ telemetry first measurement.

**Observation approach**:
- ATHENA SYSTEM_PROMPT char count measured per request (telemetry-b instrumentation).
- Trajectory tracked per sub-block sprint commit.
- Decision threshold: si budget approaches Anthropic API context window proportional limit → compression sprint trigger.

### 2.3 R6: Schwab paper trading API throttling (ADR-013 §7)

**Context**: ADR-013 §7 R6 mitigation = "rate_limiter existing + monitoring D-γ isolation pattern S.7.surf-c". Sprint 12 telemetry validates mitigation efficacy production-runs.

**Observation approach**:
- 429 throttling responses count per hour.
- D-γ isolation pattern: per-ticker failure isolation working?
- Multi-agent + Eolo subaccount activity correlation (D9 isolation working per ADR-013).
- Decision threshold: si throttling > 5/hour sustained → infrastructure intervention.

### 2.4 F-r6.5: ATHENA budget reality measurement (ADR-009 Sprint 10)

**Context**: Sprint 10 lesson — pre-Write estimate vs post-Write reality ±16% gap. Budget management requires both measurements (Sprint 10 F-r6 + F-r6.5 pair).

**Observation approach**:
- Pre-Write estimate (sub-block planning) + post-Write measurement (post-commit) tracked per ATHENA-touching sub-block.
- Accumulated gap statistic per Sprint.
- Decision threshold: si gap > 20% sustained → revise estimation methodology.

## 2.5 Cross-ADR drift catches (Sprint 12 telemetry-a pre-recolección)

Sprint 12 telemetry-a pre-recolección Camino 2 protocol catched 2 cross-ADR drift items pre-Write. Pattern: amendment via memo cross-reference, NO modify Aceptado ADRs (frozen by design). Documented here for future telemetry observation memos (Sprint 13+ reusable concept).

### Q5 status amendment Sprint 11

ADR-009 §9.4 #5 (Q5) original status: "Phase 1 DB-only, no Schwab calls. Trigger: monitor first Sprint 10 production runs." This status is **obsolete post Sprint 11 atlas-e** (commit `bfc297f`).

**Reality update Sprint 11**: Live mode (USE_LIVE_PORTFOLIO=True) SÍ hace Schwab calls vía LiveSnapshotBuilder → SchwabClient.get_positions + get_balances every 30s (CachedSnapshotBuilder TTL per ADR-013 D7). Q5 trigger fired by atlas-e commit, observation now HOT (vs original cold trigger Sprint 10).

**Resolution**: Documented via this memo. ADR-009 Aceptado NOT modified (frozen pattern). Future readers ADR-009 §9.4 #5 → cross-ref this memo §2.5 + §2.1 Q5 for current operational reality.

### R7 operator doc §11 reference drift

ADR-013 §7 R7 mitigation references "operator doc §11 explicit" pointing semantically to pre-deploy subaccount creation documentation. **But §11 actual content** (pre Sprint 12 telemetry-a) was "Future Work / Tech debt" catalog — pre-deploy subaccount info actually lives in §10.3 SCHWAB_ACCOUNT_ID subaccount isolation.

**Pre-existing drift**: The cross-ref was incorrect from origin (Sprint 11 atlas-f time), NOT caused by Sprint 12 telemetry-a §11→§12 renumber.

**Sprint 12 telemetry-a impact**: Renumber NO empeora el drift. §11 (renamed §12) still catalog, §11 NEW = Telemetry observation. Pre-deploy subaccount info still lives §10.3.

**Resolution**: Documented via this memo. ADR-013 Aceptado NOT modified (frozen pattern, same as Q5 amendment). Future readers ADR-013 §7 R7 → cross-ref operator doc §10.3 (subaccount isolation) for pre-deploy guidance, NOT §11/§12.

**Pattern emergent**: "Cross-ADR drift catches" subsection en memos Sprint N+ telemetry observation = canonical place para document Aceptado ADR drift sin re-litigation. Sprint 13+ reusable.

## 3. Implementation roadmap

**Sprint 12 Bundle Option C remaining phases**:
- S.12.telemetry-b (Day 4-5): structured logs + metrics scaffold (~200 LOC code).
- S.12.telemetry-c (ongoing 4-8 weeks): observation report + close-out memo + Sprint 13+ priority signal.

**Phased instrumentation (telemetry-b scope)**:
- Q5/R6: SchwabClient logger.warning patterns parsed via log aggregation.
- Q7/F-r6.5: ATHENA prompt char count instrumented per request (sys.getsizeof o explicit measurement).

## 4. Tools strategy DEFER

Tools choice (Prometheus + Grafana stack vs simple log analysis vs other) DEFERRED to S.12.telemetry-c data-driven decision after Phase 1 observation accumulates 2-4 weeks data signal.

**Phase 1 (telemetry-b)**: structured logger.info/warning patterns + JSON-formatted log events sufficient. No infrastructure investment pre-observation.

**Phase 2+ (telemetry-c + beyond)**: telemetry-c memo recommends tools choice based on observed needs.

## 5. Success criteria (close-out telemetry-c)

Cada trigger close-out criteria explícit:

| Trigger | Close-out criteria |
|---------|-------------------|
| Q5 | 4+ weeks observation con NO unmitigated throttling spikes. Recommendation: keep RateLimiter as-is OR migrate to centralized rate budget. |
| Q7 | Budget trajectory 4+ Sprint observation. Recommendation: compression sprint trigger threshold defined OR maintain current trajectory if linear sustainable. |
| R6 | Throttling rate measured + correlation con Eolo activity verified. Recommendation: subaccount isolation working OR escalate Schwab portal communication. |
| F-r6.5 | Estimation accuracy gap statistic stable < 20% OR methodology revision proposed S.12.telemetry-c. |

## 6. Sub-decisions firmadas (Camino 2)

- **D-φ**: Operator doc §11 NEW Telemetry observation section. Current §11 "Future Work / Tech debt" renumbered §12. Sprint chronological progression preserved.
- **D-χ**: Memo separate file `docs/decisions/sprint-12-telemetry-setup.md` paralelo a sprint-N-priority-analysis pattern. NO ADR-NN# prefix per plan-a "no formal ADR".
- **D-ψ**: Scope strict 4 triggers (Q5/Q7/R6/F-r6.5). NO scope expansion R5/R7/cross-cutting #6 SchwabClient 4 instances. Discipline rule scope creep.
- **D-ω**: Tools strategy (Prometheus/Grafana vs logs) DEFERRED to S.12.telemetry-c. Data-driven decision post 2-4 weeks observation.

## 7. References

- ADR-009 Aceptado (commit dea7ee9) — §9.4 #5 Q5 + #7 Q7 source. Q5 amended via §2.5 (Aceptado frozen).
- ADR-013 Aceptado (commit 6f51efb) — §7 R6 + §9.3 #6 cross-cutting + §7 R7 ref drift catched §2.5.
- S.12.plan-a (commit af0ee36) — Bundle Option C lock + multi-trigger unlock rationale.
- S.12.protocol-a (commit e76e879) — Day 1-2 phase Protocol refactor F-r14 resolved.
- Sprint 10 §9.2 — F-r6 + F-r6.5 lesson pair (budget pre-Write + post-Write measurement).
- Operator doc `docs/operator/schwab-setup.md` §10.3 (pre-deploy subaccount) + §11 (NEW Telemetry observation) — companion docs this memo.
