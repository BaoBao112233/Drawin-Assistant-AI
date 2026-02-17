"""Metadata service for retrieving table and column information."""
import os
import logging
from typing import Dict, List, Optional, Any
from sqlalchemy import select, inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MetadataIndex

logger = logging.getLogger(__name__)


class MetadataService:
    """
    Knowledge-first metadata service.
    Retrieves table/column descriptions, business terms, and metric definitions.
    """
    
    def __init__(self):
        self.use_opensearch = os.getenv("OPENSEARCH_HOST") is not None
        self._cache: Dict[str, Any] = {}
    
    async def get_table_metadata(self, db: AsyncSession, table_name: str) -> Dict[str, Any]:
        """Get metadata for a specific table."""
        cache_key = f"table_{table_name}"
        
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Fetch from database
        result = await db.execute(
            select(MetadataIndex).where(MetadataIndex.table_name == table_name)
        )
        entries = result.scalars().all()
        
        metadata = {
            "table_name": table_name,
            "columns": {},
            "metrics": [],
            "business_terms": {}
        }
        
        for entry in entries:
            if entry.column_name:
                metadata["columns"][entry.column_name] = {
                    "display_name": entry.display_name or entry.column_name,
                    "description": entry.description,
                    "data_type": entry.data_type,
                    "is_metric": entry.is_metric,
                    "metric_definition": entry.metric_definition
                }
                
                if entry.is_metric:
                    metadata["metrics"].append(entry.column_name)
                
                if entry.business_term:
                    # Parse business terms like "USNC=US and Canada"
                    for term in entry.business_term.split(","):
                        if "=" in term:
                            code, meaning = term.strip().split("=", 1)
                            metadata["business_terms"][code.strip()] = meaning.strip()
        
        self._cache[cache_key] = metadata
        return metadata
    
    async def search_metadata(self, db: AsyncSession, query: str) -> List[Dict[str, Any]]:
        """Search metadata by query term."""
        
        # Simple search in business terms and descriptions
        result = await db.execute(
            select(MetadataIndex).where(
                (MetadataIndex.business_term.ilike(f"%{query}%")) |
                (MetadataIndex.description.ilike(f"%{query}%")) |
                (MetadataIndex.display_name.ilike(f"%{query}%"))
            )
        )
        entries = result.scalars().all()
        
        results = []
        for entry in entries:
            results.append({
                "table": entry.table_name,
                "column": entry.column_name,
                "description": entry.description,
                "business_term": entry.business_term
            })
        
        return results
    
    async def resolve_business_term(self, db: AsyncSession, term: str) -> Optional[str]:
        """
        Resolve business term to actual value.
        E.g., "USNC" -> "US and Canada" -> region code for query.
        """
        term_upper = term.upper()
        
        # Search in metadata for business terms
        result = await db.execute(
            select(MetadataIndex).where(
                MetadataIndex.business_term.ilike(f"%{term_upper}%")
            )
        )
        entry = result.scalars().first()
        
        if entry and entry.business_term:
            # Parse to get the code
            for bt in entry.business_term.split(","):
                if "=" in bt:
                    code, meaning = bt.strip().split("=", 1)
                    if code.strip().upper() == term_upper:
                        return code.strip()
        
        return None
    
    async def get_flattened_tables(self, db: AsyncSession) -> List[str]:
        """Get list of flattened analytics tables."""
        return ["trip_metrics_daily", "region_revenue_summary"]
    
    async def get_table_schema(self, db: AsyncSession, table_name: str) -> Dict[str, Any]:
        """Get complete schema information for a table."""
        
        # This would normally use SQLAlchemy inspector
        # For now, return basic structure
        from app.database import async_engine
        
        async with async_engine.connect() as conn:
            def get_columns(connection):
                inspector = inspect(connection)
                return inspector.get_columns(table_name)
            
            columns = await conn.run_sync(get_columns)
        
        return {
            "table_name": table_name,
            "columns": [
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True)
                }
                for col in columns
            ]
        }
    
    async def build_context_for_query(self, db: AsyncSession, user_question: str) -> str:
        """
        Build knowledge context for SQL generation.
        This is the core of the knowledge-first approach.
        """
        context_parts = []
        
        context_parts.append("# DATABASE CONTEXT\n")
        
        # Get flattened tables (preferred for analytics)
        context_parts.append("## Flattened Analytics Tables (USE THESE FOR METRICS):\n")
        context_parts.append("- trip_metrics_daily: Daily aggregated trip statistics\n")
        context_parts.append("- region_revenue_summary: Monthly revenue by region\n\n")
        
        # Search for relevant metadata
        keywords = user_question.lower().split()
        relevant_metadata = []
        
        for keyword in keywords:
            if len(keyword) > 3:  # Skip short words
                matches = await self.search_metadata(db, keyword)
                relevant_metadata.extend(matches)
        
        if relevant_metadata:
            context_parts.append("## Relevant Metadata:\n")
            for meta in relevant_metadata[:5]:  # Top 5
                context_parts.append(
                    f"- {meta['table']}.{meta['column']}: {meta['description']}\n"
                )
            context_parts.append("\n")
        
        # Add business term mappings
        context_parts.append("## Business Terms:\n")
        context_parts.append("- USNC = US and Canada region (code in regions table)\n")
        context_parts.append("- EU = Europe region\n")
        context_parts.append("- APAC = Asia Pacific region\n")
        context_parts.append("- LATAM = Latin America region\n\n")
        
        # Add important rules
        context_parts.append("## IMPORTANT RULES:\n")
        context_parts.append("1. For revenue/metrics queries, USE flattened tables\n")
        context_parts.append("2. Join with regions table to resolve region codes\n")
        context_parts.append("3. Always use appropriate date filters\n")
        context_parts.append("4. Prefer aggregated data over raw transactions\n\n")
        
        return "".join(context_parts)


# Global instance
metadata_service = MetadataService()
