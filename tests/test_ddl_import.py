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


GOOD_CSV = (
    "table_name,ddl\n"
    'orders,"CREATE TABLE orders (\n'
    "    id INTEGER PRIMARY KEY,\n"
    "    customer_id INTEGER,\n"
    '    FOREIGN KEY (customer_id) REFERENCES customers(id)\n'
    ')"\n'
    'customers,"CREATE TABLE customers (\n'
    "    id INTEGER PRIMARY KEY,\n"
    '    name VARCHAR(100)\n'
    ')"\n'
)


def test_parse_success_returns_preview():
    client = make_client()
    response = client.post(
        "/api/vanna/v1/ddl/parse",
        files={"file": ("DDL.csv", io.BytesIO(GOOD_CSV.encode("utf-8")), "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tables_count"] == 2
    assert data["columns_count"] == 4  # orders: id, customer_id; customers: id, name
    assert data["relations_count"] == 1
    assert data["database_name"] == "default"
    assert data["parse_id"]
    assert data["warnings"] == []
    assert {t["table_name"] for t in data["tables"]} == {"orders", "customers"}
    orders = next(t for t in data["tables"] if t["table_name"] == "orders")
    assert [c["column_name"] for c in orders["columns"]] == ["id", "customer_id"]


def test_parse_empty_csv_returns_400():
    client = make_client()
    response = client.post(
        "/api/vanna/v1/ddl/parse",
        files={"file": ("DDL.csv", io.BytesIO(b""), "text/csv")},
    )
    assert response.status_code == 400
    assert "table" in response.json()["detail"].lower()


def test_parse_unknown_encoding_or_path_never_crashes():
    # 由 parse_csv 兜底：不存在的路径不会发生（我们落盘了）；此用例验证坏行警告。
    bad_csv = (
        "table_name,ddl\n"
        'bad_table,"CREATE TABLE bad_table (id INTEGER"\n'
        'good_table,"CREATE TABLE good_table (id INTEGER, name TEXT);"\n'
    )
    client = make_client()
    response = client.post(
        "/api/vanna/v1/ddl/parse",
        files={"file": ("DDL.csv", io.BytesIO(bad_csv.encode("utf-8")), "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tables_count"] == 1
    assert data["tables"][0]["table_name"] == "good_table"
    assert "bad_table" in data["warnings"]


def test_parse_missing_file_returns_422():
    client = make_client()
    response = client.post("/api/vanna/v1/ddl/parse")
    assert response.status_code == 422


def test_parse_non_utf8_returns_415():
    client = make_client()
    response = client.post(
        "/api/vanna/v1/ddl/parse",
        files={"file": ("DDL.csv", io.BytesIO(b"\xff\xfe\x00\x00not utf8"), "text/csv")},
    )
    assert response.status_code == 415
    assert "utf-8" in response.json()["detail"].lower()


def _parse_then(client, csv_text=GOOD_CSV):
    """Parse the staged CSV and return (parse_id, preview_data)."""
    response = client.post(
        "/api/vanna/v1/ddl/parse",
        files={"file": ("DDL.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
    )
    data = response.json()
    return data["parse_id"], data


def test_page_contains_interaction_elements():
    html = make_client().get("/ddl-import").text
    for marker in (
        "id=\"ddl-file\"",
        "id=\"database-name\"",
        "id=\"parse-btn\"",
        "id=\"ingest-btn\"",
        "id=\"preview\"",
        "id=\"result\"",
        "/api/vanna/v1/ddl/parse",
        "/api/vanna/v1/ddl/ingest",
        "fetch(",
        "parse_id",
    ):
        assert marker in html, f"missing {marker}"


def test_ingest_success_writes_to_store():
    store = FakeStore()
    client = make_client(FakeAgent(schema_vector_store=store))
    parse_id, _ = _parse_then(client)
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "database_name": "chinook"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["database_name"] == "chinook"
    assert data["tables_count"] == 2
    assert data["relations_count"] == 1
    assert len(store.ingested) == 1
    ingested = store.ingested[0]
    assert ingested["database_name"] == "chinook"
    assert {t.table_name for t in ingested["tables"]} == {"orders", "customers"}


def test_ingest_unknown_parse_id_returns_400():
    client = make_client()
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": "nope", "database_name": "default"},
    )
    assert response.status_code == 400


def test_ingest_without_store_returns_503():
    client = make_client(FakeAgent(schema_vector_store=None))
    parse_id, _ = _parse_then(client)
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "database_name": "default"},
    )
    assert response.status_code == 503
    assert "vector" in response.json()["detail"].lower()


def test_ingest_consumes_parse_id():
    store = FakeStore()
    client = make_client(FakeAgent(schema_vector_store=store))
    parse_id, _ = _parse_then(client)
    assert client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "database_name": "default"},
    ).status_code == 200
    second = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "database_name": "default"},
    )
    assert second.status_code == 400  # already consumed


def test_page_served_via_vanna_server():
    """The page must be reachable through VannaFastAPIServer.create_app()."""
    from vanna.servers.fastapi.app import VannaFastAPIServer

    agent = FakeAgent(schema_vector_store=FakeStore())
    server = VannaFastAPIServer(agent=agent)
    app = server.create_app()
    client = TestClient(app)
    response = client.get("/ddl-import")
    assert response.status_code == 200
    assert "DDL" in response.text