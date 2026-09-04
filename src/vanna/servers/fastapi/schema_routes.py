"""FastAPI routes for the built-in web UI schema management (admin only).

Namespace resolution follows the same no-fallback rule as DDL ingest:
business_id is required and must match an enabled business; the vector
namespace comes from the business configuration.
"""

from fastapi import FastAPI, HTTPException, Query, Request

from .auth import is_admin_email, resolve_user


def _resolve_business_namespace(agent, business_id: str) -> str:
    """Resolve the schema namespace for a business id (no fallback).

    Mirrors ``ddl_import._resolve_business_namespace``: raises 400 listing
    available businesses when the id is unknown or disabled.
    """
    businesses = getattr(getattr(agent, "config", None), "businesses", {}) or {}
    business = businesses.get(business_id)
    if business is None:
        available = ", ".join(sorted(businesses)) or "none"
        raise HTTPException(
            status_code=400,
            detail=(
                f"business_id '{business_id}' not found or disabled; "
                f"available: {available}"
            ),
        )
    return business.effective_database_name()


def register_schema_routes(app: FastAPI, agent, admin_emails=None) -> None:
    store = agent.schema_vector_store
    admin_emails = admin_emails or []

    def _guard(user) -> None:
        if not is_admin_email(user.email, admin_emails):
            raise HTTPException(status_code=403, detail="Admin access required")

    @app.get("/api/schema/tables")
    async def list_schema_tables(
        http_request: Request,
        business_id: str = Query(..., description="Target business id"),
    ):
        user = await resolve_user(agent, http_request)
        _guard(user)
        if store is None:
            raise HTTPException(status_code=503, detail="No schema vector store configured")
        namespace = _resolve_business_namespace(agent, business_id)
        tables = await store.list_tables(namespace)
        return {"business_id": business_id, "namespace": namespace, "tables": tables}

    @app.delete("/api/schema/tables/{table_name}")
    async def remove_schema_table(
        table_name: str,
        http_request: Request,
        business_id: str = Query(..., description="Target business id"),
    ):
        user = await resolve_user(agent, http_request)
        _guard(user)
        if store is None:
            raise HTTPException(status_code=503, detail="No schema vector store configured")
        namespace = _resolve_business_namespace(agent, business_id)
        try:
            removed = await store.remove_table(table_name, namespace)
        except NotImplementedError:
            raise HTTPException(status_code=501, detail="Backend does not support table removal")
        return {"removed_columns": removed, "table_name": table_name, "namespace": namespace}
