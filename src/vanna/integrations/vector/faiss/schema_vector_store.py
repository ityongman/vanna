"""
FAISS implementation of SchemaVectorStore.

Development / logic-verification backend ported from AutoLink's
embedding_docs.py core logic: column-level documents are encoded with
SentenceTransformer and indexed with a FAISS IndexFlatL2 per database,
persisted as index.faiss + metadata.json under
``{persist_dir}/{database_name}/``.
"""

import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import faiss
    import numpy as np

    FAISS_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on optional dependency
    FAISS_AVAILABLE = False

from vanna.capabilities.schema_vector_store import (
    SchemaColumn,
    SchemaDocumentGenerator,
    SchemaRelation,
    SchemaSearchResult,
    SchemaTable,
    SchemaVectorStore,
)

logger = logging.getLogger(__name__)

EmbedFn = Callable[[List[str]], "np.ndarray"]


class FAISSSchemaVectorStore(SchemaVectorStore):
    """FAISS-backed schema vector store (development / logic verification).

    Args:
        persist_dir: Root directory for per-database index persistence.
        embedding_model: SentenceTransformer model name used to encode
            column documents and queries.
        embed_fn: Optional embedding function (list of texts -> ndarray of
            shape (n, dim)). When provided it replaces SentenceTransformer,
            which is useful for tests and custom embedding backends.
        document_generator: Optional document generator; defaults to a plain
            SchemaDocumentGenerator without LLM descriptions.
    """

    def __init__(
        self,
        persist_dir: str = "./schema_index",
        embedding_model: str = "BAAI/bge-large-en-v1.5",
        embed_fn: Optional[EmbedFn] = None,
        document_generator: Optional[SchemaDocumentGenerator] = None,
    ):
        if not FAISS_AVAILABLE:
            raise ImportError(
                "FAISS is required for FAISSSchemaVectorStore. "
                "Install with: pip install faiss-cpu"
            )

        self.persist_dir = persist_dir
        self.embedding_model = embedding_model
        self._custom_embed_fn = embed_fn
        self._model = None
        self.document_generator = document_generator or SchemaDocumentGenerator()
        # Per-database in-memory state: index + metadata.
        self._indexes: Dict[str, Optional["faiss.Index"]] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}
        self._executor = ThreadPoolExecutor(max_workers=2)

    # ------------------------------------------------------------------
    # Embedding helpers
    # ------------------------------------------------------------------

    def _get_embed_fn(self) -> EmbedFn:
        """Return the embedding function (custom or SentenceTransformer)."""
        if self._custom_embed_fn is not None:
            return self._custom_embed_fn

        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise ImportError(
                    "sentence_transformers is required for "
                    "FAISSSchemaVectorStore embeddings. Install with: "
                    "pip install 'vanna[autolink]'"
                ) from e
            self._model = SentenceTransformer(self.embedding_model)

        model = self._model

        def _embed(texts: List[str]) -> "np.ndarray":
            return model.encode(texts, convert_to_numpy=True)

        return _embed

    def _build_embedding_text(self, column: SchemaColumn) -> str:
        """Embedding text for a column (delegates to the doc generator)."""
        return self.document_generator.format_column_document(column)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _db_dir(self, database_name: str) -> str:
        return os.path.join(self.persist_dir, database_name)

    def _load_database(self, database_name: str) -> None:
        """Load persisted index/metadata for a database if not already loaded."""
        if database_name in self._indexes:
            return
        db_dir = self._db_dir(database_name)
        index_file = os.path.join(db_dir, "index.faiss")
        metadata_file = os.path.join(db_dir, "metadata.json")

        if not (os.path.exists(index_file) and os.path.exists(metadata_file)):
            # No persisted index for this database: keep empty state.
            logger.info(
                f"No persisted schema index for database '{database_name}'"
            )
            self._indexes[database_name] = None
            self._metadata[database_name] = {
                "columns": [],
                "embedding_texts": [],
                "relations": [],
            }
            return

        self._indexes[database_name] = faiss.read_index(index_file)
        with open(metadata_file, "r", encoding="utf-8") as f:
            self._metadata[database_name] = json.load(f)

    def _persist_database(self, database_name: str) -> None:
        db_dir = self._db_dir(database_name)
        os.makedirs(db_dir, exist_ok=True)
        index = self._indexes.get(database_name)
        if index is not None:
            faiss.write_index(index, os.path.join(db_dir, "index.faiss"))
        with open(os.path.join(db_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(self._metadata.get(database_name, {}), f, ensure_ascii=False)

    # ------------------------------------------------------------------
    # SchemaVectorStore interface
    # ------------------------------------------------------------------

    async def ingest_schema(
        self,
        tables: List[SchemaTable],
        relations: List[SchemaRelation],
        database_name: str,
    ) -> None:
        """Ingest schema tables (idempotently replacing the previous index)."""
        column_docs = await self.document_generator.generate_column_documents(tables)
        columns = [column for column, _ in column_docs]
        embedding_texts = [text for _, text in column_docs]

        def _ingest() -> None:
            if not columns:
                # Empty schema: reset state, still persist empty metadata.
                self._indexes[database_name] = None
                self._metadata[database_name] = {
                    "columns": [],
                    "embedding_texts": [],
                    "relations": [r.model_dump() for r in relations],
                }
                self._persist_database(database_name)
                return

            embed_fn = self._get_embed_fn()
            embeddings = np.asarray(embed_fn(embedding_texts), dtype="float32")
            if embeddings.ndim != 2 or embeddings.shape[0] != len(embedding_texts):
                raise ValueError(
                    "Embedding function must return an array of shape "
                    f"(n, dim) for n={len(embedding_texts)} input texts"
                )

            index = faiss.IndexFlatL2(embeddings.shape[1])
            index.add(embeddings)

            # Replace any previous index for this database (idempotent ingest).
            self._indexes[database_name] = index
            self._metadata[database_name] = {
                "columns": [c.model_dump() for c in columns],
                "embedding_texts": embedding_texts,
                "relations": [r.model_dump() for r in relations],
            }
            self._persist_database(database_name)

        await asyncio.get_event_loop().run_in_executor(self._executor, _ingest)

    async def search(
        self,
        query: str,
        database_name: str,
        top_k: int = 20,
    ) -> List[SchemaSearchResult]:
        """Semantic search for columns relevant to a query."""
        self._load_database(database_name)

        def _search() -> List[SchemaSearchResult]:
            index = self._indexes.get(database_name)
            metadata = self._metadata.get(database_name) or {}
            if index is None or index.ntotal == 0:
                return []

            embed_fn = self._get_embed_fn()
            query_embedding = np.asarray(embed_fn([query]), dtype="float32")
            k = min(top_k, index.ntotal)
            distances, indices = index.search(query_embedding, k)

            columns = [
                SchemaColumn(**c) for c in metadata.get("columns", [])
            ]
            results: List[SchemaSearchResult] = []
            rank = 1
            for dist, idx in zip(distances[0], indices[0]):
                if idx == -1 or idx >= len(columns):
                    continue
                # Convert L2 distance to a similarity score (higher is better).
                similarity = 1.0 / (1.0 + float(dist))
                results.append(
                    SchemaSearchResult(
                        column=columns[idx],
                        similarity_score=similarity,
                        rank=rank,
                    )
                )
                rank += 1
            return results

        return await asyncio.get_event_loop().run_in_executor(self._executor, _search)

    async def get_column_by_name(
        self,
        column_name: str,
        table_name: str,
        database_name: str,
    ) -> Optional[SchemaColumn]:
        """Exact column lookup with case-insensitive fallback."""
        self._load_database(database_name)
        metadata = self._metadata.get(database_name) or {}
        columns = [SchemaColumn(**c) for c in metadata.get("columns", [])]

        for column in columns:
            if column.column_name == column_name and column.table_name == table_name:
                return column

        lower_column = column_name.lower()
        lower_table = table_name.lower()
        for column in columns:
            if (
                column.column_name.lower() == lower_column
                and column.table_name.lower() == lower_table
            ):
                return column
        return None

    async def get_relations(
        self,
        table_names: List[str],
        database_name: str,
    ) -> List[SchemaRelation]:
        """Relations involving any of the given tables."""
        self._load_database(database_name)
        metadata = self._metadata.get(database_name) or {}
        relations = [
            SchemaRelation(**r) for r in metadata.get("relations", [])
        ]
        lowered = {name.lower() for name in table_names}
        return [
            relation
            for relation in relations
            if relation.from_table.lower() in lowered
            or relation.to_table.lower() in lowered
        ]
