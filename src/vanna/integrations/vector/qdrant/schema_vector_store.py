"""
Qdrant implementation skeleton of SchemaVectorStore.

Interface placeholder for cloud-native deployments. The SchemaVectorStore
interface is finalized here; concrete storage logic is developed on demand.
Until then every operation raises NotImplementedError with a clear
migration hint.
"""

from typing import List, Optional

from vanna.capabilities.schema_vector_store import (
    SchemaColumn,
    SchemaRelation,
    SchemaSearchResult,
    SchemaTable,
    SchemaVectorStore,
)

_MIGRATION_HINT = (
    "QdrantSchemaVectorStore is an interface placeholder reserved for "
    "cloud-native deployments and is not yet implemented. Use "
    "FAISSSchemaVectorStore (development/logic verification) or "
    "ChromaSchemaVectorStore (small/medium production) meanwhile."
)


class QdrantSchemaVectorStore(SchemaVectorStore):
    """Interface-reserved Qdrant backend skeleton."""

    async def ingest_schema(
        self,
        tables: List[SchemaTable],
        relations: List[SchemaRelation],
        database_name: str,
    ) -> None:
        raise NotImplementedError(_MIGRATION_HINT)

    async def search(
        self,
        query: str,
        database_name: str,
        top_k: int = 20,
    ) -> List[SchemaSearchResult]:
        raise NotImplementedError(_MIGRATION_HINT)

    async def get_column_by_name(
        self,
        column_name: str,
        table_name: str,
        database_name: str,
    ) -> Optional[SchemaColumn]:
        raise NotImplementedError(_MIGRATION_HINT)

    async def get_relations(
        self,
        table_names: List[str],
        database_name: str,
    ) -> List[SchemaRelation]:
        raise NotImplementedError(_MIGRATION_HINT)
