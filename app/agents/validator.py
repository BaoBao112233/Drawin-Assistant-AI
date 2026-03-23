"""
Validator Agent - Validates generated SQL against golden queries.

PPT Architecture (Perception → Planning → Tool):
  Perception : Analyse the generated SQL and results for complexity; look up
               candidate golden queries from the database.
  Planning   : Choose a validation strategy that avoids overloading the system
               (skip golden re-execution for heavy queries; use sampled
               comparison for large result sets).
  Tool       : Execute the chosen validation plan, measure timing, compute a
               trust score that factors in result accuracy AND performance.
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GoldenQuery
from app.security import query_validator
from app.agents.cot_agent import cot_agent

# Trust-score range where COT reasoning is triggered for deeper analysis.
_COT_TRUST_LOW  = 0.35
_COT_TRUST_HIGH = 0.75

logger = logging.getLogger(__name__)

# ─────────────────────────────── constants ───────────────────────────────────

# If generated-SQL planner cost is above this, skip golden re-execution
# to avoid doubling the load on the database.
HEAVY_QUERY_COST_SKIP_THRESHOLD = 30_000

# Large result sets are compared by sampling instead of full comparison.
LARGE_RESULT_SAMPLE_SIZE = 50

# Golden query timeout — intentionally shorter than the SQL-agent timeout.
GOLDEN_QUERY_TIMEOUT = 6


# ─────────────────────────────────────────────────────────────────────────────
# Data containers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ValidationPerception:
    """Output of the Perception phase."""
    user_question: str
    generated_sql: str
    results: List[Dict]
    sql_complexity: int             # 0 = simple, 10 = very complex
    join_count: int
    has_subquery: bool
    result_size: int
    golden_candidates: List        # list of GoldenQuery ORM objects
    estimated_cost: Optional[float]  # passed in from SQLAgent if available
    perceived_at: float = field(default_factory=time.time)


@dataclass
class ValidationPlanSpec:
    """Output of the Planning phase — decides *how* to validate."""
    strategy: str                   # "full" | "lightweight" | "skip_golden"
    use_golden: bool
    max_compare_rows: int
    golden_query: Optional[Any]     # GoldenQuery ORM or None
    reason: str                     # human-readable explanation of the choice


@dataclass
class ValidationResult:
    """Output of the Tool (Action) phase."""
    trust_score: float
    matched_golden: Optional[str]
    validation_notes: List[str]
    strategy_used: str
    golden_exec_time_ms: Optional[float]
    performance_delta_ms: Optional[float]  # generated vs golden exec time


# ─────────────────────────────────────────────────────────────────────────────
# Validator Agent
# ─────────────────────────────────────────────────────────────────────────────

class ValidatorAgent:
    """
    Validator Agent — checks generated query results against golden queries
    while being careful NOT to overload the database.

    PPT loop
    --------
    1. perceive()  – analyse SQL complexity; fetch golden candidates.
    2. plan()      – choose lightweight/full/skip-golden strategy.
    3. act()       – execute plan and return a trust score with telemetry.
    """

    # ── Phase 1 – Perception ─────────────────────────────────────────────────

    async def perceive(
        self,
        db: AsyncSession,
        user_question: str,
        generated_sql: str,
        results: List[Dict],
        estimated_cost: Optional[float] = None,
    ) -> ValidationPerception:
        """
        Measure SQL complexity and gather golden-query candidates.

        Complexity is derived from structural features of the SQL text so we
        don't need to call the planner again here.
        """
        logger.info("[Validator|Perception] Analysing query complexity...")

        sql_upper = generated_sql.upper()

        join_count  = sql_upper.count("JOIN")
        has_subq    = "SELECT" in sql_upper[sql_upper.find("FROM"):] if "FROM" in sql_upper else False
        has_group   = "GROUP BY" in sql_upper
        has_window  = "OVER (" in sql_upper or "OVER(" in sql_upper
        has_cte     = sql_upper.lstrip().startswith("WITH ")

        score = 0
        if join_count >= 3:    score += 3
        elif join_count >= 1:  score += 1
        if has_subq:           score += 3
        if has_group:          score += 1
        if has_window:         score += 2
        if has_cte:            score += 2

        # Golden query candidates (keyword overlap)
        golden_candidates = await self._fetch_golden_candidates(db, user_question)

        p = ValidationPerception(
            user_question=user_question,
            generated_sql=generated_sql,
            results=results,
            sql_complexity=min(score, 10),
            join_count=join_count,
            has_subquery=has_subq,
            result_size=len(results) if results else 0,
            golden_candidates=golden_candidates,
            estimated_cost=estimated_cost,
        )

        logger.info(
            f"[Validator|Perception] complexity={p.sql_complexity} "
            f"joins={join_count} subquery={has_subq} "
            f"result_rows={p.result_size} golden_candidates={len(golden_candidates)}"
        )
        return p

    # ── Phase 2 – Planning ───────────────────────────────────────────────────

    def plan(self, perception: ValidationPerception) -> ValidationPlanSpec:
        """
        Decide validation strategy to avoid overloading the DB.

        skip_golden  → very complex query or no golden match
        lightweight  → large result set: use sampled comparison only
        full         → normal full comparison against golden query
        """
        best_golden = perception.golden_candidates[0] if perception.golden_candidates else None

        # ── Case 1: too costly to re-run golden ───────────────────────────
        if (perception.estimated_cost is not None
                and perception.estimated_cost > HEAVY_QUERY_COST_SKIP_THRESHOLD):
            spec = ValidationPlanSpec(
                strategy="skip_golden",
                use_golden=False,
                max_compare_rows=0,
                golden_query=None,
                reason=(
                    f"Estimated planner cost {perception.estimated_cost:.0f} "
                    f"> threshold {HEAVY_QUERY_COST_SKIP_THRESHOLD}; "
                    f"golden re-execution skipped to protect the database."
                ),
            )
            logger.info(f"[Validator|Planning] strategy=skip_golden (cost={perception.estimated_cost:.0f})")
            return spec

        # ── Case 2: no golden query found ────────────────────────────────
        if not best_golden:
            spec = ValidationPlanSpec(
                strategy="skip_golden",
                use_golden=False,
                max_compare_rows=0,
                golden_query=None,
                reason="No matching golden query found for this question.",
            )
            logger.info("[Validator|Planning] strategy=skip_golden (no golden)")
            return spec

        # ── Case 3: heavy SQL complexity → lightweight sampling ───────────
        if perception.sql_complexity >= 6 or perception.result_size > LARGE_RESULT_SAMPLE_SIZE * 4:
            spec = ValidationPlanSpec(
                strategy="lightweight",
                use_golden=True,
                max_compare_rows=LARGE_RESULT_SAMPLE_SIZE,
                golden_query=best_golden,
                reason=(
                    f"Complexity={perception.sql_complexity}/10 or "
                    f"result size={perception.result_size}; "
                    f"using sampled comparison ({LARGE_RESULT_SAMPLE_SIZE} rows)."
                ),
            )
            logger.info("[Validator|Planning] strategy=lightweight")
            return spec

        # ── Case 4: normal full validation ────────────────────────────────
        spec = ValidationPlanSpec(
            strategy="full",
            use_golden=True,
            max_compare_rows=perception.result_size,
            golden_query=best_golden,
            reason="Standard full result comparison.",
        )
        logger.info("[Validator|Planning] strategy=full")
        return spec

    # ── Phase 3 – Tool / Action ───────────────────────────────────────────────

    async def act(
        self,
        plan_spec: ValidationPlanSpec,
        perception: ValidationPerception,
        db: AsyncSession,
    ) -> ValidationResult:
        """Execute the validation plan and return a trust score."""
        notes: List[str] = [f"Validation strategy: {plan_spec.strategy}"]
        notes.append(plan_spec.reason)

        golden_exec_time: Optional[float] = None
        performance_delta: Optional[float] = None

        # ── skip_golden: no golden re-execution ──────────────────────────
        if plan_spec.strategy == "skip_golden":
            trust = 0.6  # moderate trust when we can't verify
            if not plan_spec.golden_query:
                notes.append("No golden query available; using baseline trust 0.6.")
            else:
                notes.append("Golden re-execution skipped (cost protection).")
            return ValidationResult(
                trust_score=trust,
                matched_golden=None,
                validation_notes=notes,
                strategy_used=plan_spec.strategy,
                golden_exec_time_ms=None,
                performance_delta_ms=None,
            )

        # ── full / lightweight: execute golden query ──────────────────────
        golden: GoldenQuery = plan_spec.golden_query

        t0 = time.time()
        success, golden_results, error = await query_validator.execute_safe_query(
            db, golden.sql_query, timeout_seconds=GOLDEN_QUERY_TIMEOUT
        )
        golden_exec_time = (time.time() - t0) * 1000

        if not success:
            notes.append(f"Golden query execution failed: {error}")
            return ValidationResult(
                trust_score=0.5,
                matched_golden=golden.question,
                validation_notes=notes,
                strategy_used=plan_spec.strategy,
                golden_exec_time_ms=golden_exec_time,
                performance_delta_ms=None,
            )

        # ── Compare results ───────────────────────────────────────────────
        generated_sample = (perception.results or [])[:plan_spec.max_compare_rows]
        golden_sample    = (golden_results or [])[:plan_spec.max_compare_rows]

        result_score, result_notes = self._compare_results(generated_sample, golden_sample)
        notes.extend(result_notes)

        # ── SQL structural similarity ─────────────────────────────────────
        sql_sim = self._sql_similarity(perception.generated_sql, golden.sql_query)
        notes.append(f"SQL structural similarity: {sql_sim:.2f}")

        # ── Performance delta note ────────────────────────────────────────
        # (we know golden execution time; generated execution time comes from
        #  the SQLAgent — we don't have it here, so we just report golden time)
        notes.append(f"Golden query executed in {golden_exec_time:.1f} ms")

        # ── Combined trust score ──────────────────────────────────────────
        # Weight: 70% result accuracy, 30% SQL structural similarity
        trust = round((result_score * 0.7) + (sql_sim * 0.3), 2)

        # Performance penalty: if golden query itself took too long, that
        # suggests the question targets a slow-path; reduce trust slightly.
        if golden_exec_time > (GOLDEN_QUERY_TIMEOUT * 1000 * 0.8):
            trust = max(0.3, trust - 0.1)
            notes.append("Trust slightly reduced: golden query is itself slow.")

        notes.append(f"Matched golden: '{golden.question}'")

        # ── COT trust refinement for borderline scores ────────────────────
        # When the automated trust computation lands in the uncertain zone
        # (0.35–0.75), use a Chain-of-Thought reasoning pass to decide
        # whether the score should be adjusted up or down.
        if _COT_TRUST_LOW <= trust <= _COT_TRUST_HIGH:
            try:
                cot_result = await cot_agent.reason_through(
                    task=(
                        f"Assess whether the trust score of {trust:.2f} for the following "
                        f"generated SQL query is accurate, too high, or too low.\n\n"
                        f"User question : {perception.user_question}\n"
                        f"Generated SQL : {perception.generated_sql[:400]}\n"
                        f"Golden SQL    : {golden.sql_query[:400]}\n"
                        f"Result rows   : {perception.result_size}\n"
                        f"SQL similarity: {sql_sim:.2f}\n"
                        f"Result score  : {result_score:.2f}\n\n"
                        f"Decide: should the trust score be INCREASED, DECREASED, or KEPT "
                        f"at {trust:.2f}?  By how much (0.05–0.15 max)?  "
                        f"Respond with a final numeric trust score between 0 and 1."
                    ),
                    name="Trust Score Reasoner",
                    description="Reasons about the reliability of a generated SQL query",
                    instructions=[
                        "A high trust score (> 0.75) means results match the golden query closely",
                        "A low trust score (< 0.35) means results differ significantly",
                        "Only adjust by a small amount (0.05–0.15) unless the evidence is strong",
                        "Consider both SQL structural similarity AND result similarity",
                        "Your final answer must be a single decimal between 0.0 and 1.0",
                    ],
                    max_iterations=4,
                    temperature=0.2,
                )
                # Try to parse a numeric score from the COT final answer
                import re as _re
                m = _re.search(r'(\d\.\d+|0\.\d+|1\.0)', cot_result.final_answer or "")
                if m:
                    cot_trust = float(m.group(1))
                    # Only apply if within sane bounds and meaningful delta
                    if 0.0 <= cot_trust <= 1.0 and abs(cot_trust - trust) <= 0.2:
                        notes.append(
                            f"COT reasoning adjusted trust {trust:.2f} → {cot_trust:.2f} "
                            f"({cot_result.iterations_used} steps, "
                            f"converged={cot_result.converged})"
                        )
                        trust = round(cot_trust, 2)
                    else:
                        notes.append(
                            f"COT suggestion ({cot_trust:.2f}) out of bounds; "
                            f"original trust {trust:.2f} kept."
                        )
                else:
                    notes.append(
                        f"COT reasoning complete but no numeric score found; "
                        f"trust {trust:.2f} unchanged."
                    )
            except Exception as cot_err:
                logger.warning(f"[Validator] COT trust refinement failed (non-fatal): {cot_err}")
                notes.append("COT trust refinement skipped due to error.")

        return ValidationResult(
            trust_score=trust,
            matched_golden=golden.question,
            validation_notes=notes,
            strategy_used=plan_spec.strategy,
            golden_exec_time_ms=golden_exec_time,
            performance_delta_ms=performance_delta,
        )

    # ── Public entry point ────────────────────────────────────────────────────

    async def validate_query(
        self,
        db: AsyncSession,
        user_question: str,
        generated_sql: str,
        results: List[Dict],
        estimated_cost: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Full PPT loop: Perception → Planning → Tool.

        Returns a flat dict with trust_score, matched_golden, validation_notes.
        """
        try:
            # Perception
            perception = await self.perceive(
                db, user_question, generated_sql, results, estimated_cost
            )

            # Planning
            plan_spec = self.plan(perception)

            # Tool
            vr = await self.act(plan_spec, perception, db)

            return {
                "trust_score":           vr.trust_score,
                "matched_golden":        vr.matched_golden,
                "validation_notes":      vr.validation_notes,
                "validation_strategy":   vr.strategy_used,
                "golden_exec_time_ms":   vr.golden_exec_time_ms,
            }

        except Exception as e:
            logger.error(f"[Validator] Unhandled error: {e}", exc_info=True)
            return {
                "trust_score":      0.5,
                "matched_golden":   None,
                "validation_notes": [f"Validation error: {e}"],
            }

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _fetch_golden_candidates(
        self, db: AsyncSession, user_question: str
    ) -> List:
        """Return golden queries whose keywords overlap sufficiently with the question."""
        try:
            result = await db.execute(
                select(GoldenQuery).where(GoldenQuery.is_active == True)
            )
            all_golden = result.scalars().all()

            user_terms = set(user_question.lower().split())
            scored = []
            for gq in all_golden:
                gq_terms = set(gq.question.lower().split())
                overlap  = len(user_terms & gq_terms)
                if overlap >= 3:
                    scored.append((overlap, gq))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [gq for _, gq in scored]

        except Exception as e:
            logger.warning(f"[Validator] Could not fetch golden queries: {e}")
            return []

    def _compare_results(
        self, r1: List[Dict], r2: List[Dict]
    ) -> Tuple[float, List[str]]:
        """Compare two (possibly sampled) result sets; return (score, notes)."""
        notes: List[str] = []

        if not r1 and not r2:
            return 1.0, ["Both result sets are empty — exact match."]
        if not r1 or not r2:
            notes.append("One result set is empty; possible query mismatch.")
            return 0.3, notes

        # Row count similarity
        if len(r1) == len(r2):
            row_score = 1.0
            notes.append(f"Row counts match: {len(r1)}")
        else:
            ratio     = min(len(r1), len(r2)) / max(len(r1), len(r2))
            row_score = ratio * 0.5
            notes.append(f"Row count mismatch: generated={len(r1)} golden={len(r2)}")

        # First-row value similarity
        first_sim = self._row_similarity(r1[0], r2[0]) if r1 and r2 else 0.0
        notes.append(f"First-row similarity: {first_sim:.2f}")

        return (row_score * 0.4) + (first_sim * 0.6), notes

    def _row_similarity(self, row1: Dict, row2: Dict) -> float:
        """Jaccard-style value similarity between two result rows."""
        keys = set(row1.keys()) | set(row2.keys())
        if not keys:
            return 1.0
        matching = 0
        for k in keys:
            v1, v2 = row1.get(k), row2.get(k)
            if v1 is None or v2 is None:
                continue
            try:
                if abs(float(v1) - float(v2)) < 0.01:
                    matching += 1
            except (TypeError, ValueError):
                if str(v1) == str(v2):
                    matching += 1
        return matching / len(keys)

    def _sql_similarity(self, sql1: str, sql2: str) -> float:
        """Word-level Jaccard similarity between two normalised SQL strings."""
        def normalise(s: str) -> set:
            s = ' '.join(s.split()).upper().rstrip(';')
            return set(s.split())
        w1, w2 = normalise(sql1), normalise(sql2)
        if not w1 and not w2:
            return 1.0
        return len(w1 & w2) / len(w1 | w2) if (w1 | w2) else 0.0


# Global singleton
validator_agent = ValidatorAgent()
