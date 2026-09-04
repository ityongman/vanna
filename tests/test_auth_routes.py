from fastapi import FastAPI
from fastapi.testclient import TestClient

from vanna.core.user import CookieEmailUserResolver
from vanna.servers.fastapi.auth_routes import register_auth_routes


class FakeAgent:
    def __init__(self, resolver=None, businesses=None):
        self.user_resolver = resolver or CookieEmailUserResolver()
        self.config = type("C", (), {"businesses": businesses or {}})()


def make_client(admin_emails=("admin@corp.com",), businesses=None):
    app = FastAPI()
    register_auth_routes(
        app, FakeAgent(businesses=businesses), admin_emails=list(admin_emails)
    )
    return TestClient(app)


def test_auth_me_returns_admin_for_whitelisted_email():
    client = make_client(admin_emails=["admin@corp.com"])
    client.cookies.set("chatbot_email", "admin@corp.com")
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "admin@corp.com"
    assert body["is_admin"] is True


def test_auth_me_returns_non_admin_for_other_email():
    client = make_client(admin_emails=["admin@corp.com"])
    client.cookies.set("chatbot_email", "user@corp.com")
    body = client.get("/api/auth/me").json()
    assert body["is_admin"] is False


def test_auth_me_anonymous_when_no_cookie():
    client = make_client(admin_emails=["admin@corp.com"])
    body = client.get("/api/auth/me").json()
    assert body["email"] is None
    assert body["is_admin"] is False


def test_auth_me_exposes_enabled_businesses():
    client = make_client(businesses={"biz_a": object(), "biz_b": object()})
    body = client.get("/api/auth/me").json()
    assert sorted(body["businesses"]) == ["biz_a", "biz_b"]
