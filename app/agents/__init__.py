"""
Agent package — Drawin AI multi-agent system.

PPT (Perception → Planning → Tool) agents:
  supervisor     : Routes user intent to the correct specialist agent.
  sql_agent      : Generates and executes performance-aware SQL queries.
  validator_agent: Validates results against golden queries with load awareness.
  doc_agent      : Answers documentation and business-logic questions.
  cot_agent      : Chain-of-Thought reasoning helper used by all agents above.
                   Improves answer quality via iterative Reason→Reflect→Answer
                   loops (inspired by BaoBao112233/Plan-Agent-with-Meta-Agent).
"""
# cot_agent has no intra-package dependencies — import it first to avoid
# any risk of circular imports in the agents that use it.
from app.agents.cot_agent import cot_agent
from app.agents.supervisor import supervisor
from app.agents.sql_agent import sql_agent
from app.agents.validator import validator_agent
from app.agents.doc_agent import doc_agent

__all__ = ["cot_agent", "supervisor", "sql_agent", "validator_agent", "doc_agent"]
