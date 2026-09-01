"""
Unit tests for the AutoLink schema ingestion pipeline:
DdlParser, SchemaDocumentGenerator, and SchemaVectorStore backends.
"""

import json
import re
from pathlib import Path

import numpy as np
import pytest

from vanna.capabilities.schema_vector_store import (
    DdlParser,
    SchemaColumn,
    SchemaDocumentGenerator,
    SchemaRelation,
    SchemaSearchResult,
    SchemaTable,
    SchemaVectorStore,
)
from vanna.integrations.vector.faiss import FAISSSchemaVectorStore


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

def make_fake_embed_fn(dim: int = 64):
    """Deterministic word-overlap embedding for tests (no heavy deps)."""
    import hashlib

    def embed(texts):
        vectors = np.zeros((len(texts), dim), dtype="float32")
        for i, text in enumerate(texts):
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % dim
                vectors[i, idx] += 1.0
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return vectors / norms

    return embed


@pytest.fixture
def embed_fn():
    return make_fake_embed_fn()


def make_sales_schema():
    """A small sales schema: customers + orders with a FK relation."""
    customers = SchemaTable(
        table_name="customers",
        database_name="sales_db",
        columns=[
            SchemaColumn(column_name="id", table_name="customers", data_type="INTEGER"),
            SchemaColumn(
                column_name="name", table_name="customers", data_type="VARCHAR"
            ),
            SchemaColumn(
                column_name="email", table_name="customers", data_type="VARCHAR"
            ),
        ],
        primary_keys=["id"],
    )
    orders = SchemaTable(
        table_name="orders",
        database_name="sales_db",
        columns=[
            SchemaColumn(column_name="id", table_name="orders", data_type="INTEGER"),
            SchemaColumn(
                column_name="customer_id", table_name="orders", data_type="INTEGER"
            ),
            SchemaColumn(
                column_name="total_amount",
                table_name="orders",
                data_type="DECIMAL(10,2)",
                description="Total order amount",
            ),
        ],
        primary_keys=["id"],
    )
    relations = [
        SchemaRelation(
            from_table="orders",
            from_column="customer_id",
            to_table="customers",
            to_column="id",
            relation_type="fk",
        )
    ]
    return [customers, orders], relations


# ---------------------------------------------------------------------------
# DdlParser tests (DP-*)
# ---------------------------------------------------------------------------

class TestDdlParser:
    def test_parse_basic_ddl(self):
        ddl = """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            total_amount DECIMAL(10, 2)
        );
        """
        parser = DdlParser()
        tables, relations = parser.parse_ddl(ddl, database_name="sales_db")

        assert len(tables) == 1
        table = tables[0]
        assert table.table_name == "orders"
        assert table.database_name == "sales_db"
        names = [c.column_name for c in table.columns]
        assert names == ["id", "customer_id", "total_amount"]
        types = {c.column_name: c.data_type for c in table.columns}
        assert types["id"] == "INTEGER"
        assert types["total_amount"] == "DECIMAL(10,2)"
        assert types["customer_id"] == "INTEGER"
        assert relations == []

    def test_parse_primary_key(self):
        ddl = """
        CREATE TABLE order_items (
            order_id BIGINT,
            product_code VARCHAR(50),
            PRIMARY KEY (order_id, product_code)
        );
        """
        parser = DdlParser()
        tables, _ = parser.parse_ddl(ddl)

        assert tables[0].primary_keys == ["order_id", "product_code"]

    def test_parse_inline_primary_key(self):
        ddl = "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT);"
        tables, _ = DdlParser().parse_ddl(ddl)
        assert tables[0].primary_keys == ["id"]

    def test_parse_foreign_key(self):
        ddl = """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );
        """
        parser = DdlParser()
        tables, relations = parser.parse_ddl(ddl)

        assert len(relations) == 1
        relation = relations[0]
        assert relation.from_table == "orders"
        assert relation.from_column == "customer_id"
        assert relation.to_table == "customers"
        assert relation.to_column == "id"
        assert relation.relation_type == "fk"
        assert tables[0].foreign_keys[0]["ref_table"] == "customers"

    def test_parse_inline_foreign_key(self):
        ddl = """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER REFERENCES customers(id)
        );
        """
        _, relations = DdlParser().parse_ddl(ddl)
        assert len(relations) == 1
        assert relations[0].to_table == "customers"

    def test_dialect_tolerance(self):
        # PostgreSQL quoted identifiers + schema prefix + constraint names.
        pg_ddl = """
        CREATE TABLE public.orders (
            id SERIAL PRIMARY KEY,
            "total amount" DECIMAL(10,2),
            customer_id INTEGER,
            CONSTRAINT fk_customer FOREIGN KEY (customer_id)
                REFERENCES public.customers (id)
        );
        """
        tables, relations = DdlParser().parse_ddl(pg_ddl)
        assert tables[0].table_name == "orders"
        names = {c.column_name for c in tables[0].columns}
        assert "total amount" in names
        assert relations[0].from_column == "customer_id"
        assert relations[0].to_table == "customers"

        # MySQL backticks, table-level KEY/INDEX definitions.
        mysql_ddl = """
        CREATE TABLE `order_items` (
            `order_id` BIGINT UNSIGNED NOT NULL,
            `product_code` VARCHAR(50),
            PRIMARY KEY (`order_id`, `product_code`),
            KEY `idx_order` (`order_id`)
        ) ENGINE=InnoDB;
        """
        tables, _ = DdlParser().parse_ddl(mysql_ddl)
        assert tables[0].table_name == "order_items"
        assert [c.column_name for c in tables[0].columns] == [
            "order_id",
            "product_code",
        ]
        assert tables[0].primary_keys == ["order_id", "product_code"]

        # Spark: IF NOT EXISTS + STRING type.
        spark_ddl = """
        CREATE TABLE IF NOT EXISTS products (
            product_id BIGINT,
            product_name STRING
        );
        """
        tables, _ = DdlParser().parse_ddl(spark_ddl)
        assert tables[0].table_name == "products"
        assert tables[0].columns[1].data_type == "STRING"

    def test_invalid_ddl_skipped_with_warning(self, caplog):
        ddl = """
        CREATE TABLE broken (id INTEGER;
        CREATE TABLE good (id INTEGER PRIMARY KEY, name TEXT);
        """
        parser = DdlParser()
        with caplog.at_level("WARNING"):
            tables, _ = parser.parse_ddl(ddl)

        assert [t.table_name for t in tables] == ["good"]
        assert any("broken" in message for message in caplog.messages)

    def test_empty_ddl_text(self):
        tables, relations = DdlParser().parse_ddl("")
        assert tables == []
        assert relations == []

    def test_parse_csv_with_header(self, tmp_path: Path):
        csv_path = tmp_path / "DDL.csv"
        csv_path.write_text(
            "database_id,table_name,ddl\n"
            'sales_db,orders,"CREATE TABLE orders (\n'
            "    id INTEGER PRIMARY KEY,\n"
            "    customer_id INTEGER,\n"
            '    FOREIGN KEY (customer_id) REFERENCES customers(id)\n'
            ')"\n'
            'sales_db,customers,"CREATE TABLE customers (\n'
            "    id INTEGER PRIMARY KEY,\n"
            '    name VARCHAR(100)\n'
            ')"\n',
            encoding="utf-8",
        )
        parser = DdlParser()
        tables, relations = parser.parse_csv(csv_path)

        assert {t.table_name for t in tables} == {"orders", "customers"}
        assert all(t.database_name == "sales_db" for t in tables)
        assert len(relations) == 1
        assert relations[0].to_table == "customers"
        customers = next(t for t in tables if t.table_name == "customers")
        assert customers.primary_keys == ["id"]

    def test_parse_csv_headerless(self, tmp_path: Path):
        csv_path = tmp_path / "DDL.csv"
        csv_path.write_text(
            'CREATE TABLE a (id INTEGER, name TEXT);\n'
            'CREATE TABLE b (id INTEGER PRIMARY KEY, amount REAL);\n',
            encoding="utf-8",
        )
        tables, _ = DdlParser().parse_csv(csv_path, database_name="db2")
        assert {t.table_name for t in tables} == {"a", "b"}
        assert all(t.database_name == "db2" for t in tables)

    def test_parse_csv_skips_system_tables(self, tmp_path: Path):
        csv_path = tmp_path / "DDL.csv"
        csv_path.write_text(
            "table_name,ddl\n"
            'sqlite_sequence,"CREATE TABLE sqlite_sequence(name,seq);"\n'
            'real_table,"CREATE TABLE real_table (id INTEGER);"\n',
            encoding="utf-8",
        )
        tables, _ = DdlParser().parse_csv(csv_path)
        assert [t.table_name for t in tables] == ["real_table"]

    def test_parse_csv_empty_file(self, tmp_path: Path):
        csv_path = tmp_path / "DDL.csv"
        csv_path.write_text("", encoding="utf-8")
        tables, relations = DdlParser().parse_csv(csv_path)
        assert tables == []
        assert relations == []

    def test_parse_csv_missing_file(self, tmp_path: Path):
        tables, relations = DdlParser().parse_csv(tmp_path / "nope.csv")
        assert tables == []
        assert relations == []

    def test_parse_csv_invalid_row_skipped(self, tmp_path: Path):
        csv_path = tmp_path / "DDL.csv"
        csv_path.write_text(
            "table_name,ddl\n"
            'bad_table,"CREATE TABLE bad_table (id INTEGER"\n'
            'good_table,"CREATE TABLE good_table (id INTEGER, name TEXT);"\n',
            encoding="utf-8",
        )
        tables, _ = DdlParser().parse_csv(csv_path)
        assert [t.table_name for t in tables] == ["good_table"]


# ---------------------------------------------------------------------------
# SchemaDocumentGenerator tests (DG-*)
# ---------------------------------------------------------------------------

class FakeLlmService:
    """Minimal fake LlmService for description generation tests."""

    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = 0

    async def send_request(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        from vanna.core.llm import LlmResponse

        return LlmResponse(content=self.content)


class TestSchemaDocumentGenerator:
    @pytest.mark.asyncio
    async def test_explicit_description_no_llm(self):
        tables, _ = make_sales_schema()
        llm = FakeLlmService(content='{"id": "primary key"}')
        generator = SchemaDocumentGenerator(llm_service=llm)

        docs = await generator.generate(tables)

        assert len(docs) == 6  # 3 + 3 columns
        amount_doc = next(
            d for d in docs if "total_amount" in d
        )
        assert "Total order amount" in amount_doc
        assert llm.calls == 0  # Explicit descriptions never trigger the LLM.

    @pytest.mark.asyncio
    async def test_llm_generates_missing_descriptions(self):
        tables, _ = make_sales_schema()
        llm = FakeLlmService(content='{"id": "primary key", "name": "customer name"}')
        generator = SchemaDocumentGenerator(
            llm_service=llm, llm_description_enabled=True
        )

        docs = await generator.generate(tables)

        assert llm.calls > 0
        name_doc = next(d for d in docs if "column name: name" in d)
        assert "customer name" in name_doc
        # Explicitly provided descriptions are preserved.
        amount_doc = next(d for d in docs if "total_amount" in d)
        assert "Total order amount" in amount_doc

    @pytest.mark.asyncio
    async def test_llm_failure_degrades(self):
        tables, _ = make_sales_schema()
        llm = FakeLlmService(error=RuntimeError("LLM down"))
        generator = SchemaDocumentGenerator(
            llm_service=llm, llm_description_enabled=True
        )

        docs = await generator.generate(tables)

        assert len(docs) == 6
        name_doc = next(d for d in docs if "column name: name" in d)
        assert "description: \n" in name_doc or name_doc.endswith("description: ")

    @pytest.mark.asyncio
    async def test_llm_disabled_degrades(self):
        tables, _ = make_sales_schema()
        llm = FakeLlmService(content='{"id": "primary key"}')
        generator = SchemaDocumentGenerator(
            llm_service=llm, llm_description_enabled=False
        )

        docs = await generator.generate(tables)
        assert llm.calls == 0
        assert len(docs) == 6

    @pytest.mark.asyncio
    async def test_document_format(self):
        tables, _ = make_sales_schema()
        generator = SchemaDocumentGenerator()

        pairs = await generator.generate_column_documents(tables)

        assert len(pairs) == 6
        column, text = pairs[0]
        assert column.column_name == "id"
        lines = text.split("\n")
        assert lines[0] == "column name: id"
        assert lines[1] == "column type: INTEGER"
        assert lines[2] == "table name: customers"
        assert lines[3] == "description: "


# ---------------------------------------------------------------------------
# FAISSSchemaVectorStore tests (SV-*)
# ---------------------------------------------------------------------------

class TestFAISSSchemaVectorStore:
    @pytest.mark.asyncio
    async def test_ingest_creates_index_and_metadata(self, tmp_path, embed_fn):
        tables, relations = make_sales_schema()
        store = FAISSSchemaVectorStore(
            persist_dir=str(tmp_path), embed_fn=embed_fn
        )

        await store.ingest_schema(tables, relations, database_name="sales_db")

        db_dir = tmp_path / "sales_db"
        assert (db_dir / "index.faiss").exists()
        metadata_file = db_dir / "metadata.json"
        assert metadata_file.exists()
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        assert len(metadata["columns"]) == 6
        assert len(metadata["embedding_texts"]) == 6
        assert len(metadata["relations"]) == 1
        assert metadata["relations"][0]["to_table"] == "customers"

    @pytest.mark.asyncio
    async def test_search_returns_relevant_columns(self, tmp_path, embed_fn):
        tables, relations = make_sales_schema()
        store = FAISSSchemaVectorStore(
            persist_dir=str(tmp_path), embed_fn=embed_fn
        )
        await store.ingest_schema(tables, relations, database_name="sales_db")

        results = await store.search(
            "customer email", database_name="sales_db", top_k=3
        )

        assert 0 < len(results) <= 3
        assert all(isinstance(r, SchemaSearchResult) for r in results)
        assert [r.rank for r in results] == list(range(1, len(results) + 1))
        top_columns = [r.column.column_name for r in results]
        assert "email" in top_columns

    @pytest.mark.asyncio
    async def test_persistence_across_instances(self, tmp_path, embed_fn):
        tables, relations = make_sales_schema()
        store1 = FAISSSchemaVectorStore(
            persist_dir=str(tmp_path), embed_fn=embed_fn
        )
        await store1.ingest_schema(tables, relations, database_name="sales_db")

        # Simulate a restart: new store instance, same persist dir.
        store2 = FAISSSchemaVectorStore(
            persist_dir=str(tmp_path), embed_fn=embed_fn
        )
        results = await store2.search(
            "customer email", database_name="sales_db"
        )
        assert len(results) > 0
        column = await store2.get_column_by_name(
            "customer_id", "orders", "sales_db"
        )
        assert column is not None

    @pytest.mark.asyncio
    async def test_multiple_databases_isolated(self, tmp_path, embed_fn):
        tables, relations = make_sales_schema()
        store = FAISSSchemaVectorStore(
            persist_dir=str(tmp_path), embed_fn=embed_fn
        )
        await store.ingest_schema(tables, relations, database_name="sales_db")

        other = SchemaTable(
            table_name="employees",
            database_name="hr_db",
            columns=[
                SchemaColumn(column_name="salary", table_name="employees", data_type="REAL")
            ],
        )
        await store.ingest_schema([other], [], database_name="hr_db")

        sales_results = await store.search("anything", database_name="sales_db")
        hr_results = await store.search("anything", database_name="hr_db")
        assert all(r.column.table_name != "employees" for r in sales_results)
        assert [r.column.table_name for r in hr_results] == ["employees"]

    @pytest.mark.asyncio
    async def test_empty_schema_ingest(self, tmp_path, embed_fn):
        store = FAISSSchemaVectorStore(
            persist_dir=str(tmp_path), embed_fn=embed_fn
        )
        await store.ingest_schema([], [], database_name="empty_db")

        results = await store.search("anything", database_name="empty_db")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_unknown_database(self, tmp_path, embed_fn):
        store = FAISSSchemaVectorStore(
            persist_dir=str(tmp_path), embed_fn=embed_fn
        )
        results = await store.search("anything", database_name="unknown_db")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_column_by_name(self, tmp_path, embed_fn):
        tables, relations = make_sales_schema()
        store = FAISSSchemaVectorStore(
            persist_dir=str(tmp_path), embed_fn=embed_fn
        )
        await store.ingest_schema(tables, relations, database_name="sales_db")

        column = await store.get_column_by_name("customer_id", "orders", "sales_db")
        assert column is not None
        assert column.data_type == "INTEGER"

        # Case-insensitive fallback.
        column_ci = await store.get_column_by_name(
            "Customer_Id", "ORDERS", "sales_db"
        )
        assert column_ci is not None

        assert await store.get_column_by_name("nope", "orders", "sales_db") is None

    @pytest.mark.asyncio
    async def test_get_relations(self, tmp_path, embed_fn):
        tables, relations = make_sales_schema()
        store = FAISSSchemaVectorStore(
            persist_dir=str(tmp_path), embed_fn=embed_fn
        )
        await store.ingest_schema(tables, relations, database_name="sales_db")

        found = await store.get_relations(["orders"], database_name="sales_db")
        assert len(found) == 1
        assert found[0].from_table == "orders"
        assert found[0].to_table == "customers"

        # Relation matches when only the target table is queried.
        found_reverse = await store.get_relations(
            ["customers"], database_name="sales_db"
        )
        assert len(found_reverse) == 1

        assert await store.get_relations(["other"], database_name="sales_db") == []

    @pytest.mark.asyncio
    async def test_duplicate_ingest_is_idempotent(self, tmp_path, embed_fn):
        tables, relations = make_sales_schema()
        store = FAISSSchemaVectorStore(
            persist_dir=str(tmp_path), embed_fn=embed_fn
        )
        await store.ingest_schema(tables, relations, database_name="sales_db")
        await store.ingest_schema(tables, relations, database_name="sales_db")

        results = await store.search("customer", database_name="sales_db", top_k=20)
        # 6 columns total, no duplication from re-ingest.
        assert len(results) == 6
        index = store._indexes["sales_db"]
        assert index.ntotal == 6

    @pytest.mark.asyncio
    async def test_implements_interface(self):
        assert issubclass(FAISSSchemaVectorStore, SchemaVectorStore)

    def test_embedding_model_path_preferred_over_name(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A local model path is loaded directly; no HuggingFace download."""

        class FakeSentenceTransformer:
            def __init__(self, model_ref):
                self.model_ref = model_ref

        monkeypatch.setattr(
            "sentence_transformers.SentenceTransformer", FakeSentenceTransformer
        )
        store = FAISSSchemaVectorStore(
            persist_dir="./schema_index",
            embedding_model="BAAI/bge-large-en-v1.5",
            embedding_model_path="/models/bge-local",
        )

        assert store._embedding_model_path == "/models/bge-local"
        store._get_embed_fn()  # triggers lazy SentenceTransformer loading
        loaded = store._model
        assert isinstance(loaded, FakeSentenceTransformer)
        assert loaded.model_ref == "/models/bge-local"

    def test_embedding_model_name_used_without_path(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Without a path, the default model name is used."""

        class FakeSentenceTransformer:
            def __init__(self, model_ref):
                self.model_ref = model_ref

        monkeypatch.setattr(
            "sentence_transformers.SentenceTransformer", FakeSentenceTransformer
        )
        store = FAISSSchemaVectorStore(
            persist_dir="./schema_index",
            embedding_model="BAAI/bge-large-en-v1.5",
        )

        assert store._embedding_model_path is None
        store._get_embed_fn()  # triggers lazy SentenceTransformer loading
        assert store._model.model_ref == "BAAI/bge-large-en-v1.5"


# ---------------------------------------------------------------------------
# Chroma backend tests (skipped when chromadb is unavailable)
# ---------------------------------------------------------------------------

chromadb = pytest.importorskip("chromadb", reason="chromadb is not installed")


class TestChromaSchemaVectorStore:
    @pytest.fixture
    def store(self, tmp_path, embed_fn):
        from vanna.integrations.vector.chroma import ChromaSchemaVectorStore

        return ChromaSchemaVectorStore(
            persist_dir=str(tmp_path / "chroma"), embed_fn=embed_fn
        )

    @pytest.mark.asyncio
    async def test_ingest_and_search(self, store):
        tables, relations = make_sales_schema()
        await store.ingest_schema(tables, relations, database_name="sales_db")

        results = await store.search("customer email", database_name="sales_db", top_k=3)
        assert 0 < len(results) <= 3
        assert "email" in [r.column.column_name for r in results]

    @pytest.mark.asyncio
    async def test_get_column_by_name_and_relations(self, store):
        tables, relations = make_sales_schema()
        await store.ingest_schema(tables, relations, database_name="sales_db")

        column = await store.get_column_by_name("customer_id", "orders", "sales_db")
        assert column is not None

        found = await store.get_relations(["orders"], database_name="sales_db")
        assert len(found) == 1
        assert found[0].to_table == "customers"

    @pytest.mark.asyncio
    async def test_empty_schema_ingest(self, store):
        await store.ingest_schema([], [], database_name="empty_db")
        assert await store.search("anything", database_name="empty_db") == []


# ---------------------------------------------------------------------------
# Multi-backend interface consistency (SV-009 / SV-010)
# ---------------------------------------------------------------------------

class TestBackendConsistency:
    @pytest.mark.asyncio
    async def test_faiss_and_chroma_same_interface_semantics(self, tmp_path, embed_fn):
        """Same data + same embed_fn => both backends retrieve the same columns."""
        from vanna.integrations.vector.chroma import ChromaSchemaVectorStore

        tables, relations = make_sales_schema()

        faiss_store = FAISSSchemaVectorStore(
            persist_dir=str(tmp_path / "faiss"), embed_fn=embed_fn
        )
        chroma_store = ChromaSchemaVectorStore(
            persist_dir=str(tmp_path / "chroma"), embed_fn=embed_fn
        )

        for store in (faiss_store, chroma_store):
            await store.ingest_schema(tables, relations, database_name="sales_db")

        for query in ("customer email", "order total amount"):
            faiss_results = await faiss_store.search(
                query, database_name="sales_db", top_k=6
            )
            chroma_results = await chroma_store.search(
                query, database_name="sales_db", top_k=6
            )
            faiss_keys = {
                (r.column.table_name, r.column.column_name) for r in faiss_results
            }
            chroma_keys = {
                (r.column.table_name, r.column.column_name) for r in chroma_results
            }
            assert faiss_keys == chroma_keys

    @pytest.mark.asyncio
    async def test_milvus_qdrant_skeletons_raise(self):
        from vanna.integrations.vector.milvus import MilvusSchemaVectorStore
        from vanna.integrations.vector.qdrant import QdrantSchemaVectorStore

        for cls in (MilvusSchemaVectorStore, QdrantSchemaVectorStore):
            store = cls()
            assert isinstance(store, SchemaVectorStore)
            with pytest.raises(NotImplementedError):
                await store.search("q", database_name="db")
