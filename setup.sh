#!/bin/bash
# =============================================================================
# Trading Workspace — Setup Script
# =============================================================================
# Automates initial workspace setup.
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
# =============================================================================

set -e  # Exit on any error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=========================================="
echo "Trading Workspace — Setup"
echo -e "==========================================${NC}"
echo ""

# -----------------------------------------------------------------------------
# Step 1: Check prerequisites
# -----------------------------------------------------------------------------
echo -e "${BLUE}[1/7]${NC} Verificando prerequisitos..."

check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}✗ $1 no está instalado.${NC} Por favor instalalo antes de continuar."
        return 1
    else
        echo -e "${GREEN}✓ $1${NC}"
        return 0
    fi
}

check_command python3 || exit 1
check_command pip || exit 1
check_command docker || exit 1
check_command docker-compose || exit 1

# Verificar versión Python
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    echo -e "${RED}✗ Python 3.11+ required. Found: $PYTHON_VERSION${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python $PYTHON_VERSION${NC}"
echo ""

# -----------------------------------------------------------------------------
# Step 2: Setup .env
# -----------------------------------------------------------------------------
echo -e "${BLUE}[2/7]${NC} Configurando variables de entorno..."

if [ ! -f .env ]; then
    cp .env.example .env
    echo -e "${YELLOW}⚠ .env creado desde template.${NC}"
    echo -e "${YELLOW}  Por favor editá .env con tus credenciales reales antes de continuar.${NC}"
    echo ""
    read -p "¿Continuar de todos modos? (y/N): " CONTINUE
    if [ "$CONTINUE" != "y" ] && [ "$CONTINUE" != "Y" ]; then
        echo "Saliendo. Editá .env y volvé a correr el script."
        exit 0
    fi
else
    echo -e "${GREEN}✓ .env ya existe${NC}"
fi
echo ""

# -----------------------------------------------------------------------------
# Step 3: Crear venv
# -----------------------------------------------------------------------------
echo -e "${BLUE}[3/7]${NC} Configurando virtual environment..."

if [ ! -d venv ]; then
    python3 -m venv venv
    echo -e "${GREEN}✓ venv creado${NC}"
else
    echo -e "${GREEN}✓ venv ya existe${NC}"
fi

# Activar venv
source venv/bin/activate
echo -e "${GREEN}✓ venv activado${NC}"
echo ""

# -----------------------------------------------------------------------------
# Step 4: Levantar servicios
# -----------------------------------------------------------------------------
echo -e "${BLUE}[4/7]${NC} Levantando PostgreSQL y Redis..."

docker-compose up -d postgres redis

echo "Esperando a que los servicios estén listos..."
sleep 5

# Verificar PostgreSQL
if docker-compose exec -T postgres pg_isready -U trader -d trading &> /dev/null; then
    echo -e "${GREEN}✓ PostgreSQL listo${NC}"
else
    echo -e "${RED}✗ PostgreSQL no responde${NC}"
    docker-compose logs postgres
    exit 1
fi

# Verificar Redis
if docker-compose exec -T redis redis-cli ping | grep -q PONG; then
    echo -e "${GREEN}✓ Redis listo${NC}"
else
    echo -e "${RED}✗ Redis no responde${NC}"
    docker-compose logs redis
    exit 1
fi
echo ""

# -----------------------------------------------------------------------------
# Step 5: Instalar shared-core
# -----------------------------------------------------------------------------
echo -e "${BLUE}[5/7]${NC} Instalando shared-core..."

if [ -d shared-core ]; then
    cd shared-core
    pip install -e ".[dev]" --quiet
    echo -e "${GREEN}✓ shared-core instalado${NC}"
    cd ..
else
    echo -e "${YELLOW}⚠ Carpeta shared-core no encontrada. Saltando.${NC}"
fi
echo ""

# -----------------------------------------------------------------------------
# Step 6: Instalar claude_router
# -----------------------------------------------------------------------------
echo -e "${BLUE}[6/7]${NC} Instalando claude_router..."

if [ -d multi-agent-system/claude_router ]; then
    cd multi-agent-system/claude_router
    pip install -r requirements.txt --quiet
    pip install pytest pytest-mock --quiet
    echo -e "${GREEN}✓ claude_router instalado${NC}"
    cd ../..
else
    echo -e "${YELLOW}⚠ claude_router no encontrado. Saltando.${NC}"
fi
echo ""

# -----------------------------------------------------------------------------
# Step 7: Correr tests
# -----------------------------------------------------------------------------
echo -e "${BLUE}[7/7]${NC} Corriendo tests..."

if [ -d shared-core ]; then
    cd shared-core
    if pytest tests/ -q 2>&1 | tail -3; then
        echo -e "${GREEN}✓ Tests shared-core${NC}"
    else
        echo -e "${RED}✗ Tests shared-core fallaron${NC}"
    fi
    cd ..
fi

if [ -d multi-agent-system/claude_router ]; then
    cd multi-agent-system/claude_router
    if pytest tests/ -q 2>&1 | tail -3; then
        echo -e "${GREEN}✓ Tests claude_router${NC}"
    else
        echo -e "${RED}✗ Tests claude_router fallaron${NC}"
    fi
    cd ../..
fi
echo ""

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
echo -e "${GREEN}=========================================="
echo "✓ Setup completo!"
echo -e "==========================================${NC}"
echo ""
echo "Próximos pasos:"
echo ""
echo "1. Verificá tu .env tiene todas las credenciales reales"
echo "2. Abrí el workspace en PyCharm"
echo "3. Instalá Claude Code:"
echo "   ${BLUE}npm install -g @anthropic-ai/claude-code${NC}"
echo "4. Instalá el plugin en PyCharm:"
echo "   Settings → Plugins → 'Claude Code [Beta]'"
echo "5. En PyCharm terminal: ${BLUE}claude${NC}"
echo "6. Decile: 'Lee CLAUDE.md y resumime los 6 agentes'"
echo ""
echo "Servicios corriendo:"
echo "  • PostgreSQL: localhost:5432"
echo "  • Redis: localhost:6379"
echo ""
echo "Tools opcionales (con: docker-compose --profile tools up):"
echo "  • pgAdmin: http://localhost:5050"
echo "  • Redis Commander: http://localhost:8081"
echo ""
