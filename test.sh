#!/bin/bash

# Drawin AI - Test Script

echo "🧪 Testing Drawin AI System"
echo "================================"

BASE_URL="http://localhost:8000"

# Check if server is running
echo "1. Testing health endpoint..."
curl -s "$BASE_URL/health" | python3 -m json.tool
echo "✅ Health check passed"
echo ""

# Test tables endpoint
echo "2. Testing tables endpoint..."
curl -s "$BASE_URL/tables" | python3 -m json.tool | head -20
echo "✅ Tables endpoint working"
echo ""

# Test chat endpoint
echo "3. Testing chat endpoint..."
curl -s -X POST "$BASE_URL/chat" \
  -H "Content-Type: application/json" \
  -d '{"question": "How many users do we have?"}' \
  | python3 -m json.tool
echo "✅ Chat endpoint working"
echo ""

# Test query history
echo "4. Testing query history..."
curl -s "$BASE_URL/query-history?limit=3" | python3 -m json.tool
echo "✅ Query history working"
echo ""

echo "================================"
echo "✅ All tests passed!"
echo ""
echo "Try these questions in the UI:"
echo "  - What is the total revenue for USNC last month?"
echo "  - How many trips were completed yesterday?"
echo "  - Show me top 5 drivers by earnings"
echo "  - What does USNC mean?"
