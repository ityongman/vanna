"""Tests for multi-business storage routing."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.agent.config import AgentConfig, BusinessConfig
from vanna.core.tool.models import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory.in_memory import DemoAgentMemory


class FakeSqlRunner(SqlRunner):
    """Minimal SqlRunner for testing."""

    async def run_sql(self, args: RunSqlToolArgs, context) -> pd.DataFrame:
        return pd.DataFrame()


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


# --- Task 2: ToolContext sql_runner ---


def test_tool_context_has_sql_runner_field():
    """ToolContext accepts optional sql_runner."""
    ctx = ToolContext(
        user=User(id="u1", email="u1@example.com"),
        conversation_id="c1",
        request_id="r1",
        agent_memory=DemoAgentMemory(),
    )
    assert ctx.sql_runner is None


def test_tool_context_with_sql_runner():
    runner = FakeSqlRunner()
    ctx = ToolContext(
        user=User(id="u1", email="u1@example.com"),
        conversation_id="c1",
        request_id="r1",
        agent_memory=DemoAgentMemory(),
        sql_runner=runner,
    )
    assert ctx.sql_runner is runner
