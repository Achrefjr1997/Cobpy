#!/bin/bash

# COBOL Migrator - Development Server Runner
# Starts both backend and frontend, cleans up on exit
#
# Usage:
#   ./run.sh              # Run with auto-reload (for development)
#   ./run.sh --no-reload  # Run without auto-reload (for stable migration testing)

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT=8000
FRONTEND_PORT=5173

# Parse arguments
USE_RELOAD="--reload"
if [ "$1" = "--no-reload" ] || [ "$1" = "-n" ]; then
    USE_RELOAD=""
    echo "Running WITHOUT auto-reload (stable mode for testing migrations)"
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# PIDs for cleanup
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    echo -e "\n${YELLOW}Shutting down servers...${NC}"
    
    # Kill backend
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo -e "${BLUE}Stopping backend (PID: $BACKEND_PID)...${NC}"
        kill "$BACKEND_PID" 2>/dev/null || true
        wait "$BACKEND_PID" 2>/dev/null || true
    fi
    
    # Kill frontend
    if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo -e "${BLUE}Stopping frontend (PID: $FRONTEND_PID)...${NC}"
        kill "$FRONTEND_PID" 2>/dev/null || true
        wait "$FRONTEND_PID" 2>/dev/null || true
    fi
    
    # Force kill anything still on the ports
    echo -e "${BLUE}Clearing ports...${NC}"
    fuser -k ${BACKEND_PORT}/tcp 2>/dev/null || true
    fuser -k ${FRONTEND_PORT}/tcp 2>/dev/null || true
    
    echo -e "${GREEN}Cleanup complete.${NC}"
    exit 0
}

# Set trap for cleanup on exit
trap cleanup EXIT INT TERM

# Check if ports are already in use
check_port() {
    local port=$1
    local name=$2
    if lsof -i :$port -t >/dev/null 2>&1; then
        echo -e "${YELLOW}Port $port is in use. Killing existing process...${NC}"
        fuser -k ${port}/tcp 2>/dev/null || true
        sleep 1
    fi
}

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  COBOL to Python Migrator - Dev Mode  ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check and clear ports
check_port $BACKEND_PORT "Backend"
check_port $FRONTEND_PORT "Frontend"

# Start backend
echo -e "${BLUE}Starting backend on port $BACKEND_PORT...${NC}"
cd "$PROJECT_ROOT/backend"
if [ -n "$USE_RELOAD" ]; then
    uv run python run_backend.py --reload &
else
    uv run python run_backend.py &
fi
BACKEND_PID=$!
echo -e "${GREEN}Backend started (PID: $BACKEND_PID)${NC}"

# Wait a moment for backend to initialize
sleep 2

# Check if backend started successfully
if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo -e "${RED}Backend failed to start!${NC}"
    exit 1
fi

# Start frontend
echo -e "${BLUE}Starting frontend on port $FRONTEND_PORT...${NC}"
cd "$PROJECT_ROOT/frontend"
npm run dev &
FRONTEND_PID=$!
echo -e "${GREEN}Frontend started (PID: $FRONTEND_PID)${NC}"

# Wait a moment for frontend to initialize
sleep 2

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Servers are running!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "  Backend:  ${BLUE}http://localhost:$BACKEND_PORT${NC}"
echo -e "  Frontend: ${BLUE}http://localhost:$FRONTEND_PORT${NC}"
echo -e "  Health:   ${BLUE}http://localhost:$BACKEND_PORT/health${NC}"
if [ -n "$USE_RELOAD" ]; then
    echo -e "  Mode:     ${YELLOW}Development (auto-reload enabled)${NC}"
else
    echo -e "  Mode:     ${GREEN}Stable (no auto-reload)${NC}"
fi
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all servers${NC}"
echo ""

# Wait for either process to exit
wait
