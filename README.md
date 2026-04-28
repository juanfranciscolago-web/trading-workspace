# Trading Workspace

Multi-agent trading system + Eolo legacy + shared infrastructure.

> **Si sos Claude Code, leé `CLAUDE.md` antes de seguir.**
> Ese archivo tiene todas las instrucciones, reglas y contexto del proyecto.

---

## Estado del Proyecto

```
Sprint 1 — COMPLETE  ████████████████████ 100%
Sprint 2 — next      ░░░░░░░░░░░░░░░░░░░░
```

**Sprint 1 (semanas 1-2) — Foundations:** completado el 28 de abril de 2026.
Ver `docs/SPRINT_1_RETROSPECTIVE.md` para el cierre formal.

---

## Lo que se construyó en Sprint 1

| Componente | Archivos | Tests |
|---|---|---|
| Pydantic schemas (6 message types) | `communication/schemas/` | 15 |
| Redis Streams message bus + DLQ | `communication/message_bus.py` | 28 |
| PostgreSQL schemas (9 migrations, 7 hypertables) | `db/migrations/` | 38 integration |
| Mock agents (Athena, Apollo, Hermes, Nyx, Vesta, Atlas) | `agents/*.py` | 103 |
| Consensus engine (Phase 3, 5 rules) | `agents/consensus.py` | incluido arriba |
| MessageRepository (dual-write pattern) | `persistence/message_repository.py` | 4 integration |
| ClaudeRouter (LLM routing, cost tracking) | `claude_router/` | 28 |
| Workspace test runner | `run_tests.sh` | — |

**Totales:** 5 commits · ~3 500 LOC producción · 179 tests unitarios · 42 tests de integración

---

## Quick Start

### 1. Prerequisitos

- Python 3.11+
- Docker & Docker Compose
- Node.js LTS (para el dashboard futuro)

### 2. Clonar y configurar

```bash
git clone <repo-url>
cd trading-workspace
cp .env.example .env        # editar con credenciales reales
```

### 3. Levantar servicios

```bash
docker-compose up -d        # PostgreSQL + Redis
docker-compose ps           # verificar que están running
```

### 4. Instalar paquetes Python

```bash
python -m venv venv
source venv/bin/activate

cd shared-core && pip install -e ".[dev]" && cd ..
cd multi-agent-system && pip install -e ".[dev]" && cd ..
```

### 5. Aplicar migraciones de base de datos

```bash
cd multi-agent-system
source ../venv/bin/activate
DATABASE_URL=postgresql://trader:trader@localhost:5432/trading \
    python db/migrate.py
```

### 6. Correr todos los tests

```bash
./run_tests.sh
# Esperado: shared_core 23 + multi-agent 179 + claude_router 28 = 230 passing
```

Con la base de datos levantada, los tests de integración también corren:

```bash
cd multi-agent-system
DATABASE_URL=postgresql://trader:trader@localhost:5432/trading \
    pytest tests/ -v
# Esperado: ~217 passing (179 unit + 38 integration)
```

### 7. Correr un ciclo de demo

```bash
cd multi-agent-system
source ../venv/bin/activate

# Escenarios disponibles:
python run_cycle.py --scenario all_agree
python run_cycle.py --scenario nyx_dissents
python run_cycle.py --scenario deep_disagreement
python run_cycle.py --scenario atlas_blocks
python run_cycle.py --scenario high_conviction_solo

# Con seed explícito para reproducibilidad exacta:
python run_cycle.py --scenario nyx_dissents --seed 1002
```

---

## Flujo de un ciclo de trading

```
  ┌──────────────────────────────────────────────────────────────┐
  │                      TRADE CYCLE                            │
  │                                                              │
  │   ┌─────────┐                                               │
  │   │ ATHENA  │  ProposalMessage (ticker, strategy,           │
  │   │  quant  │  conviction_score, sizing, thesis)            │
  │   └────┬────┘                                               │
  │        │ correlation_id (UUID) threads all messages         │
  │        ▼                                                     │
  │   ┌────────────────────────────────────────────────────┐    │
  │   │  PHASE 2 — 4 parallel critiques                    │    │
  │   │                                                    │    │
  │   │  APOLLO  (macro)     →  CritiqueMessage + stance   │    │
  │   │  HERMES  (flow)      →  CritiqueMessage + stance   │    │
  │   │  NYX     (contrarian)→  CritiqueMessage + stance   │    │
  │   │  VESTA   (sector)    →  CritiqueMessage + stance   │    │
  │   └──────────────────────────┬─────────────────────────┘    │
  │                              │ 4 critiques                   │
  │                              ▼                               │
  │   ┌──────────────────────────────────────────────────────┐  │
  │   │  PHASE 3 — Consensus Engine                          │  │
  │   │                                                      │  │
  │   │  4/4 AGREE        → UNANIMOUS     → APPROVED 100%   │  │
  │   │  3/4 + contrarian → PRODUCTIVE    → APPROVED  50%   │  │
  │   │  2/2 split        → SPLIT         → REJECTED        │  │
  │   │  all NEUTRAL + c≥90 → NO_QUORUM  → APPROVED  33%   │  │
  │   └──────────────────────────┬─────────────────────────┘    │
  │                              │ DecisionMessage               │
  │                              ▼                               │
  │   ┌──────────────────────────────────────────────────────┐  │
  │   │  PHASE 4 — ATLAS validation                          │  │
  │   │                                                      │  │
  │   │  checks: buying power, tech concentration, beta,    │  │
  │   │          vega, drawdown, stress tests               │  │
  │   │                                                      │  │
  │   │  → APPROVED / APPROVED_WITH_CONDITIONS / BLOCKED    │  │
  │   └──────────────────────────────────────────────────────┘  │
  │                                                              │
  │  All messages persisted via MessageRepository:               │
  │  messages.agent_messages (hypertable) + domain tables        │
  └──────────────────────────────────────────────────────────────┘
```

---

## Estructura del workspace

```
trading-workspace/
├── CLAUDE.md                           ← Instrucciones para Claude Code
├── README.md                           ← Este archivo
├── run_tests.sh                        ← Correr todos los tests del workspace
├── docker-compose.yml                  ← PostgreSQL + Redis
├── .env.example                        ← Template de variables de entorno
│
├── docs/
│   ├── sistema_multiagente_trading.md  ← Documento maestro (v1.2, fuente de verdad)
│   ├── SPRINT_1_RETROSPECTIVE.md       ← Cierre formal Sprint 1
│   └── decisions/                      ← ADRs (Architecture Decision Records)
│
├── shared-core/                        ← Infraestructura común (Eolo + multi-agente)
│   └── src/shared_core/
│       ├── models/                     ← Pydantic models compartidos
│       ├── brokers/                    ← SchwabClient, CCXT wrappers
│       ├── storage/                    ← PostgresPool, TradeLogger
│       └── messaging/                  ← EventBus (Redis Pub/Sub)
│
├── eolo-legacy/                        ← Sistema Eolo actual (intocable)
│
└── multi-agent-system/
    ├── run_cycle.py                    ← CLI: demo de un ciclo completo
    ├── claude_router/                  ← Routing LLM (28 tests)
    ├── db/
    │   ├── migrate.py                  ← Aplica migraciones con checksum
    │   ├── reset_dev.py                ← Reset dev DB (protegido contra prod)
    │   └── migrations/                 ← V001–V009 (7 schemas, 19 tables)
    └── src/multi_agent/
        ├── communication/              ← Schemas + Redis Streams bus
        │   └── schemas/                ← Proposal/Critique/Decision/Atlas/Exec/Postmortem
        ├── agents/                     ← 6 mock agents + consensus engine
        │   ├── fixtures.py             ← 5 escenarios nombrados
        │   ├── consensus.py            ← Phase 3 decision logic
        │   ├── base.py                 ← BaseMockAgent + MockOrchestrator
        │   ├── athena_mock.py          ← Proposal generator (CSP, iron condor)
        │   ├── apollo_mock.py          ← Macro critique
        │   ├── hermes_mock.py          ← Flow critique
        │   ├── nyx_mock.py             ← Contrarian critique
        │   ├── vesta_mock.py           ← Sector critique
        │   └── atlas_mock.py          ← Risk validation
        └── persistence/
            └── message_repository.py  ← Dual-write: agent_messages + domain tables
```

---

## Los 6 Agentes

| Agente | Rol | Time horizon | Modelo LLM |
|--------|-----|--------------|------------|
| **ATHENA** | Cuantitativa sistemática (CSP, credit spreads, mean reversion) | 15-45 días | Sonnet 4.6 |
| **APOLLO** | Macro discrecional (LEAPs, swing equity, crypto spot) | Semanas-meses | Sonnet 4.6 |
| **HERMES** | Tactical flow (0DTE, intraday, weeklies) | Minutos-horas | Sonnet 4.6 |
| **NYX** | Contrarian independiente (asimetría narrativa-realidad) | 2-12 semanas | Sonnet 4.6 |
| **VESTA** | Rotación sectorial (cross-sectional, sub-industrias) | 4-26 semanas | Sonnet 4.6 |
| **ATLAS** | Guardian del portfolio — riesgo, validación pre-ejecución | Continuo | Sonnet/Opus |

**ATLAS no es un agente de trading.** Es un servicio de validación que se interpone entre consensus y ejecución. Todo trade pasa por ATLAS antes de ejecutarse.

---

## Objetivos del sistema

- CAGR > 25% anualizado
- Sharpe > 2.0
- Max drawdown < 15%
- % meses positivos > 70%

**Estado:** Paper trading durante 6 meses antes de capital real.

---

## Comandos frecuentes

```bash
# Servicios
docker-compose up -d                        # Postgres + Redis
docker-compose down                         # Bajar servicios
docker-compose logs -f postgres             # Logs de postgres

# Acceso directo a la BD
psql postgresql://trader:trader@localhost:5432/trading

# Tests
./run_tests.sh                              # Todos los tests del workspace
cd multi-agent-system && pytest tests/ -v   # Tests multi-agent (unit)
DATABASE_URL=... pytest tests/ -v           # Incluye integration tests

# Ciclo de demo
python multi-agent-system/run_cycle.py --scenario all_agree
python multi-agent-system/run_cycle.py --scenario atlas_blocks

# Migraciones
cd multi-agent-system
DATABASE_URL=postgresql://... python db/migrate.py     # Aplicar
DATABASE_URL=postgresql://... python db/reset_dev.py   # Reset dev (no prod)

# Linting y types (cuando estén configurados)
ruff check .
mypy src/
```

---

## Reglas críticas

1. **Nunca commit del `.env`** — contiene secretos
2. **`SCHWAB_PAPER_TRADING=true`** hasta que el sistema esté validado
3. **`ATLAS_FAIL_OPEN=false`** siempre — fail closed
4. **Eolo es intocable** durante el desarrollo del multi-agente
5. **Tests obligatorios** para código que toca dinero
6. **`claude_router.send()`** siempre — nunca llamar Anthropic SDK directamente

---

## Roadmap

| Sprint | Semanas | Estado |
|--------|---------|--------|
| Sprint 1 — Foundations | 1-2 | **COMPLETE** |
| Sprint 2 — ATLAS Infrastructure + Dashboard básico | 3-4 | next |
| Sprint 3 — ATHENA debate-only mode | 5-6 | |
| Sprint 4 — APOLLO y HERMES | 7-8 | |
| Sprint 5 — Conexión Schwab paper trading | 9-10 | |
| Sprint 6 — Ejecución real en paper | 11-12 | |
| Sprint 7 — NYX integration | 13-14 | |
| Sprint 8 — VESTA, sistema completo | 15-16 | |

Ver sección 10 del documento maestro para el roadmap detallado.

---

## Troubleshooting

**"psycopg2 not installed"**
```bash
pip install psycopg2-binary
```

**"Cannot connect to PostgreSQL"**
```bash
docker-compose ps          # verificar que postgres está running
docker-compose logs postgres
```

**Tests del workspace fallan desde el root**
```bash
./run_tests.sh             # usar el script, no pytest desde root
# razón: pyproject.toml en multi-agent-system modifica rootdir
```

**"can't adapt type 'UUID'"**
```bash
# Agregar al conftest.py: psycopg2.extras.register_uuid()
```

---

## Documentación adicional

- **Documento maestro:** `docs/sistema_multiagente_trading.md`
- **Retrospectiva Sprint 1:** `docs/SPRINT_1_RETROSPECTIVE.md`
- **Shared-core:** `shared-core/README.md`
- **ClaudeRouter:** `multi-agent-system/claude_router/README.md`
- **Instrucciones para Claude Code:** `CLAUDE.md`

---

**Última actualización:** 28 de abril 2026 — Sprint 1 complete
