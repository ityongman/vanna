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
