"""
Capabilities module.

This package contains abstractions for tool capabilities - reusable utilities
that tools can compose via dependency injection.
"""

from .file_system import CommandResult, FileSearchMatch, FileSystem
from .schema_vector_store import (
    DdlParser,
    SchemaColumn,
    SchemaDocumentGenerator,
    SchemaRelation,
    SchemaSearchResult,
    SchemaTable,
    SchemaVectorStore,
)
from .sql_runner import RunSqlToolArgs, SqlRunner

__all__ = [
    "FileSystem",
    "FileSearchMatch",
    "CommandResult",
    "SqlRunner",
    "RunSqlToolArgs",
    "DdlParser",
    "SchemaVectorStore",
    "SchemaDocumentGenerator",
    "SchemaColumn",
    "SchemaRelation",
    "SchemaSearchResult",
    "SchemaTable",
]
