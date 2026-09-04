import pytest

from vanna.core.user import CookieEmailUserResolver
from vanna.core.user.request_context import RequestContext


def make_context(cookies=None):
    return RequestContext(cookies=cookies or {}, headers={}, query_params={})


@pytest.mark.asyncio
async def test_resolves_email_from_cookie():
    resolver = CookieEmailUserResolver(cookie_name="chatbot_email")
    user = await resolver.resolve_user(
        make_context({"chatbot_email": "admin@corp.com"})
    )
    assert user.email == "admin@corp.com"
    assert user.id == "admin@corp.com"


@pytest.mark.asyncio
async def test_anonymous_when_cookie_missing():
    resolver = CookieEmailUserResolver(cookie_name="chatbot_email")
    user = await resolver.resolve_user(make_context({}))
    assert user.email is None
    assert user.id == "anonymous"


@pytest.mark.asyncio
async def test_uses_custom_cookie_name():
    resolver = CookieEmailUserResolver(cookie_name="vanna_email")
    user = await resolver.resolve_user(make_context({"vanna_email": "u@x.com"}))
    assert user.email == "u@x.com"
