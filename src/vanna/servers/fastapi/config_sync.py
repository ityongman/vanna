"""Shared app.json (business configuration) read/write helpers.

``business_routes`` and the DDL import flow both mutate
``storage.businesses`` in app.json and hot-reload the running agent, so
the file I/O lives here to avoid duplicated config-handling logic.
"""

import json
import os
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

# Default config path (matches server_runner.py)
_DEFAULT_APP_CONFIG_PATH = "config/app.json"


def config_path() -> str:
    """Resolve the app.json path (overridable via APP_CONFIG_PATH)."""
    return os.getenv("APP_CONFIG_PATH") or _DEFAULT_APP_CONFIG_PATH


def load_app_config() -> Dict[str, Any]:
    """Load app.json; a missing file yields an empty config."""
    path = config_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to read app config: {e}"
        ) from e


def save_app_config(config: Dict[str, Any]) -> None:
    """Persist app.json (pretty-printed, UTF-8)."""
    path = config_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except OSError as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to save app config: {e}"
        ) from e


def get_businesses_from_config(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract the storage.businesses list from a config dict."""
    storage = config.get("storage") or {}
    return storage.get("businesses") or []


def sync_agent_businesses(agent, config: Dict[str, Any]) -> None:
    """Hot-reload businesses (enabled or not) into the running agent."""
    from vanna.core.agent.config import BusinessConfig

    new_businesses = {}
    for biz_data in get_businesses_from_config(config):
        biz_id = biz_data.get("id")
        if biz_id:
            try:
                new_businesses[biz_id] = BusinessConfig(**biz_data)
            except Exception:
                pass  # Skip invalid entries
    agent.config.businesses = new_businesses


def _find_business(config: Dict[str, Any], business_id: str):
    """First business entry whose id matches (case-insensitive)."""
    for biz in get_businesses_from_config(config):
        if str(biz.get("id", "")).lower() == business_id.lower():
            return biz
    return None


def set_business_enabled(agent, business_id: str, enabled: bool) -> bool:
    """Set ``enabled`` for one business in app.json and hot-reload.

    Returns True when the business exists in app.json.
    """
    config = load_app_config()
    biz = _find_business(config, business_id)
    if biz is None:
        return False
    biz["enabled"] = enabled
    save_app_config(config)
    sync_agent_businesses(agent, config)
    return True


def resolve_business_namespace_from_config(business_id: str) -> Optional[str]:
    """Namespace from app.json for a business (disabled entries included).

    Returns None when the file is unreadable or the business is unknown.
    """
    try:
        config = load_app_config()
    except HTTPException:
        return None
    biz = _find_business(config, business_id)
    if biz is None:
        return None
    schema_vector = biz.get("schema_vector") or {}
    return schema_vector.get("namespace") or None