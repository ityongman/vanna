import tempfile
from types import SimpleNamespace

from fastapi.testclient import TestClient

from vanna.core.user import CookieEmailUserResolver
from vanna.integrations.local import SQLiteConversationStore
from vanna.servers.fastapi.app import VannaFastAPIServer


class FakeAgent:
    def __init__(self):
        self.user_resolver = CookieEmailUserResolver()
        self.schema_vector_store = None
        self.conversation_store = SQLiteConversationStore(db_path=":memory:")
        self.config = SimpleNamespace(businesses={})


def test_serves_spa_for_client_routes(tmp_path):
    (tmp_path / "index.html").write_text("SPA", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    server = VannaFastAPIServer(agent=FakeAgent(), config={"web_dist": str(tmp_path)})
    client = TestClient(server.create_app())
    # Client-side routes like /login should serve index.html
    resp = client.get("/login")
    assert resp.status_code == 200
    assert resp.text == "SPA"
    # Deep links should also serve index.html
    resp = client.get("/equipment_decay/chat")
    assert resp.status_code == 200
    assert resp.text == "SPA"


def test_fallback_to_templates_when_dist_missing():
    server = VannaFastAPIServer(
        agent=FakeAgent(),
        config={"web_dist": tempfile.mkdtemp() + "/no-dist"},
    )
    client = TestClient(server.create_app())
    # / falls through to existing templates.py page
    assert client.get("/").status_code == 200
