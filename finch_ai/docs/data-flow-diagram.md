# Data Flow Diagram - Finch AI

## Luồng dữ liệu từ User Question đến Final Answer

### Overview Flow

```mermaid
graph LR
    A[👤 User Question] --> B[🌐 Web UI]
    B --> C[📡 FastAPI]
    C --> D[🤖 Supervisor<br/>Agent]
    D --> E{Intent?}
    E -->|SQL Query| F[📊 SQL Agent]
    E -->|Documentation| G[📚 Doc Agent]
    F --> H[🔍 Metadata<br/>Service]
    H --> I[💾 PostgreSQL]
    F --> J[🤖 AI Gateway]
    J --> K[⚡ Groq API]
    F --> I
    F --> L[✅ Validator<br/>Agent]
    L --> I
    G --> J
    F --> M[📤 Response]
    G --> M
    M --> B
    B --> N[👤 User Answer]
    
    style A fill:#e1f5ff
    style N fill:#c8e6c9
    style D fill:#fff9c4
    style F fill:#fff59d
    style G fill:#fff59d
    style K fill:#81c784
    style I fill:#90caf9
```

---

## Detailed Data Flow

### 1️⃣ User Input → Web UI

```mermaid
sequenceDiagram
    participant U as 👤 User
    participant UI as 🌐 Web UI
    
    U->>UI: Types question
    Note over U,UI: "Show me top 5 drivers<br/>by total earnings"
    UI->>UI: Validate input
    UI->>UI: Prepare JSON payload
    Note over UI: {"question": "..."}
```

**Data Format:**
```javascript
{
  question: "Show me top 5 drivers by total earnings"
}
```

---

### 2️⃣ Web UI → FastAPI

```mermaid
sequenceDiagram
    participant UI as 🌐 Web UI
    participant API as 📡 FastAPI
    participant RL as ⏱️ Rate Limiter
    
    UI->>API: POST /chat
    Note over UI,API: HTTP/JSON
    API->>RL: Check limit
    RL-->>API: IP: 127.0.0.1<br/>Count: 5/30
    Note over API: Request allowed
```

**HTTP Request:**
```http
POST /chat HTTP/1.1
Content-Type: application/json

{
  "question": "Show me top 5 drivers by total earnings"
}
```

---

### 3️⃣ Supervisor Classification

```mermaid
graph TB
    A[Question:<br/>'Show me top 5 drivers by total earnings'] --> B[Supervisor Agent]
    B --> C[AI Gateway]
    C --> D[Groq API]
    D --> E[System Prompt:<br/>'You are an intent classifier...']
    E --> F[User Prompt:<br/>Question]
    F --> G[AI Response:<br/>'SQL_QUERY']
    G --> H{Intent Type}
    H -->|SQL_QUERY| I[Route to SQL Agent]
    H -->|DOC_QUERY| J[Route to Doc Agent]
    
    style D fill:#81c784
    style I fill:#fff59d
```

**AI Request to Groq:**
```json
{
  "model": "openai/gpt-oss-20b",
  "messages": [
    {
      "role": "system",
      "content": "You are an intent classifier. Determine if this is a SQL_QUERY or DOC_QUERY."
    },
    {
      "role": "user",
      "content": "Question: Show me top 5 drivers by total earnings"
    }
  ],
  "temperature": 0.7
}
```

**AI Response:**
```
Intent: SQL_QUERY
Confidence: 0.95

This is a data query requesting specific records from the database.
```

---

### 4️⃣ SQL Agent - Build Context

```mermaid
graph TB
    A[SQL Agent] --> B[Metadata Service]
    B --> C[Search metadata_index]
    C --> D[(PostgreSQL)]
    D --> E[Column: drivers.total_earnings<br/>Description: 'Total earnings accumulated']
    D --> F[Column: drivers.name<br/>Description: 'Driver full name']
    D --> G[Business Term: 'earnings' = total_earnings]
    E --> H[Context Package]
    F --> H
    G --> H
    
    H --> I[Full Context:<br/>- Table schemas<br/>- Column descriptions<br/>- Business terms<br/>- Query rules]
    
    style D fill:#90caf9
    style I fill:#ce93d8
```

**Context Built:**
```markdown
# DATABASE CONTEXT

## Transactional Tables:
- drivers: id, name, email, total_earnings, rating, region_id
  ⚠️ drivers table has name/email directly, NO user_id!

## Important Rules:
1. For INDIVIDUAL driver queries, USE drivers table
2. ORDER BY for top/best queries
3. Use LIMIT for result count

## Business Terms:
- earnings = total_earnings column
```

---

### 5️⃣ SQL Agent - Generate SQL

```mermaid
sequenceDiagram
    participant SQL as SQL Agent
    participant AI as AI Gateway
    participant GROQ as Groq API
    
    SQL->>AI: Generate SQL
    Note over SQL,AI: Context + Question
    AI->>GROQ: API Request
    Note over GROQ: model: openai/gpt-oss-20b<br/>temperature: 0.3
    GROQ-->>AI: Generated SQL
    Note over GROQ: ```sql<br/>SELECT d.id, d.name,<br/>d.total_earnings...<br/>```
    AI-->>SQL: SQL Response
    SQL->>SQL: Extract SQL from response
```

**AI Request:**
```json
{
  "model": "openai/gpt-oss-20b",
  "messages": [
    {
      "role": "system",
      "content": "You are an expert SQL generator..."
    },
    {
      "role": "user",
      "content": "[CONTEXT]\n\nQuestion: Show me top 5 drivers by total earnings"
    }
  ],
  "temperature": 0.3,
  "max_tokens": 1000
}
```

**AI Response:**
```sql
SELECT
    d.id,
    d.name,
    d.total_earnings,
    r.code AS region_code
FROM
    drivers d
LEFT JOIN
    regions r ON d.region_id = r.id
ORDER BY
    d.total_earnings DESC
LIMIT 5;
```

**Explanation:** This query retrieves the top 5 drivers by total earnings...

**Confidence:** High

---

### 6️⃣ Security Validation

```mermaid
graph TB
    A[Generated SQL] --> B{Security<br/>Validator}
    B -->|Check 1| C[Blocked Keywords?<br/>DROP, DELETE, UPDATE...]
    B -->|Check 2| D[Multiple Statements?<br/>; separation]
    B -->|Check 3| E[Comments?<br/>--, /*, */]
    B -->|Check 4| F[SELECT Only?]
    
    C -->|None| G[✅ Pass]
    D -->|Single| G
    E -->|None| G
    F -->|Yes| G
    
    C -->|Found| H[❌ Block]
    D -->|Multiple| H
    E -->|Found| H
    F -->|No| H
    
    G --> I[Execute SQL]
    H --> J[Return Error]
    
    style G fill:#c8e6c9
    style H fill:#ffcdd2
```

**Validation Result:**
```json
{
  "is_valid": true,
  "error_message": null,
  "checks_passed": [
    "No blocked keywords",
    "Single statement",
    "No comments",
    "SELECT only"
  ]
}
```

---

### 7️⃣ SQL Execution

```mermaid
sequenceDiagram
    participant SQL as SQL Agent
    participant DB as PostgreSQL
    
    SQL->>DB: SET statement_timeout = '5s'
    SQL->>DB: BEGIN TRANSACTION
    SQL->>DB: Execute SELECT query
    Note over DB: Query execution
    DB-->>SQL: Results (5 rows)
    SQL->>DB: RESET statement_timeout
    SQL->>DB: COMMIT
    
    Note over SQL: Convert rows to JSON
```

**Database Query:**
```sql
SET statement_timeout = '5s';

SELECT
    d.id,
    d.name,
    d.total_earnings,
    r.code AS region_code
FROM drivers d
LEFT JOIN regions r ON d.region_id = r.id
ORDER BY d.total_earnings DESC
LIMIT 5;

RESET statement_timeout;
```

**Results:**
```json
[
  {
    "id": 456,
    "name": "John Smith",
    "total_earnings": "15234.50",
    "region_code": "USNC"
  },
  {
    "id": 789,
    "name": "Maria Garcia",
    "total_earnings": "14890.25",
    "region_code": "USNE"
  },
  ...
]
```

---

### 8️⃣ Validator Agent - Golden Query Check

```mermaid
graph TB
    A[Validator Agent] --> B[Search golden_queries]
    B --> C[(PostgreSQL)]
    C --> D[Match similar questions]
    D --> E{Found<br/>Match?}
    E -->|Yes| F[Compare SQL]
    F --> G[Calculate Similarity]
    G --> H[Trust Score: 0.85]
    E -->|No| I[Trust Score: 0.6<br/>No golden reference]
    
    H --> J[Validation Notes]
    I --> J
    
    style C fill:#90caf9
    style H fill:#c8e6c9
    style I fill:#fff9c4
```

**Golden Query Search:**
```sql
SELECT * FROM golden_queries
WHERE question ILIKE '%top%driver%earning%'
ORDER BY created_at DESC
LIMIT 5;
```

**Validation Result:**
```json
{
  "trust_score": 0.85,
  "validation_notes": [
    "Similar to golden query #3",
    "SQL structure matches best practice",
    "Result count appropriate"
  ],
  "matched_golden_id": 3
}
```

---

### 9️⃣ Save Query History

```mermaid
sequenceDiagram
    participant SQL as SQL Agent
    participant DB as PostgreSQL
    
    SQL->>DB: INSERT INTO query_history
    Note over DB: Store:<br/>- question<br/>- generated_sql<br/>- results<br/>- confidence_score<br/>- trust_score<br/>- execution_time_ms
    DB-->>SQL: History ID: 1234
```

**Insert:**
```sql
INSERT INTO query_history (
  user_question,
  generated_sql,
  execution_result,
  confidence_score,
  trust_score,
  agent_used,
  execution_time_ms
) VALUES (
  'Show me top 5 drivers by total earnings',
  'SELECT d.id, d.name...',
  '[{"id": 456, "name": "John Smith"...}]',
  0.9,
  0.85,
  'sql_agent',
  1550
);
```

---

### 🔟 Build Final Response

```mermaid
graph TB
    A[SQL Agent Results] --> B[Build ChatResponse]
    A1[Confidence: 0.9] --> B
    A2[Trust Score: 0.85] --> B
    A3[Results: 5 rows] --> B
    A4[Execution Time: 1550ms] --> B
    
    B --> C[JSON Response Object]
    C --> D[Return to FastAPI]
    D --> E[Return to Web UI]
    
    style C fill:#c8e6c9
```

**Final Response:**
```json
{
  "question": "Show me top 5 drivers by total earnings",
  "agent_used": "sql_agent",
  "sql": "SELECT d.id, d.name, d.total_earnings, r.code AS region_code FROM drivers d LEFT JOIN regions r ON d.region_id = r.id ORDER BY d.total_earnings DESC LIMIT 5;",
  "explanation": "This query retrieves the top 5 drivers...",
  "answer": null,
  "results": [
    {
      "id": 456,
      "name": "John Smith",
      "total_earnings": "15234.50",
      "region_code": "USNC"
    },
    ...
  ],
  "row_count": 5,
  "confidence_score": 0.9,
  "trust_score": 0.85,
  "validation_notes": [
    "Similar to golden query #3",
    "SQL structure matches best practice"
  ],
  "error": null,
  "execution_time_ms": 1550
}
```

---

### 1️⃣1️⃣ Display to User

```mermaid
graph LR
    A[JSON Response] --> B[Web UI JavaScript]
    B --> C[Parse Response]
    C --> D[Display SQL]
    C --> E[Display Table]
    C --> F[Display Metrics]
    
    D --> G[Syntax Highlighted Code Block]
    E --> H[Interactive Data Table]
    F --> I[Trust Score: 0.85<br/>Execution: 1550ms]
    
    G --> J[👤 User Sees Results]
    H --> J
    I --> J
    
    style J fill:#c8e6c9
```

**UI Display:**
```
╔═══════════════════════════════════════╗
║  SQL Generated:                        ║
║  SELECT d.id, d.name, d.total_earnings║
║  FROM drivers d                        ║
║  ORDER BY d.total_earnings DESC        ║
║  LIMIT 5;                              ║
╠═══════════════════════════════════════╣
║  Results (5 rows):                     ║
║  ┌────┬──────────────┬────────────┐   ║
║  │ ID │ Name         │ Earnings   │   ║
║  ├────┼──────────────┼────────────┤   ║
║  │456 │ John Smith   │ $15,234.50 │   ║
║  │789 │ Maria Garcia │ $14,890.25 │   ║
║  └────┴──────────────┴────────────┘   ║
╠═══════════════════════════════════════╣
║  Trust Score: 0.85 ⭐⭐⭐⭐            ║
║  Execution Time: 1.55s                 ║
╚═══════════════════════════════════════╝
```

---

## Data Flow Summary

```mermaid
stateDiagram-v2
    [*] --> UserInput: Question
    UserInput --> RateLimit: HTTP POST
    RateLimit --> Supervisor: Check OK
    Supervisor --> Classification: AI Call
    Classification --> SQLAgent: SQL_QUERY
    Classification --> DocAgent: DOC_QUERY
    SQLAgent --> BuildContext: Get Schema
    BuildContext --> GenerateSQL: AI Call
    GenerateSQL --> ValidateSQL: Security Check
    ValidateSQL --> ExecuteSQL: Valid
    ExecuteSQL --> ValidateResults: Query OK
    ValidateResults --> SaveHistory: Trust Score
    SaveHistory --> Response: Build JSON
    DocAgent --> GenerateAnswer: AI Call
    GenerateAnswer --> Response: Build JSON
    Response --> UserOutput: Display
    UserOutput --> [*]
    
    ValidateSQL --> ErrorResponse: Invalid
    ExecuteSQL --> ErrorResponse: Failed
    ErrorResponse --> [*]
```

---

## Timing Breakdown

```
Total: ~1.5 seconds
├── Rate Limit Check: <1ms
├── Supervisor Classification: ~500ms
│   └── Groq API call
├── Build Context: ~50ms
│   └── Search metadata_index
├── Generate SQL: ~800ms
│   └── Groq API call
├── Validate SQL: <1ms
├── Execute SQL: ~20ms
│   └── PostgreSQL query
├── Validate Results: ~5ms
│   └── Golden query check
└── Save History: ~5ms
    └── Insert to query_history
```

---

## Data Size Flow

```
User Input:     ~50 bytes
  ↓
Context Built:  ~2 KB (metadata + rules)
  ↓
AI Request:     ~3 KB (context + prompt)
  ↓
AI Response:    ~500 bytes (SQL + explanation)
  ↓
SQL Query:      ~200 bytes
  ↓
DB Results:     ~1 KB (5 rows × ~200 bytes)
  ↓
Final Response: ~2 KB (all fields)
  ↓
User Display:   ~2 KB (rendered HTML)
```

---

**Total Data Transferred:** ~11 KB per query
