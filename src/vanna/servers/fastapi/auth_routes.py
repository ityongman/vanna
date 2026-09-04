"""FastAPI routes for the built-in web UI authentication."""

from typing import List

from fastapi import FastAPI, Request

from .auth import is_admin_email, resolve_user


def register_auth_routes(
    app: FastAPI, agent, admin_emails: List[str] | None = None
) -> None:
    admin_emails = admin_emails or []

    @app.get("/api/auth/me")
    async def auth_me(http_request: Request):
        user = await resolve_user(agent, http_request)
        businesses = list(getattr(agent.config, "businesses", {}) or {})
        return {
            "id": user.id,
            "email": user.email,
            "is_admin": is_admin_email(user.email, admin_emails),
            "businesses": businesses,
        }
