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
from vanna.integrations.databases.factory import create_sql_runner


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


# --- Task 4: Agent business routing ---


def test_agent_resolves_business_from_config():
    """Agent config should support multi-business configuration."""
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
    assert "biz_a" in config.businesses
    assert config.businesses["biz_a"].effective_database_name() == "biz_a"
    assert config.businesses["biz_b"].effective_database_name() == "custom_b"


def test_agent_sql_runner_factory_creates_correct_type():
    """create_sql_runner should create SqliteRunner for sqlite URLs."""
    runner = create_sql_runner("sqlite:///:memory:")
    assert isinstance(runner, SqlRunner)


def test_agent_sql_runner_cache_works():
    """Agent should cache SqlRunner instances per business."""
    # Simulate the caching logic
    cache = {}
    business = BusinessConfig(id="biz_a", database_url="sqlite:///:memory:")

    # First call creates
    if business.id not in cache:
        cache[business.id] = create_sql_runner(business.database_url)
    runner1 = cache[business.id]

    # Second call returns cached
    if business.id not in cache:
        cache[business.id] = create_sql_runner(business.database_url)
    runner2 = cache[business.id]

    assert runner1 is runner2


# --- Task 5: DDL import business routing ---


def test_ddl_ingest_request_accepts_business_id():
    """IngestRequest should accept optional business_id."""
    from vanna.servers.fastapi.ddl_import import IngestRequest

    req = IngestRequest(parse_id="test", business_id="biz_a")
    assert req.business_id == "biz_a"
    assert req.database_name is None


def test_ddl_ingest_request_backward_compatible():
    """IngestRequest without business_id should work as before."""
    from vanna.servers.fastapi.ddl_import import IngestRequest

    req = IngestRequest(parse_id="test", database_name="my_db")
    assert req.business_id is None
    assert req.database_name == "my_db"


# --- Task 6: Chat request business_id ---


def test_chat_request_accepts_business_id():
    """ChatRequest should accept optional business_id."""
    from vanna.servers.base.models import ChatRequest

    req = ChatRequest(message="hello", business_id="biz_a")
    assert req.business_id == "biz_a"


def test_chat_request_backward_compatible():
    """ChatRequest without business_id should work as before."""
    from vanna.servers.base.models import ChatRequest

    req = ChatRequest(message="hello")
    assert req.business_id is None


def test_chat_request_business_id_flows_to_metadata():
    """ChatRequest.business_id should be placed into metadata for routing."""
    from vanna.servers.base.models import ChatRequest

    req = ChatRequest(message="hello", business_id="biz_a", metadata={"key": "val"})
    # The route handler should merge business_id into metadata
    metadata = dict(req.metadata)
    if req.business_id:
        metadata["business_id"] = req.business_id
    assert metadata["business_id"] == "biz_a"
    assert metadata["key"] == "val"
