#!/bin/bash
# Development script - runs backend and frontend in parallel

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting TubeSync Development Server${NC}"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv and install dependencies
source venv/bin/activate
pip install -q -r requirements.txt

# Install frontend dependencies if needed
if [ ! -d "frontend/node_modules" ]; then
    echo "Installing frontend dependencies..."
    cd frontend && npm install && cd ..
fi

# Start backend
echo -e "${GREEN}Starting backend on http://localhost:9876${NC}"
uvicorn app.main:app --host 0.0.0.0 --port 9876 --reload &
BACKEND_PID=$!

# Wait for backend to start
sleep 2

# Start frontend dev server
echo -e "${GREEN}Starting frontend on http://localhost:3000${NC}"
cd frontend && npm run dev &
FRONTEND_PID=$!

# Trap to clean up on exit
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT

echo ""
echo -e "${GREEN}TubeSync is running!${NC}"
echo "  Backend:  http://localhost:9876"
echo "  Frontend: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop"

# Wait for processes
wait
