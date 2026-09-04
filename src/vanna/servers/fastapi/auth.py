"""Auth helpers shared by the built-in FastAPI web UI routes."""

from typing import List, Optional

from fastapi import Request

from ...core.user import RequestContext, User


def is_admin_email(email: Optional[str], admin_emails: List[str]) -> bool:
    """Check an email against the app.json ``server.admin_emails`` list."""
    return bool(email and email in admin_emails)


def build_request_context(http_request: Request) -> RequestContext:
    return RequestContext(
        cookies=dict(http_request.cookies),
        headers=dict(http_request.headers),
        remote_addr=http_request.client.host if http_request.client else None,
        query_params=dict(http_request.query_params),
    )


async def resolve_user(agent, http_request: Request) -> User:
    return await agent.user_resolver.resolve_user(build_request_context(http_request))
