# Sprint 1 Retrospective — Foundations

**Sprint:** 1 de 8  
**Duración:** Semanas 1-2 (completado 28 de abril 2026)  
**Objetivo general:** Construir la infraestructura base sobre la que se van a ejecutar los 6 agentes reales.

---

## Objetivos planeados vs cumplidos

| Objetivo | Estado | Notas |
|---|---|---|
| Schemas Pydantic para protocolo inter-agente | ✅ Completo | 6 message types + base, enums, factory |
| Bus de mensajes Redis funcional | ✅ Completo | Redis Streams con DLQ y crash recovery |
| PostgreSQL con todos los schemas | ✅ Completo | 9 migraciones, 7 hypertables, checksum enforcement |
| Mock agents que producen mensajes válidos | ✅ Completo | 5 alpha agents + ATLAS mock, seeded RNG |
| Flujo completo proposal → critique → decision | ✅ Completo | 5 escenarios nombrados, CLI `run_cycle.py` |
| ClaudeRouter integrado | ⚠️ Parcial | Router construido + 28 tests; integración real con agents = Sprint 2 |
| Métricas de costo LLM trackeadas | ⚠️ Parcial | Tabla `analytics.llm_costs` creada; `log_llm_cost()` en repo; llamada real en Sprint 2 |

**Resultado:** 5/7 objetivos completados al 100%, 2/7 al ~80%.

---

## Métricas del sprint

| Métrica | Valor |
|---|---|
| Commits | 5 |
| Archivos creados/modificados | 43 |
| Líneas de código (neto) | +5 009 |
| Tests unitarios | 179 |
| Tests de integración (requieren DB) | 42 |
| Tests ClaudeRouter | 28 |
| **Total tests** | **249** |
| Cobertura de paths críticos (estimado) | >85% |
| Bugs bloqueantes encontrados y corregidos | 3 |

---

## Decisiones técnicas importantes

### 1. Redis Streams en lugar de Pub/Sub para el flujo de trading

**Decisión:** El flujo crítico (proposals → critiques → decisions → ATLAS) usa Redis Streams (XADD/XREADGROUP/XACK). El bus de eventos del sistema (dashboard, alertas) usa Redis Pub/Sub vía `shared_core`.

**Razón:** Streams es persistente y ACK-based. Si un agente se cae a mitad de un ciclo, puede retomar desde donde quedó. Pub/Sub es fire-and-forget: un crash pierde el mensaje.

**Trade-off aceptado:** Mayor complejidad operacional (consumer groups, PEL drain on startup, DLQ). Para el flujo de dinero real, es la única opción correcta.

---

### 2. Unique indexes en hypertables de TimescaleDB

**Decisión:** Los indexes de `message_id` en `messages.agent_messages` y `execution_id` en `trades.executions` son índices regulares (no únicos). La unicidad se garantiza en la capa de aplicación vía UUID4.

**Razón:** TimescaleDB no permite unique indexes que no incluyan la columna de partición. Agregar `received_at` al unique index haría que el index sea inútil para lookup por `message_id`.

**Trade-off aceptado:** Sin enforcement de BD para duplicados. UUID4 tiene colisiones probabilísticas despreciables (~1 en 5.3×10^36). Para el volumen del sistema (decenas de mensajes por día), es seguro.

---

### 3. Event sourcing via `correlation_id` sin FK entre tablas de trades

**Decisión:** Las tablas `trades.proposals`, `trades.critiques`, `trades.decisions`, `trades.atlas_validations`, `trades.executions` no tienen foreign keys entre sí. El join es por `correlation_id`.

**Razón:** Facilita ingesta append-only desde múltiples productores concurrentes. Sin FKs, cada tabla puede crecer independientemente. TimescaleDB hypertables no soportan bien FKs cross-chunk.

**Trade-off aceptado:** Pierdes enforcement de integridad referencial en BD. El contrato es garantizado por el protocolo de mensajes (el orchestrator siempre crea todas las partes del ciclo).

---

### 4. `MessageRepository` como capa de persistencia separada de los agentes

**Decisión:** Los agentes (mock y futuros reales) nunca escriben a la BD directamente. Reciben un `repo` por inyección de dependencias y llaman `save_proposal()` etc.

**Razón:** Separa la lógica de negocio del agente (generar una propuesta de calidad) de la preocupación de persistencia. En tests unitarios, se pasa un `CapturingRepository` y no necesita DB. En integración, se pasa el `MessageRepository` real.

**Trade-off aceptado:** Una capa más de indirección. Pero es la diferencia entre tests que tardan 0.08s (sin DB) y tests que tardan segundos (con DB).

---

### 5. Dual-write atómico: `messages.agent_messages` + tabla de dominio

**Decisión:** Cada `save_*` en `MessageRepository` escribe en dos tablas dentro de una sola transacción: el log de auditoría (`messages.agent_messages`) y la tabla de dominio (`trades.proposals`, etc.).

**Razón:** Garantiza consistencia. Si el INSERT en `trades.proposals` falla, el mensaje de auditoría también se revierte. Nunca queda un mensaje en el log sin la fila de dominio correspondiente.

**Trade-off aceptado:** Las transacciones son ligeramente más lentas que writes separados. Para el volumen esperado (decenas de trades por día), es irrelevante.

---

### 6. Checksum enforcement en migraciones

**Decisión:** `migrate.py` calcula SHA-256 de cada archivo SQL antes de aplicarlo. Si un archivo ya aplicado cambia, lanza `RuntimeError` y detiene la migración.

**Razón:** Evitar el error clásico de "editar una migración ya aplicada". Si el checksum no coincide, es un error humano que requiere intervención explícita.

**Trade-off aceptado:** Obliga a crear nuevas migraciones para cualquier cambio de schema, incluso pequeños. Es el comportamiento correcto — la historia del schema debe ser inmutable.

---

### 7. `postgresql://trader:trader@localhost:5432/trading` como DSN de dev

**Decisión:** El entorno de desarrollo usa credenciales simples hardcodeadas en el docker-compose. El entorno de producción usará `DATABASE_URL` desde `.env` o AWS Secrets Manager.

**Razón:** Reduce fricción en setup local. Las credenciales de dev no son un secreto en sentido real.

**Trade-off aceptado:** Riesgo de que alguien use las credenciales de dev en prod. Mitigado por `reset_dev.py` que bloquea ejecución si detecta hostnames de prod.

---

## Bugs importantes encontrados y corregidos

### Bug 1: Connection pool leak en `TradeLogger` (shared_core)

**Síntoma:** `getconn()` era llamado pero `putconn()` nunca. Con el tiempo, el pool se agotaba y el sistema se colgaba.

**Fix:** Reemplazar `getconn/putconn` manual por `pool.connection()` context manager. El `putconn` se ejecuta en el `finally` del context manager.

**Impacto potencial:** Sin este fix, cualquier sistema de larga duración (producción) hubiera tenido un leak de conexiones garantizado.

---

### Bug 2: `migrate.py` rompía en sentencias con punto y coma en comentarios

**Síntoma:** `syntax error at or near "docker"` al aplicar V007. El splitter dividía en `;` sin considerar que podían estar dentro de comentarios SQL.

**Fix:** Strip de comentarios (`re.sub(r"--[^\n]*", "", sql)`) antes de hacer `split(";")`.

**Impacto potencial:** Migration aplica con error no detectado o falla silenciosa.

---

### Bug 3: psycopg2 no puede serializar `uuid.UUID` por defecto

**Síntoma:** `can't adapt type 'UUID'` en todos los tests de integración que pasaban UUIDs.

**Fix:** `psycopg2.extras.register_uuid()` en `conftest.py`. Es idempotente — se puede llamar múltiples veces sin problema.

**Impacto potencial:** Todo INSERT con UUID hubiera fallado en runtime.

---

## Lecciones aprendidas

**1. Correr tests desde el directorio del subproyecto, no desde el root.**
`pytest` desde workspace root cambia el `rootdir` y rompe los `pythonpath` del `pyproject.toml`. El `run_tests.sh` encapsula esto correctamente.

**2. TimescaleDB tiene restricciones no documentadas en el happy path.**
Unique indexes sin la columna de partición, nombres de columnas en vistas (`time_interval` vs `interval_length`), comportamiento de `create_hypertable()` con `SELECT`. Estos detalles solo se descubren con tests de integración reales contra la BD.

**3. Los tests de integración valen el costo de setup.**
Todos los bugs críticos de esta sprint fueron detectados por tests de integración (migration tests, smoke tests), no por unit tests. Los unit tests validan lógica; los integration tests validan que el sistema real funciona como se espera.

**4. `frozen=True` en Pydantic es una restricción que se siente temprano.**
`BaseMessage` es `frozen=True` (inmutable). Esto significa que los agentes deben construir el objeto completo de una vez en el constructor, no construirlo en partes. Fue la decisión correcta (mensajes como valores inmutables), pero requiere diseñar los constructores de los agentes con cuidado.

**5. Seeded RNG + scenarios explícitos es mejor que magic numbers.**
La primera versión tenía solo seeds. Agregar `ScenarioDef` con `agent_stances` explícitas hace que los tests sean auto-documentados: lees el escenario y sabés exactamente qué debería pasar, sin necesidad de correr el código.

---

## Tech debt identificado para Sprint 2

| Item | Prioridad | Descripción |
|---|---|---|
| Integración real de ClaudeRouter | Alta | Los mock agents usan lógica hardcodeada; los agentes reales deben usar `claude_router.send()` |
| LLM cost tracking en agents | Alta | `log_llm_cost()` existe en el repo pero ningún agente lo llama todavía |
| `run_cycle.py` no escribe a DB por defecto | Media | Sin `DATABASE_URL`, los mensajes no se persisten. En Sprint 2 la DB debe ser obligatoria |
| Typing en `BaseMockAgent` | Baja | `agent_id` está declarado como variable de clase pero no como `ClassVar[AgentId]` |
| `consensus.py` no tiene tests para `AGREE_WITH_CONDITIONS` stance | Baja | El stance existe en el enum pero ningún mock lo produce todavía |
| `AtlasValidationRef` en `DecisionMessage` siempre `PENDING` | Baja | El ref se actualiza a `VALIDATED` cuando llega el `AtlasValidationMessage`, pero el update no está implementado |
| Error handling en `MessageRepository` | Media | Las excepciones de DB se reraisean sin wrapping; Sprint 2 debe agregar logging estructurado y métricas |

---

## Lo que quedó fuera del scope (y estaba bien que quedara)

- **LangGraph:** Deferred a Sprint 2+. El orchestrator sincrónico de Sprint 1 es suficiente para validar el protocolo.
- **Dashboard:** Deferred a Sprint 2. No tiene sentido sin datos reales fluyendo.
- **ATHENA real con LLM:** Deferred a Sprint 3. Primero necesitamos ATLAS real (Sprint 2) que valide las propuestas.
- **Ejecución de órdenes:** Deferred a Sprint 5. Paper trading solo después de validar el ciclo completo con LLMs.
- **Backtesting con vectorbt:** Deferred post-Sprint 3.

---

## Próximos pasos — Sprint 2

1. **Integrar ClaudeRouter en los agentes** — reemplazar la lógica hardcodeada por llamadas reales a Claude
2. **ATLAS real** — implementar el motor de riesgo real (no mock): buying power, Greeks, drawdown, correlation
3. **Dashboard básico** — Next.js con visualización del flujo en tiempo real
4. **Async bus** — mover del orchestrator sincrónico a un consumer loop real en Redis Streams
5. **LLM cost tracking** — instrumentar cada llamada al ClaudeRouter con `log_llm_cost()`

---

*Documento generado el 28 de abril 2026. Próxima revisión: al cierre de Sprint 2.*
