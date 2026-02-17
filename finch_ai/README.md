# 🚀 Finch AI - Agentic SQL Analytics Platform

Multi-agent AI system for natural language SQL queries on PostgreSQL, inspired by Uber's Finch architecture.

## 📋 Features

✅ **Multi-Agent Architecture**
- Supervisor Agent: Routes queries to appropriate agent
- SQL Writer Agent: Generates SQL from natural language
- Doc Reader Agent: Answers documentation questions
- Validator Agent: Validates queries against golden queries

✅ **Knowledge-First Approach**
- Metadata retrieval before SQL generation
- Business term resolution (USNC → US and Canada)
- Flattened analytics tables for performance

✅ **AI Gateway**
- OpenAI (GPT-4o-mini)
- Google Gemini (Gemini 1.5 Flash)
- Local model support (stub)
- Automatic fallback

✅ **Security**
- Read-only SQL enforcement
- Query validation and sanitization
- 5-second query timeout
- Rate limiting (30 req/min)

✅ **Golden Query Validation**
- Compare AI-generated queries with validated examples
- Calculate trust scores
- Human-in-the-loop review system

✅ **Database**
- 10 transactional tables (users, drivers, trips, etc.)
- 2 flattened analytics tables
- 1000+ records per table
- PostgreSQL with full indexing

✅ **UI**
- Chat interface for natural language queries
- Database explorer with table preview
- Query history with trust scores
- Real-time SQL display

## 🏗 Architecture

```
┌─────────────────┐
│   User Query    │
└────────┬────────┘
         │
    ┌────▼────┐
    │Supervisor│
    └────┬────┘
         │
    ┌────┴─────┐
    │          │
┌───▼──┐   ┌──▼───┐
│ SQL  │   │ Doc  │
│Agent │   │Agent │
└───┬──┘   └──────┘
    │
┌───▼────────┐
│ Validator  │
└────────────┘
```

## 📦 Tech Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy
- **Database**: PostgreSQL 16
- **Search**: OpenSearch 2.11 (metadata)
- **AI**: OpenAI, Google Gemini, Local models
- **Frontend**: HTML/CSS/JavaScript
- **Deployment**: Docker Compose

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- OpenAI API key (required)
- Google API key (optional)

### 1. Clone & Setup

```bash
cd finch_ai
cp .env.example .env
```

### 2. Configure Environment

Edit `.env`:

```env
DATABASE_URL=postgresql+asyncpg://finch_user:finch_password@localhost:5432/finch_db
OPENAI_API_KEY=sk-your-actual-openai-key-here
GOOGLE_API_KEY=your-google-key-here  # Optional
DEFAULT_AI_MODEL=openai
```

### 3. Start Services

```bash
# Start PostgreSQL and OpenSearch
docker compose up -d postgres opensearch

# Wait for services to be healthy
docker compose ps
```

### 4. Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install packages
pip install -r requirements.txt
```

### 5. Seed Database

```bash
# Initialize database and seed 1000+ records
python seed_data.py
```

Expected output:
```
Creating 5 regions
Created 1000 users
Created 1000 vehicles
Created 1000 drivers
Created 1000 trips
...
✅ SEEDING COMPLETED SUCCESSFULLY!
```

### 6. Run Application

```bash
# Start FastAPI server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 7. Access UI

Open browser: **http://localhost:8000**

## 💬 Example Queries

Try these questions in the chat interface:

### Analytics Queries (SQL Agent)
```
What is the total revenue for USNC last month?
How many trips were completed yesterday?
Show me top 5 drivers by earnings
What is the average rating of drivers in APAC?
How many active users do we have?
```

### Documentation Queries (Doc Agent)
```
What does USNC mean?
Explain surge pricing
What tables are available?
What metrics can I query?
```

## 🎯 Expected Behavior

When you ask: **"What is the total revenue for USNC last month?"**

**Step 1**: Supervisor classifies as SQL_QUERY

**Step 2**: SQL Agent:
- Retrieves metadata: "USNC = US and Canada"
- Finds flattened table: `region_revenue_summary`
- Generates SQL:
```sql
SELECT SUM(total_revenue) as revenue
FROM region_revenue_summary rrs
JOIN regions r ON rrs.region_id = r.id
WHERE r.code = 'USNC'
AND rrs.year = 2026 AND rrs.month = 1
```

**Step 3**: Validator:
- Compares with golden query
- Calculates trust score: 0.85

**Step 4**: UI displays:
- ✅ SQL query
- 📊 Results table
- 📈 Confidence: 0.9
- ✅ Trust: 0.85
- 📝 Explanation

## 📁 Project Structure

```
finch_ai/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app
│   ├── database.py          # DB config
│   ├── models.py            # SQLAlchemy models (10 tables)
│   ├── ai_gateway.py        # Multi-provider AI gateway
│   ├── metadata.py          # Metadata service
│   ├── security.py          # Query validator & rate limiter
│   └── agents/
│       ├── supervisor.py    # Routes queries
│       ├── sql_agent.py     # SQL generation
│       ├── doc_agent.py     # Documentation
│       └── validator.py     # Golden query validation
├── templates/
│   └── index.html           # UI
├── static/
│   └── style.css            # Styles
├── seed_data.py             # Data seeding script
├── requirements.txt
├── docker compose.yml
├── Dockerfile
└── README.md
```

## 🗄 Database Schema

### Transactional Tables (10)
1. `users` - User accounts
2. `drivers` - Driver accounts
3. `trips` - Trip records
4. `payments` - Payment transactions
5. `regions` - Geographic regions
6. `vehicles` - Vehicle information
7. `promotions` - Promotional campaigns
8. `ratings` - Trip ratings
9. `surge_pricing` - Surge pricing events
10. `support_tickets` - Customer support

### Flattened Analytics Tables (2)
1. `trip_metrics_daily` - Daily aggregated metrics
2. `region_revenue_summary` - Monthly regional revenue

### System Tables
- `golden_queries` - Validated reference queries
- `metadata_index` - Table/column metadata
- `query_history` - AI query logs

## 🔒 Security Features

### Query Validation
- ✅ Only SELECT queries allowed
- ❌ Blocks: DROP, DELETE, UPDATE, INSERT, ALTER
- ✅ 5-second query timeout
- ✅ SQL injection prevention

### Rate Limiting
- 30 requests per minute per IP
- Configurable via `MAX_REQUESTS_PER_MINUTE`

### Database Access
- Read-only role recommended for AI
- Connection pooling (min=10, max=20)
- Async/await for performance

## 🧪 Testing

### Test SQL Agent
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "How many trips were completed yesterday?"}'
```

### Test Database Explorer
```bash
# List all tables
curl http://localhost:8000/tables

# Preview table
curl http://localhost:8000/table/trips
```

### Test Query History
```bash
curl http://localhost:8000/query-history?limit=10
```

## 📊 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web UI |
| GET | `/health` | Health check |
| POST | `/chat` | Submit question |
| GET | `/tables` | List all tables |
| GET | `/table/{name}` | Table preview |
| GET | `/query-history` | Query history |
| POST | `/request-review` | Request human review |
| GET | `/stats` | System statistics |

## 🐳 Docker Deployment

Full stack with Docker Compose:

```bash
# Build and start all services
docker compose up --build

# App runs on: http://localhost:8000
# PostgreSQL: localhost:5432
# OpenSearch: localhost:9200
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Async PostgreSQL URL | - |
| `OPENAI_API_KEY` | OpenAI API key | Required |
| `GOOGLE_API_KEY` | Google Gemini key | Optional |
| `DEFAULT_AI_MODEL` | openai/gemini/local | openai |
| `QUERY_TIMEOUT_SECONDS` | SQL timeout | 5 |
| `MAX_REQUESTS_PER_MINUTE` | Rate limit | 30 |

### AI Models

**OpenAI** (Default):
- Model: gpt-4o-mini
- Cost-effective, fast
- Best for production

**Google Gemini**:
- Model: gemini-1.5-flash
- Free tier available
- Good fallback option

**Local Model**:
- Stub implementation provided
- Replace with Ollama/vLLM in production

## 📈 Performance

- **Query Response**: 500ms - 2s
- **Database Queries**: < 100ms (with indexes)
- **AI Response**: 1-3s (depends on model)
- **Concurrent Users**: 50+ (with rate limiting)

## 🎓 Key Concepts

### Knowledge-First
Metadata is retrieved BEFORE SQL generation to avoid AI hallucination.

### Multi-Agent
Different agents for different tasks (SQL vs. documentation).

### Flattened Tables
Pre-aggregated data for faster analytics queries.

### Golden Queries
Validated reference queries for trust scoring.

### Human-in-the-Loop
Queries can be flagged for human review.

## 🐛 Troubleshooting

### Database Connection Error
```bash
# Check PostgreSQL is running
docker compose ps postgres

# Check connection
psql postgresql://finch_user:finch_password@localhost:5432/finch_db
```

### OpenAI API Error
```bash
# Verify API key
echo $OPENAI_API_KEY

# Test API
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

### No Results in UI
- Check browser console for errors
- Verify API endpoint: http://localhost:8000/health
- Check FastAPI logs for errors

## 📝 License

MIT License

## 🙋 Support

For issues or questions, check:
- Application logs: `docker compose logs app`
- Database logs: `docker compose logs postgres`
- Query history: http://localhost:8000/query-history

## 🚀 Next Steps

1. ✅ System is running
2. 🧪 Test example queries
3. 📊 Explore database tables
4. 🔍 Check query history
5. ⚙️ Customize for your use case

---

**Built with ❤️ using FastAPI, PostgreSQL, and OpenAI**
