"""
Chroma implementation of SchemaVectorStore.

Production backend for small/medium scale: uses chromadb (embedded or
client/server) with one collection per database_name and external
embeddings, so retrieval semantics stay consistent with the FAISS backend.
"""

import asyncio
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, List, Optional

from vanna.capabilities.schema_vector_store import (
    SchemaColumn,
    SchemaDocumentGenerator,
    SchemaRelation,
    SchemaSearchResult,
    SchemaTable,
    SchemaVectorStore,
)

logger = logging.getLogger(__name__)

EmbedFn = Callable[[List[str]], Any]


def _collection_name(database_name: str) -> str:
    """Sanitize a database name into a valid chroma collection name."""
    sanitized = "".join(
        ch if (ch.isalnum() or ch in "-_") else "_" for ch in database_name
    )
    sanitized = sanitized[:60] or "db_default"
    if not (sanitized[0].isalnum() or sanitized[0] == "_"):
        sanitized = f"db_{sanitized}"
    return sanitized


class ChromaSchemaVectorStore(SchemaVectorStore):
    """Chroma-backed schema vector store (small/medium production).

    Args:
        persist_dir: Directory for chromadb persistent storage.
        embedding_model: SentenceTransformer model name used for encoding.
        embed_fn: Optional embedding function replacing SentenceTransformer.
        client: Optional pre-configured chromadb client (e.g. HttpClient).
        document_generator: Optional document generator.
    """

    def __init__(
        self,
        persist_dir: str = "./schema_index_chroma",
        embedding_model: str = "BAAI/bge-large-en-v1.5",
        embed_fn: Optional[EmbedFn] = None,
        client: Optional[Any] = None,
        document_generator: Optional[SchemaDocumentGenerator] = None,
    ):
        try:
            import chromadb
        except ImportError as e:
            raise ImportError(
                "chromadb is required for ChromaSchemaVectorStore. "
                "Install with: pip install 'vanna[chromadb]' or 'pip install chromadb'"
            ) from e

        if client is not None:
            self._client = client
        else:
            self._client = chromadb.PersistentClient(path=persist_dir)
        self.embedding_model = embedding_model
        self._custom_embed_fn = embed_fn
        self._model = None
        self.document_generator = document_generator or SchemaDocumentGenerator()
        self._executor = ThreadPoolExecutor(max_workers=2)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_embed_fn(self) -> EmbedFn:
        if self._custom_embed_fn is not None:
            return self._custom_embed_fn
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise ImportError(
                    "sentence_transformers is required for "
                    "ChromaSchemaVectorStore embeddings. Install with: "
                    "pip install 'vanna[autolink]'"
                ) from e
            self._model = SentenceTransformer(self.embedding_model)
        model = self._model

        def _embed(texts: List[str]):
            return model.encode(texts, convert_to_numpy=True).tolist()

        return _embed

    def _get_collection(self, database_name: str):
        try:
            return self._client.get_collection(name=_collection_name(database_name))
        except Exception:
            return None

    @staticmethod
    def _column_from_metadata(meta: dict) -> SchemaColumn:
        return SchemaColumn(
            column_name=meta.get("column_name", ""),
            table_name=meta.get("table_name", ""),
            data_type=meta.get("data_type", ""),
            description=meta.get("description") or None,
            sample_values=_parse_samples(meta.get("sample_values")),
        )

    # ------------------------------------------------------------------
    # SchemaVectorStore interface
    # ------------------------------------------------------------------

    async def ingest_schema(
        self,
        tables: List[SchemaTable],
        relations: List[SchemaRelation],
        database_name: str,
    ) -> None:
        column_docs = await self.document_generator.generate_column_documents(tables)
        columns = [column for column, _ in column_docs]
        embedding_texts = [text for _, text in column_docs]
        relations_payload = [r.model_dump() for r in relations]

        def _ingest() -> None:
            collection = self._client.get_or_create_collection(
                name=_collection_name(database_name)
            )
            # Idempotent ingest: replace previous content.
            existing = collection.get()
            if existing and existing.get("ids"):
                collection.delete(ids=existing["ids"])

            if columns:
                embed_fn = self._get_embed_fn()
                embeddings = embed_fn(embedding_texts)
                ids = [str(uuid.uuid4()) for _ in columns]
                metadatas = [
                    {
                        "table_name": c.table_name,
                        "column_name": c.column_name,
                        "data_type": c.data_type,
                        "description": c.description or "",
                        "sample_values": json.dumps(c.sample_values),
                    }
                    for c in columns
                ]
                collection.add(
                    ids=ids,
                    documents=embedding_texts,
                    embeddings=embeddings,
                    metadatas=metadatas,
                )

            # Persist relations (PK/FK) as collection-level metadata.
            collection.modify(
                metadata={
                    "relations": json.dumps(relations_payload),
                    "database_name": database_name,
                }
            )

        await asyncio.get_event_loop().run_in_executor(self._executor, _ingest)

    async def search(
        self,
        query: str,
        database_name: str,
        top_k: int = 20,
    ) -> List[SchemaSearchResult]:
        def _search() -> List[SchemaSearchResult]:
            collection = self._get_collection(database_name)
            if collection is None:
                return []
            count = collection.count()
            if count == 0:
                return []
            embed_fn = self._get_embed_fn()
            query_embedding = embed_fn([query])[0]
            result = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, count),
                include=["metadatas", "distances"],
            )
            metadatas = (result.get("metadatas") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]
            out: List[SchemaSearchResult] = []
            for rank, (meta, dist) in enumerate(zip(metadatas, distances), start=1):
                if not meta:
                    continue
                similarity = 1.0 / (1.0 + float(dist))
                out.append(
                    SchemaSearchResult(
                        column=self._column_from_metadata(meta),
                        similarity_score=similarity,
                        rank=rank,
                    )
                )
            return out

        return await asyncio.get_event_loop().run_in_executor(self._executor, _search)

    async def get_column_by_name(
        self,
        column_name: str,
        table_name: str,
        database_name: str,
    ) -> Optional[SchemaColumn]:
        def _get() -> Optional[SchemaColumn]:
            collection = self._get_collection(database_name)
            if collection is None:
                return None
            exact = collection.get(
                where={
                    "$and": [
                        {"column_name": column_name},
                        {"table_name": table_name},
                    ]
                }
            )
            metadatas = exact.get("metadatas") or []
            if metadatas:
                return self._column_from_metadata(metadatas[0])

            # Case-insensitive fallback.
            all_items = collection.get()
            lowered_column = column_name.lower()
            lowered_table = table_name.lower()
            for meta in all_items.get("metadatas") or []:
                if (
                    str(meta.get("column_name", "")).lower() == lowered_column
                    and str(meta.get("table_name", "")).lower() == lowered_table
                ):
                    return self._column_from_metadata(meta)
            return None

        return await asyncio.get_event_loop().run_in_executor(self._executor, _get)

    async def get_relations(
        self,
        table_names: List[str],
        database_name: str,
    ) -> List[SchemaRelation]:
        def _get() -> List[SchemaRelation]:
            collection = self._get_collection(database_name)
            if collection is None:
                return []
            raw = (getattr(collection, "metadata", None) or {}).get("relations")
            if not raw:
                return []
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                return []
            lowered = {name.lower() for name in table_names}
            out: List[SchemaRelation] = []
            for item in payload:
                relation = SchemaRelation(**item)
                if (
                    relation.from_table.lower() in lowered
                    or relation.to_table.lower() in lowered
                ):
                    out.append(relation)
            return out

        return await asyncio.get_event_loop().run_in_executor(self._executor, _get)


def _parse_samples(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [str(s) for s in parsed] if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []
