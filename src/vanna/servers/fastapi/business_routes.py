"""FastAPI routes for business management (admin only).

Provides endpoints to list, create, and enable/disable business
configurations. Changes are persisted to app.json and hot-reloaded
into the running agent.
"""

from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .auth import is_admin_email, resolve_user
from .config_sync import (
    get_businesses_from_config,
    load_app_config,
    save_app_config,
    sync_agent_businesses,
)


class CreateBusinessRequest(BaseModel):
    """Request to create a new business configuration."""

    id: str = Field(description="Business identifier")
    database_url: str = Field(description="Database URL (e.g., sqlite:///data/db/xxx.db)")
    namespace: str = Field(description="Schema vector namespace")


class EnableBusinessRequest(BaseModel):
    """Request to enable/disable a business."""

    enabled: bool = Field(description="Whether to enable or disable the business")


def _update_business_in_config(
    config: Dict[str, Any], business_id: str, updates: Dict[str, Any]
) -> Dict[str, Any]:
    """Update a business in the config. Returns updated config."""
    storage = config.setdefault("storage", {})
    businesses = storage.setdefault("businesses", [])

    for biz in businesses:
        if biz.get("id") == business_id:
            biz.update(updates)
            return config

    # Not found, add new
    businesses.append({"id": business_id, **updates})
    return config


def register_business_routes(
    app: FastAPI, agent, admin_emails: List[str] | None = None
) -> None:
    """Register business management routes."""
    admin_emails = admin_emails or []

    def _guard(user) -> None:
        if not is_admin_email(user.email, admin_emails):
            raise HTTPException(status_code=403, detail="Admin access required")

    @app.get("/api/businesses")
    async def list_businesses(http_request: Request):
        """List all businesses (including disabled ones)."""
        user = await resolve_user(agent, http_request)
        _guard(user)

        config = load_app_config()
        businesses = get_businesses_from_config(config)

        # Also include businesses from running agent config
        agent_businesses = getattr(agent.config, "businesses", {}) or {}
        result = []

        for biz in businesses:
            biz_id = biz.get("id")
            result.append({
                "id": biz_id,
                "enabled": biz.get("enabled", True),
                "database": biz.get("database", {}),
                "schema_vector": biz.get("schema_vector", {}),
            })

        # Add any agent-only businesses not in config file
        config_ids = {b.get("id") for b in businesses}
        for biz_id, biz_config in agent_businesses.items():
            if biz_id not in config_ids:
                result.append({
                    "id": biz_id,
                    "enabled": biz_config.enabled,
                    "database": {"url": biz_config.database.url} if biz_config.database else {},
                    "schema_vector": {
                        "namespace": biz_config.schema_vector.namespace,
                        "backend": biz_config.schema_vector.backend,
                        "embedding_model_path": biz_config.schema_vector.embedding_model_path,
                    } if biz_config.schema_vector else {},
                })

        return result

    @app.post("/api/businesses")
    async def create_business(
        request_body: CreateBusinessRequest, http_request: Request
    ):
        """Create a new business configuration."""
        user = await resolve_user(agent, http_request)
        _guard(user)

        # Validate business ID
        if not request_body.id or not request_body.id.strip():
            raise HTTPException(status_code=400, detail="Business ID is required")

        # Check if already exists
        config = load_app_config()
        existing = get_businesses_from_config(config)
        for biz in existing:
            if biz.get("id") == request_body.id:
                raise HTTPException(
                    status_code=409,
                    detail=f"Business '{request_body.id}' already exists",
                )

        # Find embedding_model_path from vector_db config
        default_embedding_model_path = None
        storage = config.get("storage", {})
        project = storage.get("project", {})
        vector_db = project.get("vector_db", {})
        instances = vector_db.get("instances", {})
        active_instance = instances.get(vector_db.get("active", ""), {})
        default_embedding_model_path = active_instance.get("embedding_model_path")

        # Create new business entry (disabled by default)
        new_business = {
            "id": request_body.id,
            "enabled": False,
            "database": {"url": request_body.database_url},
            "schema_vector": {
                "namespace": request_body.namespace,
                "backend": None,
                "embedding_model_path": default_embedding_model_path,
            },
        }

        # Update config
        _update_business_in_config(config, request_body.id, new_business)
        save_app_config(config)

        # Hot-reload into agent
        sync_agent_businesses(agent, config)

        return new_business

    @app.put("/api/businesses/{business_id}/enable")
    async def enable_business(
        business_id: str, request_body: EnableBusinessRequest, http_request: Request
    ):
        """Enable or disable a business."""
        user = await resolve_user(agent, http_request)
        _guard(user)

        config = load_app_config()
        businesses = get_businesses_from_config(config)

        # Find business
        found = False
        for biz in businesses:
            if biz.get("id") == business_id:
                biz["enabled"] = request_body.enabled
                found = True
                break

        if not found:
            raise HTTPException(
                status_code=404, detail=f"Business '{business_id}' not found"
            )

        # Save config
        save_app_config(config)

        # Hot-reload into agent
        sync_agent_businesses(agent, config)

        return {"id": business_id, "enabled": request_body.enabled}
