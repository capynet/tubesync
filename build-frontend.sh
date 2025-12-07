#!/bin/bash
# Build frontend for production

cd frontend

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install
fi

# Build
echo "Building frontend..."
npm run build

echo "Frontend built successfully in frontend/dist/"
