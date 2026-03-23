"""
SQL Writer Agent - Generates and executes optimised SQL queries.

PPT Architecture (Perception → Planning → Tool):
  Perception : Collect metadata, analyse the question for complexity signals,
               and build a rich knowledge context.
  Planning   : Decide query strategy, set performance guardrails (timeout,
               row limit, index hints), then generate the SQL via LLM.
  Tool       : Validate → cost-estimate (EXPLAIN) → execute with timeout →
               return results with performance telemetry.
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_gateway import ai_gateway
from app.metadata import metadata_service
from app.security import query_validator
from app.agents.cot_agent import cot_agent, COTResult
from app.progress import emit

logger = logging.getLogger(__name__)

# ─────────────────────────────── constants ───────────────────────────────────

# Planner cost threshold; queries above this get tighter limits.
EXPENSIVE_QUERY_COST_THRESHOLD = 50_000

DEFAULT_TIMEOUT_SECONDS   = 8
EXPENSIVE_TIMEOUT_SECONDS = 20
DEFAULT_ROW_LIMIT         = 1000
EXPENSIVE_ROW_LIMIT       = 200


# ─────────────────────────────────────────────────────────────────────────────
# Data containers for each PPT phase
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SQLPerception:
    """Output of the Perception phase."""
    user_question: str
    metadata_context: str
    complexity_score: int           # 0 (simple) → 10 (very complex)
    detected_tables: List[str]
    has_aggregation: bool
    has_date_filter: bool
    has_multi_table_join: bool
    perceived_at: float = field(default_factory=time.time)


@dataclass
class QueryPlan:
    """Output of the Planning phase."""
    generated_sql: str
    explanation: str
    confidence: float
    strategy: str                   # "aggregated_table" | "raw_table" | "hybrid"
    timeout_seconds: int
    row_limit: int
    require_explain: bool
    was_auto_limited: bool = False


@dataclass
class QueryResult:
    """Output of the Tool (Action) phase."""
    sql: str
    explanation: str
    confidence_score: float
    results: Optional[List[Dict]]
    row_count: int
    error: Optional[str]
    execution_time_ms: float
    estimated_cost: Optional[float]
    was_limited: bool
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    ai_tokens: Optional[int] = None


# ─────────────────────────────────────────────────────────────────────────────
# SQL Agent
# ─────────────────────────────────────────────────────────────────────────────

class SQLAgent:
    """
    SQL Writer Agent — generates and executes PostgreSQL SELECT queries.

    PPT loop
    --------
    1. perceive()  – build metadata context; score query complexity.
    2. plan()      – choose strategy; set guardrails; generate SQL via LLM.
    3. act()       – validate → cost-estimate → execute → return telemetry.
    """

    GENERATION_PROMPT = """You are an expert PostgreSQL query generator for Drawin AI, \
a ride-sharing analytics platform.

You will receive:
1. Database context (table descriptions, metrics, business terms)
2. A user question
3. Performance constraints

Rules:
- Generate a SINGLE valid PostgreSQL SELECT statement.
- Prefer flattened analytics tables (trip_metrics_daily, region_revenue_summary)
  to avoid expensive full-table scans.
- Always resolve business-term codes (e.g. USNC → region lookup).
- Add explicit date filters when the question mentions a time period.
- NEVER use SELECT *; always name columns explicitly.
- Include LIMIT {row_limit} if result could be large and no LIMIT is present.
- Use indexed columns in WHERE / JOIN conditions where possible.

Return EXACTLY this format:

```sql
[QUERY HERE]
```

Explanation: [one sentence]

Confidence: [High | Medium | Low]

Strategy: [aggregated_table | raw_table | hybrid]"""

    # ── Phase 1 – Perception ─────────────────────────────────────────────────

    async def perceive(self, user_question: str, db: AsyncSession) -> SQLPerception:
        """Collect metadata context and score query complexity."""
        await emit({"type": "sql_agent", "phase": "perception",
                    "text": "🧠 SQL Agent: Building knowledge context..."})
        logger.info("[SQLAgent|Perception] Building knowledge context...")

        context = await metadata_service.build_context_for_query(db, user_question)
        q_lower = user_question.lower()

        has_aggregation  = any(w in q_lower for w in [
            "total", "sum", "count", "average", "avg", "max", "min",
            "group", "per ", "by region", "by driver", "by day"])
        has_date_filter  = any(w in q_lower for w in [
            "today", "yesterday", "last week", "last month", "this month",
            "year", "between", "since", "from ", " to "])
        has_multi_join   = any(w in q_lower for w in [
            " and ", "with ", "across", "compare", " vs ", "breakdown"])

        score = 0
        if has_aggregation:              score += 2
        if has_date_filter:              score += 1
        if has_multi_join:               score += 2
        if len(user_question) > 120:     score += 1
        if "subquery" in q_lower or "nested" in q_lower: score += 3

        detected_tables: List[str] = []
        if "trip"    in q_lower: detected_tables.append("trips")
        if "driver"  in q_lower: detected_tables.append("drivers")
        if "user"    in q_lower: detected_tables.append("users")
        if "revenue" in q_lower or "region" in q_lower:
            detected_tables.append("region_revenue_summary")
        if "metric"  in q_lower or "daily" in q_lower:
            detected_tables.append("trip_metrics_daily")

        p = SQLPerception(
            user_question=user_question,
            metadata_context=context,
            complexity_score=min(score, 10),
            detected_tables=list(set(detected_tables)),
            has_aggregation=has_aggregation,
            has_date_filter=has_date_filter,
            has_multi_table_join=has_multi_join,
        )
        logger.info(
            f"[SQLAgent|Perception] complexity={p.complexity_score} "
            f"tables={p.detected_tables} agg={has_aggregation} date={has_date_filter}"
        )
        await emit({"type": "sql_agent", "phase": "perception_done",
                    "complexity": p.complexity_score,
                    "tables": p.detected_tables,
                    "text": (
                        f"📊 Complexity: {p.complexity_score}/10 — "
                        f"tables: {', '.join(p.detected_tables) or 'auto-detect'}"
                    )})
        return p

    # ── Phase 2 – Planning ───────────────────────────────────────────────────

    async def plan(self, perception: SQLPerception) -> QueryPlan:
        """
        Calibrate performance guardrails based on perceived complexity,
        then generate the SQL via LLM.
        """
        c = perception.complexity_score

        if c >= 6:
            timeout_s, row_cap, need_explain, strategy_hint = (
                EXPENSIVE_TIMEOUT_SECONDS, EXPENSIVE_ROW_LIMIT, True, "raw_table")
        elif c >= 3:
            timeout_s, row_cap, need_explain, strategy_hint = (
                DEFAULT_TIMEOUT_SECONDS + 4, DEFAULT_ROW_LIMIT, True, "hybrid")
        else:
            timeout_s, row_cap, need_explain, strategy_hint = (
                DEFAULT_TIMEOUT_SECONDS, DEFAULT_ROW_LIMIT, False, "aggregated_table")

        # If we recognise aggregated tables in the question, prefer them
        if any(t in perception.detected_tables
               for t in ["trip_metrics_daily", "region_revenue_summary"]):
            strategy_hint = "aggregated_table"

        logger.info(
            f"[SQLAgent|Planning] strategy={strategy_hint} "
            f"timeout={timeout_s}s row_limit={row_cap} explain={need_explain}"
        )
        await emit({"type": "sql_agent", "phase": "planning",
                    "strategy": strategy_hint, "timeout": timeout_s,
                    "text": (
                        f"⚙️ Strategy: {strategy_hint} | "
                        f"timeout: {timeout_s}s | row cap: {row_cap}"
                    )})

        # ── COT pre-reasoning (complexity >= 3) ───────────────────────────
        # For non-trivial queries, run a chain-of-thought reasoning pass to
        # figure out the right tables, joins, and filtering strategy BEFORE
        # generating the SQL.  The trace is injected into the generation prompt
        # so the SQL-generation LLM has a full reasoning trail.
        cot_trace_text = ""
        if c >= 3:
            await emit({"type": "sql_agent", "phase": "cot_start",
                        "text": f"🔗 Chain-of-Thought reasoning starting (max 4 steps)..."})
            cot_result: COTResult = await cot_agent.reason_through(
                task=(
                    f"Determine the best PostgreSQL query strategy for:\n"
                    f"{perception.user_question}\n\n"
                    f"Consider: which table(s) to use, what JOINs are needed, "
                    f"what date filters apply, which columns to aggregate, "
                    f"and how to keep the query fast (prefer aggregated tables)."
                ),
                context=perception.metadata_context[:2000],  # trim to avoid token explosion
                name="SQL Strategy Reasoner",
                description="Reasons step-by-step about the optimal SQL query structure",
                instructions=[
                    f"Preferred table strategy: {strategy_hint}",
                    f"Row limit: {row_cap}",
                    "Prefer trip_metrics_daily and region_revenue_summary over raw tables",
                    "Identify all required JOINs before deciding on the final query",
                    "Note any date / region filters that should be applied",
                ],
                max_iterations=4,
                temperature=0.25,
            )
            cot_trace_text = (
                "\n\n## Chain-of-Thought Pre-Reasoning\n"
                + cot_agent.format_trace_for_context(cot_result)
                + "\n\nUse the reasoning above to guide the SQL you generate.\n"
            )
            logger.info(
                f"[SQLAgent|Planning] COT completed: "
                f"converged={cot_result.converged} "
                f"iterations={cot_result.iterations_used} "
                f"time={cot_result.total_time_ms:.0f}ms"
            )
            await emit({"type": "sql_agent", "phase": "cot_done",
                        "iterations": cot_result.iterations_used,
                        "converged": cot_result.converged,
                        "text": (
                            f"✅ COT reasoning done — {cot_result.iterations_used} steps, "
                            f"converged={cot_result.converged}"
                        )})

        system_prompt = self.GENERATION_PROMPT.replace("{row_limit}", str(row_cap))
        plan_ctx = (
            f"\n\n## Performance Constraints\n"
            f"- Preferred strategy : {strategy_hint}\n"
            f"- Auto row limit     : {row_cap}\n"
            f"- Query timeout      : {timeout_s}s\n"
            f"- Complexity estimate: {c}/10\n"
        )
        prompt = (
            f"{perception.metadata_context}{plan_ctx}{cot_trace_text}\n"
            f"User Question: {perception.user_question}\n\n"
            f"Generate the optimised SQL query now."
        )

        ai_result = await ai_gateway.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.2,
            max_tokens=1200,
        )
        raw = ai_result["text"]

        sql         = self._extract_sql(raw)
        explanation = self._extract_explanation(raw)
        confidence  = self._extract_confidence(raw)
        strategy    = self._extract_strategy(raw) or strategy_hint

        # Strip any trailing semicolon the LLM may have added BEFORE
        # auto-appending LIMIT, otherwise EXPLAIN gets "... ; LIMIT n"
        if sql:
            sql = sql.rstrip(';').strip()

        await emit({"type": "sql_agent", "phase": "sql_generated",
                    "sql_preview": (sql or "")[:120],
                    "confidence": confidence,
                    "text": f"📝 SQL generated (confidence: {confidence:.0%})"})

        # Auto-inject LIMIT when absent
        was_auto_limited = False
        if sql and "LIMIT" not in sql.upper():
            sql += f"\nLIMIT {row_cap}"
            was_auto_limited = True
            logger.info(f"[SQLAgent|Planning] Auto-applied LIMIT {row_cap}")

        return QueryPlan(
            generated_sql=sql or "",
            explanation=explanation,
            confidence=confidence,
            strategy=strategy,
            timeout_seconds=timeout_s,
            row_limit=row_cap,
            require_explain=need_explain,
            was_auto_limited=was_auto_limited,
        )

    # ── Phase 3 – Tool / Action ───────────────────────────────────────────────

    async def act(
        self, plan: QueryPlan, perception: SQLPerception, db: AsyncSession
    ) -> QueryResult:
        """Validate → EXPLAIN cost-estimate → execute → return with telemetry."""
        sql = plan.generated_sql

        # 3a. Security validation
        is_valid, err_msg = query_validator.validate_query(sql)
        if not is_valid:
            return QueryResult(
                sql=sql, explanation=plan.explanation,
                confidence_score=0.0, results=None, row_count=0,
                error=f"Security validation failed: {err_msg}",
                execution_time_ms=0.0, estimated_cost=None, was_limited=False,
            )

        sql = query_validator.sanitize_query(sql)

        # 3b. Optional EXPLAIN cost estimate
        estimated_cost: Optional[float] = None
        if plan.require_explain:
            await emit({"type": "sql_agent", "phase": "explain",
                        "text": "🔎 Running EXPLAIN cost analysis..."})
            estimated_cost = await self._estimate_query_cost(db, sql)
            logger.info(f"[SQLAgent|Tool] EXPLAIN planner cost = {estimated_cost}")

            # Extremely expensive query → tighten LIMIT defensively
            if estimated_cost and estimated_cost > EXPENSIVE_QUERY_COST_THRESHOLD * 5:
                floor = max(EXPENSIVE_ROW_LIMIT // 2, 50)
                sql = re.sub(r'\bLIMIT\s+\d+', f'LIMIT {floor}',
                             sql, flags=re.IGNORECASE)
                if "LIMIT" not in sql.upper():
                    sql += f"\nLIMIT {floor}"
                logger.warning(
                    f"[SQLAgent|Tool] Very high cost ({estimated_cost:.0f}); "
                    f"row cap tightened to {floor}."
                )

        # 3c. Execute with calibrated timeout
        await emit({"type": "sql_agent", "phase": "executing",
                    "text": f"⚡ Executing SQL (timeout: {plan.timeout_seconds}s)..."})
        exec_start = time.time()
        success, results, exec_error = await query_validator.execute_safe_query(
            db, sql, timeout_seconds=plan.timeout_seconds
        )
        execution_time_ms = (time.time() - exec_start) * 1000

        await emit({"type": "sql_agent", "phase": "executed",
                    "success": success,
                    "rows": len(results) if results else 0,
                    "exec_ms": round(execution_time_ms),
                    "text": (
                        f"✅ Executed in {execution_time_ms:.0f}ms — "
                        f"{len(results) if results else 0} rows"
                        if success else
                        f"❌ Execution failed: {exec_error}"
                    )})

        logger.info(
            f"[SQLAgent|Tool] success={success} rows={len(results) if results else 0} "
            f"time={execution_time_ms:.1f}ms timeout={plan.timeout_seconds}s"
        )

        if not success:
            return QueryResult(
                sql=sql, explanation=plan.explanation,
                confidence_score=plan.confidence, results=None, row_count=0,
                error=exec_error, execution_time_ms=execution_time_ms,
                estimated_cost=estimated_cost, was_limited=plan.was_auto_limited,
            )

        return QueryResult(
            sql=sql, explanation=plan.explanation,
            confidence_score=plan.confidence,
            results=results,
            row_count=len(results) if results else 0,
            error=None,
            execution_time_ms=execution_time_ms,
            estimated_cost=estimated_cost,
            was_limited="LIMIT" in sql.upper(),
        )

    # ── Public entry point ────────────────────────────────────────────────────

    async def generate_and_execute(
        self, user_question: str, db: AsyncSession
    ) -> Dict[str, Any]:
        """Full PPT loop → flat dict compatible with ChatResponse."""
        try:
            perception = await self.perceive(user_question, db)
            plan       = await self.plan(perception)
            result     = await self.act(plan, perception, db)

            return {
                "sql":               result.sql,
                "explanation":       result.explanation,
                "confidence_score":  result.confidence_score,
                "results":           result.results,
                "row_count":         result.row_count,
                "error":             result.error,
                "execution_time_ms": result.execution_time_ms,
                "estimated_cost":    result.estimated_cost,
                "was_limited":       result.was_limited,
                "ppt_complexity":    perception.complexity_score,
                "ppt_strategy":      plan.strategy,
            }

        except Exception as e:
            logger.error(f"[SQLAgent] Unhandled error: {e}", exc_info=True)
            return {
                "sql": None, "explanation": None,
                "confidence_score": 0.0, "results": None, "error": str(e),
            }

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _estimate_query_cost(
        self, db: AsyncSession, sql: str
    ) -> Optional[float]:
        """EXPLAIN (ANALYZE FALSE) → return planner Total Cost, or None on failure.

        Wrapped in a SAVEPOINT so a failed EXPLAIN never poisons the outer
        transaction (asyncpg marks the session as aborted on any error).
        """
        try:
            sp = await db.begin_nested()   # SAVEPOINT
            try:
                row = await db.execute(
                    text(f"EXPLAIN (FORMAT JSON, ANALYZE FALSE) {sql}")
                )
                data = row.fetchone()
                await sp.commit()
                if data:
                    plan_json = data[0]
                    if isinstance(plan_json, str):
                        plan_json = json.loads(plan_json)
                    cost = plan_json[0].get("Plan", {}).get("Total Cost")
                    return float(cost) if cost is not None else None
            except Exception as inner:
                await sp.rollback()        # roll back ONLY to the savepoint
                logger.warning(f"[SQLAgent] EXPLAIN skipped: {inner}")
        except Exception as e:
            logger.warning(f"[SQLAgent] EXPLAIN savepoint error: {e}")
        return None

    def _extract_sql(self, response: str) -> Optional[str]:
        m = re.search(r'```sql\s*\n(.*?)\n```', response, re.DOTALL | re.IGNORECASE)
        if m: return m.group(1).strip()
        m = re.search(r'```\s*\n(SELECT.*?)\n```', response, re.DOTALL | re.IGNORECASE)
        if m: return m.group(1).strip()
        if 'SELECT' in response.upper():
            lines, capturing = [], False
            for line in response.splitlines():
                if not capturing and 'SELECT' in line.upper(): capturing = True
                if capturing:
                    lines.append(line)
                    if line.strip().endswith(';'): break
            if lines: return '\n'.join(lines).strip()
        return None

    def _extract_explanation(self, response: str) -> str:
        m = re.search(
            r'Explanation:\s*(.+?)(?:\n\n|Confidence:|$)',
            response, re.DOTALL | re.IGNORECASE
        )
        return m.group(1).strip() if m else "No explanation provided."

    def _extract_confidence(self, response: str) -> float:
        lower = response.lower()
        if "confidence: high"   in lower: return 0.9
        if "confidence: medium" in lower: return 0.7
        if "confidence: low"    in lower: return 0.4
        return 0.7

    def _extract_strategy(self, response: str) -> Optional[str]:
        m = re.search(
            r'Strategy:\s*(aggregated_table|raw_table|hybrid)',
            response, re.IGNORECASE
        )
        return m.group(1).lower() if m else None


# Global singleton
sql_agent = SQLAgent()
