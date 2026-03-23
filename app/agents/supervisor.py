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

        # LLM-based classification for ambiguous cases
        try:
            result = await ai_gateway.generate(
                prompt=perception.user_question,
                system_prompt=self.CLASSIFICATION_PROMPT,
                temperature=0.15,
                max_tokens=80,
            )
            text = result["text"].strip()

            intent     = "sql_query"
            confidence = "medium"
            reasoning  = text

            for line in text.splitlines():
                line_upper = line.upper()
                if line_upper.startswith("INTENT:"):
                    raw = line.split(":", 1)[1].strip().upper()
                    intent = "documentation" if "DOCUMENTATION" in raw else "sql_query"
                elif line_upper.startswith("CONFIDENCE:"):
                    raw = line.split(":", 1)[1].strip().upper()
                    confidence = (
                        "high"   if "HIGH" in raw else
                        "low"    if "LOW"  in raw else
                        "medium"
                    )
                elif line_upper.startswith("REASON:"):
                    reasoning = line.split(":", 1)[1].strip()

            plan = SupervisorPlan(intent=intent, confidence=confidence, reasoning=reasoning)
            logger.info(
                f"[Supervisor|Planning] intent={intent} "
                f"confidence={confidence} reason={reasoning}"
            )
            return plan

        except Exception as e:
            logger.error(f"[Supervisor|Planning] LLM classification failed: {e}")
            return SupervisorPlan(
                intent="sql_query", confidence="low",
                reasoning=f"LLM error – defaulting to SQL_QUERY: {e}"
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
        perception = self.perceive(user_question)

        # Planning
        plan = await self.plan(perception)

        # Tool / Action
        return await self.act(plan, perception, db)


# Global singleton
supervisor = SupervisorAgent()


# Global instance
supervisor = SupervisorAgent()
