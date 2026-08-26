"""
Schema vector store capability interface.

Abstract base class for schema ingestion and retrieval, decoupled from any
concrete vector backend (FAISS / Chroma / Milvus / Qdrant).
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from .models import SchemaColumn, SchemaRelation, SchemaSearchResult, SchemaTable


class SchemaVectorStore(ABC):
    """Abstract base class for schema vector stores.

    A schema vector store ingests parsed schema metadata (tables + relations),
    builds column-level embeddings and supports semantic retrieval so agents
    can discover relevant tables/columns and JOIN conditions for a question.
    """

    @abstractmethod
    async def ingest_schema(
        self,
        tables: List[SchemaTable],
        relations: List[SchemaRelation],
        database_name: str,
    ) -> None:
        """Ingest schema tables and relations for a database.

        Idempotent: re-ingesting the same database replaces the previous index.

        Args:
            tables: Parsed table metadata (each table carries its columns).
            relations: Parsed PK/FK relations (typically from DDL parsing).
            database_name: Logical database name used to namespace the index.
        """
        pass

    @abstractmethod
    async def search(
        self,
        query: str,
        database_name: str,
        top_k: int = 20,
    ) -> List[SchemaSearchResult]:
        """Semantic search for columns relevant to a natural language query.

        Args:
            query: Natural language query.
            database_name: Database namespace to search within.
            top_k: Maximum number of columns to return.

        Returns:
            Ranked schema search results (best match first).
        """
        pass

    @abstractmethod
    async def get_column_by_name(
        self,
        column_name: str,
        table_name: str,
        database_name: str,
    ) -> Optional[SchemaColumn]:
        """Exact (with case-insensitive fallback) column lookup.

        Args:
            column_name: Column name to look up.
            table_name: Table name to look up.
            database_name: Database namespace.

        Returns:
            The matching column, or None if not found.
        """
        pass

    @abstractmethod
    async def get_relations(
        self,
        table_names: List[str],
        database_name: str,
    ) -> List[SchemaRelation]:
        """Get stored PK/FK relations involving the given tables.

        Args:
            table_names: Tables to look up relations for.
            database_name: Database namespace.

        Returns:
            Relations where from_table or to_table is in table_names.
        """
        pass
