#!/bin/bash

# Finch AI - Quick Setup Script

set -e

echo "=================================================="
echo "🚀 Finch AI - Quick Setup"
echo "=================================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if we're in the right directory
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}❌ Error: Must run from finch_ai directory${NC}"
    exit 1
fi

# Step 1: Check .env
echo -e "\n${YELLOW}Step 1: Checking .env file...${NC}"
if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo -e "${RED}⚠️  IMPORTANT: Edit .env and add your OPENAI_API_KEY!${NC}"
    echo "Press Enter after you've updated .env with your API key..."
    read
fi

# Step 2: Start PostgreSQL
echo -e "\n${YELLOW}Step 2: Starting PostgreSQL...${NC}"
docker compose up -d postgres
echo "Waiting for PostgreSQL to be ready..."
sleep 10
echo -e "${GREEN}✅ PostgreSQL started${NC}"

# Step 3: Setup Python environment
echo -e "\n${YELLOW}Step 3: Setting up Python environment...${NC}"

# Check for PostgreSQL development headers
if ! command -v pg_config > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  PostgreSQL development headers not found${NC}"
    echo "Installing libpq-dev (required for psycopg2)..."
    echo "If this fails, run manually:"
    echo -e "${YELLOW}  sudo apt-get install -y libpq-dev${NC}"
    echo "  (or equivalent for your OS)"
    echo ""
fi

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}✅ Virtual environment created${NC}"
fi

. venv/bin/activate
echo "Upgrading pip..."
pip install --upgrade pip > /dev/null 2>&1
echo "Installing dependencies..."
pip install --upgrade setuptools wheel > /dev/null 2>&1
pip install -r requirements.txt
echo -e "${GREEN}✅ Dependencies installed${NC}"

# Step 4: Seed database
echo -e "\n${YELLOW}Step 4: Seeding database (this may take a minute)...${NC}"
python seed_data.py

# Step 5: Instructions
echo -e "\n${GREEN}=================================================="
echo "✅ Setup Complete!"
echo "==================================================${NC}"
echo ""
echo "To start the application:"
echo "  1. Make sure you're in the virtual environment:"
echo "     ${YELLOW}source venv/bin/activate${NC}"
echo ""
echo "  2. Run the server:"
echo "     ${YELLOW}uvicorn app.main:app --reload --host 0.0.0.0 --port 8000${NC}"
echo ""
echo "  3. Open browser:"
echo "     ${YELLOW}http://localhost:8000${NC}"
echo ""
echo "Try these example questions:"
echo "  - What is the total revenue for USNC last month?"
echo "  - How many trips were completed yesterday?"
echo "  - What does USNC mean?"
echo ""
echo -e "${GREEN}Happy querying! 🎉${NC}"
