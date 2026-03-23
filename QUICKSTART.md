# QUICK START GUIDE - DRAWIN AI

## 🎯 Mục tiêu
Chạy được hệ thống Drawin AI hoàn chỉnh trong 5 phút.

## ✅ Các bước thực hiện

### Bước 1: Chuẩn bị môi trường

```bash
cd /home/baobao/Projects/Drawin-Assistant-AI/drawin_ai

# Copy file env
cp .env.example .env
```

### Bước 2: Cấu hình API Key

Mở file `.env` và thay thế API key:

```bash
nano .env
```

Thay đổi dòng:
```
OPENAI_API_KEY=sk-your-openai-key-here
```

Thành API key thực tế của bạn.

### Bước 3: Khởi động Database

```bash
# Start PostgreSQL
docker compose up -d postgres

# Chờ 10 giây để database khởi động
sleep 10
```

### Bước 4: Cài đặt Python dependencies

```bash
# Tạo virtual environment
python3 -m venv venv

# Activate
source venv/bin/activate

# Install packages
pip install -r requirements.txt
```

### Bước 5: Seed database (quan trọng!)

```bash
# Chạy script seed data - tạo 10,000+ records
python seed_data.py
```

Kết quả mong đợi:
```
✅ SEEDING COMPLETED SUCCESSFULLY!

Database Summary:
  - Users: 1000
  - Drivers: 1000
  - Vehicles: 1000
  - Regions: 5
  - Trips: 1000
  - Trip Metrics Daily: 450
  - Region Revenue Summary: 70
  - Golden Queries: 4
  - Metadata Entries: 7
```

### Bước 6: Chạy ứng dụng

```bash
# Start FastAPI
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Bước 7: Truy cập UI

Mở trình duyệt: **http://localhost:8000**

## 🧪 Test câu hỏi mẫu

Copy và paste vào chat:

```
What is the total revenue for USNC last month?
```

Kết quả mong đợi:
1. ✅ Agent: sql_agent
2. 📝 SQL query được generate
3. 📊 Bảng kết quả hiển thị
4. 📈 Confidence score: ~0.9
5. ✅ Trust score: ~0.7-0.8
6. 💡 Explanation hiển thị

## 🎯 Demo hoàn chỉnh

### Test 1: SQL Query - Revenue
```
Question: "What is the total revenue for USNC last month?"

Expected:
- Agent: sql_agent
- SQL: SELECT SUM(total_revenue) ... WHERE r.code = 'USNC'
- Result: Một số revenue
- Trust score: High
```

### Test 2: SQL Query - Trip Count
```
Question: "How many trips were completed yesterday?"

Expected:
- Agent: sql_agent
- SQL: SELECT SUM(completed_trips) FROM trip_metrics_daily ...
- Result: Số lượng trips
```

### Test 3: Documentation
```
Question: "What does USNC mean?"

Expected:
- Agent: doc_agent
- Answer: "USNC stands for US and Canada region..."
- No SQL generated
```

## 📊 Kiểm tra các tính năng

### 1. Database Explorer (Sidebar trái)
- Click vào bất kỳ table nào
- Xem schema
- Xem 20 rows preview

### 2. Query History (Sidebar phải)
- Tất cả queries được lưu
- Hiển thị trust score
- Hiển thị execution time

### 3. Multi-Provider AI
Thay đổi trong `.env`:
```
DEFAULT_AI_MODEL=gemini  # Hoặc openai hoặc local
```

## 🔍 Kiểm tra logs

```bash
# Xem logs real-time
# Terminal đang chạy uvicorn sẽ hiển thị:

INFO: Processing question: What is the total revenue...
INFO: Classified as SQL_QUERY
INFO: Building knowledge context...
INFO: Generating SQL query...
INFO: Executing SQL: SELECT SUM...
```

## ⚠️ Troubleshooting

### Lỗi: Database connection refused
```bash
# Kiểm tra PostgreSQL
docker compose ps postgres

# Nếu không chạy
docker compose up -d postgres
sleep 10
```

### Lỗi: OpenAI API error
```bash
# Kiểm tra API key
echo $OPENAI_API_KEY

# Hoặc xem trong .env
cat .env | grep OPENAI
```

### Lỗi: No module named 'app'
```bash
# Phải chạy từ thư mục drawin_ai/
cd /home/baobao/Projects/Drawin-Assistant-AI/drawin_ai

# Và activate venv
source venv/bin/activate
```

## 📸 Screenshots mong đợi

### UI Layout:
```
┌──────────────────────────────────────────┐
│        🚀 Drawin AI                       │
├──────────┬─────────────────┬─────────────┤
│ Database │   Chat UI       │ Query       │
│ Explorer │                 │ History     │
│          │                 │             │
│ Tables   │  User Question  │ Recent      │
│ List     │  -----------    │ Queries     │
│          │  AI Response    │             │
│ Preview  │  -----------    │ Trust       │
│          │  SQL Display    │ Scores      │
│          │  Results Table  │             │
└──────────┴─────────────────┴─────────────┘
```

## ✅ Checklist hoàn thành

- [ ] PostgreSQL đang chạy
- [ ] Database đã được seed (1000+ records)
- [ ] FastAPI server đang chạy
- [ ] Mở được UI ở localhost:8000
- [ ] Chat trả lời được câu hỏi
- [ ] SQL được hiển thị
- [ ] Results được hiển thị  
- [ ] Trust score được tính
- [ ] Database explorer hoạt động
- [ ] Query history hoạt động

## 🎓 Kiến thức bổ sung

### Architecture Flow:
```
1. User nhập câu hỏi
   ↓
2. Supervisor Agent phân loại (SQL vs Doc)
   ↓
3a. SQL Agent:                3b. Doc Agent:
    - Lấy metadata                 - Lấy documentation
    - Gen SQL                      - Trả lời trực tiếp
    - Execute query
   ↓
4. Validator Agent:
    - So sánh golden query
    - Tính trust score
   ↓
5. Hiển thị kết quả đầy đủ
```

### Key Features:
1. **Knowledge-First**: Lấy metadata trước, không để AI đoán
2. **Multi-Agent**: Các agent chuyên biệt cho từng task
3. **Flattened Tables**: Dùng bảng aggregated cho analytics
4. **Golden Queries**: Validate bằng queries mẫu
5. **Security**: Chỉ cho phép SELECT, timeout 5s

## 🚀 Production Checklist

Để deploy production:

- [ ] Thay đổi database credentials
- [ ] Setup PostgreSQL cluster
- [ ] Add OpenSearch cho metadata (optional)
- [ ] Configure load balancer
- [ ] Setup monitoring (Prometheus/Grafana)
- [ ] Add authentication
- [ ] Setup log aggregation
- [ ] Configure backup
- [ ] Add SSL certificates
- [ ] Configure rate limiting theo user

---

**Chúc bạn thành công! 🎉**
