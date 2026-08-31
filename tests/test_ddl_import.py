"""Tests for the DDL import page (parse/ingest into schema vector store)."""
import io
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vanna.capabilities.schema_vector_store.base import SchemaVectorStore
from vanna.servers.fastapi.ddl_import import register_ddl_import_routes


class FakeStore(SchemaVectorStore):
    """Records ingest calls; no real vector backend needed."""

    def __init__(self):
        self.ingested = []

    async def ingest_schema(self, tables, relations, database_name):
        self.ingested.append(
            {"tables": tables, "relations": relations, "database_name": database_name}
        )

    async def search(self, query, database_name, top_k=20):
        return []

    async def get_column_by_name(self, column_name, table_name, database_name):
        return None

    async def get_relations(self, table_names, database_name):
        return []


class FakeAgent:
    def __init__(self, schema_vector_store=None):
        self.schema_vector_store = schema_vector_store


def make_client(agent=None):
    app = FastAPI()
    register_ddl_import_routes(app, agent or FakeAgent(FakeStore()))
    return TestClient(app)


def test_page_served():
    response = make_client().get("/ddl-import")
    assert response.status_code == 200
    assert "DDL" in response.text
    assert "database_name" in response.text