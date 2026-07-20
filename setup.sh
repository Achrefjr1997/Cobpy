#!/bin/bash

# =============================================================================
# COBOL to Python Migrator - Setup Script
# =============================================================================
# This script sets up the entire development environment from scratch.
# After running this, just execute ./run.sh to start the application.
#
# Requirements:
#   - Linux or macOS
#   - Python 3.11+
#   - Node.js 18+
#   - curl (for installing uv)
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Project root directory
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

echo -e "${CYAN}"
echo "============================================================"
echo "  COBOL to Python Migrator - Environment Setup"
echo "============================================================"
echo -e "${NC}"

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

print_step() {
    echo -e "\n${BLUE}▶ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

check_command() {
    if command -v "$1" &> /dev/null; then
        return 0
    else
        return 1
    fi
}

# -----------------------------------------------------------------------------
# Check prerequisites
# -----------------------------------------------------------------------------

print_step "Checking prerequisites..."

# Check curl
if ! check_command curl; then
    print_error "curl is required but not installed."
    echo "  Please install curl first:"
    echo "    Ubuntu/Debian: sudo apt install curl"
    echo "    macOS: brew install curl"
    exit 1
fi
print_success "curl is installed"

# Check git
if ! check_command git; then
    print_error "git is required but not installed."
    echo "  Please install git first:"
    echo "    Ubuntu/Debian: sudo apt install git"
    echo "    macOS: brew install git"
    exit 1
fi
print_success "git is installed"

# Check Python version
print_step "Checking Python version..."
if check_command python3; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
    PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
    
    if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 11 ]; then
        print_success "Python $PYTHON_VERSION found (>= 3.11 required)"
    else
        print_error "Python 3.11+ is required, but found $PYTHON_VERSION"
        echo "  Please install Python 3.11 or later:"
        echo "    Ubuntu/Debian: sudo apt install python3.11"
        echo "    macOS: brew install python@3.11"
        exit 1
    fi
else
    print_error "Python 3 is not installed"
    echo "  Please install Python 3.11+:"
    echo "    Ubuntu/Debian: sudo apt install python3.11"
    echo "    macOS: brew install python@3.11"
    exit 1
fi

# Check Node.js version
print_step "Checking Node.js version..."
if check_command node; then
    NODE_VERSION=$(node -v | sed 's/v//' | cut -d. -f1)
    if [ "$NODE_VERSION" -ge 18 ]; then
        print_success "Node.js v$(node -v | sed 's/v//') found (>= 18 required)"
    else
        print_error "Node.js 18+ is required, but found v$(node -v | sed 's/v//')"
        echo "  Please install Node.js 18+:"
        echo "    https://nodejs.org/ or use nvm"
        exit 1
    fi
else
    print_error "Node.js is not installed"
    echo "  Please install Node.js 18+:"
    echo "    https://nodejs.org/ or use nvm"
    exit 1
fi

# Check npm
if ! check_command npm; then
    print_error "npm is required but not installed (should come with Node.js)"
    exit 1
fi
print_success "npm is installed"

# Check GnuCOBOL (required for COBOL validation and differential testing)
print_step "Checking GnuCOBOL (COBOL compiler)..."
if check_command cobc; then
    print_success "GnuCOBOL is installed ($(cobc --version 2>&1 | head -1))"
else
    print_warning "GnuCOBOL (cobc) not found. Installing..."
    if check_command apt-get; then
        sudo apt-get update -qq && sudo apt-get install -y gnucobol
    elif check_command brew; then
        brew install gnucobol
    elif check_command dnf; then
        sudo dnf install -y gnucobol
    elif check_command pacman; then
        sudo pacman -S --noconfirm gnucobol
    else
        print_error "Could not install GnuCOBOL automatically."
        echo "  Please install GnuCOBOL manually for your platform."
        echo "  Ubuntu/Debian: sudo apt install gnucobol"
        echo "  macOS: brew install gnucobol"
        echo "  Fedora: sudo dnf install gnucobol"
        exit 1
    fi

    if check_command cobc; then
        print_success "GnuCOBOL installed successfully"
    else
        print_error "GnuCOBOL installation failed"
        echo "  Please install manually: sudo apt install gnucobol"
        exit 1
    fi
fi

# -----------------------------------------------------------------------------
# Install uv (Python package manager)
# -----------------------------------------------------------------------------

print_step "Checking uv (Python package manager)..."
if check_command uv; then
    print_success "uv is already installed ($(uv --version))"
else
    print_warning "uv not found. Installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    
    # Add uv to PATH for this session
    export PATH="$HOME/.local/bin:$PATH"
    
    if check_command uv; then
        print_success "uv installed successfully"
    else
        print_error "Failed to install uv"
        echo "  Please install manually: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
fi

# -----------------------------------------------------------------------------
# Setup Backend
# -----------------------------------------------------------------------------

print_step "Setting up backend..."

cd "$PROJECT_ROOT/backend"

# Sync Python dependencies with uv
echo "  Installing Python dependencies..."
uv sync --all-groups

print_success "Backend dependencies installed"

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        print_warning ".env file created from .env.example"
        echo -e "  ${YELLOW}⚠ Please edit backend/.env and add your API keys!${NC}"
    else
        print_error ".env.example not found"
    fi
else
    print_success ".env file already exists"
fi

# -----------------------------------------------------------------------------
# Setup Frontend
# -----------------------------------------------------------------------------

print_step "Setting up frontend..."

cd "$PROJECT_ROOT/frontend"

# Install Node.js dependencies
echo "  Installing Node.js dependencies..."
npm install

print_success "Frontend dependencies installed"

# -----------------------------------------------------------------------------
# Create required directories
# -----------------------------------------------------------------------------

print_step "Creating required directories..."

cd "$PROJECT_ROOT"

# Create logs directory
if [ ! -d "logs" ]; then
    mkdir -p logs
    touch logs/.gitkeep
    print_success "Created logs/ directory"
else
    print_success "logs/ directory already exists"
fi

# Create data directory
if [ ! -d "data" ]; then
    mkdir -p data
    print_success "Created data/ directory"
else
    print_success "data/ directory already exists"
fi

# -----------------------------------------------------------------------------
# Make scripts executable
# -----------------------------------------------------------------------------

print_step "Making scripts executable..."
chmod +x "$PROJECT_ROOT/run.sh"
chmod +x "$PROJECT_ROOT/setup.sh"
print_success "Scripts are now executable"

# -----------------------------------------------------------------------------
# Final instructions
# -----------------------------------------------------------------------------

echo -e "\n${CYAN}"
echo "============================================================"
echo "  Setup Complete!"
echo "============================================================"
echo -e "${NC}"

echo -e "${GREEN}Your environment is ready.${NC}\n"

echo -e "${YELLOW}Before running the application:${NC}"
echo -e "  1. Edit ${BLUE}backend/.env${NC} and add your LLM API key"
echo -e "     (OpenAI, Anthropic, Google, or xAI)"
echo ""

echo -e "${YELLOW}To start the application:${NC}"
echo -e "  ${BLUE}./run.sh${NC}              # Development mode (auto-reload)"
echo -e "  ${BLUE}./run.sh --no-reload${NC}  # Stable mode (for testing migrations)"
echo ""

echo -e "${YELLOW}Access the application:${NC}"
echo -e "  Frontend: ${BLUE}http://localhost:5173${NC}"
echo -e "  Backend:  ${BLUE}http://localhost:8000${NC}"
echo -e "  Health:   ${BLUE}http://localhost:8000/health${NC}"
echo ""

# Check if .env has default API key
if grep -q "sk-your-openai-key" "$PROJECT_ROOT/backend/.env" 2>/dev/null; then
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}⚠ WARNING: You must add your API key to backend/.env${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
fi

echo -e "${GREEN}Happy coding! 🚀${NC}"
