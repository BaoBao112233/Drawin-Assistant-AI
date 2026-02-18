"""SQL Writer Agent - Generates and executes SQL queries."""
import json
import logging
import re
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_gateway import ai_gateway
from app.metadata import metadata_service
from app.security import query_validator

logger = logging.getLogger(__name__)


class SQLAgent:
    """
    SQL Writer Agent that generates SQL queries based on user questions.
    
    Implements knowledge-first approach:
    1. Retrieve metadata from database
    2. Build context with table/column descriptions
    3. Generate SQL using AI with full context
    4. Return SQL + explanation + confidence score
    """
    
    async def generate_and_execute(
        self,
        user_question: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Generate SQL query and execute it.
        
        Returns:
            {
                "sql": generated SQL,
                "explanation": explanation of query,
                "confidence_score": 0-1,
                "results": query results,
                "error": error message if any
            }
        """
        try:
            # Step 1: Build knowledge context
            logger.info("Building knowledge context...")
            context = await metadata_service.build_context_for_query(db, user_question)
            
            # Step 2: Generate SQL
            logger.info("Generating SQL query...")
            ai_result = await self._generate_sql(user_question, context)
            sql_response = ai_result["text"]
            
            # Parse response
            sql_query = self._extract_sql(sql_response)
            explanation = self._extract_explanation(sql_response)
            confidence = self._calculate_confidence(sql_response)
            
            if not sql_query:
                return {
                    "sql": None,
                    "explanation": "Could not generate valid SQL",
                    "confidence_score": 0.0,
                    "results": None,
                    "error": "SQL generation failed"
                }
            
            # Step 3: Validate SQL
            is_valid, error_msg = query_validator.validate_query(sql_query)
            if not is_valid:
                return {
                    "sql": sql_query,
                    "explanation": explanation,
                    "confidence_score": 0.0,
                    "results": None,
                    "error": f"Security validation failed: {error_msg}"
                }
            
            # Step 4: Execute SQL
            logger.info(f"Executing SQL: {sql_query}")
            success, results, exec_error = await query_validator.execute_safe_query(
                db, sql_query
            )
            
            if not success:
                return {
                    "sql": sql_query,
                    "explanation": explanation,
                    "confidence_score": confidence,
                    "results": None,
                    "error": exec_error
                }
            
            return {
                "sql": sql_query,
                "explanation": explanation,
                "confidence_score": confidence,
                "results": results,
                "error": None,
                "row_count": len(results) if results else 0,
                "ai_provider": ai_result.get("provider"),
                "ai_model": ai_result.get("model"),
                "ai_tokens": ai_result.get("tokens")
            }
            
        except Exception as e:
            logger.error(f"SQL agent error: {e}")
            return {
                "sql": None,
                "explanation": None,
                "confidence_score": 0.0,
                "results": None,
                "error": str(e)
            }
    
    async def _generate_sql(self, user_question: str, context: str) -> Dict[str, Any]:
        """Generate SQL using AI with full context. Returns full AI response."""
        
        system_prompt = """You are an expert SQL query generator for a PostgreSQL database.

You will receive:
1. Database context with table descriptions, metrics, and business terms
2. A user question

Your task:
- Generate a SINGLE PostgreSQL SELECT query
- Use the flattened analytics tables when possible (trip_metrics_daily, region_revenue_summary)
- Always resolve business terms (e.g., USNC -> code in regions table)
- Include appropriate JOINs with regions table when needed
- Add date filters when relevant

Return your response in this EXACT format:

```sql
[YOUR SQL QUERY HERE]
```

Explanation: [Brief explanation of what the query does]

Confidence: [High/Medium/Low]

IMPORTANT:
- Query must be a valid PostgreSQL SELECT statement
- Use explicit column names, not SELECT *
- Add LIMIT if counting many rows
- Prefer aggregated tables over raw data"""

        prompt = f"""{context}

User Question: {user_question}

Generate the SQL query now."""

        result = await ai_gateway.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.3,  # Low temp for consistency
            max_tokens=1000
        )
        
        return result  # Return full result object
    
    def _extract_sql(self, response: str) -> Optional[str]:
        """Extract SQL query from AI response."""
        
        # Look for SQL in code blocks
        sql_pattern = r'```sql\n(.*?)\n```'
        match = re.search(sql_pattern, response, re.DOTALL | re.IGNORECASE)
        
        if match:
            sql = match.group(1).strip()
            return sql
        
        # Try without backticks
        sql_pattern2 = r'```\n(SELECT.*?)\n```'
        match2 = re.search(sql_pattern2, response, re.DOTALL | re.IGNORECASE)
        
        if match2:
            return match2.group(1).strip()
        
        # Try to find SELECT statement directly
        if 'SELECT' in response.upper():
            # Find SELECT statement
            lines = response.split('\n')
            sql_lines = []
            in_sql = False
            
            for line in lines:
                if 'SELECT' in line.upper():
                    in_sql = True
                
                if in_sql:
                    sql_lines.append(line)
                    
                    # Check if query ended
                    if line.strip().endswith(';'):
                        break
            
            if sql_lines:
                return '\n'.join(sql_lines).strip()
        
        return None
    
    def _extract_explanation(self, response: str) -> str:
        """Extract explanation from AI response."""
        
        # Look for "Explanation:" section
        pattern = r'Explanation:\s*(.+?)(?:\n\n|Confidence:|$)'
        match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
        
        if match:
            return match.group(1).strip()
        
        return "No explanation provided"
    
    def _calculate_confidence(self, response: str) -> float:
        """Calculate confidence score from response."""
        
        # Look for confidence statement
        if "Confidence: High" in response or "confidence: high" in response.lower():
            return 0.9
        elif "Confidence: Medium" in response or "confidence: medium" in response.lower():
            return 0.7
        elif "Confidence: Low" in response or "confidence: low" in response.lower():
            return 0.4
        
        # Default medium confidence
        return 0.7


# Global instance
sql_agent = SQLAgent()
