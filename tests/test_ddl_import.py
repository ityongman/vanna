"""Tests for the DDL import page (parse/ingest into schema vector store)."""
import io
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vanna.capabilities.schema_vector_store.base import SchemaVectorStore
from vanna.core.agent.config import BusinessConfig
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


class IndexedStore(FakeStore):
    """FakeStore with a per-namespace table index backing list_tables."""

    def __init__(self, index=None):
        super().__init__()
        self.index = index or {}

    async def list_tables(self, namespace):
        from vanna.capabilities.schema_vector_store.models import SchemaTable

        return [
            SchemaTable(table_name=name, database_name=namespace, columns=[])
            for name in self.index.get(namespace, [])
        ]


def _business(business_id="biz_a", namespace="ns_a"):
    return BusinessConfig(
        id=business_id,
        database={"url": "sqlite:///a.db"},
        schema_vector={"namespace": namespace},
    )


class FakeAgent:
    def __init__(self, schema_vector_store=None, businesses=None):
        self.schema_vector_store = schema_vector_store
        # VannaFastAPIServer.create_app() 注册 conversation 路由时需要该属性
        self.conversation_store = None
        self.config = SimpleNamespace(
            businesses=businesses if businesses is not None else {"biz_a": _business()}
        )


def make_client(agent=None):
    app = FastAPI()
    register_ddl_import_routes(app, agent or FakeAgent(FakeStore()))
    return TestClient(app)


def test_page_served():
    response = make_client().get("/ddl-import")
    assert response.status_code == 200
    assert "DDL" in response.text
    assert "business-select" in response.text


GOOD_CSV = (
    "db_name,table_name,ddl\n"
    'mydb,orders,"CREATE TABLE orders (\n'
    "    id INTEGER PRIMARY KEY,\n"
    "    customer_id INTEGER,\n"
    '    FOREIGN KEY (customer_id) REFERENCES customers(id)\n'
    ')"\n'
    'mydb,customers,"CREATE TABLE customers (\n'
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
    assert data["db_name"] == "mydb"
    assert data["tables_count"] == 2
    assert data["columns_count"] == 4  # orders: id, customer_id; customers: id, name
    assert data["relations_count"] == 1
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
        "db_name,table_name,ddl\n"
        'mydb,bad_table,"CREATE TABLE bad_table (id INTEGER"\n'
        'mydb,good_table,"CREATE TABLE good_table (id INTEGER, name TEXT);"\n'
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
        "id=\"business-select\"",
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
        json={"parse_id": parse_id, "business_id": "biz_a"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["database_name"] == "ns_a"
    assert data["tables_count"] == 2
    assert data["relations_count"] == 1
    assert len(store.ingested) == 1
    ingested = store.ingested[0]
    assert ingested["database_name"] == "ns_a"
    assert {t.table_name for t in ingested["tables"]} == {"orders", "customers"}


def test_ingest_unknown_business_returns_400():
    """未知业务必须拒绝写入（无兜底路由）。"""
    store = FakeStore()
    client = make_client(FakeAgent(schema_vector_store=store))
    parse_id, _ = _parse_then(client)
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "business_id": "nope"},
    )
    assert response.status_code == 400
    assert "not found or disabled" in response.json()["detail"]
    assert store.ingested == []  # nothing was written


def test_ingest_missing_business_id_is_rejected():
    """business_id 缺失时请求体校验失败（必填）。"""
    client = make_client()
    parse_id, _ = _parse_then(client)
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id},
    )
    assert response.status_code == 422


def test_ingest_unknown_parse_id_returns_400():
    client = make_client()
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": "nope", "business_id": "biz_a"},
    )
    assert response.status_code == 400


def test_ingest_without_store_returns_503():
    client = make_client(FakeAgent(schema_vector_store=None))
    parse_id, _ = _parse_then(client)
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "business_id": "biz_a"},
    )
    assert response.status_code == 503
    assert "vector" in response.json()["detail"].lower()


def test_ingest_consumes_parse_id():
    store = FakeStore()
    client = make_client(FakeAgent(schema_vector_store=store))
    parse_id, _ = _parse_then(client)
    assert client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "business_id": "biz_a"},
    ).status_code == 200
    second = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "business_id": "biz_a"},
    )
    assert second.status_code == 400  # already consumed


def test_page_lists_businesses_with_namespaces():
    """页面下拉框应列出可用业务及其 namespace。"""
    html = make_client(
        FakeAgent(
            FakeStore(),
            businesses={
                "biz_a": _business("biz_a", "ns_a"),
                "biz_b": _business("biz_b", "ns_b"),
            },
        )
    ).get("/ddl-import").text
    assert 'value="biz_a"' in html
    assert 'data-ns="ns_a"' in html
    assert 'value="biz_b"' in html
    assert 'data-ns="ns_b"' in html
    assert "默认（不路由）" not in html


def test_page_without_businesses_shows_placeholder():
    html = make_client(
        FakeAgent(FakeStore(), businesses={})
    ).get("/ddl-import").text
    assert "无可用业务" in html


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


# ---------- CSV 严格校验（db_name/table_name/ddl 三列 + 空值） ----------

MISSING_DB_NAME_CSV = 'table_name,ddl\norders,"CREATE TABLE orders (id INTEGER)"\n'
MISSING_TABLE_NAME_CSV = 'db_name,ddl\nmydb,"CREATE TABLE orders (id INTEGER)"\n'
MISSING_DDL_CSV = "db_name,table_name\nmydb,orders\n"
EMPTY_DDL_CSV = (
    "db_name,table_name,ddl\n"
    'mydb,orders,"CREATE TABLE orders (id INTEGER)"\n'
    "mydb,customers,\n"
)
MULTI_DB_CSV = (
    "db_name,table_name,ddl\n"
    'mydb,orders,"CREATE TABLE orders (id INTEGER)"\n'
    'otherdb,customers,"CREATE TABLE customers (id INTEGER)"\n'
)


def _post_parse(client, csv_text):
    return client.post(
        "/api/vanna/v1/ddl/parse",
        files={"file": ("DDL.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
    )


def _tmp_app_config(tmp_path, monkeypatch, config=None):
    """把 APP_CONFIG_PATH 指向临时 app.json，隔离对仓库真实配置文件的读写。"""
    cfg_path = tmp_path / "app.json"
    cfg_path.write_text(json.dumps(config or {}), encoding="utf-8")
    monkeypatch.setenv("APP_CONFIG_PATH", str(cfg_path))
    return cfg_path


@pytest.mark.parametrize(
    "csv_text,missing_col",
    [
        (MISSING_DB_NAME_CSV, "db_name"),
        (MISSING_TABLE_NAME_CSV, "table_name"),
        (MISSING_DDL_CSV, "ddl"),
    ],
)
def test_parse_missing_required_column_returns_400(csv_text, missing_col):
    client = make_client()
    response = _post_parse(client, csv_text)
    assert response.status_code == 400
    assert missing_col in response.json()["detail"]


def test_parse_empty_ddl_row_returns_400():
    client = make_client()
    response = _post_parse(client, EMPTY_DDL_CSV)
    assert response.status_code == 400
    assert "第 3 行 ddl 为空" in response.json()["detail"]


def test_parse_multiple_db_names_returns_400():
    client = make_client()
    response = _post_parse(client, MULTI_DB_CSV)
    assert response.status_code == 400
    assert "多个不同的 db_name" in response.json()["detail"]


# ---------- 业务配置状态判断（active / disabled / missing） ----------


def test_parse_reports_business_state_active(monkeypatch, tmp_path):
    store = FakeStore()
    agent = FakeAgent(
        schema_vector_store=store,
        businesses={"mydb": _business("mydb", "ns_mydb")},
    )
    client = make_client(agent)
    _tmp_app_config(tmp_path, monkeypatch)
    data = _post_parse(client, GOOD_CSV).json()
    assert data["db_name"] == "mydb"
    assert data["business_state"] == "active"
    assert data["business_id"] == "mydb"


def test_parse_reports_business_state_missing(monkeypatch, tmp_path):
    client = make_client()  # agent 只配置了 biz_a
    _tmp_app_config(tmp_path, monkeypatch)
    data = _post_parse(client, GOOD_CSV).json()
    assert data["business_state"] == "missing"


def test_parse_reports_business_state_disabled_from_app_json(monkeypatch, tmp_path):
    cfg = {
        "storage": {
            "businesses": [
                {
                    "id": "mydb",
                    "enabled": False,
                    "database": {"url": "sqlite:///data/db/mydb.db"},
                    "schema_vector": {"namespace": "ns_mydb", "backend": None},
                }
            ]
        }
    }
    client = make_client()  # mydb 未加载进 agent
    _tmp_app_config(tmp_path, monkeypatch, cfg)
    data = _post_parse(client, GOOD_CSV).json()
    assert data["business_state"] == "disabled"


# ---------- insert_update 增量合并 ----------


def test_ingest_merges_into_existing_namespace():
    store = IndexedStore({"ns_a": ["legacy", "orders"]})
    client = make_client(
        FakeAgent(
            schema_vector_store=store,
            businesses={"biz_a": _business("biz_a", "ns_a")},
        )
    )
    parse_id, _ = _parse_then(client)
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "business_id": "biz_a"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["added_tables"] == ["customers"]
    assert data["updated_tables"] == ["orders"]
    assert data["kept_tables"] == ["legacy"]
    assert data["merge_warning"] is None
    ingested_names = {t.table_name for t in store.ingested[-1]["tables"]}
    assert ingested_names == {"orders", "customers", "legacy"}


def test_ingest_merge_fallback_when_list_tables_unsupported():
    store = FakeStore()  # 未实现 list_tables（基类抛 NotImplementedError）
    client = make_client(FakeAgent(schema_vector_store=store))
    parse_id, _ = _parse_then(client)
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "business_id": "biz_a"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["added_tables"] == ["customers", "orders"]
    assert data["updated_tables"] == []
    assert data["merge_warning"]


# ---------- enabled 流转与 app.json 兜底 ----------


def test_enable_after_ingest(monkeypatch, tmp_path):
    cfg = {
        "storage": {
            "businesses": [
                {
                    "id": "biz_a",
                    "enabled": False,
                    "database": {"url": "sqlite:///data/db/a.db"},
                    "schema_vector": {"namespace": "ns_a", "backend": None},
                }
            ]
        }
    }
    cfg_path = _tmp_app_config(tmp_path, monkeypatch, cfg)
    store = FakeStore()
    client = make_client(
        FakeAgent(
            schema_vector_store=store,
            businesses={"biz_a": _business("biz_a", "ns_a")},
        )
    )
    parse_id, _ = _parse_then(client)
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "business_id": "biz_a"},
    )
    assert response.status_code == 200
    saved = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert saved["storage"]["businesses"][0]["enabled"] is True


def test_namespace_fallback_to_app_json_for_disabled_business(
    monkeypatch, tmp_path
):
    cfg = {
        "storage": {
            "businesses": [
                {
                    "id": "other_biz",
                    "enabled": False,
                    "database": {"url": "sqlite:///data/db/other.db"},
                    "schema_vector": {"namespace": "ns_other", "backend": None},
                }
            ]
        }
    }
    _tmp_app_config(tmp_path, monkeypatch, cfg)
    client = make_client(FakeAgent(schema_vector_store=FakeStore()))
    parse_id, _ = _parse_then(client)
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "business_id": "other_biz"},
    )
    assert response.status_code == 200
    assert response.json()["database_name"] == "ns_other"
