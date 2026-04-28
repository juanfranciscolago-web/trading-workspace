# Claude Code — Cheat Sheet

Comandos útiles para trabajar con Claude Code en este proyecto.

---

## 🚀 Comandos Esenciales

### Iniciar Claude Code

```bash
# Desde la terminal de PyCharm (en el root del workspace)
claude
```

### Atajos de Teclado en PyCharm

| Atajo | Acción |
|-------|--------|
| `Cmd+Esc` (Mac) / `Ctrl+Esc` (Win) | Abrir Claude Code con contexto del archivo activo |
| `Cmd+Shift+L` | Compartir selección con Claude |
| `Cmd+Shift+E` | Compartir errores del IDE con Claude |

---

## 💬 Frases Útiles para Claude Code

### Para iniciar bien una sesión

```
Lee CLAUDE.md primero. Después confirmame que entendés:
1. La misión del proyecto
2. Los 6 agentes
3. En qué Sprint estamos
4. Las reglas no negociables
```

### Para implementar features

```
Voy a implementar [X].
Antes de codear, mostrame el plan de archivos que vas a crear/modificar.
```

```
Implementá [feature] siguiendo la sección [Y] del documento maestro.
Tests obligatorios al final.
```

### Para debugging

```
Tengo este error: [pegar error]
Trace it through the codebase y proponé un fix.
```

```
Este test falla: [nombre del test]
Reproducilo, identificá la causa raíz, y arreglalo.
No solo hagas que pase — quiero entender por qué fallaba.
```

### Para refactor

```
Refactorizá [archivo] para mejorar [claridad/performance/testabilidad].
NO cambies el comportamiento. Tests existentes deben seguir pasando.
```

### Para reviews

```
Revisá [archivo/PR] contra:
1. Las reglas de CLAUDE.md
2. La especificación en sección [Y] del documento maestro
3. Convenciones de código del proyecto

Dame una lista priorizada de issues encontrados.
```

### Para tests

```
Agregá tests unitarios para [módulo].
Cobertura objetivo: >80%.
Incluí edge cases y casos de error.
```

### Para gestión de modelo LLM

```
# Cambiar a Opus para decisiones complejas
"Switch a Opus para esta decisión arquitectónica."

# Bajar a Sonnet para implementación mecánica
"Bajá a Sonnet para este boilerplate."

# Pedir reporte de uso
"Mostrame los costos LLM de esta sesión."
```

---

## 🛡️ Validaciones Frecuentes

### Antes de commit

```
Antes de commitear:
1. Corré los tests del módulo afectado
2. Verificá que no hay secrets hardcodeados
3. Verificá que no usaste Anthropic SDK directo (debe ser ClaudeRouter)
4. Verificá que no llamaste a Schwab API directo (debe ser shared_core)
5. Mostrame los archivos modificados con git diff
```

### Antes de PR

```
Antes de PR:
1. Todos los tests pasan
2. Linting clean (ruff check)
3. Type checking clean (mypy)
4. Documentación actualizada
5. CHANGELOG.md actualizado si aplica
```

---

## 🔥 Patrones que Funcionan Bien

### Patrón 1: Plan → Implement → Test → Review

```
1. "Mostrame el plan para implementar [X]"
   → Claude muestra estructura de archivos

2. (después de aprobar)
   "Implementá según el plan"
   → Claude crea/modifica archivos

3. "Agregá tests con cobertura >80%"
   → Claude agrega tests

4. "Revisá tu implementación contra los requirements originales"
   → Claude self-reviews y corrige
```

### Patrón 2: Sandwich Opus-Sonnet-Opus

```
1. (Opus) "Diseñá la arquitectura de [X]"
   → Spec detallada

2. (Sonnet) "Implementá según el diseño anterior"
   → Código siguiendo el plan

3. (Opus) "Revisá la implementación contra el diseño"
   → Lista de mejoras y edge cases
```

### Patrón 3: Test-Driven con Claude

```
1. "Escribí tests para [feature] basado en [spec]"
   → Tests que actualmente fallan

2. "Implementá la feature para que pasen los tests"
   → Implementación

3. "¿Hay edge cases adicionales no cubiertos?"
   → Tests adicionales si aplica
```

---

## ⛔ Banderas Rojas — Cuándo Cambiar de Modelo

### Cambiar a Opus si...

- Sonnet te dio 2+ respuestas inconsistentes en tareas relacionadas
- El código generado tiene bugs sutiles que descubriste tarde
- Sonnet pierde contexto entre archivos
- Sonnet pidió aclarar 3+ veces lo mismo

### Cambiar a Sonnet si...

- Estás en Opus haciendo tareas mecánicas/repetitivas
- Las respuestas de Opus son obviamente más detalladas de lo necesario
- Estás implementando algo bien especificado

### Cambiar a Haiku si...

- Solo necesitás búsquedas, validaciones simples
- Quick fixes triviales
- Operaciones de un paso

---

## 🚨 Comandos de Emergencia

### Si Claude está confundido

```
PARÁ.

1. Ignorá lo último que estabas haciendo
2. Releé CLAUDE.md
3. Releé la sección [X] del documento maestro
4. Resumime qué entendés del contexto actual
5. Después seguimos con [tarea]
```

### Si Claude rompió algo

```
PARÁ.

¿Qué cambios hiciste en los últimos N minutos?
¿Algún cambio fue irreversible?
Mostrame git status y git diff antes de hacer nada más.
```

### Si te perdiste en una conversación larga

```
Resumime:
1. En qué tarea estábamos
2. Qué decisiones tomamos
3. Qué archivos modificamos
4. Qué falta para completar la tarea actual
5. Qué viene después

No agregues nada nuevo, solo resumí.
```

---

## 📊 Comandos para Monitorear Costos

```
"¿Cuánto llevamos gastado en LLM esta sesión?"
"Mostrame distribución de uso: % Opus / Sonnet / Haiku"
"¿Estoy en cronograma del Sprint actual?"
"Generá un reporte de la sesión: qué hicimos, costo, decisiones tomadas"
```

---

## 💡 Tips Avanzados

### Aprovechar prompt caching

Cuando trabajás repetidamente sobre los mismos archivos:

```
"Cargá los siguientes archivos en contexto:
- shared-core/src/shared_core/models.py
- shared-core/src/shared_core/risk/atlas_client.py
- multi-agent-system/claude_router/router.py

Voy a hacer múltiples preguntas sobre estos."
```

Claude Code automáticamente cachea, lo cual reduce mucho los costos.

### Usar `/clear` para resetear contexto

Si la sesión está pesada y querés empezar fresh:

```
/clear
```

Después releé CLAUDE.md y empezás limpio.

### Slash commands útiles

```
/init       → Inicializar Claude Code en un proyecto
/clear      → Limpiar conversación actual
/restart    → Reiniciar Claude Code
/cost       → Ver costo de la sesión
/help       → Lista de comandos
```

---

## 📞 Cuándo Pedir Ayuda Humana

Pausá y pedí input cuando:

- ✋ Encontrás contradicciones en el documento maestro
- ✋ Necesitás modificar Eolo legacy
- ✋ Una decisión arquitectónica tiene trade-offs significativos
- ✋ Vas a tocar algo que afecta capital real (incluso paper)
- ✋ Necesitás overrider límites de ATLAS
- ✋ El test fail no tiene causa obvia después de 30 min

---

**Última actualización:** Abril 2026
