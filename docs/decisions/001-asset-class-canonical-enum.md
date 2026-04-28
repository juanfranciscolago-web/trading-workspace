# ADR-001: AssetClass — Enum Canónico en shared_core

**Fecha:** 2026-04-28  
**Estado:** Aceptado  
**Contexto:** Sprint 1 — Implementación de schemas Pydantic

---

## Decisión

`AssetClass` (y demás enums de dominio compartido) viven en `shared_core.models` como fuente única de verdad.  
El sistema multi-agente los **re-exporta** desde `multi_agent.communication.enums` en lugar de redefinirlos.

## Contexto

El documento maestro (v1.2, sección 5.2) muestra valores de `AssetClass` en mayúsculas y plural:

```json
"asset_class": "OPTIONS"
```

`shared_core.models` ya tenía `AssetClass` definido con convención diferente:

```python
class AssetClass(str, Enum):
    EQUITY = "equity"   # minúsculas, singular
    OPTION = "option"
    FUTURE = "future"
    CRYPTO = "crypto"
    ETF    = "etf"
```

Eolo ya usa esta convención en producción (paper trading). Cambiarla rompería el sistema operativo actual.

## Alternativas evaluadas

| Opción | Descripción | Descartada porque |
|--------|-------------|-------------------|
| A | Crear `AssetClass` separado en multi-agent con valores del doc (`"OPTIONS"`) | Divergencia entre Eolo y multi-agent; ATLAS no podría comparar posiciones entre sistemas |
| B | Cambiar shared_core para adoptar mayúsculas | Rompe Eolo (regla no negociable) |
| **C** | **Re-exportar shared_core como canónico** | **Elegida: un solo enum, Eolo intacto** |

## Consecuencias

**Positivas:**
- ATLAS puede comparar posiciones de Eolo y multi-agent con el mismo tipo
- Un solo lugar para agregar nuevos asset classes
- Sin riesgo para Eolo

**Tech debt introducido:**
- El documento maestro v1.2 tiene error de convención en los ejemplos JSON de la sección 5 (muestra `"OPTIONS"` en lugar de `"option"`).  
  **Acción pendiente:** Actualizar sección 5 del documento maestro para reflejar valores reales de los enums (minúsculas singular). Prioridad baja — no afecta comportamiento, solo documentación.

## Enums afectados por esta decisión

Esta misma regla aplica a todos los enums de shared_core que aparezcan en los schemas:

| Enum | Ubicación canónica | Valores reales | Error en doc maestro |
|------|--------------------|----------------|----------------------|
| `AssetClass` | `shared_core.models` | `"option"`, `"equity"` | Doc dice `"OPTIONS"` |
| `Direction` | `shared_core.models` | `"buy"`, `"sell"` | Doc dice `"BUY"`, `"SELL"` |
| `OptionType` | `shared_core.models` | `"call"`, `"put"` | Doc dice `"PUT"`, `"CALL"` |
| `TradeStatus` | `shared_core.models` | `"filled"`, `"partial"` | Doc dice `"FILLED"`, `"PARTIAL"` |
| `TradeSource` | `shared_core.models` | `"multi_agent_athena"` | No mencionado explícitamente |
