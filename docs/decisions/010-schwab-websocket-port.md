# ADR-010: Schwab WebSocket Port — Phase 1 Infra + Auth + Connection

**Fecha:** 2026-05-29 (viernes)
**Estado:** Propuesto
**Contexto:** Sprint 15 Bundle C3 LOCKED via S.15.plan-a (commit `1da261a`, viernes 29-may, scoring #1 ADR-010 WebSocket part 1 3.25 tied + #11 Operator unblock 4.00 3er consecutive). Esta ADR define ADR-010 Phase 1 design plan firmado: SchwabStreamer NEW class shared_core + auth REST OAuth reuse + connection lifecycle lifespan singleton + Settings flag USE_SCHWAB_WEBSOCKET. Phase 2 Sprint 16+ deferred (subscription + message handlers + reconnection + REST migration). Multi-sprint commitment honest acknowledged.

---

## 1. Context

### 1.1 Sprint 15 lock per S.15.plan-a Bundle C3

- S.14.bundle-c ✓ Sprint 14 close-out parcial 83% (commit `4a42df5`, jueves 28-may). Bundle B1 F-r16 RESOLVED.
- S.15.plan-a ✓ Sprint 15 priority analysis Bundle C3 LOCKED (commit `1da261a`, viernes 29-may). #1 ADR-010 WebSocket part 1 (3.25) + #11 Operator unblock (4.00 3er consecutive numerical winner).
- Strategic rationale Bundle C3: 3rd-time deferral problem resolution + ADR-010 foundation completion narrative (last remaining Tier D ADR-008 D6 canonical) + bundle pattern Sprint 12+14 precedent validated 2x.
- Multi-sprint commitment Sprint 15-16+ honest acknowledged: Sprint 15 = Phase 1 design + initial impl, Sprint 16+ = Phase 2 completion + Aceptado milestone.

### 1.2 ADR number decision + ADR-008 D6 timeline amendment inline

ADR-010 NEW canonical per ADR-008 D6 #3 sequencing ("ADR-010 (Schwab WebSocket port) — Sprint 11-12 (multi-sprint sub-blocks pattern: part 1 infra Sprint 11 + part 2 completion Sprint 12 per D7). Tier D real-time L2/tape").

**ADR-008 D6 timeline OUTDATED amendment** (inline §1.2 this ADR, NO modify ADR-008 Aceptado frozen pattern — mirror Q5 status amendment Sprint 12 telemetry-a §2.5 precedent):

- **Original ADR-008 D6**: ADR-010 Sprint 11-12 multi-sprint (part 1 Sprint 11 + part 2 Sprint 12).
- **Actual Sprint 11**: ATLAS portfolio integration (ADR-013 NEW canonical).
- **Actual Sprint 12**: Bundle Option C (Protocol + Telemetry + Operator memo).
- **Actual Sprint 13**: ADR-011 GEX compute pipeline.
- **Actual Sprint 14**: Bundle B1 (Operator + F-r16 cluster-resolved).
- **Actual Sprint 15-16+**: ADR-010 Phase 1 + Phase 2 (this ADR).

Resolution: amendment via memo cross-reference, NO ADR-008 re-litigation. Future readers ADR-008 D6 → cross-ref this ADR §1.2 + S.15.plan-a §5.2 for actual sequencing.

Current ADR list: 001-009 + 011 + 013 (10 files). NO 012 (HERMES Sprint 16-18+ depends ADR-010 ready). ADR-010 NEW canonical slot disponible.

### 1.3 Eolo precedent verified pre-recolección (D-ζ-16)

🔥 **CRITICAL precedent**: Eolo HAS Schwab Streaming WebSocket implementation 2 files:

- `eolo-options/stream/options_stream.py` — Schwab streaming custom websockets library.
- `Bot-v1.2/stream.py` — L1_FIELDS Schwab API vigente (33=MarkPrice update vs older 31=Mark).

**Pattern verified**:
- Library: `websockets` (Python websockets package, NOT schwab-py).
- URL: `wss://streamer-api.schwab.com/ws`.
- Endpoint preliminary: `POST /v1/userPreference` → fetches streamer info (URL, ID, credentials).
- Auth: REST OAuth `access_token` reuse (via existing `get_access_token()` helper).
- Services: `LEVELONE_EQUITIES` (quotes L1) + `CHART_EQUITY` (intraday bars).
- L1 fields canonical Schwab API vigente: `0=Symbol, 1=Bid, 2=Ask, 3=Last, 4=BidSize, 5=AskSize, 8=TotalVolume, 9=LastSize, 10=HighPrice, 11=LowPrice, 12=PrevClose, 17=OpenPrice, 18=NetChange, 33=MarkPrice, 42=NetPercentChange`.
- Pattern: async + reconnect (exponential backoff) + handlers callback registration.

**Port pattern Sprint 15 ws-a** mirror Sprint 11 atlas-b/c precedent (Eolo source → shared_core unified).

### 1.4 Pre-recolección findings F-r1-6 (rule #15 strict)

- **F-r1**: schwab-py library NOT installed + NOT importable (3 evidence convergent: `pip show schwab-py` Package not found + `pip list | grep schwab` empty + `python3 -c "import schwab"` ModuleNotFoundError). D2 confirms `websockets` library decision.
- **F-r2**: SchwabClient REST 100% sync (16+ endpoints, NO `async def` methods). NEW SchwabStreamer async class required (NOT extension of SchwabClient).
- **F-r3**: WebSocket precedent shared_core EMPTY (NO existing websocket/streamer/StreamClient code). ADR-010 = greenfield design via Eolo port.
- **F-r4**: `websockets` library NOT en deps (`multi-agent-system/pyproject.toml` + `shared_core/pyproject.toml`). NEW dependency Sprint 15 ws-a (`websockets>=12.0`).
- **F-r5**: ADR-008 D6 timeline OUTDATED (Sprint 11-12 originally → Sprint 15-16+ actual). Amendment inline §1.2 this ADR (NO modify ADR-008).
- **F-r6**: Async patterns precedent AlertWorker validated (`async def run() + asyncio.create_task lifespan + _stop event shutdown`). SchwabStreamer mirror pattern.

---

## 2. Decisions

### D1. Scope Phase 1 Sprint 15 vs Phase 2 Sprint 16+

**Decisión**: Multi-sprint commitment honest acknowledged. Sprint 15 ADR-010 = Phase 1 only (design plan firmado + initial impl SchwabStreamer + auth + connection + heartbeat + 5-8 mock tests). Sprint 16+ = Phase 2 completion (subscription protocol + message handlers + reconnection logic + REST migration evaluation + Aceptado milestone).

**Phase 1 Sprint 15 deliverables** (S.15.adr-a design + S.15.ws-a impl):
- NEW `shared_core/src/shared_core/brokers/schwab_streamer.py` class (~200-300 LOC).
- NEW dependency `websockets>=12.0` añadido `multi-agent-system/pyproject.toml`.
- NEW Settings flag `USE_SCHWAB_WEBSOCKET: bool = False`.
- Lifespan singleton `app.state.schwab_streamer` + `_build_schwab_streamer(settings, schwab_client)` helper.
- 5-8 NEW tests mock-based.

**Phase 2 Sprint 16+ deferred**:
- Subscription protocol (SUBS/ADD/UNSUBS/VIEW commands).
- Message handlers per service (LEVELONE_EQUITIES + CHART_EQUITY).
- Full reconnection logic (exponential backoff + state recovery + heartbeat monitoring).
- REST → WebSocket migration plan evaluation.
- Aceptado milestone (post Phase 2 complete).

**Justificación**: ADR-011 single-sprint complete pattern NOT applicable (ADR-010 complexity + multi-sprint commitment legitimate). Phase 1 = "connection viable demonstrated". Phase 2 = "subscription + migration production-ready". D-β-16 firmado.

### D2. Library `websockets` (NOT schwab-py)

**Decisión**: Use Python `websockets` library (NOT schwab-py).

**Justificación** (3 evidence convergent F-r1):
1. **Eolo precedent F4-F5**: Both `eolo-options/stream/options_stream.py` + `Bot-v1.2/stream.py` use `websockets` library (NOT schwab-py).
2. **schwab-py NOT viable**: `pip show schwab-py` returns "Package(s) not found" + `import schwab` raises `ModuleNotFoundError`. NEW dependency + integration work + license/maintenance concerns.
3. **`websockets` library stdlib-adjacent**: well-maintained, async native, minimal API surface, Python 3.11+ supported.

**Implementation**: NEW dependency `websockets>=12.0` añadido `multi-agent-system/pyproject.toml` Sprint 15 ws-a. D-γ-16 firmado.

### D3. Authentication: REST OAuth token reuse + POST /v1/userPreference

**Decisión**: SchwabStreamer auth via REST OAuth `access_token` reuse (existing SchwabClient ctor pattern) + pre-connect handshake `POST /v1/userPreference` (Schwab API) → fetch streamer info.

**Implementation**:
- `SchwabStreamer(schwab_client: SchwabClient)` ctor accepts SchwabClient instance (per F-r16 singleton pattern).
- Pre-connect: `await self._fetch_user_preferences()` → `POST {SCHWAB_API_BASE}/v1/userPreference` con `Authorization: Bearer {access_token}` header.
- Response parsed: streamer URL + streamerSocketUrl + customerId + schwabClientChannel + schwabClientFunctionId.
- WebSocket connect: `await websockets.connect(streamerSocketUrl)` con auth tokens en LOGIN command payload.
- Token refresh on 401: `self._schwab_client._refresh_access_token()` + reconnect (mirror REST 401 retry pattern Sprint 11 atlas-b).

**Justificación**: Eolo precedent verified (`eolo-options/stream/options_stream.py` `helpers.get_access_token()` + REST → WebSocket bridge pattern). Single OAuth source of truth. D-δ-16 firmado.

**🚨 Amendment Sprint 15 ws-a (this commit, mirror ADR-011 D6 amendment Sprint 13 gex-a precedent)**:

Pre-implementation Eolo source files verbatim review (S.15.ws-a PARTE 1 pre-recolección) catched URL/method INCORRECT vs Schwab API current:

**Original D3 (S.15.adr-a 15a027d)**:
- `POST /v1/userPreference`

**Corrected D3 (this commit, D-γ-17)**:
- `GET /trader/v1/userPreference` (per Eolo `eolo-options/stream/options_stream.py` `_get_streamer_info()` line 78 verbatim).

**Rationale**: Schwab API endpoint canonical Trader v1 namespace (NOT v1 deprecated). HTTP method GET (NOT POST, idempotent read user preferences). Pattern verified Eolo precedent `eolo-options/stream/options_stream.py` + `Bot-v1.2/stream.py` 2 source files convergent.

**Impact**: SchwabStreamer `_fetch_user_preferences()` method implements `GET /trader/v1/userPreference` (via SchwabClient HTTP wrapper). NO breaking change Phase 1 design (auth + connection + LOGIN sustained).

**Pattern emergent**: pre-implementation Eolo source files verbatim review = CRITICAL F-r catches ADR design corrections (mirror Sprint 13 ADR-011 D6 amendment 2x Sprint 13 gex-a precedent + Sprint 11 atlas-d cross-sprint gap catched material Sprint 14 operator-a).

### D4. Connection lifecycle: lifespan singleton mirror F-r16

**Decisión**: SchwabStreamer lifespan singleton pattern `app.state.schwab_streamer` mirror Sprint 14 F-r16 (`app.state.schwab_client` commits `0c8c59f` + `119a077`).

**Implementation**:
- NEW helper `_build_schwab_streamer(settings_obj, schwab_client) → SchwabStreamer | None` en `multi-agent-system/src/multi_agent/api/app.py`.
- Lazy conditional creation: `USE_SCHWAB_WEBSOCKET=True` AND `schwab_client is not None` → SchwabStreamer instance. Else None.
- Lifespan integration:
  ```python
  app.state.schwab_streamer = _build_schwab_streamer(settings, app.state.schwab_client)
  if app.state.schwab_streamer is not None:
      await app.state.schwab_streamer.connect()
      logger.info("✓ SchwabStreamer connected (user=%s)", ...)
  ```
- Async context manager pattern (connect/disconnect).

**NEW Settings flag**: `USE_SCHWAB_WEBSOCKET: bool = False` default (mirror USE_LIVE_PORTFOLIO Sprint 11 atlas-e).

**Fail-fast contract**: NO blocking gate Sprint 15 Phase 1 (USE_SCHWAB_WEBSOCKET=True + USE_SCHWAB_DATA_LAYER=False viable, streamer + DataLayer separable).

**Cleanup**: lifespan exit `await app.state.schwab_streamer.disconnect()` if not None.

### D5. Subscription protocol Phase 2 (DEFERRED Sprint 16+)

**Decisión**: Subscription protocol design Phase 2 Sprint 16+ (NOT Sprint 15).

**Phase 2 scope**:
- SUBS command (subscribe to symbols + fields).
- ADD command (add symbols to existing subscription).
- UNSUBS command (unsubscribe).
- VIEW command (change fields requested).

**Rationale defer Sprint 15**: Phase 1 = connection viable demonstrated. Phase 2 = subscription requires migration plan REST → WebSocket evaluation.

### D6. Message handlers Phase 2 (DEFERRED Sprint 16+)

**Decisión**: Message handlers per service Phase 2 Sprint 16+ (NOT Sprint 15).

**Phase 1 Sprint 15 minimal**: receive + log raw messages only (debugging). NO callbacks per service.

**Phase 2 Sprint 16+ scope**:
- LEVELONE_EQUITIES handler (real-time quotes Tier C/D).
- CHART_EQUITY handler (intraday bars Tier C migration from OhlcvWorker REST).
- Per-symbol routing.

### D7. Error handling + reconnection Phase 1 minimal

**Decisión**: Phase 1 error handling minimal (logging + manual reconnect on connection drop).

**Phase 1 minimal**:
- Connection drop → log ERROR + raise exception (no auto-reconnect).
- Auth failure → log ERROR + raise.

**Phase 2 Sprint 16+ scope**:
- Exponential backoff reconnect (per Eolo precedent).
- State recovery (re-subscribe on reconnect).
- Heartbeat monitoring + force reconnect on missed.

### D8. Testing strategy Phase 1 mock-based

**Decisión**: Phase 1 tests mock-based unit tests (5-8 NEW tests).

**Test classes propuestas Sprint 15 ws-a**:
- TestSchwabStreamerInit (ctor + auth credentials read).
- TestSchwabStreamerHandshake (POST /v1/userPreference mock + parse response).
- TestSchwabStreamerConnect (websocket mock + LOGIN command send + verify response).
- TestSchwabStreamerDisconnect (cleanup verify).
- TestBuildSchwabStreamer (lazy conditional creation + USE_SCHWAB_WEBSOCKET flag).

**Integration tests deferred Sprint 16+ Phase 2** (require Schwab production endpoint + paper subaccount).

### D9. REST → WebSocket migration Phase 2 (DEFERRED)

**Decisión**: REST → WebSocket migration plan Phase 2 Sprint 16+ (NOT Sprint 15).

**Evaluation contingent post Sprint 15+**:
- Q5 RateLimiter throttle counter data accumulated post operator action.
- R6 429 detection 3 ATLAS endpoints data accumulated.
- If REST throttling magnitudes justify WebSocket migration → Phase 2 scope.
- If REST patterns sufficient → ADR-010 closed without migration (keep WebSocket optional Tier D ONLY).

**Workers candidates migration evaluation Phase 2**:
- IvHistoryWorker (Sprint 7) — current REST polling daily 21:15 UTC.
- OhlcvWorker (Sprint 9) — current REST polling daily 21:30 UTC.
- LiveSnapshotBuilder (Sprint 11 atlas-e) — current REST polling TTL 30s.

### D10. Out of scope Sprint 15 Phase 1

**Decisión**: OUT of scope Sprint 15 ADR-010 Phase 1:
- Subscription protocol (D5 Phase 2).
- Message handlers per service (D6 Phase 2).
- Reconnection logic full (D7 Phase 2).
- Integration tests live (D8 Phase 2).
- REST → WebSocket migration (D9 Phase 2).
- HERMES Tier D consumers (ADR-012 Sprint 16-18+, depends ADR-010 ready Phase 2 first).
- Production deployment (post Phase 2 + post-operator action complete).

## 3. Sub-blocks Sprint 15

Sprint 15 expected sub-blocks ADR-010 Phase 1:
- **S.15.adr-a** (this commit): ADR-010 Propuesto design D1-D10.
- **S.15.ws-a** (Day 3-4): ADR-010 Phase 1 implementation:
  - NEW `shared_core/src/shared_core/brokers/schwab_streamer.py` (~200-300 LOC).
  - NEW dependency `websockets>=12.0` añadido `multi-agent-system/pyproject.toml`.
  - NEW Settings flag `USE_SCHWAB_WEBSOCKET: bool = False`.
  - lifespan singleton `app.state.schwab_streamer` + `_build_schwab_streamer(settings, schwab_client)` helper.
  - 5-8 NEW tests mock-based.

Sprint 15+ NEXT (post Sprint 15 ws-a):
- S.15.operator-b — DEFERRED (operator portal action pending sustained).
- S.15.bundle-c — Sprint 15 close-out + ADR-010 status (Propuesto sustained Sprint 15+ Phase 2 completion).

## 4. Open questions Sprint 15 Phase 1

- **OQ1**: POST /v1/userPreference response schema exact (Eolo precedent reference + Schwab API docs verification Sprint 15 ws-a).
- **OQ2**: LOGIN command payload format exact (Eolo precedent reference + verify Schwab Streaming Specification doc).
- **OQ3**: Heartbeat interval (Eolo precedent ~30s? verify).
- **OQ4**: `websockets` library exact version pin (`>=12.0` minimum, latest stable verify).

OQ1-4 resolved Sprint 15 ws-a (pre-impl research).

## 5. Out of scope (NOT this ADR)

- ADR-012 HERMES tactical Tier D consumers (separate ADR per ADR-008 D6 #4).
- ATHENA streaming consumer integration (post Phase 2).
- Real-time signal pipelines (Tier A NEW post Phase 2).

## 6. Success criteria Phase 1

- ✅ SchwabStreamer NEW class shared_core delivered.
- ✅ Auth + connection + LOGIN handshake functional (manual test viable).
- ✅ Heartbeat keepalive functional.
- ✅ Disconnect cleanup functional.
- ✅ 5-8 NEW tests mock-based passing.
- ✅ lifespan singleton integration multi-agent app.py.
- ✅ NEW dependency websockets installed + pyproject.toml updated.

Phase 1 = "connection viable demonstrated". NO subscription, NO message handlers, NO migration.

## 7. Risks + mitigations

- **R1**: schwab-py library may be official Schwab solution → re-evaluate post Phase 1 (research Schwab API official docs Sprint 15 ws-a).
  - Mitigation: websockets library port pattern preserved, schwab-py adoption possible Phase 2 if official Schwab support emerges.
- **R2**: Connection lifecycle async complexity (race conditions, leaked connections).
  - Mitigation: lifespan singleton mirror F-r16 pattern (Sprint 14 validated) + careful cleanup.
- **R3**: Multi-sprint scope creep risk (Phase 1 expanding into Phase 2 territory).
  - Mitigation: Strict scope discipline per D1 Phase 1 vs Phase 2 split + sub-block atomic close-out S.15.ws-a.
- **R4**: `websockets` library version compatibility (Python 3.14 compatibility verify).
  - Mitigation: pyproject.toml dependency pin + CI tests.
- **R5**: POST /v1/userPreference + LOGIN command Schwab API changes (Eolo precedent may be outdated).
  - Mitigation: OQ1-OQ2 verify Sprint 15 ws-a pre-impl + Schwab API docs reference.

## 8. Sub-decisions firmadas (Camino 2, -16 suffix Sprint 15 adr-a)

- **D-α-16**: ADR-010 NEW canonical (per ADR-008 D6 #3 reserved slot). Mirror ADR-011 + ADR-013 9 sections + D1-D10 structure.
- **D-β-16**: D1 scope Phase 1 Sprint 15 + Phase 2 Sprint 16+ multi-sprint commitment honest acknowledged per S.15.plan-a §5.5.
- **D-γ-16**: D2 library websockets (NOT schwab-py) per Eolo precedent F4-F5 verified + schwab-py NOT importable C1-C4 verified (3 evidence convergent).
- **D-δ-16**: D3 auth REST OAuth token reuse + POST /v1/userPreference per Eolo precedent eolo-options/stream/options_stream.py + Bot-v1.2/stream.py.
- **D-ε-16**: D4 lifespan singleton mirror F-r16 Sprint 14 (commits 0c8c59f + 119a077) + NEW Settings flag USE_SCHWAB_WEBSOCKET (mirror USE_LIVE_PORTFOLIO Sprint 11 atlas-e).
- **D-ζ-16**: Eolo port pattern mirror Sprint 11 atlas-b/c precedent. L1_FIELDS Schwab API vigente per Eolo Bot-v1.2 update (33=MarkPrice vs older 31=Mark).
- **D-η-16**: ADR-008 D6 timeline OUTDATED documented inline §1.2 ADR-010 (Sprint 11-12 originalmente → Sprint 15-16+ actual). NO modify ADR-008 (Aceptado frozen pattern, mirror Q5 status amendment Sprint 12 telemetry-a §2.5 precedent).

## 9. Cumplimiento (Sprint 15+ tech debt + Sprint 16+ next steps)

### 9.1 Sub-blocks delivered Sprint 15 Phase 1

Placeholder (post-S.15.ws-a close-out):
- S.15.adr-a ✓ ADR-010 Propuesto design (this commit).
- S.15.ws-a — Phase 1 implementation NEW SchwabStreamer + dependency + tests (pending).

### 9.2 Findings

Placeholder (post-S.15.ws-a close-out).

### 9.3 Tech debt registered

Placeholder (post-S.15.ws-a close-out).

### 9.4 Sprint 16+ candidates TENTATIVE

- ADR-010 Phase 2 completion (subscription + handlers + reconnection + migration).
- ADR-010 Aceptado milestone (post Phase 2 complete).
- ADR-012 HERMES Sprint 16-18+ (depends ADR-010 Phase 2 ready).
- Telemetry-c real close-out memo (post operator portal action + 2+ weeks observation).
- Sprint 11 tech debt unresolved 4 items (Greeks D-η + portfolio_beta D-κ + PnL D-θ + OCC parser).
- Sprint 13 NEW tech debt remaining (FRED API + ATHENA prompt + iv_surface freshness + CachedGexBuilder).

## 10. References

- ADR-008 D6 #3 (Aceptado) — ADR-010 reserved slot canonical sequencing (timeline OUTDATED amendment inline §1.2 this ADR).
- ADR-011 GEX compute pipeline (Aceptado, commit aa78ad5) — 9 sections + D1-D10 structure precedent.
- ADR-013 ATLAS portfolio integration (Aceptado, commit 6f51efb + Sprint 14 amendments) — 9 sections + D1-D10 structure precedent.
- S.15.plan-a (commit 1da261a) — Sprint 15 Bundle C3 LOCK strategic rationale + §5.5 multi-sprint ADR-010 commitment.
- S.14.f-r16-a (commit 0c8c59f) — SchwabClient singleton DI lifespan F-r16 pattern precedent (D4).
- S.14.f-r16-b (commit 119a077) — singleton tests coverage backward-compat pattern.
- Sprint 11 atlas-b/c — Eolo port pattern precedent (D-ζ-16).
- Eolo source files:
  - `eolo-options/stream/options_stream.py` — Schwab streaming custom websockets library (D2 + D3).
  - `Bot-v1.2/stream.py` — L1_FIELDS Schwab API vigente (D-ζ-16).
- Sprint 12 telemetry-a §2.5 (commit 974f6f3) — Q5 status amendment inline precedent (D-η-16 + F-r ant #1).
