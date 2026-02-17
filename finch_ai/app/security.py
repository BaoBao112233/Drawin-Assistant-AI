"""Security module for query validation and protection."""
import re
import logging
from typing import Tuple, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class QuerySecurityValidator:
    """
    Validates and sanitizes SQL queries to prevent destructive operations.
    Enforces read-only access and implements query timeouts.
    """
    
    # Destructive keywords that should be blocked
    BLOCKED_KEYWORDS = [
        r'\bDROP\b',
        r'\bDELETE\b',
        r'\bTRUNCATE\b',
        r'\bUPDATE\b',
        r'\bINSERT\b',
        r'\bALTER\b',
        r'\bCREATE\b',
        r'\bGRANT\b',
        r'\bREVOKE\b',
        r'\bEXEC\b',
        r'\bEXECUTE\b',
        r';.*DROP',
        r';.*DELETE',
        r';.*UPDATE',
    ]
    
    # Allowed keywords
    ALLOWED_KEYWORDS = [
        r'\bSELECT\b',
        r'\bWHERE\b',
        r'\bFROM\b',
        r'\bJOIN\b',
        r'\bGROUP BY\b',
        r'\bORDER BY\b',
        r'\bHAVING\b',
        r'\bLIMIT\b',
    ]
    
    def validate_query(self, sql: str) -> Tuple[bool, Optional[str]]:
        """
        Validate SQL query for security.
        
        Returns:
            (is_valid, error_message)
        """
        if not sql or not sql.strip():
            return False, "Empty query"
        
        # Convert to uppercase for checking
        sql_upper = sql.upper()
        
        # Check for blocked keywords
        for pattern in self.BLOCKED_KEYWORDS:
            if re.search(pattern, sql_upper, re.IGNORECASE):
                return False, f"Blocked keyword detected: {pattern}"
        
        # Check for multiple statements (basic check)
        if sql.count(';') > 1:
            return False, "Multiple statements not allowed"
        
        # Must start with SELECT
        if not re.match(r'^\s*SELECT\b', sql_upper):
            return False, "Only SELECT queries are allowed"
        
        # Check for comment-based injection attempts
        if '--' in sql or '/*' in sql or '*/' in sql:
            # Allow -- in strings but be cautious
            if sql.count('--') > 2:
                return False, "Suspicious comment patterns detected"
        
        return True, None
    
    def sanitize_query(self, sql: str) -> str:
        """
        Sanitize query by removing potential dangerous elements.
        """
        # Remove trailing semicolons
        sql = sql.rstrip(';').strip()
        
        # Remove multiple spaces
        sql = re.sub(r'\s+', ' ', sql)
        
        return sql
    
    async def execute_safe_query(
        self,
        db: AsyncSession,
        sql: str,
        timeout_seconds: int = 5
    ) -> Tuple[bool, Optional[list], Optional[str]]:
        """
        Execute query safely with timeout and validation.
        
        Returns:
            (success, results, error_message)
        """
        # Validate query
        is_valid, error_msg = self.validate_query(sql)
        if not is_valid:
            logger.warning(f"Query validation failed: {error_msg}")
            return False, None, f"Security validation failed: {error_msg}"
        
        # Sanitize
        sql = self.sanitize_query(sql)
        
        try:
            # Set statement timeout
            await db.execute(text(f"SET statement_timeout = '{timeout_seconds}s'"))
            
            # Execute query
            result = await db.execute(text(sql))
            
            # Fetch results
            rows = result.fetchall()
            
            # Convert to list of dicts
            if rows:
                columns = result.keys()
                results = [dict(zip(columns, row)) for row in rows]
            else:
                results = []
            
            # Reset timeout
            await db.execute(text("RESET statement_timeout"))
            
            return True, results, None
            
        except Exception as e:
            logger.error(f"Query execution error: {e}")
            
            # Reset timeout
            try:
                await db.execute(text("RESET statement_timeout"))
            except:
                pass
            
            return False, None, str(e)
    
    def extract_table_names(self, sql: str) -> list:
        """Extract table names from SQL query."""
        # Simple extraction using regex
        # Matches: FROM table_name or JOIN table_name
        pattern = r'(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)'
        matches = re.findall(pattern, sql, re.IGNORECASE)
        return list(set(matches))


class RateLimiter:
    """
    Simple in-memory rate limiter.
    In production, use Redis or similar.
    """
    
    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests = {}  # {ip: [timestamps]}
    
    def is_allowed(self, identifier: str) -> Tuple[bool, Optional[str]]:
        """
        Check if request is allowed.
        
        Args:
            identifier: IP address or user ID
            
        Returns:
            (is_allowed, error_message)
        """
        import time
        
        current_time = time.time()
        
        if identifier not in self._requests:
            self._requests[identifier] = []
        
        # Clean old requests
        self._requests[identifier] = [
            ts for ts in self._requests[identifier]
            if current_time - ts < self.window_seconds
        ]
        
        # Check limit
        if len(self._requests[identifier]) >= self.max_requests:
            return False, f"Rate limit exceeded. Max {self.max_requests} requests per {self.window_seconds}s."
        
        # Add current request
        self._requests[identifier].append(current_time)
        
        return True, None


# Global instances
query_validator = QuerySecurityValidator()
rate_limiter = RateLimiter(
    max_requests=int(os.getenv("MAX_REQUESTS_PER_MINUTE", 30)),
    window_seconds=60
)


import os
