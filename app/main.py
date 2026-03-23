"""FastAPI main application."""
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, desc, inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, init_db, async_engine
from app.models import QueryHistory, User, Driver, Trip, Region, Vehicle
from app.agents.supervisor import supervisor
from app.agents.validator import validator_agent
from app.security import rate_limiter
from app.ai_gateway import ai_gateway
from app.progress import set_emitter
from app.chart_generator import try_generate_chart

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# In-memory SSE event queues keyed by session_id
_session_queues: dict[str, asyncio.Queue] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup
    logger.info("Starting Drawin AI application...")
    await init_db()
    logger.info("Database initialized")
    yield
    # Shutdown
    logger.info("Shutting down Drawin AI application...")


# Create FastAPI app
app = FastAPI(
    title="Drawin AI - Agentic SQL Analytics",
    description="AI-powered PostgreSQL analytics with multi-agent architecture",
    version="1.0.0",
    lifespan=lifespan
)

# Setup templates and static files
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static", html=True), name="static")


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class ChatRequest(BaseModel):
    question: str
    model: Optional[str] = None
    session_id: Optional[str] = None   # if set, progress events are emitted to /api/events/{session_id}


class ChatResponse(BaseModel):
    question: str
    agent_used: str
    sql: Optional[str] = None
    explanation: Optional[str] = None
    answer: Optional[str] = None  # For doc agent
    results: Optional[list] = None
    row_count: Optional[int] = None
    confidence_score: Optional[float] = None
    trust_score: Optional[float] = None
    validation_notes: Optional[list] = None
    error: Optional[str] = None
    execution_time_ms: int
    # Performance telemetry (PPT)
    db_execution_time_ms: Optional[float] = None   # actual DB round-trip
    estimated_query_cost: Optional[float] = None   # planner cost units
    was_result_limited: Optional[bool] = None      # True if auto-LIMIT applied
    ppt_complexity: Optional[int] = None           # 0-10 complexity score
    ppt_strategy: Optional[str] = None             # aggregated_table|raw_table|hybrid
    validation_strategy: Optional[str] = None      # full|lightweight|skip_golden
    chart_image: Optional[str] = None              # base64 PNG (data URI content)
    chart_type: Optional[str] = None               # bar|line|pie|horizontal_bar|multi_bar


class ReviewRequest(BaseModel):
    query_id: int
    feedback: str


# ============================================================================
# MIDDLEWARE
# ============================================================================

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests."""
    start_time = time.time()
    
    # Process request
    response = await call_next(request)
    
    # Calculate duration
    duration = (time.time() - start_time) * 1000
    
    logger.info(
        f"{request.method} {request.url.path} - "
        f"Status: {response.status_code} - "
        f"Duration: {duration:.2f}ms"
    )
    
    return response


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render main UI."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "drawin-ai",
        "version": "2.0.0",
        "architecture": "PPT (Perception-Planning-Tool)"
    }


@app.get("/api/events/{session_id}")
async def sse_events(session_id: str, request: Request):
    """
    Server-Sent Events stream for a given session.
    Clients connect here to receive streamed updates while a query runs.
    """

    # Create a queue for this session if it doesn't exist yet
    if session_id not in _session_queues:
        _session_queues[session_id] = asyncio.Queue()

    queue: asyncio.Queue = _session_queues[session_id]

    async def event_stream() -> AsyncGenerator[bytes, None]:
        try:
            while True:
                # Honour client disconnects
                if await request.is_disconnected():
                    break

                try:
                    # Wait up to 25 s for a real event; send a heartbeat comment
                    # if nothing arrives so the connection stays alive.
                    event_data = await asyncio.wait_for(queue.get(), timeout=25)
                    yield f"data: {json.dumps(event_data)}\n\n".encode()
                    queue.task_done()

                    # Sentinel: close the stream gracefully after the final event
                    if event_data.get("type") == "done":
                        break

                except asyncio.TimeoutError:
                    # SSE heartbeat comment (ignored by browsers, keeps TCP alive)
                    yield b": heartbeat\n\n"

        finally:
            _session_queues.pop(session_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    req: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Main chat endpoint - processes user questions.
    Routes to appropriate agent via supervisor.
    """
    start_time = time.time()

    # ── SSE progress emitter setup ───────────────────────────────────────────
    emitter_token = None
    if request.session_id:
        sid = request.session_id
        if sid not in _session_queues:
            _session_queues[sid] = asyncio.Queue()
        _queue = _session_queues[sid]

        async def _emit(event: dict) -> None:
            try:
                await _queue.put(event)
            except Exception:
                pass

        emitter_token = set_emitter(_emit)

    # Rate limiting
    client_ip = req.client.host
    is_allowed, error_msg = rate_limiter.is_allowed(client_ip)

    if not is_allowed:
        raise HTTPException(status_code=429, detail=error_msg)

    try:
        # Route query through supervisor
        logger.info(f"Processing question: {request.question}")

        response = await supervisor.route_query(request.question, db)
        
        # If SQL agent was used, validate results
        trust_score = None
        validation_notes = None
        validation: dict = {}

        if response.get("agent_used") == "sql_agent" and response.get("sql"):
            if response.get("results") is not None and not response.get("error"):
                validation = await validator_agent.validate_query(
                    db,
                    request.question,
                    response["sql"],
                    response["results"],
                    estimated_cost=response.get("estimated_cost"),
                )
                trust_score = validation["trust_score"]
                validation_notes = validation["validation_notes"]
        
        # Calculate execution time
        execution_time_ms = int((time.time() - start_time) * 1000)
        
        # Save to query history (with error handling)
        try:
            history = QueryHistory(
                user_question=request.question,
                generated_sql=response.get("sql"),
                execution_result=str(response.get("results", ""))[:5000],  # Truncate
                confidence_score=response.get("confidence_score"),
                trust_score=trust_score,
                agent_used=response.get("agent_used"),
                error_message=response.get("error"),
                execution_time_ms=execution_time_ms
            )
            db.add(history)
            await db.commit()
        except Exception as hist_error:
            logger.error(f"Failed to save query history: {hist_error}")
            await db.rollback()
        
        # Auto-generate chart for SQL agent results
        chart_result = None
        if (
            response.get("agent_used") == "sql_agent"
            and response.get("results")
            and not response.get("error")
        ):
            try:
                chart_result = try_generate_chart(
                    response["results"],
                    request.question,
                    response.get("sql", ""),
                )
            except Exception as chart_err:
                logger.warning(f"Chart generation failed (non-fatal): {chart_err}")

        # Build response
        chat_response = ChatResponse(
            question=request.question,
            agent_used=response.get("agent_used", "unknown"),
            sql=response.get("sql"),
            explanation=response.get("explanation"),
            answer=response.get("answer"),
            results=response.get("results"),
            row_count=response.get("row_count"),
            confidence_score=response.get("confidence_score"),
            trust_score=trust_score,
            db_execution_time_ms=response.get("execution_time_ms"),
            estimated_query_cost=response.get("estimated_cost"),
            was_result_limited=response.get("was_limited"),
            ppt_complexity=response.get("ppt_complexity"),
            ppt_strategy=response.get("ppt_strategy"),
            validation_strategy=validation.get("validation_strategy") if trust_score is not None else None,
            validation_notes=validation_notes,
            error=response.get("error"),
            execution_time_ms=execution_time_ms,
            chart_image=chart_result.get("chart_b64") if chart_result else None,
            chart_type=chart_result.get("chart_type") if chart_result else None,
        )

        # Signal SSE stream that processing is complete
        if request.session_id and request.session_id in _session_queues:
            await _session_queues[request.session_id].put({
                "type": "done",
                "execution_time_ms": execution_time_ms,
            })

        return chat_response

    except Exception as e:
        logger.error(f"Chat error: {e}")
        execution_time_ms = int((time.time() - start_time) * 1000)

        if request.session_id and request.session_id in _session_queues:
            await _session_queues[request.session_id].put({
                "type": "done",
                "error": str(e),
                "execution_time_ms": execution_time_ms,
            })
        
        return ChatResponse(
            question=request.question,
            agent_used="error",
            error=str(e),
            execution_time_ms=execution_time_ms
        )


@app.get("/tables")
async def get_tables(db: AsyncSession = Depends(get_db)):
    """Get list of all tables with row counts."""
    
    try:
        tables_info = []
        
        # Get all table names from database
        async with async_engine.connect() as conn:
            def get_table_names(connection):
                inspector = inspect(connection)
                return inspector.get_table_names()
            
            table_names = await conn.run_sync(get_table_names)
        
        # Get row counts
        for table_name in table_names:
            try:
                # Execute count query
                from sqlalchemy import text
                result = await db.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                count = result.scalar()
                
                tables_info.append({
                    "name": table_name,
                    "row_count": count,
                    "type": "flattened" if "metrics" in table_name or "summary" in table_name else "transactional"
                })
            except Exception as e:
                logger.error(f"Error counting {table_name}: {e}")
                tables_info.append({
                    "name": table_name,
                    "row_count": 0,
                    "type": "unknown"
                })
        
        return {"tables": tables_info}
        
    except Exception as e:
        logger.error(f"Error fetching tables: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/table/{table_name}")
async def get_table_preview(
    table_name: str,
    db: AsyncSession = Depends(get_db)
):
    """Get preview of table data (first 20 rows) and schema."""
    
    try:
        from sqlalchemy import text
        
        # Validate table name (prevent SQL injection)
        async with async_engine.connect() as conn:
            def get_table_names(connection):
                inspector = inspect(connection)
                return inspector.get_table_names()
            
            valid_tables = await conn.run_sync(get_table_names)
        
        if table_name not in valid_tables:
            raise HTTPException(status_code=404, detail="Table not found")
        
        # Get schema
        async with async_engine.connect() as conn:
            def get_columns(connection):
                inspector = inspect(connection)
                return inspector.get_columns(table_name)
            
            columns = await conn.run_sync(get_columns)
        
        schema = [
            {
                "name": col["name"],
                "type": str(col["type"]),
                "nullable": col.get("nullable", True)
            }
            for col in columns
        ]
        
        # Get preview data
        result = await db.execute(text(f"SELECT * FROM {table_name} LIMIT 20"))
        rows = result.fetchall()
        
        # Convert to list of dicts
        if rows:
            column_names = result.keys()
            preview_data = [dict(zip(column_names, row)) for row in rows]
        else:
            preview_data = []
        
        return {
            "table_name": table_name,
            "schema": schema,
            "preview_data": preview_data,
            "preview_row_count": len(preview_data)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching table {table_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/query-history")
async def get_query_history(
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """Get query history."""
    
    try:
        result = await db.execute(
            select(QueryHistory)
            .order_by(desc(QueryHistory.created_at))
            .limit(limit)
        )
        history = result.scalars().all()
        
        return {
            "history": [
                {
                    "id": h.id,
                    "question": h.user_question,
                    "sql": h.generated_sql,
                    "agent_used": h.agent_used,
                    "confidence_score": h.confidence_score,
                    "trust_score": h.trust_score,
                    "error": h.error_message,
                    "execution_time_ms": h.execution_time_ms,
                    "is_reviewed": h.is_reviewed,
                    "created_at": h.created_at.isoformat()
                }
                for h in history
            ]
        }
        
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/request-review")
async def request_review(
    review_req: ReviewRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Request human review for a query.
    Implements human-in-the-loop.
    """
    
    try:
        # Get query from history
        result = await db.execute(
            select(QueryHistory).where(QueryHistory.id == review_req.query_id)
        )
        query = result.scalar_one_or_none()
        
        if not query:
            raise HTTPException(status_code=404, detail="Query not found")
        
        # Update with review feedback
        query.is_reviewed = True
        query.review_feedback = review_req.feedback
        
        await db.commit()
        
        logger.info(f"Query {review_req.query_id} marked for review")
        
        return {
            "success": True,
            "message": "Query submitted for human review",
            "query_id": review_req.query_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting review: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Get system statistics."""
    
    try:
        # Query counts
        user_count = await db.scalar(select(func.count(User.id)))
        driver_count = await db.scalar(select(func.count(Driver.id)))
        trip_count = await db.scalar(select(func.count(Trip.id)))
        query_count = await db.scalar(select(func.count(QueryHistory.id)))
        
        # AI gateway stats
        ai_stats = ai_gateway.get_usage_stats()
        
        from sqlalchemy import func
        
        return {
            "database": {
                "users": user_count,
                "drivers": driver_count,
                "trips": trip_count,
                "queries_executed": query_count
            },
            "ai_gateway": ai_stats
        }
        
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/api/events/{session_id}')
async def get_session_events(session_id: str):
    events = SessionEvent.query.filter_by(session_id=session_id).all()
    return {
        'session_id': session_id,
        'events': [
            {
                'timestamp': event.timestamp.isoformat(),
                'event_type': event.event_type,
                'payload': event.payload
            } for event in events
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
