from types import SimpleNamespace

from fastapi.testclient import TestClient

from vanna.core.user import CookieEmailUserResolver
from vanna.integrations.local import SQLiteConversationStore
from vanna.servers.fastapi.app import VannaFastAPIServer


class FakeBusiness:
    def effective_database_name(self):
        return "ns_a"


class FakeAgent:
    def __init__(self):
        self.user_resolver = CookieEmailUserResolver()
        self.schema_vector_store = None
        self.config = SimpleNamespace(businesses={"biz_a": FakeBusiness()})
        self.conversation_store = SQLiteConversationStore(db_path=":memory:")
        self._business_sql_runners = {}


def _admin_client():
    server = VannaFastAPIServer(
        agent=FakeAgent(),
        config={"admin_emails": ["admin@corp.com"]},
    )
    client = TestClient(server.create_app())
    client.cookies.set("chatbot_email", "admin@corp.com")
    return client


def test_new_routes_registered():
    server = VannaFastAPIServer(
        agent=FakeAgent(),
        config={"admin_emails": ["admin@corp.com"]},
    )
    client = TestClient(server.create_app())
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/conversations").status_code == 200
    body = client.get("/api/auth/me").json()
    assert body["businesses"] == ["biz_a"]


def test_schema_tables_requires_business_id():
    server = VannaFastAPIServer(
        agent=FakeAgent(),
        config={"admin_emails": ["admin@corp.com"]},
    )
    client = TestClient(server.create_app())
    client.cookies.set("chatbot_email", "admin@corp.com")
    assert client.get("/api/schema/tables").status_code == 422


# ---------- 创建业务：结构化 database 字段 ----------


def test_create_business_stores_structured_sqlite(tmp_path, monkeypatch):
    """结构化字段落 app.json，不再存拼接好的 url。"""
    cfg_path = tmp_path / "app.json"
    cfg_path.write_text('{"storage": {"businesses": []}}', encoding="utf-8")
    monkeypatch.setenv("APP_CONFIG_PATH", str(cfg_path))

    resp = _admin_client().post(
        "/api/businesses",
        json={
            "id": "shop",
            "database": {"type": "sqlite", "path": "data/db/shop.db"},
            "namespace": "shop",
        },
    )
    assert resp.status_code == 200
    stored = resp.json()["database"]
    assert stored == {"type": "sqlite", "path": "data/db/shop.db"}
    assert "url" not in stored


def test_create_business_stores_structured_server_fields(tmp_path, monkeypatch):
    cfg_path = tmp_path / "app.json"
    cfg_path.write_text('{"storage": {"businesses": []}}', encoding="utf-8")
    monkeypatch.setenv("APP_CONFIG_PATH", str(cfg_path))

    resp = _admin_client().post(
        "/api/businesses",
        json={
            "id": "pg",
            "database": {
                "type": "postgresql",
                "host": "db.internal",
                "port": 5432,
                "user": "u",
                "password": "p",
                "database": "shop",
            },
            "namespace": "pg",
        },
    )
    assert resp.status_code == 200
    stored = resp.json()["database"]
    assert stored["type"] == "postgresql"
    assert stored["host"] == "db.internal"
    assert stored["password"] == "p"


def test_create_business_rejects_unsupported_type(tmp_path, monkeypatch):
    cfg_path = tmp_path / "app.json"
    cfg_path.write_text('{"storage": {"businesses": []}}', encoding="utf-8")
    monkeypatch.setenv("APP_CONFIG_PATH", str(cfg_path))

    resp = _admin_client().post(
        "/api/businesses",
        json={
            "id": "weird",
            "database": {"type": "snowflake", "host": "h"},
            "namespace": "weird",
        },
    )
    assert resp.status_code == 400
    assert "unsupported" in resp.json()["detail"]


def test_create_business_rejects_duplicate_id(tmp_path, monkeypatch):
    cfg_path = tmp_path / "app.json"
    cfg_path.write_text('{"storage": {"businesses": []}}', encoding="utf-8")
    monkeypatch.setenv("APP_CONFIG_PATH", str(cfg_path))

    client = _admin_client()
    payload = {
        "id": "dup",
        "database": {"type": "sqlite", "path": "a.db"},
        "namespace": "dup",
    }
    assert client.post("/api/businesses", json=payload).status_code == 200
    assert client.post("/api/businesses", json=payload).status_code == 409
