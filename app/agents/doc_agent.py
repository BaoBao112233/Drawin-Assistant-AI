"""
Documentation Agent - Answers business/documentation questions.

PPT Architecture (Perception → Planning → Tool):
  Perception : Extract keywords from the question; gather relevant metadata
               and system documentation context.
  Planning   : Determine the answer scope (topic detection, context depth)
               and formulate the answering strategy.
  Tool       : Generate the explanation via LLM using the assembled context.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_gateway import ai_gateway
from app.metadata import metadata_service

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data containers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DocPerception:
    """Output of the Perception phase."""
    user_question: str
    keywords: List[str]
    matched_topics: List[str]       # e.g. ["business_terms", "metrics", "schema"]
    raw_context: str                # assembled documentation context
    metadata_matches: List[Dict]    # matched metadata entries
    perceived_at: float = field(default_factory=time.time)


@dataclass
class DocAnswerPlan:
    """Output of the Planning phase."""
    focus_topics: List[str]
    context_sections: List[str]     # ordered sections to include in answer
    tone: str                       # "technical" | "business"
    max_tokens: int


# ─────────────────────────────────────────────────────────────────────────────
# Doc Agent
# ─────────────────────────────────────────────────────────────────────────────

TOPIC_KEYWORDS = {
    "business_terms": [
        "usnc", "apac", "latam", "eu", "region", "zone", "market"],
    "metrics": [
        "revenue", "earnings", "trips", "rating", "surge", "multiplier",
        "completion rate", "active users", "drivers"],
    "schema": [
        "table", "column", "field", "schema", "database", "structure",
        "trip_metrics", "region_revenue"],
    "pricing": [
        "surge", "fare", "price", "pricing", "cost", "fee"],
    "operations": [
        "how does", "how do", "explain", "process", "workflow",
        "on-boarding", "onboarding"],
}


class DocAgent:
    """
    Documentation Agent — answers business logic and documentation questions.
    Does NOT generate SQL; that is the SQL Agent's responsibility.

    PPT loop
    --------
    1. perceive()  – extract keywords; gather metadata context.
    2. plan()      – identify answer scope and tone; order context sections.
    3. act()       – generate the answer via LLM.
    """

    SYSTEM_PROMPT = """You are a knowledgeable assistant for Drawin AI, \
a ride-sharing analytics platform.

Answer the user's question based ONLY on the provided context.

Rules:
- Be clear and concise (2-4 sentences unless depth is needed).
- Reference specific tables, metrics, or terms when relevant.
- Do NOT write SQL queries — that is handled by a separate SQL Agent.
- If the context does not contain enough information, say so honestly.
- Adapt tone to the question: use business language for business questions,
  technical language for schema/data questions."""

    # ── Phase 1 – Perception ─────────────────────────────────────────────────

    async def perceive(
        self, user_question: str, db: AsyncSession
    ) -> DocPerception:
        """Extract keywords, detect topics, and gather relevant context."""
        logger.info("[DocAgent|Perception] Extracting documentation context...")

        q_lower   = user_question.lower()
        keywords  = [w for w in q_lower.split() if len(w) > 3]

        # Topic detection
        matched_topics: List[str] = []
        for topic, signals in TOPIC_KEYWORDS.items():
            if any(sig in q_lower for sig in signals):
                matched_topics.append(topic)
        if not matched_topics:
            matched_topics = ["general"]

        # Build base documentation context
        context_parts: List[str] = [
            "# DRAWIN AI — Ride-sharing Analytics Platform\n\n",
            "## Business Terms\n",
            "- USNC : US and Canada region\n",
            "- EU   : Europe region\n",
            "- APAC : Asia-Pacific region\n",
            "- LATAM: Latin America region\n\n",
            "## Key Metrics\n",
            "- Total Revenue : Sum of all trip fares\n",
            "- Completed Trips: Count of successfully finished trips\n",
            "- Active Users  : Users with ≥1 trip in the period\n",
            "- Average Rating: Driver ratings (1–5 stars)\n",
            "- Surge Multiplier: Price factor during high demand (1.0 = normal)\n\n",
            "## Database Structure\n",
            "- Transactional tables : users, drivers, trips, payments, vehicles\n",
            "- Analytics tables    :\n",
            "  * trip_metrics_daily   : Daily aggregated trip statistics\n",
            "  * region_revenue_summary: Monthly revenue by region\n\n",
        ]

        # Metadata search for question-specific enrichment
        metadata_matches: List[Dict] = []
        for kw in keywords:
            matches = await metadata_service.search_metadata(db, kw)
            if matches:
                context_parts.append(f"## Relevant context for '{kw}'\n")
                for m in matches[:3]:
                    context_parts.append(
                        f"- {m['table']}.{m['column']}: {m['description']}\n"
                    )
                    metadata_matches.append(m)

        perception = DocPerception(
            user_question=user_question,
            keywords=keywords[:10],
            matched_topics=matched_topics,
            raw_context="".join(context_parts),
            metadata_matches=metadata_matches,
        )

        logger.info(
            f"[DocAgent|Perception] topics={matched_topics} "
            f"keywords={keywords[:5]} metadata_hits={len(metadata_matches)}"
        )
        return perception

    # ── Phase 2 – Planning ───────────────────────────────────────────────────

    def plan(self, perception: DocPerception) -> DocAnswerPlan:
        """Decide answer scope, tone, and section ordering."""
        topics = perception.matched_topics

        tone = "business"
        if "schema" in topics or "metrics" in topics:
            tone = "technical"

        # Decide section depth (more sections = richer context → longer answer)
        sections = list(topics)
        if "general" in sections:
            sections = ["business_terms", "metrics", "schema"]

        max_tokens = 400 if len(topics) <= 1 else 700

        plan = DocAnswerPlan(
            focus_topics=topics,
            context_sections=sections,
            tone=tone,
            max_tokens=max_tokens,
        )

        logger.info(
            f"[DocAgent|Planning] tone={tone} sections={sections} "
            f"max_tokens={max_tokens}"
        )
        return plan

    # ── Phase 3 – Tool / Action ───────────────────────────────────────────────

    async def act(
        self, plan: DocAnswerPlan, perception: DocPerception
    ) -> Dict[str, Any]:
        """Generate the documentation answer via LLM."""
        tone_instruction = (
            "Use plain business language."
            if plan.tone == "business"
            else "Use precise technical language."
        )

        prompt = (
            f"{perception.raw_context}\n"
            f"User Question: {perception.user_question}\n\n"
            f"Instructions: {tone_instruction} "
            f"Focus on: {', '.join(plan.focus_topics)}.\n\n"
            f"Provide a helpful answer:"
        )

        result = await ai_gateway.generate(
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT,
            temperature=0.6,
            max_tokens=plan.max_tokens,
        )

        answer = result.get("text", "No answer generated.")

        logger.info(
            f"[DocAgent|Tool] Answer generated "
            f"({len(answer)} chars, provider={result.get('provider')})"
        )

        return {
            "answer":  answer,
            "sources": self._build_sources(perception),
            "sql":     None,
            "results": None,
            "error":   None,
        }

    # ── Public entry point ────────────────────────────────────────────────────

    async def answer_documentation(
        self, user_question: str, db: AsyncSession
    ) -> Dict[str, Any]:
        """Full PPT loop: Perception → Planning → Tool."""
        try:
            perception = await self.perceive(user_question, db)
            plan       = self.plan(perception)
            return await self.act(plan, perception)
        except Exception as e:
            logger.error(f"[DocAgent] Unhandled error: {e}", exc_info=True)
            return {
                "answer":  f"Error generating answer: {e}",
                "sources": [],
                "sql":     None,
                "results": None,
                "error":   str(e),
            }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_sources(self, perception: DocPerception) -> List[str]:
        sources = ["Business term definitions", "System documentation"]
        for m in perception.metadata_matches[:3]:
            sources.append(f"{m['table']}.{m['column']}")
        return list(dict.fromkeys(sources))   # deduplicate, preserve order


# Global singleton
doc_agent = DocAgent()
