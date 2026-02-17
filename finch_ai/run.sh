#!/bin/bash

# Finch AI - Run Script

set -e

echo "🚀 Starting Finch AI..."

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found. Run ./setup.sh first"
    exit 1
fi

# Activate venv
. venv/bin/activate

# Check if PostgreSQL is running
if ! docker compose ps postgres | grep -q "Up"; then
    echo "⚠️  PostgreSQL not running. Starting..."
    docker compose up -d postgres
    sleep 5
fi

# Start the application
echo "Starting FastAPI server..."
echo "Access UI at: http://localhost:8000"
echo "Press Ctrl+C to stop"
echo ""

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
