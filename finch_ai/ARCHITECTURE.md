# 🏗 Finch AI - Architecture Documentation

## 📋 Tổng quan kiến trúc

Finch AI được xây dựng theo mô hình **Multi-Agent Supervisor** với **Knowledge-First approach**, lấy cảm hứng từ kiến trúc Finch của Uber.

## 🎯 Nguyên tắc thiết kế cốt lõi

### 1. Knowledge-First Philosophy

**Vấn đề**: AI models thường "đoán" cấu trúc database, dẫn đến SQL sai.

**Giải pháp**: 
```
User Question
    ↓
Retrieve Metadata FIRST
    ↓
Build Context (table descriptions, business terms, metrics)
    ↓
Generate SQL with full context
```

**Implementation**:
```python
# app/metadata.py
async def build_context_for_query(self, db, user_question):
    # 1. Get relevant metadata
    metadata = await self.search_metadata(db, question)
    
    # 2. Resolve business terms (USNC -> US and Canada)
    term = await self.resolve_business_term(db, term)
    
    # 3. Add flattened table info
    context += "Use trip_metrics_daily for aggregated data..."
    
    return context
```

### 2. Multi-Agent Architecture

**Architecture**:
```
┌─────────────────────────────────────────┐
│          Supervisor Agent               │
│  (Intent Classification)                │
└────────────┬────────────────────────────┘
             │
        ┌────┴─────┐
        │          │
   ┌────▼───┐  ┌──▼──────┐
   │ SQL    │  │ Doc     │
   │ Agent  │  │ Agent   │
   └────┬───┘  └─────────┘
        │
   ┌────▼──────┐
   │Validator  │
   │Agent      │
   └───────────┘
```

**Agents**:

#### Supervisor Agent
- **Nhiệm vụ**: Phân loại câu hỏi → SQL query hoặc Documentation
- **Input**: User question
- **Output**: Agent type (sql_agent / doc_agent)
- **Logic**: Sử dụng AI để classify với low temperature (0.3)

#### SQL Writer Agent
- **Nhiệm vụ**: Generate + execute SQL
- **Flow**:
  1. Lấy metadata từ MetadataService
  2. Build context với business terms
  3. Generate SQL bằng AI
  4. Validate SQL (security check)
  5. Execute với timeout
  6. Return kết quả + explanation + confidence

#### Doc Reader Agent
- **Nhiệm vụ**: Trả lời câu hỏi nghiệp vụ
- **Không generate SQL**
- **Input**: Documentation question
- **Output**: Text answer với sources

#### Validator Agent
- **Nhiệm vụ**: So sánh với golden queries
- **Flow**:
  1. Tìm golden query tương tự
  2. Execute golden query
  3. So sánh kết quả (row count + values)
  4. Tính trust score (0-1)

### 3. Data Flattening Strategy

**Vấn đề**: Join nhiều bảng transactional → slow queries

**Giải pháp**: Flattened analytics tables

```sql
-- Thay vì join nhiều bảng:
SELECT r.name, COUNT(t.id), SUM(t.total_fare)
FROM trips t
JOIN regions r ON t.region_id = r.id
JOIN users u ON t.user_id = u.id
JOIN drivers d ON t.driver_id = d.id
WHERE t.pickup_time >= '2026-01-01'
GROUP BY r.name;

-- Dùng flattened table:
SELECT region_name, total_trips, total_revenue
FROM region_revenue_summary
WHERE year = 2026 AND month = 1;
```

**Flattened Tables**:

1. **trip_metrics_daily**: 
   - Daily aggregated trip statistics
   - Columns: date, region_id, total_trips, completed_trips, total_revenue, avg_fare, etc.
   - Updated: Daily batch job (hoặc real-time với triggers)

2. **region_revenue_summary**:
   - Monthly regional revenue
   - Columns: region_id, year, month, total_revenue, active_users, avg_rating, etc.
   - Updated: Monthly batch job

**AI được train để ưu tiên flattened tables**:
```python
context += """
## Flattened Analytics Tables (USE THESE FOR METRICS):
- trip_metrics_daily: Daily aggregated trip statistics
- region_revenue_summary: Monthly revenue by region

RULE: For revenue/metrics queries, USE flattened tables
"""
```

### 4. Generative AI Gateway

**Vấn đề**: Phụ thuộc vào 1 provider → downtime risk

**Giải pháp**: Multi-provider abstraction layer

```python
# app/ai_gateway.py
class AIGateway:
    async def generate(self, prompt, model=None):
        # Try primary model
        try:
            return await self._generate_openai(...)
        except:
            # Fallback to Gemini
            try:
                return await self._generate_gemini(...)
            except:
                # Fallback to local
                return await self._generate_local(...)
```

**Providers**:

| Provider | Model | Use Case | Cost |
|----------|-------|----------|------|
| OpenAI | gpt-4o-mini | Production | Low |
| Gemini | gemini-1.5-flash | Fallback | Free tier |
| Local | Stub/Ollama | Dev/Privacy | Free |

**Fallback Order**: OpenAI → Gemini → Local

**Token Tracking**:
```python
self.token_usage = {
    "total_requests": 100,
    "total_tokens": 50000,
    "by_provider": {
        "openai": {"requests": 95, "tokens": 48000},
        "gemini": {"requests": 5, "tokens": 2000}
    }
}
```

## 🗄 Database Schema Design

### Entity Relationship

```
users 1─────────* trips *─────────1 drivers
                    │                │
                    │                │
                    *                *
                 payments         vehicles
                    
trips *─────────1 regions
  │
  │
  *
ratings

trips *─────────* promotions
```

### Table Categories

**Transactional (OLTP)**:
- High write volume
- Normalized structure
- Foreign key constraints
- Real-time data

**Flattened (OLAP)**:
- Read-optimized
- Pre-aggregated
- Updated batch/scheduled
- Analytics queries

**System**:
- golden_queries: Validated reference queries
- metadata_index: Table/column metadata
- query_history: AI query logs

### Indexes Strategy

**Transactional tables**: Index on frequent JOIN/WHERE columns
```sql
CREATE INDEX idx_trips_region_date ON trips(region_id, pickup_time);
CREATE INDEX idx_drivers_region_active ON drivers(region_id, is_active);
```

**Flattened tables**: Composite indexes on query patterns
```sql
CREATE INDEX idx_metrics_region_date ON trip_metrics_daily(region_id, date);
CREATE INDEX idx_revenue_region_year_month ON region_revenue_summary(region_id, year, month);
```

## 🔐 Security Architecture

### Defense Layers

**Layer 1: Query Validation**
```python
# app/security.py
class QuerySecurityValidator:
    BLOCKED_KEYWORDS = [
        r'\bDROP\b', r'\bDELETE\b', r'\bUPDATE\b',
        r'\bINSERT\b', r'\bALTER\b', r'\bCREATE\b'
    ]
    
    def validate_query(self, sql):
        # Check destructive keywords
        # Allow only SELECT
        # Block multiple statements
```

**Layer 2: Query Timeout**
```sql
SET statement_timeout = '5s';
SELECT ... -- Query auto-killed after 5s
```

**Layer 3: Read-only Role**
```sql
CREATE ROLE finch_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO finch_readonly;
REVOKE INSERT, UPDATE, DELETE ON ALL TABLES FROM finch_readonly;
```

**Layer 4: Rate Limiting**
```python
class RateLimiter:
    max_requests = 30  # per minute
    
    def is_allowed(self, ip):
        # Track requests per IP
        # Block if exceeded
```

### SQL Injection Prevention

1. **Parameterized queries**: Via SQLAlchemy
2. **Regex validation**: Block suspicious patterns
3. **Comment stripping**: Remove -- and /* */
4. **Table whitelist**: Only allow known tables

## 📊 Golden Query System

### Purpose
- Validate AI-generated queries
- Calculate trust scores
- Continuous improvement

### Flow

```
AI generates SQL
    ↓
Find matching golden query
    ↓
Execute both queries
    ↓
Compare results:
  - Row count
  - Column values
  - SQL similarity
    ↓
Calculate trust score (0-1)
    ↓
If score < 0.6 → Flag for review
```

### Trust Score Calculation

```python
trust_score = (
    result_similarity * 0.7 +  # Results match
    sql_similarity * 0.3        # SQL structure match
)

# Result similarity
if row_count_matches:
    score += 0.4
if first_row_matches:
    score += 0.6

# SQL similarity (Jaccard)
words_overlap / words_union
```

### Human-in-the-Loop

```
Low trust score (< 0.6)
    ↓
Flag in UI
    ↓
User clicks "Request Review"
    ↓
Query saved with feedback
    ↓
Human analyst reviews
    ↓
If approved → Add to golden queries
```

## 🔄 Request Flow

### Complete Flow Example

**Question**: "What is the total revenue for USNC last month?"

**Step-by-step**:

```
1. POST /chat
   Body: {question: "What is the total revenue for USNC last month?"}
   ↓

2. Rate Limiter
   Check: IP has quota?
   Action: Allow (increment counter)
   ↓

3. Supervisor Agent
   Classify: "total revenue" → SQL_QUERY
   Route to: SQL Agent
   ↓

4. SQL Agent - Phase 1: Metadata
   Query metadata_index for:
     - "revenue" → region_revenue_summary.total_revenue (metric)
     - "USNC" → regions.code (business term)
   
   Build context:
   """
   - USNC = US and Canada region (code in regions table)
   - total_revenue in region_revenue_summary (monthly metric)
   - Use flattened table for performance
   """
   ↓

5. SQL Agent - Phase 2: Generate
   Call AI Gateway:
     Model: OpenAI (gpt-4o-mini)
     Prompt: context + question
     Temperature: 0.3
   
   AI Response:
   ```sql
   SELECT SUM(total_revenue) as revenue
   FROM region_revenue_summary rrs
   JOIN regions r ON rrs.region_id = r.id
   WHERE r.code = 'USNC'
   AND rrs.year = 2026 AND rrs.month = 1
   ```
   Explanation: "Summing monthly revenue for USNC in Jan 2026"
   Confidence: High
   ↓

6. Security Validator
   Check: Only SELECT? ✅
   Check: No destructive keywords? ✅
   Check: Single statement? ✅
   Action: PASS
   ↓

7. SQL Agent - Phase 3: Execute
   Set timeout: 5s
   Execute query
   Result: [{revenue: 245678.50}]
   ↓

8. Validator Agent
   Find golden query: "total revenue for region"
   Execute golden query
   Compare results:
     - Row count: 1 = 1 ✅
     - Revenue value: Similar ✅
     - SQL structure: 85% match
   
   Trust score: 0.87 (High)
   ↓

9. Save to query_history
   INSERT INTO query_history (
     user_question,
     generated_sql,
     confidence_score: 0.9,
     trust_score: 0.87,
     execution_time_ms: 145
   )
   ↓

10. Return Response
   {
     agent_used: "sql_agent",
     sql: "SELECT SUM...",
     explanation: "Summing monthly...",
     results: [{revenue: 245678.50}],
     confidence_score: 0.9,
     trust_score: 0.87,
     execution_time_ms: 145
   }
```

## 📈 Performance Optimization

### Database Level
- **Indexes**: All FK + common WHERE clauses
- **Connection pooling**: 10-20 connections
- **Async queries**: Non-blocking I/O
- **Query timeout**: Kill long queries at 5s

### Application Level
- **Async FastAPI**: Handle 50+ concurrent requests
- **Metadata caching**: Cache table schemas
- **Rate limiting**: Prevent DoS

### AI Gateway Level
- **Token limits**: Max 2000 tokens per response
- **Timeouts**: 30s per AI call
- **Fallback**: 3 providers for reliability

## 🧪 Testing Strategy

### Unit Tests
```python
# Test SQL generation
assert sql_agent.generate_sql("revenue for USNC") 
    contains "region_revenue_summary"

# Test security
assert validator.validate_query("DROP TABLE") == (False, "Blocked")

# Test metadata
assert metadata.resolve_term("USNC") == "US and Canada"
```

### Integration Tests
```bash
# Test full flow
curl -X POST /chat -d '{"question": "trip count"}'
assert response.status_code == 200
assert response.json()["sql"] is not None
```

### Load Tests
```bash
# 100 concurrent requests
ab -n 1000 -c 100 http://localhost:8000/chat
```

## 🚀 Deployment

### Development
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Production (Docker)
```bash
docker compose up -d
# Includes: app, postgres, opensearch
# Auto-scaling: Configure replicas
```

### Environment Variables
```env
DATABASE_URL=postgresql://...
OPENAI_API_KEY=sk-...
DEFAULT_AI_MODEL=openai
QUERY_TIMEOUT_SECONDS=5
MAX_REQUESTS_PER_MINUTE=30
```

## 🔮 Future Enhancements

1. **Real-time Updates**: WebSocket for live results
2. **Query Caching**: Redis for repeated queries
3. **Semantic Search**: Vector DB for better metadata search
4. **Auto-tuning**: ML model to optimize SQL
5. **Multi-tenancy**: Per-user query limits and history
6. **Audit Logs**: Complete query audit trail
7. **Visualization**: Auto-generate charts from results
8. **Natural Language to Chart**: Generate visualizations

---

**Designed for Production Scale** 🚀
