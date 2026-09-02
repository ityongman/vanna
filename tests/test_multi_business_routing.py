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


# --- Task 3: RunSqlTool prefers context.sql_runner ---


def test_run_sql_prefers_context_sql_runner():
    """RunSqlTool should use context.sql_runner when available."""
    from vanna.tools.run_sql import RunSqlTool

    bound_runner = FakeSqlRunner()
    context_runner = FakeSqlRunner()

    # Track which runner was called
    bound_called = False
    context_called = False

    async def bound_run_sql(args, context):
        nonlocal bound_called
        bound_called = True
        return pd.DataFrame()

    async def context_run_sql(args, context):
        nonlocal context_called
        context_called = True
        return pd.DataFrame()

    bound_runner.run_sql = bound_run_sql
    context_runner.run_sql = context_run_sql

    tool = RunSqlTool(sql_runner=bound_runner)
    ctx = ToolContext(
        user=User(id="u1", email="u1@example.com"),
        conversation_id="c1",
        request_id="r1",
        agent_memory=DemoAgentMemory(),
        sql_runner=context_runner,
    )
    args = RunSqlToolArgs(sql="SELECT 1")
    asyncio.run(tool.execute(ctx, args))

    assert context_called, "context.sql_runner should be called"
    assert not bound_called, "self.sql_runner should NOT be called"


def test_run_sql_falls_back_to_bound_runner():
    """RunSqlTool should use self.sql_runner when context.sql_runner is None."""
    from vanna.tools.run_sql import RunSqlTool

    bound_runner = FakeSqlRunner()
    bound_called = False

    async def bound_run_sql(args, context):
        nonlocal bound_called
        bound_called = True
        return pd.DataFrame()

    bound_runner.run_sql = bound_run_sql

    tool = RunSqlTool(sql_runner=bound_runner)
    ctx = ToolContext(
        user=User(id="u1", email="u1@example.com"),
        conversation_id="c1",
        request_id="r1",
        agent_memory=DemoAgentMemory(),
    )
    args = RunSqlToolArgs(sql="SELECT 1")
    asyncio.run(tool.execute(ctx, args))

    assert bound_called, "self.sql_runner should be called as fallback"
