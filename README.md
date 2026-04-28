# Trading Workspace

Multi-agent trading system + Eolo legacy + shared infrastructure.

> **Si sos Claude Code, leé `CLAUDE.md` antes de seguir.**
> Ese archivo tiene todas las instrucciones, reglas y contexto del proyecto.

---

## 🚀 Quick Start

### 1. Prerequisitos

- Python 3.11+
- Docker & Docker Compose
- Node.js LTS (para Claude Code y el dashboard)
- PyCharm (recomendado como IDE)

### 2. Clonar y configurar

```bash
# Clonar el repo
git clone <repo-url>
cd trading-workspace

# Copiar template de variables de entorno
cp .env.example .env
# Editar .env con tus credenciales reales (Anthropic, Schwab, etc.)
```

### 3. Levantar servicios

```bash
# PostgreSQL + Redis
docker-compose up -d

# Verificar que están corriendo
docker-compose ps
```

### 4. Instalar paquetes Python

```bash
# Crear venv
python -m venv venv
source venv/bin/activate  # Linux/Mac
# o: venv\Scripts\activate  # Windows

# Instalar shared-core en modo editable
cd shared-core
pip install -e ".[dev]"
cd ..

# Instalar dependencias del multi-agent system
cd multi-agent-system
pip install -e ".[dev]"
cd ..
```

### 5. Validar que todo funciona

```bash
# Tests de shared-core
cd shared-core && pytest tests/ -v
# Esperado: 23 tests passed

# Tests del ClaudeRouter
cd ../multi-agent-system/claude_router && pytest tests/ -v
# Esperado: 28 tests passed
```

### 6. Setup de Claude Code en PyCharm

```bash
# Instalar Claude Code globalmente
npm install -g @anthropic-ai/claude-code

# En PyCharm:
# Settings → Plugins → Marketplace → buscar "Claude Code [Beta]" → Install
# Reiniciar PyCharm
# Abrir terminal integrada → ejecutar `claude` → autenticar
```

Una vez que Claude Code está configurado, abrí el workspace en PyCharm y verificá que lee el contexto:

```
> Lee CLAUDE.md y resumime los 6 agentes del proyecto.
```

Si responde correctamente, ya estás listo.

---

## 📂 Estructura

```
trading-workspace/
├── CLAUDE.md                          ← Instrucciones para Claude Code
├── README.md                          ← Este archivo
├── docker-compose.yml                 ← Servicios locales (Postgres + Redis)
├── .env.example                       ← Template de variables de entorno
├── .gitignore
│
├── docs/                              ← Documentación del proyecto
│   └── sistema_multiagente_trading.md ← Documento maestro (v1.2)
│
├── shared-core/                       ← Infraestructura común
│   ├── src/shared_core/
│   ├── tests/
│   ├── pyproject.toml
│   └── README.md
│
├── eolo-legacy/                       ← Sistema Eolo actual
│   └── (estructura existente)
│
└── multi-agent-system/                ← Proyecto nuevo
    ├── claude_router/                 ← Routing de modelos LLM
    ├── src/multi_agent/
    ├── dashboard/
    ├── db/migrations/
    ├── tests/
    └── README.md
```

---

## 🎯 Misión

Construir un sistema multi-agente de trading que genere **riqueza desmedida con baja exposición al riesgo**, mediante el trabajo coordinado de 6 agentes especializados:

| Agente | Rol |
|--------|-----|
| **ATHENA** | Cuantitativa sistemática |
| **APOLLO** | Macro discrecional |
| **HERMES** | Tactical flow trader |
| **NYX** | Contrarian independiente |
| **VESTA** | Especialista en rotación sectorial |
| **ATLAS** | Guardian del portfolio (riesgo) |

**Métricas objetivo:**
- CAGR > 25% anualizado
- Sharpe > 2.0
- Max drawdown < 15%
- % meses positivos > 70%

Ver `docs/sistema_multiagente_trading.md` para el documento maestro completo.

---

## 🔧 Comandos Útiles

```bash
# Servicios
docker-compose up -d                   # Levantar Postgres + Redis
docker-compose down                    # Bajar servicios
docker-compose logs -f                 # Ver logs en tiempo real
docker-compose --profile tools up      # Levantar tools (pgAdmin, Redis Commander)

# Tools accesibles
# pgAdmin: http://localhost:5050 (admin@trading.local / admin)
# Redis Commander: http://localhost:8081

# Conectar a la BD directamente
psql postgresql://trader:trader@localhost:5432/trading

# Tests
cd shared-core && pytest -v                                  # Tests shared-core
cd multi-agent-system/claude_router && pytest -v             # Tests router
cd multi-agent-system && pytest -v                           # Tests multi-agent

# Reset completo (CUIDADO: borra datos)
docker-compose down -v
```

---

## 🛣️ Roadmap

**Sprint 1 (semanas 1-2):** Foundations — Schemas + plumbing + ClaudeRouter
**Sprint 2 (semanas 3-4):** ATLAS Infrastructure + Dashboard básico
**Sprint 3 (semanas 5-6):** ATHENA en debate-only mode
**Sprint 4 (semanas 7-8):** APOLLO y HERMES
**Sprint 5 (semanas 9-10):** Conexión Schwab paper trading
**Sprint 6 (semanas 11-12):** Ejecución real en paper de los 3 agentes
**Sprint 7 (semanas 13-14):** NYX integration
**Sprint 8 (semanas 15-16):** VESTA — sistema completo

**Mes 5-6:** Estabilización y validación
**Mes 7+:** Transición gradual a capital real

Ver sección 10 del documento maestro para detalles.

---

## ⚠️ Reglas Críticas

1. **Nunca commit el archivo `.env`** — contiene secretos
2. **`SCHWAB_PAPER_TRADING=true`** hasta que el sistema esté validado
3. **`ATLAS_FAIL_OPEN=false`** siempre — fail closed por seguridad
4. **Eolo es intocable** durante el desarrollo del multi-agente, salvo extracciones a shared-core
5. **Tests obligatorios** para código que toca dinero
6. **ClaudeRouter siempre** — nunca llamar Anthropic SDK directamente

---

## 📞 Documentación Adicional

- **Documento maestro:** `docs/sistema_multiagente_trading.md` (fuente de verdad)
- **Shared-core:** `shared-core/README.md`
- **ClaudeRouter:** `multi-agent-system/claude_router/README.md`
- **Instrucciones para Claude Code:** `CLAUDE.md`

---

## 🆘 Troubleshooting

### "psycopg2 not installed"
```bash
pip install psycopg2-binary
```

### "Cannot connect to PostgreSQL"
```bash
docker-compose ps  # Verificar que postgres está running
docker-compose logs postgres  # Ver errores
```

### "Redis connection refused"
```bash
docker-compose restart redis
```

### Tests del shared-core fallan
```bash
cd shared-core
pip install -e ".[dev]"  # Reinstalar con dev deps
pytest tests/ -v
```

### Claude Code no encuentra el contexto
- Verificar que `CLAUDE.md` está en el root del workspace
- Reiniciar Claude Code: `/restart` en la terminal
- Pedirle explícitamente: "Lee CLAUDE.md primero"

---

**Última actualización:** Abril 2026
