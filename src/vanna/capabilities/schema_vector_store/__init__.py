"""
Schema vector store capability package.

Provides schema ingestion and semantic retrieval over database schema
metadata (tables, columns, PK/FK relations), backing the AutoLink
integration. Concrete vector backends live in vanna.integrations.vector.*.
"""

from .base import SchemaVectorStore
from .ddl_parser import DdlParser, SKIP_TABLES
from .document_generator import SchemaDocumentGenerator
from .models import (
    SchemaColumn,
    SchemaRelation,
    SchemaSearchResult,
    SchemaTable,
)

__all__ = [
    "SchemaVectorStore",
    "DdlParser",
    "SKIP_TABLES",
    "SchemaDocumentGenerator",
    "SchemaColumn",
    "SchemaRelation",
    "SchemaSearchResult",
    "SchemaTable",
]
