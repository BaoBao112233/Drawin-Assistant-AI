"""Supervisor Agent - Routes user queries to appropriate agent."""
import logging
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_gateway import ai_gateway

logger = logging.getLogger(__name__)


class SupervisorAgent:
    """
    Supervisor agent that classifies user intent and routes to appropriate agent.
    
    Routes to:
    - SQL Agent: For data queries that need SQL execution
    - Doc Agent: For documentation/explanation questions
    """
    
    SYSTEM_PROMPT = """You are a query classifier for a ride-sharing analytics system.

Your task is to classify the user's question into one of these categories:

1. SQL_QUERY: Questions asking for data, metrics, statistics, counts, revenue, etc.
   Examples:
   - "What is the total revenue for USNC last month?"
   - "How many trips were completed yesterday?"
   - "Show me top drivers by earnings"

2. DOCUMENTATION: Questions asking for explanations, definitions, how things work.
   Examples:
   - "What does USNC mean?"
   - "Explain surge pricing"
   - "What tables are available?"

Respond with ONLY one word: SQL_QUERY or DOCUMENTATION"""
    
    async def classify_intent(self, user_question: str) -> str:
        """
        Classify user intent.
        
        Returns:
            "sql_query" or "documentation"
        """
        try:
            result = await ai_gateway.generate(
                prompt=user_question,
                system_prompt=self.SYSTEM_PROMPT,
                temperature=0.3,  # Low temperature for consistent classification
                max_tokens=50
            )
            
            response = result["text"].strip().upper()
            
            if "SQL_QUERY" in response or "SQL" in response:
                logger.info(f"Classified as SQL_QUERY: {user_question}")
                return "sql_query"
            elif "DOCUMENTATION" in response or "DOC" in response:
                logger.info(f"Classified as DOCUMENTATION: {user_question}")
                return "documentation"
            else:
                # Default to SQL query if unclear
                logger.info(f"Unclear classification, defaulting to SQL_QUERY: {response}")
                return "sql_query"
                
        except Exception as e:
            logger.error(f"Classification error: {e}")
            # Default to SQL query on error
            return "sql_query"
    
    async def route_query(
        self,
        user_question: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Route query to appropriate agent.
        
        Returns:
            Response dict with agent_used, result, etc.
        """
        # Classify intent
        intent = await self.classify_intent(user_question)
        
        if intent == "sql_query":
            # Import here to avoid circular imports
            from app.agents.sql_agent import sql_agent
            
            response = await sql_agent.generate_and_execute(user_question, db)
            response["agent_used"] = "sql_agent"
            
        else:  # documentation
            from app.agents.doc_agent import doc_agent
            
            response = await doc_agent.answer_documentation(user_question, db)
            response["agent_used"] = "doc_agent"
        
        return response


# Global instance
supervisor = SupervisorAgent()
