"""
FAISS integration for Vanna Agents.
"""

from .agent_memory import FAISSAgentMemory
from .schema_vector_store import FAISSSchemaVectorStore

__all__ = ["FAISSAgentMemory", "FAISSSchemaVectorStore"]
