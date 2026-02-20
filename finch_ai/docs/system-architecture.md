# System Architecture - Finch AI

## Tổng quan Kiến trúc Hệ thống

```mermaid
graph LR
    User["👤 Data Analyst<br/>Asks business questions<br/>in natural language"]
    Finch["🚀 Finch AI System<br/>AI-powered SQL analytics<br/>Multi-agent query processing"]
    Groq["⚡ Groq API<br/>Ultra-fast LLM<br/>gpt-oss-20b"]
    OpenAI["🤖 OpenAI API<br/>Fallback<br/>gpt-4o-mini"]
    Gemini["🔮 Google Gemini<br/>Fallback<br/>gemini-1.5-flash"]
    DB[("💾 PostgreSQL<br/>15 tables")]
    
    User -->|"Asks questions<br/>HTTPS/JSON"| Finch
    Finch -->|"Generate SQL<br/>HTTPS/JSON"| Groq
    Finch -.->|Fallback| OpenAI
    Finch -.->|Fallback| Gemini
    Finch -->|"Query data<br/>PostgreSQL"| DB
    
    style User fill:#e1f5ff
    style Finch fill:#fff9c4
    style Groq fill:#81c784
    style OpenAI fill:#90caf9
    style Gemini fill:#ce93d8
    style DB fill:#90caf9
```

---

## Deployment Architecture

```mermaid
graph TB
    Browser["🌐 Web Browser"]
    API["📡 REST API - FastAPI :8888"]
    Agents["🤖 Multi-Agent System"]
    Services["⚙️ Services Layer"]
    PG[("💾 PostgreSQL 16")]
    Trans["Transactional Tables (10)"]
    Flat["Analytics Tables (2)"]
    Sys["System Tables (3)"]
    Groq["⚡ Groq API"]
    OpenAI["🤖 OpenAI API"]
    Gemini["🔮 Gemini API"]
    Docker["🐳 Docker Compose"]
    
    Browser-->API
    API-->Agents
    Agents-->Services
    Services-->PG
    Agents-->Groq
    Agents-.->OpenAI
    Agents-.->Gemini
    Docker-->PG
    PG-->Trans
    PG-->Flat
    PG-->Sys
    
    style Browser fill:#e3f2fd
    style API fill:#bbdefb
    style Agents fill:#fff9c4
    style Services fill:#ce93d8
    style PG fill:#90caf9
    style Groq fill:#81c784
    style Docker fill:#b39ddb
```

---

## Technology Stack

```mermaid
graph LR
    Root["🚀 Finch AI Tech Stack"]
    
    B["📦 Backend<br/>FastAPI 0.109<br/>Python 3.13<br/>Uvicorn"]
    D["💾 Database<br/>PostgreSQL 16<br/>SQLAlchemy 2.0<br/>15 Tables"]
    A["🤖 AI/ML<br/>Groq SDK<br/>OpenAI SDK<br/>Gemini"]
    F["🎨 Frontend<br/>HTML5/CSS3<br/>JavaScript<br/>Dark Theme"]
    O["🔧 DevOps<br/>Docker Compose<br/>venv<br/>Shell Scripts"]
    S["🔒 Security<br/>Query Validation<br/>Rate Limiting<br/>Timeouts"]
    
    Root-->B
    Root-->D
    Root-->A
    Root-->F
    Root-->O
    Root-->S
    
    style Root fill:#fff9c4
    style A fill:#81c784
    style D fill:#90caf9
    style B fill:#bbdefb
    style S fill:#ffcdd2
```

---

## Database Schema Overview

```mermaid
erDiagram
    %% Transactional Tables
    users ||--o{ trips : "takes"
    drivers ||--o{ trips : "provides"
    drivers ||--o| vehicles : "drives"
    regions ||--o{ drivers : "operates in"
    regions ||--o{ trips : "occurs in"
    trips ||--o| payments : "paid by"
    trips ||--o{ ratings : "rated by"
    trips ||--o| promotions : "uses"
    trips ||--o| surge_pricing : "subject to"
    trips ||--o{ support_tickets : "generates"
    
    %% Analytics Tables
    regions ||--o{ trip_metrics_daily : "aggregated in"
    regions ||--o{ region_revenue_summary : "summarized in"
    
    users {
        int id PK
        string email UK
        string name
        string phone
        datetime created_at
    }
    
    drivers {
        int id PK
        string name
        string email UK
        string license_number UK
        int region_id FK
        int vehicle_id FK
        float rating
        bool is_active
        int total_trips
        decimal total_earnings
    }
    
    trips {
        int id PK
        int user_id FK
        int driver_id FK
        string origin
        string destination
        float distance_km
        int duration_minutes
        decimal fare
        string status
        int payment_id FK
        int region_id FK
        datetime created_at
        datetime completed_at
    }
    
    trip_metrics_daily {
        int id PK
        date date
        int region_id FK
        int total_trips
        int completed_trips
        decimal total_revenue
        float avg_trip_distance
        int unique_users
        int unique_drivers
    }
    
    region_revenue_summary {
        int id PK
        int region_id FK
        int year
        int month
        decimal total_revenue
        int total_trips
        int active_users
        int active_drivers
        float avg_rating
    }
    
    golden_queries {
        int id PK
        string question
        string sql_query
        string description
        datetime created_at
    }
    
    metadata_index {
        int id PK
        string table_name
        string column_name
        string description
        string business_term
        datetime created_at
    }
    
    query_history {
        int id PK
        string user_question
        string generated_sql
        string execution_result
        float confidence_score
        float trust_score
        string agent_used
        string error_message
        int execution_time_ms
        datetime created_at
    }
```

---

## Request Flow - Sequence Diagram

```mermaid
sequenceDiagram
    actor User
    participant UI as Web UI
    participant API as FastAPI
    participant RL as Rate Limiter
    participant SUP as Supervisor
    participant SQL as SQL Agent
    participant META as Metadata Service
    participant SEC as Security
    participant VAL as Validator
    participant AI as AI Gateway
    participant GROQ as Groq API
    participant DB as PostgreSQL
    
    User->>UI: Enter question
    UI->>API: POST /chat
    API->>RL: Check rate limit
    RL-->>API: OK
    
    API->>SUP: Route query
    SUP->>AI: Classify intent
    AI->>GROQ: API call
    GROQ-->>AI: "SQL_QUERY"
    AI-->>SUP: Intent type
    
    SUP->>SQL: Route to SQL Agent
    SQL->>META: Build context
    META->>DB: Search metadata
    DB-->>META: Schema info
    META-->>SQL: Context package
    
    SQL->>AI: Generate SQL
    AI->>GROQ: API call with context
    GROQ-->>AI: SQL query
    AI-->>SQL: Generated SQL
    
    SQL->>SEC: Validate SQL
    SEC-->>SQL: Valid
    
    SQL->>DB: Execute query
    DB-->>SQL: Results
    
    SQL->>VAL: Validate results
    VAL->>DB: Check golden queries
    DB-->>VAL: Trust score
    VAL-->>SQL: Validation done
    
    SQL->>DB: Save to query_history
    DB-->>SQL: Saved
    
    SQL-->>API: Response
    API-->>UI: JSON
    UI-->>User: Display results
```

---

## File Structure

```
finch_ai/
├── app/
│   ├── __init__.py              # Package init
│   ├── main.py                  # FastAPI application (433 lines)
│   ├── database.py              # DB configuration
│   ├── models.py                # SQLAlchemy models (15 tables, 394 lines)
│   ├── ai_gateway.py            # Multi-provider AI gateway (375 lines)
│   ├── metadata.py              # Metadata service (195 lines)
│   ├── security.py              # Query validator + rate limiter (210 lines)
│   └── agents/
│       ├── __init__.py
│       ├── supervisor.py        # Intent classification
│       ├── sql_agent.py         # SQL generation & execution (232 lines)
│       ├── doc_agent.py         # Documentation queries
│       └── validator.py         # Golden query validation
│
├── templates/
│   └── index.html               # Main UI (complete chat interface)
│
├── static/
│   └── style.css                # Professional dark theme
│
├── docs/                        # 📁 Documentation (THIS FOLDER)
│   ├── query-processing-flow.md # Query flow diagram
│   ├── agent-architecture.md    # Multi-agent architecture
│   └── system-architecture.md   # System overview (THIS FILE)
│
├── seed_data.py                 # Database seeding (10,000+ records)
├── requirements.txt             # Python dependencies
├── docker-compose.yml           # PostgreSQL + OpenSearch
├── Dockerfile                   # Production container
├── .env                         # Environment config
├── setup.sh                     # Automated setup
├── run.sh                       # Start application
├── test.sh                      # API tests
├── README.md                    # Complete documentation
├── QUICKSTART.md                # 5-minute setup
├── ARCHITECTURE.md              # Technical architecture (13KB)
├── PROJECT_SUMMARY.md           # Project overview
└── START_HERE.txt               # Getting started

Total: 26 files created, ~4,000+ lines of code
```

---

## Key Features

### 🎯 **Knowledge-First Approach**
- Build comprehensive context before SQL generation
- Metadata service provides table schemas, business terms
- AI has full database knowledge for accurate queries

### 🤖 **Multi-Agent Architecture**
- **Supervisor**: Intent classification
- **SQL Agent**: Query generation & execution
- **Doc Agent**: Documentation queries
- **Validator**: Golden query validation

### 🔄 **AI Provider Fallback**
- Primary: Groq (free, ultra-fast)
- Fallback chain: OpenAI → Gemini → Local
- Automatic retry with exponential backoff

### 🛡️ **Security First**
- Read-only SQL enforcement
- Blocked destructive keywords
- SQL injection prevention
- Query timeout (5s)
- Rate limiting (30 req/min)

### 📊 **Data Flattening**
- 10 transactional tables for raw data
- 2 flattened analytics tables for aggregates
- Optimized for analytical queries

### ✅ **Quality Validation**
- Golden query comparison
- Trust score calculation
- Query history tracking
- Confidence scoring

---

## Configuration

### Environment Variables (.env)

```bash
# Database
DATABASE_URL=postgresql+asyncpg://finch_user:finch_password@localhost:5432/finch_db

# AI Providers
GROQ_API_KEY=gsk_your_groq_api_key_here
OPENAI_API_KEY=sk-your-openai-key-here
GOOGLE_API_KEY=your-google-api-key-here
DEFAULT_AI_MODEL=groq

# Security
QUERY_TIMEOUT_SECONDS=5
MAX_REQUESTS_PER_MINUTE=30

# App
DEBUG=true
LOG_LEVEL=INFO
```

---

## Performance Metrics

| Metric | Value | Notes |
|--------|-------|-------|
| Avg Query Time | 1.3-1.5s | End-to-end |
| AI Call Time | ~800ms | Groq inference |
| DB Query Time | ~10-20ms | PostgreSQL |
| Throughput | 30 req/min/IP | Rate limited |
| DB Records | 10,000+ | Seeded data |
| Tables | 15 | 10 trans + 2 flat + 3 sys |

---

## Deployment Commands

```bash
# Setup (one-time)
cd finch_ai
chmod +x setup.sh run.sh test.sh
./setup.sh

# Start server
./run.sh

# Test API
./test.sh

# Access
http://localhost:8888
```

---

## Monitoring & Logging

### Logging Levels
- **INFO**: Normal operations, API requests
- **WARNING**: Fallback providers used, rate limits
- **ERROR**: SQL errors, AI API failures, validation issues

### Key Metrics Tracked
- Request count per minute (rate limiting)
- AI provider usage (Groq, OpenAI, Gemini, Local)
- Query execution times
- SQL validation failures
- Trust scores from golden queries

### Log Examples

```
2026-02-18 14:30:21 - app.ai_gateway - INFO - 🚀 Calling Groq API with model: openai/gpt-oss-20b
2026-02-18 14:30:22 - app.ai_gateway - INFO - ✅ Groq API success! Model: openai/gpt-oss-20b, Tokens: 1019
2026-02-18 14:30:22 - app.agents.sql_agent - INFO - Executing SQL: SELECT d.id, d.name...
2026-02-18 14:30:22 - app.main - INFO - POST /chat - Status: 200 - Duration: 1550.19ms
```

---

## Future Enhancements

- [ ] Redis for distributed rate limiting
- [ ] OpenSearch integration for semantic metadata search
- [ ] Query caching layer
- [ ] User authentication & authorization
- [ ] Query plan visualization
- [ ] Historical query analytics dashboard
- [ ] A/B testing for AI models
- [ ] Custom golden query management UI
- [ ] Export results to CSV/Excel
- [ ] Real-time query streaming
