#!/bin/bash
# Clean TubeSync data for fresh testing

set -e

DATA_DIR="$HOME/.local/share/tubesync"

echo "Stopping TubeSync processes..."
pkill -f uvicorn 2>/dev/null || true
pkill -f vite 2>/dev/null || true
pkill -f "node.*tubesync" 2>/dev/null || true
sleep 2

echo "Cleaning database..."
rm -f "$DATA_DIR/data/videos.db"*
rm -f "$DATA_DIR/tubesync.db"*

echo "Cleaning downloads..."
rm -rf "$DATA_DIR/downloads/"*

echo "Done! Data cleaned."
echo ""
echo "To start fresh, run: ./run-dev.sh"
