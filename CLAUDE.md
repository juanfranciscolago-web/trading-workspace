# CLAUDE.md — Instrucciones para Claude Code

> **Este archivo es leído automáticamente por Claude Code al iniciar sesión en este workspace. Contiene todo el contexto, reglas y convenciones del proyecto.**

---

## 🎯 Misión del Proyecto

Construir un **sistema multi-agente de trading** que genere riqueza desmedida con baja exposición al riesgo, mediante el trabajo coordinado de 6 agentes especializados con personalidades complementarias.

**Métricas objetivo:**
- CAGR > 25% anualizado
- Sharpe > 2.0
- Max drawdown < 15%
- % meses positivos > 70%

**Estado actual:** Fase de construcción inicial. Paper trading durante 6 meses antes de capital real.

---

## 📚 Documentación Principal

**Antes de hacer cualquier cambio significativo, leé:**

1. **`docs/sistema_multiagente_trading.md`** — Documento maestro completo del proyecto (v1.2). Esta es la **fuente de verdad**. Contiene:
   - Arquitectura general (sección 2)
   - Especificación de los 6 agentes (sección 3)
   - Protocolo de comunicación (sección 4)
   - Schemas JSON de mensajes (sección 5)
   - Sistema de riesgo de ATLAS (sección 6)
   - Stack técnico (sección 7)
   - Estrategia de delegación de modelos LLM (sección 8)
   - Dashboard del operador (sección 9)
   - Roadmap por sprints (sección 10)
   - Métricas de éxito (sección 11)
   - Apéndices (sección 12)
   - Integración con Eolo legacy (sección 13)

2. **`shared-core/README.md`** — Cómo usar la infraestructura común
3. **`multi-agent-system/claude_router/README.md`** — Cómo usar el router de modelos LLM

**Si encontrás contradicciones o gaps en el documento maestro, marcalos para revisión humana antes de implementar tu interpretación.**

---

## 🏗️ Estructura del Workspace

```
trading-workspace/
├── CLAUDE.md                          ← ESTE ARCHIVO
├── docs/
│   └── sistema_multiagente_trading.md ← Documento maestro (fuente de verdad)
├── shared-core/                       ← Infraestructura común (Eolo + multi-agente)
│   ├── src/shared_core/
│   ├── tests/
│   └── README.md
├── eolo-legacy/                       ← Sistema Eolo actual (intocable inicialmente)
│   └── (estructura propia)
├── multi-agent-system/                ← Proyecto nuevo
│   ├── claude_router/                 ← Routing de modelos LLM (ya construido)
│   ├── src/multi_agent/
│   │   ├── agents/                    ← Athena, Apollo, Hermes, Nyx, Vesta, Atlas
│   │   ├── communication/             ← Bus de mensajes, schemas
│   │   ├── data_layer/
│   │   ├── execution/
│   │   ├── risk/                      ← ATLAS engine
│   │   └── tools/
│   ├── dashboard/                     ← Next.js
│   ├── db/migrations/
│   └── tests/
├── docker-compose.yml                 ← PostgreSQL + Redis
└── .env                               ← Variables de entorno (gitignored)
```

---

## 🤖 Los 6 Agentes (Resumen Rápido)

| Agente | Rol | Time horizon | Modelo LLM default |
|--------|-----|--------------|--------------------|
| **ATHENA** | Cuantitativa sistemática (CSP, credit spreads, mean reversion) | 15-45 días | Sonnet 4.6 |
| **APOLLO** | Macro discrecional (LEAPs, swing equity, crypto spot) | Semanas-meses | Sonnet 4.6 |
| **HERMES** | Tactical flow (0DTE, intraday, weeklies) | Minutos-horas | Sonnet 4.6 |
| **NYX** | Contrarian independiente (asimetría narrativa-realidad) | 2-12 semanas | Sonnet 4.6 |
| **VESTA** | Rotación sectorial (cross-sectional, sub-industrias) | 4-26 semanas | Sonnet 4.6 |
| **ATLAS** | Guardian del portfolio (riesgo, validación pre-execution) | Continuo | Sonnet/Opus según mode |

**Crítico:** ATLAS NO es un agente más. Es un servicio que se interpone entre signal generation y execution. **Todo trade pasa por ATLAS antes de ejecutarse.**

---

## 🔧 Stack Técnico

- **Lenguaje:** Python 3.11+
- **Orquestación de agentes:** LangGraph
- **LLM:** Claude API vía `ClaudeRouter` (NUNCA llamar Anthropic SDK directamente)
- **Database:** PostgreSQL 16+ con TimescaleDB para series temporales
- **Cache/Bus:** Redis 7+ con pub/sub
- **Vector DB:** Qdrant o pgvector para embeddings
- **Broker:** Schwab API (vía `shared_core.brokers.SchwabClient`)
- **Crypto:** CCXT (vía `shared_core.brokers`)
- **Frontend dashboard:** Next.js 14+ con TypeScript, Tailwind, shadcn/ui
- **Charting:** Recharts + TradingView Charting Library
- **Backtesting:** Vectorbt
- **Testing:** Pytest + Hypothesis

---

## 🚦 Reglas No Negociables

### Sobre Código

1. **Nunca llames a la Anthropic API directamente.** Usá `claude_router.send(...)` siempre.

2. **Nunca llames a la Schwab API directamente.** Usá `shared_core.brokers.SchwabClient`.

3. **Toda decisión de riesgo pasa por `shared_core.risk.atlas_client`.** Eolo y multi-agente lo consultan antes de cualquier ejecución.

4. **Tests obligatorios para código que toca dinero:** executor, ATLAS, risk checks, sizing. Sin excepciones.

5. **Nunca rompas Eolo durante refactors.** Eolo es el sistema operativo actual del usuario. Preservar funcionamiento.

6. **Schemas JSON son contratos.** Si necesitás cambiar un schema (sección 5 del documento maestro), proponelo antes de implementarlo.

7. **No inventes nuevos `task_types` para el ClaudeRouter.** Hay 28 definidos en `claude_router/config/routing_rules.yaml`. Si necesitás uno nuevo, propónelo primero.

8. **Type hints obligatorios en código nuevo.** Python 3.11+ syntax (no `Optional[X]`, usá `X | None`).

9. **Logging estructurado:** usar `logging` module, no `print`. Niveles correctos (INFO para eventos, DEBUG para detalles, ERROR para errores reales).

10. **Cero secrets hardcodeados.** Todo va en `.env` o AWS Secrets Manager. Si encontrás algún secret en código, marcalo como bug crítico.

### Sobre Decisiones Arquitectónicas

11. **Antes de tareas grandes (>30 min de trabajo), mostrame el plan de archivos que vas a crear/modificar.** Yo apruebo antes de implementar.

12. **Si encontrás una decisión arquitectónica importante** (ej: "uso Pydantic v1 o v2?", "REST vs gRPC?"), pausá y preguntá. No asumas.

13. **Mantenete fiel al documento maestro.** Si vas a desviarte, justificalo y preguntá.

14. **Fail closed por default.** Si algo del sistema de riesgo falla, bloqueá el trade. Nunca apruebes en duda.

---

## 🎯 Reglas de Uso de Modelos LLM

Para tu propio trabajo en este proyecto (Claude Code en PyCharm):

**Default: Opus 4.7** para diseño arquitectónico, debugging complejo, decisiones estratégicas.

**Switch a Sonnet 4.6** para implementación siguiendo specs claras, tests boilerplate, refactors simples.

**Switch a Haiku 4.5** solo para búsquedas simples, validaciones triviales.

**Para el código que generes que va a estar EN producción**, los agentes deben usar el `ClaudeRouter` con la distribución 70% Haiku / 25% Sonnet / 5% Opus. Esa es una decisión de runtime, separada de cómo te uso a vos para desarrollar.

---

## 📝 Convenciones de Código

### Python

```python
# Imports ordenados: stdlib, third-party, local
from __future__ import annotations  # Siempre al inicio

import logging
from datetime import datetime
from typing import Optional

import pandas as pd
from pydantic import BaseModel

from shared_core.models import Position, TradeSource

# Type hints modernos (Python 3.11+)
def calculate_pnl(positions: list[Position]) -> Decimal | None:
    ...

# Docstrings estilo Google
def my_function(arg: int) -> str:
    """Short description.

    Args:
        arg: What this argument is.

    Returns:
        What this returns.

    Raises:
        ValueError: When this happens.
    """
```

### Naming

- `snake_case` para funciones, variables, módulos
- `PascalCase` para clases
- `SCREAMING_SNAKE_CASE` para constantes
- Nombres descriptivos, no abreviaciones (`risk_check` no `rsk_chk`)

### Tests

- Un archivo de test por módulo (`test_X.py` para `X.py`)
- Clases por feature/comportamiento
- Tests deterministas, sin dependencias de red salvo integration tests marcados
- Mocks vía `unittest.mock` o `pytest-mock`

### Commits

Conventional commits:
- `feat:` nueva funcionalidad
- `fix:` corrección de bug
- `refactor:` cambio de estructura sin cambiar comportamiento
- `test:` agregar/modificar tests
- `docs:` documentación
- `chore:` tareas auxiliares

Ejemplo: `feat(athena): implement CSP proposal generator with backtest validation`

---

## 🗂️ Workflow Recomendado

### Cuando empiezas una sesión

1. **Leéme primero** (este archivo).
2. **Verificá `git status`** — ¿hay cambios pendientes? ¿estamos en qué branch?
3. **Verificá tests pasan** antes de empezar: `pytest` en cada subproyecto activo.
4. **Confirmá qué Sprint estamos** (ver sección 10 del documento maestro).

### Antes de implementar feature

1. Identificá la sección del documento maestro relevante.
2. Mostrame el plan de archivos a crear/modificar.
3. Esperá mi aprobación.
4. Implementá.
5. Tests obligatorios.
6. Commit con mensaje descriptivo.

### Cuando encuentras un bug

1. Reproducilo con un test que falla.
2. Arreglá el bug.
3. Verificá que el test ahora pasa.
4. Verificá que ningún otro test se rompió.
5. Commit con `fix:`.

### Cuando algo está ambiguo

1. **Preguntame.** No asumas.
2. Si tengo que decidir entre opciones, presentamelas con pros/cons.
3. Documentá la decisión final en `docs/decisions/`.

---

## 🛠️ Comandos Frecuentes

```bash
# Instalar shared-core en modo editable (en eolo-legacy y multi-agent-system)
pip install -e ../shared-core

# ── Tests ────────────────────────────────────────────────────────────────────

# Correr TODOS los tests del workspace (comando correcto)
./run_tests.sh
# ⚠️  NO usar: pytest shared_core/tests/ multi-agent-system/tests/ desde root.
#    Razón: multi-agent-system/pyproject.toml rompe la resolución de paths
#    cuando pytest se invoca desde el workspace root.

# Correr tests de un subproyecto específico (siempre desde su directorio)
cd shared-core && pytest tests/ -v
cd multi-agent-system && pytest tests/ -v
cd multi-agent-system/claude_router && pytest tests/ -v

# Levantar servicios locales
docker-compose up -d postgres redis

# Conectar a la BD
psql postgresql://trader:trader@localhost:5432/trading

# Ver logs en tiempo real
docker-compose logs -f

# Linting (cuando esté configurado)
ruff check .
ruff format .

# Type checking
mypy src/
```

---

## 🚨 Áreas Sensibles (Cuidado Extremo)

Estas partes del código requieren especial atención:

1. **`multi-agent-system/src/multi_agent/risk/atlas.py`** — Si hay un bug acá, el sistema puede aprobar trades que deberían bloquearse. Tests exhaustivos obligatorios.

2. **`multi-agent-system/src/multi_agent/execution/`** — El ejecutor manda órdenes reales. Validaciones triple-check, manejo de errores explícito, retries con backoff.

3. **`shared-core/src/shared_core/brokers/schwab_client.py`** — Wrapper del broker. Errores acá afectan a Eolo Y multi-agente.

4. **`shared-core/src/shared_core/storage/trade_logger.py`** — La fuente de verdad de qué se ejecutó. Si se corrompe, perdemos auditoría.

5. **Cualquier código que maneje credenciales** — Schwab API keys, refresh tokens. Nunca loggear, nunca commitear.

---

## 📊 Sprints Actuales

**Sprint actual:** Sprint 1 — Foundations (semanas 1-2)

**Objetivos del sprint actual:**
- [ ] Schemas Pydantic implementados
- [ ] Bus de mensajes Redis funcional
- [ ] PostgreSQL con todos los schemas
- [ ] Mock agents que producen mensajes válidos
- [ ] Test de flujo completo proposal → critique → decision con mocks
- [ ] ClaudeRouter integrado y funcionando
- [ ] Métricas de costo LLM trackeadas

**Sprint próximo:** Sprint 2 — ATLAS Infrastructure + Dashboard Básico

Ver sección 10 del documento maestro para el roadmap completo.

---

## 🔗 Integración con Eolo Legacy

**Eolo es el sistema operativo actual del usuario.** Tres variantes:
- Eolo v1 (equities/opciones)
- Eolo v2 con bot SPX 0DTE (orquestado vía n8n)
- Eolo Crypto

**Reglas para Eolo:**
1. Eolo es **intocable** durante el desarrollo del multi-agente excepto para extracciones a `shared-core`.
2. Eolo sigue funcionando idéntico mientras se construye el multi-agente.
3. Cualquier refactor en Eolo requiere tests de regresión.
4. En Fase 2 (mes 4-6), Eolo expone API para que los agentes puedan invocarlo como tool.
5. ATLAS eventualmente coordina riesgo de TODO el portfolio (Eolo + multi-agente + manuales).

Ver sección 13 del documento maestro para detalles completos.

---

## 💬 Cómo Comunicarte Conmigo

### Bien

- "Voy a implementar X. Mi plan es: 1) crear archivo A, 2) modificar B, 3) agregar tests en C. ¿Apruebas?"
- "Encontré una ambigüedad en el documento: la sección 5.4 dice X pero la sección 6.2 dice Y. ¿Cuál tomamos?"
- "Implementé X. Cambié estos 3 archivos. Los 12 tests pasan. ¿Querés que continue con Y?"
- "Detecté un edge case que no está en el documento maestro. ¿Cómo lo manejamos?"

### Mal

- Implementar 500 líneas de código sin avisar.
- Modificar código de Eolo sin pedir permiso.
- Inventar nuevos schemas o task_types sin proponerlos.
- Usar Anthropic SDK directamente en lugar del ClaudeRouter.
- Asumir que algo es "obvio" y no preguntar.

---

## 📈 Métricas que Track Yo

En cada sesión, mantené visible:

- Tiempo estimado vs tiempo real de cada tarea
- Modelo LLM usado (Opus/Sonnet/Haiku) por tarea
- Costo aproximado de la sesión
- Tests agregados / modificados
- Líneas de código (estimación)
- Decisiones técnicas importantes tomadas

Esto me ayuda a calibrar y a optimizar tu uso.

---

## 🆘 Si Algo Sale Muy Mal

Si por algún motivo:
- Borraste archivos críticos
- Rompiste Eolo
- Pusiste secrets en un commit
- Ejecutaste código que afectó el broker real (no paper)
- Cualquier cosa irreversible

**PARÁ INMEDIATAMENTE. Avísame. No intentes "arreglarlo" rápidamente.**

---

## 📞 Contacto y Decisión Humana

Para decisiones que requieren input humano (operador del proyecto), pausá tu trabajo y preguntame explícitamente:

- Decisiones arquitectónicas con trade-offs significativos
- Cambios al documento maestro
- Modificaciones a Eolo
- Cualquier acción que toque capital real (incluso si es paper)
- Override de límites de riesgo de ATLAS

---

**Última actualización:** Abril 2026 — v1.0 del CLAUDE.md
**Documento maestro de referencia:** v1.2

---

> 💡 **Tip final:** Si en algún momento sentís que estás trabajando "a oscuras", pausá y leé de nuevo este archivo + la sección relevante del documento maestro. Es preferible perder 10 minutos releyendo contexto que generar 200 líneas de código mal alineado.
