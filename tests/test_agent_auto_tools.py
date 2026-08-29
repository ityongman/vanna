"""Tests for Agent capability-driven tool auto-registration."""
import logging
from unittest.mock import MagicMock

import pytest

from vanna.core import Agent, AgentConfig, ToolRegistry
from vanna.core.agent.config import DatabaseConfig
from vanna.integrations.local.agent_memory.in_memory import DemoAgentMemory


def _make_agent(**kwargs):
    return Agent(
        llm_service=MagicMock(),
        tool_registry=ToolRegistry(),
        user_resolver=MagicMock(),
        agent_memory=kwargs.pop("agent_memory", DemoAgentMemory()),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_memory_tools_auto_registered():
    agent = _make_agent()
    tools = await agent.tool_registry.list_tools()
    for name in (
        "search_saved_correct_tool_uses",
        "save_question_tool_args",
        "save_text_memory",
    ):
        assert name in tools, f"{name} should be auto-registered"


@pytest.mark.asyncio
async def test_schema_tool_registered_when_store_present():
    agent = _make_agent(schema_vector_store=MagicMock())
    assert "explore_schema_links" in await agent.tool_registry.list_tools()


@pytest.mark.asyncio
async def test_schema_tool_absent_without_store():
    agent = _make_agent()
    assert "explore_schema_links" not in await agent.tool_registry.list_tools()


@pytest.mark.asyncio
async def test_sql_tools_registered_from_config():
    config = AgentConfig(database=DatabaseConfig(url="sqlite:///Chinook.sqlite"))
    agent = _make_agent(config=config)
    tools = await agent.tool_registry.list_tools()
    assert "run_sql" in tools
    assert "visualize_data" in tools


@pytest.mark.asyncio
async def test_explicit_runner_wins_over_config():
    mock_runner = MagicMock()
    config = AgentConfig(database=DatabaseConfig(url="sqlite:///Chinook.sqlite"))
    agent = _make_agent(config=config, sql_runner=mock_runner)
    tool = await agent.tool_registry.get_tool("run_sql")
    assert tool.sql_runner is mock_runner


@pytest.mark.asyncio
async def test_no_sql_runner_logs_warning(caplog):
    with caplog.at_level(logging.WARNING):
        agent = _make_agent()
    assert "run_sql" not in await agent.tool_registry.list_tools()
    assert any("text-to-SQL" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_auto_register_disabled():
    agent = _make_agent(config=AgentConfig(auto_register_tools=False))
    assert await agent.tool_registry.list_tools() == []


@pytest.mark.asyncio
async def test_extra_tools_registered():
    from vanna.tools.file_system import ListFilesTool

    agent = _make_agent(extra_tools=[ListFilesTool()])
    assert "list_files" in await agent.tool_registry.list_tools()


@pytest.mark.asyncio
async def test_existing_tool_not_overwritten():
    """Pre-registered run_sql must survive auto-assembly."""
    from vanna.tools.run_sql import RunSqlTool

    registry = ToolRegistry()
    my_runner = MagicMock()
    registry.register(RunSqlTool(sql_runner=my_runner))
    agent = Agent(
        llm_service=MagicMock(),
        tool_registry=registry,
        user_resolver=MagicMock(),
        agent_memory=DemoAgentMemory(),
        config=AgentConfig(database=DatabaseConfig(url="sqlite:///Chinook.sqlite")),
    )
    tool = await agent.tool_registry.get_tool("run_sql")
    assert tool.sql_runner is my_runner


def _make_basic_agent(
    agent_memory=None,
    schema_vector_store=None,
    vector_backend=None,
):
    from vanna.agents import create_basic_agent

    return create_basic_agent(
        llm_service=MagicMock(),
        agent_memory=agent_memory,
        schema_vector_store=schema_vector_store,
        vector_backend=vector_backend,
    )


@pytest.mark.asyncio
async def test_vector_backend_derives_faiss_stores():
    """create_basic_agent(vector_backend='faiss') derives both stores."""
    faiss_memory = pytest.importorskip("vanna.integrations.vector.faiss")
    faiss_memory  # noqa: B018 - imported for its conditioning effect
    # The module can be present while the faiss runtime package is not;
    # skip in that case as the backend cannot be instantiated.
    pytest.importorskip("faiss")

    agent = _make_basic_agent(vector_backend="faiss")
    from vanna.integrations.vector.faiss import (
        FAISSAgentMemory,
        FAISSSchemaVectorStore,
    )

    assert isinstance(agent.agent_memory, FAISSAgentMemory)
    assert isinstance(agent.schema_vector_store, FAISSSchemaVectorStore)


@pytest.mark.asyncio
async def test_vector_backend_unknown_falls_back_to_default():
    """Unknown vector_backend: agent_memory is the default implementation."""
    agent = _make_basic_agent(vector_backend="mysql")
    default = _make_basic_agent()

    assert agent.agent_memory is not None
    assert type(agent.agent_memory) is type(default.agent_memory)
    assert not isinstance(agent.agent_memory, MagicMock)
    assert agent.schema_vector_store is None


@pytest.mark.asyncio
async def test_vector_backend_none_keeps_defaults():
    """vector_backend=None must behave exactly like before (default memory)."""
    default = _make_basic_agent()
    explicit_none = _make_basic_agent(vector_backend=None)

    assert explicit_none.agent_memory is not None
    assert type(explicit_none.agent_memory) is type(default.agent_memory)
    assert explicit_none.schema_vector_store is default.schema_vector_store
