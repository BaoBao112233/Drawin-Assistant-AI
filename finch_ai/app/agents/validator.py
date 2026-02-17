"""Validator Agent - Validates query results against golden queries."""
import logging
import hashlib
import json
from typing import Dict, Any, Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GoldenQuery
from app.security import query_validator

logger = logging.getLogger(__name__)


class ValidatorAgent:
    """
    Validator Agent that compares generated queries with golden queries.
    Calculates trust score based on result similarity.
    """
    
    async def validate_query(
        self,
        db: AsyncSession,
        user_question: str,
        generated_sql: str,
        results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Validate query against golden queries.
        
        Returns:
            {
                "trust_score": 0-1,
                "matched_golden": golden query if matched,
                "validation_notes": list of notes
            }
        """
        try:
            # Find matching golden query
            golden_query = await self._find_matching_golden_query(db, user_question)
            
            if not golden_query:
                # No golden query to compare - return moderate trust
                return {
                    "trust_score": 0.6,
                    "matched_golden": None,
                    "validation_notes": ["No matching golden query found for comparison"]
                }
            
            # Execute golden query
            success, golden_results, error = await query_validator.execute_safe_query(
                db, golden_query.sql_query
            )
            
            if not success:
                return {
                    "trust_score": 0.5,
                    "matched_golden": golden_query.question,
                    "validation_notes": [f"Could not execute golden query: {error}"]
                }
            
            # Compare results
            trust_score, notes = self._compare_results(results, golden_results)
            
            # Also compare SQL similarity
            sql_similarity = self._calculate_sql_similarity(generated_sql, golden_query.sql_query)
            
            # Combined trust score
            final_trust = (trust_score * 0.7) + (sql_similarity * 0.3)
            
            notes.append(f"Golden query match: {golden_query.question}")
            notes.append(f"SQL similarity: {sql_similarity:.2f}")
            
            return {
                "trust_score": round(final_trust, 2),
                "matched_golden": golden_query.question,
                "validation_notes": notes
            }
            
        except Exception as e:
            logger.error(f"Validation error: {e}")
            return {
                "trust_score": 0.5,
                "matched_golden": None,
                "validation_notes": [f"Validation error: {e}"]
            }
    
    async def _find_matching_golden_query(
        self,
        db: AsyncSession,
        user_question: str
    ) -> Optional[GoldenQuery]:
        """Find golden query that matches user question."""
        
        # Simple keyword matching
        # In production, use semantic similarity
        
        result = await db.execute(
            select(GoldenQuery).where(GoldenQuery.is_active == True)
        )
        golden_queries = result.scalars().all()
        
        user_lower = user_question.lower()
        
        for gq in golden_queries:
            gq_lower = gq.question.lower()
            
            # Check for key term matches
            user_terms = set(user_lower.split())
            gq_terms = set(gq_lower.split())
            
            # Calculate overlap
            overlap = len(user_terms & gq_terms)
            
            if overlap >= 3:  # At least 3 matching words
                return gq
        
        return None
    
    def _compare_results(
        self,
        results1: List[Dict],
        results2: List[Dict]
    ) -> tuple[float, List[str]]:
        """
        Compare two result sets.
        
        Returns:
            (similarity_score, notes)
        """
        notes = []
        
        if not results1 and not results2:
            return 1.0, ["Both queries returned empty results"]
        
        if not results1 or not results2:
            notes.append("One query returned empty results")
            return 0.3, notes
        
        # Compare row counts
        if len(results1) != len(results2):
            notes.append(f"Row count mismatch: {len(results1)} vs {len(results2)}")
            row_score = 0.5
        else:
            notes.append(f"Row counts match: {len(results1)}")
            row_score = 1.0
        
        # Compare first row values (simplified)
        if results1 and results2:
            first_row_similarity = self._compare_rows(results1[0], results2[0])
            notes.append(f"First row similarity: {first_row_similarity:.2f}")
        else:
            first_row_similarity = 0.0
        
        # Combined score
        score = (row_score * 0.4) + (first_row_similarity * 0.6)
        
        return score, notes
    
    def _compare_rows(self, row1: Dict, row2: Dict) -> float:
        """Compare two result rows."""
        
        # Get all keys
        all_keys = set(row1.keys()) | set(row2.keys())
        
        if not all_keys:
            return 1.0
        
        matching = 0
        for key in all_keys:
            val1 = row1.get(key)
            val2 = row2.get(key)
            
            # Convert to comparable types
            if val1 is not None and val2 is not None:
                # For numbers, check if close
                try:
                    if abs(float(val1) - float(val2)) < 0.01:
                        matching += 1
                except:
                    # For strings, exact match
                    if str(val1) == str(val2):
                        matching += 1
        
        return matching / len(all_keys)
    
    def _calculate_sql_similarity(self, sql1: str, sql2: str) -> float:
        """Calculate similarity between two SQL queries."""
        
        # Normalize SQL
        def normalize(sql):
            # Remove extra whitespace
            sql = ' '.join(sql.split())
            # Convert to uppercase
            sql = sql.upper()
            # Remove semicolon
            sql = sql.rstrip(';')
            return sql
        
        norm1 = normalize(sql1)
        norm2 = normalize(sql2)
        
        # Simple word-based similarity
        words1 = set(norm1.split())
        words2 = set(norm2.split())
        
        if not words1 and not words2:
            return 1.0
        
        intersection = words1 & words2
        union = words1 | words2
        
        if not union:
            return 0.0
        
        jaccard = len(intersection) / len(union)
        
        return jaccard
    
    def _hash_results(self, results: List[Dict]) -> str:
        """Create hash of results for comparison."""
        
        # Sort and serialize
        sorted_results = sorted(
            [sorted(r.items()) for r in results]
        )
        
        serialized = json.dumps(sorted_results, sort_keys=True, default=str)
        
        return hashlib.md5(serialized.encode()).hexdigest()


# Global instance
validator_agent = ValidatorAgent()
