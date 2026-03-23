"""
Supervisor Agent - Routes user queries to the appropriate specialist agent.

PPT Architecture (Perception → Planning → Tool):
  Perception : Read the user question and extract intent signals.
  Planning   : Use LLM reasoning to classify intent and decide routing strategy.
  Tool       : Dispatch to SQL Agent or Doc Agent and return the result.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_gateway import ai_gateway
from app.agents.cot_agent import cot_agent
from app.progress import emit

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data containers for each PPT phase
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SupervisorPerception:
    """Output of the Perception phase."""
    user_question: str
    question_length: int
    has_data_keywords: bool       # contains words like count, total, revenue …
    has_doc_keywords: bool        # contains words like explain, what is, define …
    perceived_at: float = field(default_factory=time.time)


@dataclass
class SupervisorPlan:
    """Output of the Planning phase."""
    intent: str                   # "sql_query" | "documentation"
    confidence: str               # "high" | "medium" | "low"
    reasoning: str                # LLM one-line reasoning
    fallback_intent: str = "sql_query"


# ─────────────────────────────────────────────────────────────────────────────
# Supervisor Agent
# ─────────────────────────────────────────────────────────────────────────────

class SupervisorAgent:
    """
    Supervisor agent — the entry point of the multi-agent system.

    PPT loop
    --------
    1. perceive()  – extract signals from the raw question.
    2. plan()      – classify intent via LLM reasoning.
    3. act()       – dispatch to the correct specialist agent.
    """

    # ── keywords used for rule-based pre-filter ──────────────────────────────
    DATA_KEYWORDS = {
        "how many", "count", "total", "revenue", "earnings", "show me",
        "list", "top", "average", "sum", "weekly", "monthly", "daily",
        "yesterday", "last month", "last week", "trips", "drivers",
        "users", "percentage", "rate", "metrics", "stats", "statistics",
    }
    DOC_KEYWORDS = {
        "what is", "what does", "explain", "define", "definition",
        "describe", "how does", "meaning", "tables available",
        "documentation", "docs",
    }

    CLASSIFICATION_PROMPT = """You are a query classifier for a ride-sharing analytics system (Drawin AI).

Classify the user question into ONE of:

1. SQL_QUERY  – requests for data, metrics, numbers, lists, statistics.
   Examples: "total revenue last month", "top 10 drivers", "trip count by region"

2. DOCUMENTATION – requests for explanations, definitions, system knowledge.
   Examples: "what does USNC mean", "explain surge pricing", "what tables exist"

Respond in this EXACT format:
INTENT: <SQL_QUERY or DOCUMENTATION>
CONFIDENCE: <HIGH or MEDIUM or LOW>
REASON: <one short sentence>"""

    # ── Phase 1 – Perception ─────────────────────────────────────────────────

    def perceive(self, user_question: str) -> SupervisorPerception:
        """Extract intent signals from the raw user question."""
        q_lower = user_question.lower()

        has_data = any(kw in q_lower for kw in self.DATA_KEYWORDS)
        has_doc  = any(kw in q_lower for kw in self.DOC_KEYWORDS)

        perception = SupervisorPerception(
            user_question=user_question,
            question_length=len(user_question),
            has_data_keywords=has_data,
            has_doc_keywords=has_doc,
        )

        logger.info(
            f"[Supervisor|Perception] data_signal={has_data} "
            f"doc_signal={has_doc} len={len(user_question)}"
        )
        return perception
    # ── Phase 2 – Planning ───────────────────────────────────────────────────

    async def plan(self, perception: SupervisorPerception) -> SupervisorPlan:
        """Classify intent using LLM reasoning; fall back to rule-based heuristics."""

        # Fast rule-based path (avoids LLM call when signals are unambiguous)
        if perception.has_data_keywords and not perception.has_doc_keywords:
            return SupervisorPlan(
                intent="sql_query", confidence="high",
                reasoning="Data keywords detected; no doc keywords."
            )
        if perception.has_doc_keywords and not perception.has_data_keywords:
            return SupervisorPlan(
                intent="documentation", confidence="high",
                reasoning="Documentation keywords detected; no data keywords."
            )

        # ── COT-enhanced classification for ambiguous queries ─────────────
        # When BOTH data and documentation signals are present the question is
        # genuinely ambiguous.  We use a Chain-of-Thought pass to reason
        # through the most likely intent before making the final decision.
        try:
            cot_result = await cot_agent.reason_through(
                task=(
                    f'Classify this question as either SQL_QUERY (requests data, '
                    f'numbers, metrics, lists) or DOCUMENTATION (requests '
                    f'explanations, definitions, or system knowledge):\n'
                    f'"{perception.user_question}"'
                ),
                name="Intent Classifier",
                description="Reasons about whether a question needs SQL data or documentation",
                instructions=[
                    "SQL_QUERY: asks for counts, totals, revenue, trip data, driver lists, etc.",
                    "DOCUMENTATION: asks what something means, explains a term or process",
                    "When in doubt, prefer SQL_QUERY — data questions are more common",
                    f"Data signal detected: {perception.has_data_keywords}",
                    f"Documentation signal detected: {perception.has_doc_keywords}",
                ],
                max_iterations=3,
                temperature=0.2,
            )

            cot_answer = (cot_result.final_answer or "").upper()
            if "DOCUMENTATION" in cot_answer or "DOC" in cot_answer:
                intent, confidence = "documentation", "medium"
            else:
                intent, confidence = "sql_query", "medium"

            # Upgrade to high confidence if COT converged cleanly
            if cot_result.converged and cot_result.iterations_used <= 2:
                confidence = "high"

            reasoning = f"COT reasoning ({cot_result.iterations_used} steps): {cot_result.final_answer}"

            plan = SupervisorPlan(intent=intent, confidence=confidence, reasoning=reasoning)
            logger.info(
                f"[Supervisor|Planning] COT classification: intent={intent} "
                f"confidence={confidence} converged={cot_result.converged}"
            )
            return plan

        except Exception as e:
            logger.error(f"[Supervisor|Planning] COT classification failed: {e}")
            return SupervisorPlan(
                intent="sql_query", confidence="low",
                reasoning=f"COT error – defaulting to SQL_QUERY: {e}"
            )

    # ── Phase 3 – Tool / Action ───────────────────────────────────────────────

    async def act(
        self,
        plan: SupervisorPlan,
        perception: SupervisorPerception,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Dispatch to the appropriate specialist agent."""

        user_question = perception.user_question

        if plan.intent == "sql_query":
            from app.agents.sql_agent import sql_agent
            response = await sql_agent.generate_and_execute(user_question, db)
            response["agent_used"] = "sql_agent"
        else:
            from app.agents.doc_agent import doc_agent
            response = await doc_agent.answer_documentation(user_question, db)
            response["agent_used"] = "doc_agent"

        response["supervisor_plan"] = {
            "intent": plan.intent,
            "confidence": plan.confidence,
            "reasoning": plan.reasoning,
        }

        logger.info(
            f"[Supervisor|Tool] dispatched to {response['agent_used']} "
            f"(confidence={plan.confidence})"
        )
        return response

    # ── Public entry point ────────────────────────────────────────────────────

    async def route_query(
        self,
        user_question: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """
        Full PPT loop: Perception → Planning → Tool.

        Returns a response dict with agent_used, result fields, and
        supervisor_plan metadata.
        """
        # Perception
        await emit({"type": "supervisor", "phase": "perception",
                    "text": "🔍 Supervisor: Analysing question..."})
        perception = self.perceive(user_question)
        await emit({"type": "supervisor", "phase": "perception_done",
                    "data_signal": perception.has_data_keywords,
                    "doc_signal":  perception.has_doc_keywords,
                    "text": (
                        f"🔍 Signals detected — "
                        f"data={'yes' if perception.has_data_keywords else 'no'}, "
                        f"doc={'yes' if perception.has_doc_keywords else 'no'}"
                    )})

        # Planning
        await emit({"type": "supervisor", "phase": "planning",
                    "text": "🤔 Supervisor: Classifying intent..."})
        plan = await self.plan(perception)
        await emit({"type": "supervisor", "phase": "routing",
                    "intent": plan.intent,
                    "confidence": plan.confidence,
                    "reasoning": plan.reasoning,
                    "text": (
                        f"🎯 Routing to → "
                        f"{'SQL Agent' if plan.intent == 'sql_query' else 'Doc Agent'} "
                        f"(confidence: {plan.confidence.upper()})"
                    )})

        # Tool / Action
        return await self.act(plan, perception, db)


# Global singleton
supervisor = SupervisorAgent()

