from fastapi import FastAPI
from fastapi.testclient import TestClient

from vanna.core.user import CookieEmailUserResolver
from vanna.servers.fastapi.schema_routes import register_schema_routes


class FakeStore:
    def __init__(self):
        self.tables = ["equipment", "sensors"]

    async def list_tables(self, namespace):
        return self.tables

    async def remove_table(self, table_name, namespace):
        self.tables = [t for t in self.tables if t != table_name]
        return 1


class FakeBusiness:
    def __init__(self, namespace):
        self._ns = namespace

    def effective_database_name(self):
        return self._ns


class FakeAgent:
    def __init__(self):
        self.user_resolver = CookieEmailUserResolver()
        self.schema_vector_store = FakeStore()
        self.config = type(
            "C", (), {"businesses": {"biz_a": FakeBusiness("ns_a")}}
        )()


def make_client(admin_emails=("admin@corp.com",)):
    app = FastAPI()
    register_schema_routes(app, FakeAgent(), admin_emails=list(admin_emails))
    return TestClient(app)


def test_list_tables_requires_admin():
    client = make_client()
    client.cookies.set("chatbot_email", "user@corp.com")
    resp = client.get("/api/schema/tables", params={"business_id": "biz_a"})
    assert resp.status_code == 403


def test_list_tables_requires_business_id():
    client = make_client()
    client.cookies.set("chatbot_email", "admin@corp.com")
    resp = client.get("/api/schema/tables")
    assert resp.status_code == 422  # FastAPI validation error for missing required param


def test_list_tables_unknown_business_returns_400():
    client = make_client()
    client.cookies.set("chatbot_email", "admin@corp.com")
    resp = client.get("/api/schema/tables", params={"business_id": "nope"})
    assert resp.status_code == 400
    assert "biz_a" in resp.json()["detail"]


def test_list_tables_as_admin():
    client = make_client()
    client.cookies.set("chatbot_email", "admin@corp.com")
    resp = client.get("/api/schema/tables", params={"business_id": "biz_a"})
    assert resp.status_code == 200
    assert resp.json()["namespace"] == "ns_a"
    assert resp.json()["tables"] == ["equipment", "sensors"]


def test_remove_table_as_admin():
    client = make_client()
    client.cookies.set("chatbot_email", "admin@corp.com")
    resp = client.delete(
        "/api/schema/tables/equipment", params={"business_id": "biz_a"}
    )
    assert resp.status_code == 200
    resp2 = client.get("/api/schema/tables", params={"business_id": "biz_a"})
    assert resp2.json()["tables"] == ["sensors"]
