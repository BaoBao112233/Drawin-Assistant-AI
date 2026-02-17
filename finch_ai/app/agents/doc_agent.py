"""Documentation Agent - Answers business/documentation questions."""
import logging
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_gateway import ai_gateway
from app.metadata import metadata_service

logger = logging.getLogger(__name__)


class DocAgent:
    """
    Documentation Agent that answers business logic and documentation questions.
    Does NOT generate SQL - only provides explanations and definitions.
    """
    
    async def answer_documentation(
        self,
        user_question: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Answer documentation/explanation question.
        
        Returns:
            {
                "answer": text answer,
                "sources": list of referenced metadata,
                "sql": None (doc agent doesn't generate SQL)
            }
        """
        try:
            # Build context from metadata
            context = await self._build_doc_context(db, user_question)
            
            # Generate answer
            answer = await self._generate_answer(user_question, context)
            
            return {
                "answer": answer,
                "sources": self._extract_sources(context),
                "sql": None,
                "results": None,
                "error": None
            }
            
        except Exception as e:
            logger.error(f"Doc agent error: {e}")
            return {
                "answer": f"Error generating answer: {e}",
                "sources": [],
                "sql": None,
                "results": None,
                "error": str(e)
            }
    
    async def _build_doc_context(self, db: AsyncSession, question: str) -> str:
        """Build documentation context."""
        
        context_parts = []
        
        # Add general system documentation
        context_parts.append("# RIDE-SHARING ANALYTICS SYSTEM\n\n")
        
        context_parts.append("## Business Terms:\n")
        context_parts.append("- USNC: US and Canada region\n")
        context_parts.append("- EU: Europe region\n")
        context_parts.append("- APAC: Asia Pacific region\n")
        context_parts.append("- LATAM: Latin America region\n\n")
        
        context_parts.append("## Key Metrics:\n")
        context_parts.append("- Total Revenue: Sum of all trip fares\n")
        context_parts.append("- Completed Trips: Number of successfully finished trips\n")
        context_parts.append("- Active Users: Users who took at least one trip in period\n")
        context_parts.append("- Average Rating: Driver ratings from 1-5 stars\n")
        context_parts.append("- Surge Multiplier: Price increase during high demand (1.0 = normal)\n\n")
        
        context_parts.append("## Database Structure:\n")
        context_parts.append("- Transactional Tables: users, drivers, trips, payments, etc.\n")
        context_parts.append("- Flattened Analytics Tables:\n")
        context_parts.append("  * trip_metrics_daily: Daily aggregated trip statistics\n")
        context_parts.append("  * region_revenue_summary: Monthly revenue by region\n\n")
        
        # Search metadata for relevant info
        keywords = question.lower().split()
        for keyword in keywords:
            if len(keyword) > 3:
                matches = await metadata_service.search_metadata(db, keyword)
                if matches:
                    context_parts.append(f"## Relevant to '{keyword}':\n")
                    for match in matches[:3]:
                        context_parts.append(
                            f"- {match['table']}.{match['column']}: {match['description']}\n"
                        )
        
        return "".join(context_parts)
    
    async def _generate_answer(self, question: str, context: str) -> str:
        """Generate answer using AI."""
        
        system_prompt = """You are a helpful assistant explaining a ride-sharing analytics system.

Answer the user's question based on the provided context.

Rules:
- Provide clear, concise explanations
- Reference specific tables or metrics when relevant
- Do NOT generate SQL queries (that's a different agent's job)
- If you don't have enough information, say so

Keep your answer brief and informative."""

        prompt = f"""{context}

User Question: {question}

Provide a helpful answer:"""

        result = await ai_gateway.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.7,
            max_tokens=500
        )
        
        return result["text"]
    
    def _extract_sources(self, context: str) -> list:
        """Extract referenced sources from context."""
        # Simple implementation - return general sources
        return [
            "Business term definitions",
            "Database metadata",
            "System documentation"
        ]


# Global instance
doc_agent = DocAgent()
