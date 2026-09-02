"""Tests for multi-business storage routing."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from vanna.core.agent.config import AgentConfig, BusinessConfig


# --- Task 1: BusinessConfig model ---


def test_business_config_defaults():
    """database_name defaults to empty string, effective_database_name falls back to id."""
    bc = BusinessConfig(id="biz_a", database_url="sqlite:///a.db")
    assert bc.database_name == ""
    assert bc.effective_database_name() == "biz_a"


def test_business_config_custom_database_name():
    bc = BusinessConfig(
        id="biz_a", database_url="sqlite:///a.db", database_name="custom_ns"
    )
    assert bc.effective_database_name() == "custom_ns"


def test_agent_config_businesses_default_empty():
    config = AgentConfig()
    assert config.businesses == {}


def test_agent_config_businesses_multiple():
    config = AgentConfig(
        businesses={
            "biz_a": BusinessConfig(id="biz_a", database_url="sqlite:///a.db"),
            "biz_b": BusinessConfig(
                id="biz_b",
                database_url="sqlite:///b.db",
                database_name="custom_b",
            ),
        }
    )
    assert len(config.businesses) == 2
    assert config.businesses["biz_a"].effective_database_name() == "biz_a"
    assert config.businesses["biz_b"].effective_database_name() == "custom_b"
