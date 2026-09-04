"""Cookie-based email user resolver for the built-in web UI."""

from typing import Optional
from urllib.parse import unquote

from .models import User
from .request_context import RequestContext
from .resolver import UserResolver


class CookieEmailUserResolver(UserResolver):
    """Resolves a user from an email stored in a request cookie.

    Used by the built-in FastAPI web UI: the login page writes the chosen
    email into a cookie, and this resolver turns it into a ``User``. When
    the cookie is absent an anonymous ``User`` is returned (email=None).
    """

    def __init__(self, cookie_name: str = "chatbot_email"):
        self.cookie_name = cookie_name

    async def resolve_user(self, request_context: RequestContext) -> User:
        email = request_context.get_cookie(self.cookie_name)
        email = unquote(email or "").strip() or None
        if email is None:
            return User(id="anonymous", username="anonymous", email=None)
        return User(id=email, username=email.split("@")[0], email=email)
