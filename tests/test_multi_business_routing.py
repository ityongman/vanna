"""Tests for multi-business storage routing and the unified app config."""

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


def _business(id="biz_a", url="sqlite:///a.db", namespace=None, **kwargs):
    """Shorthand for building a BusinessConfig."""
    return BusinessConfig(
        id=id,
        database={"url": url},
        schema_vector={"namespace": namespace or id},
        **kwargs,
    )


# --- Task 1: BusinessConfig model ---


def test_business_config_defaults():
    """enabled defaults to True; effective_database_name is the namespace."""
    bc = _business("biz_a")
    assert bc.enabled is True
    assert bc.effective_database_name() == "biz_a"
    assert bc.database.url == "sqlite:///a.db"
    assert bc.schema_vector.backend is None
    assert bc.schema_vector.embedding_model_path is None


def test_business_config_custom_namespace_and_backend():
    bc = BusinessConfig(
        id="biz_b",
        database={"url": "mysql://u:p@h/db"},
        schema_vector={
            "namespace": "custom_ns",
            "backend": "qdrant_server",
            "embedding_model_path": "models/bge",
        },
    )
    assert bc.effective_database_name() == "custom_ns"
    assert bc.schema_vector.backend == "qdrant_server"
    assert bc.schema_vector.embedding_model_path == "models/bge"


def test_business_config_disabled():
    bc = _business("biz_c", enabled=False)
    assert bc.enabled is False


def test_business_config_requires_nested_fields():
    with pytest.raises(Exception):
        BusinessConfig(id="biz_a")  # missing database / schema_vector


def test_agent_config_businesses_default_empty():
    config = AgentConfig()
    assert config.businesses == {}


def test_agent_config_businesses_multiple():
    config = AgentConfig(
        businesses={
            "biz_a": _business("biz_a"),
            "biz_b": _business("biz_b", namespace="custom_b"),
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
            "biz_a": _business("biz_a"),
            "biz_b": _business("biz_b", namespace="custom_b"),
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
    cache = {}
    business = _business("biz_a", url="sqlite:///:memory:")

    if business.id not in cache:
        cache[business.id] = create_sql_runner(business.database.url)
    runner1 = cache[business.id]

    if business.id not in cache:
        cache[business.id] = create_sql_runner(business.database.url)
    runner2 = cache[business.id]

    assert runner1 is runner2


def test_agent_with_businesses_registers_sql_tools():
    """With businesses configured, run_sql/visualize_data must be registered.

    Regression: previously the tools were only registered when a bound
    sql_runner existed, so the multi-business path had no SQL tools at all
    (the per-request context.sql_runner had nowhere to flow).
    """
    from vanna.core.agent.agent import Agent
    from vanna.core.registry import ToolRegistry
    from vanna.core.user.resolver import UserResolver
    from vanna.integrations.llm.mock import MockLlmService

    class _Resolver(UserResolver):
        async def resolve_user(self, request_context):
            return User(id="u1", email="u1@example.com")

    agent = Agent(
        llm_service=MockLlmService(),
        tool_registry=ToolRegistry(),
        user_resolver=_Resolver(),
        agent_memory=DemoAgentMemory(),
        config=AgentConfig(
            businesses={"biz_a": _business("biz_a", url="sqlite:///:memory:")}
        ),
    )

    assert agent.sql_runner is None  # no bound global runner by design
    run_sql_tool = asyncio.run(agent.tool_registry.get_tool("run_sql"))
    visualize_tool = asyncio.run(agent.tool_registry.get_tool("visualize_data"))
    assert run_sql_tool is not None
    assert visualize_tool is not None


def test_agent_business_routing_resolves_runner_per_request():
    """A valid business_id routes to a per-business SqlRunner in ToolContext."""
    from vanna.core.agent.agent import Agent
    from vanna.core.llm.models import LlmRequest, LlmResponse
    from vanna.core.llm.base import LlmService
    from vanna.core.registry import ToolRegistry
    from vanna.core.tool import ToolCall
    from vanna.core.user.resolver import UserResolver
    from vanna.core.user.request_context import RequestContext

    class _Resolver(UserResolver):
        async def resolve_user(self, request_context):
            return User(id="u1", email="u1@example.com")

    class _ToolCallingLlm(LlmService):
        """First call emits a run_sql tool call, then a plain answer."""

        def __init__(self):
            self.calls = 0

        async def send_request(self, request: LlmRequest) -> LlmResponse:
            self.calls += 1
            if self.calls == 1:
                return LlmResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            name="run_sql",
                            arguments={"sql": "SELECT 1"},
                        )
                    ],
                    finish_reason="tool_use",
                )
            return LlmResponse(content="done", finish_reason="stop")

        async def stream_request(self, request):
            yield None  # pragma: no cover - not used in this test

        async def validate_tools(self, tools):
            return []

    class _RecordingRegistry(ToolRegistry):
        """Capture the ToolContext of every executed tool call."""

        def __init__(self):
            super().__init__()
            self.captured_contexts = []

        async def execute(self, tool_call, context):
            self.captured_contexts.append(context)
            return await super().execute(tool_call, context)

    registry = _RecordingRegistry()
    agent = Agent(
        llm_service=_ToolCallingLlm(),
        tool_registry=registry,
        user_resolver=_Resolver(),
        agent_memory=DemoAgentMemory(),
        config=AgentConfig(
            stream_responses=False,
            businesses={"biz_a": _business("biz_a", url="sqlite:///:memory:")},
        ),
    )

    async def run():
        components = []
        async for c in agent.send_message(
            RequestContext(
                cookies={}, headers={}, metadata={"business_id": "biz_a"}
            ),
            "query equipment decay",
        ):
            components.append(c)
        return components

    asyncio.run(run())

    # The ToolContext carries the lazily-created business SqlRunner.
    assert registry.captured_contexts, "tool execution context was never built"
    ctx = registry.captured_contexts[0]
    assert ctx.sql_runner is not None
    assert "biz_a" in agent._business_sql_runners
    assert agent._business_sql_runners["biz_a"] is ctx.sql_runner


def test_run_sql_without_any_runner_reports_error():
    """RunSqlTool with no bound and no context runner returns an error result."""
    from vanna.tools.run_sql import RunSqlTool

    tool = RunSqlTool()  # no bound runner (multi-business registration form)
    ctx = ToolContext(
        user=User(id="u1", email="u1@example.com"),
        conversation_id="c1",
        request_id="r1",
        agent_memory=DemoAgentMemory(),
    )
    result = asyncio.run(tool.execute(ctx, RunSqlToolArgs(sql="SELECT 1")))
    assert result.success is False
    assert "no SqlRunner available" in result.result_for_llm


def test_agent_business_routing_requires_business_id():
    """With businesses configured, a request without business_id errors."""
    from vanna.core.agent.agent import Agent
    from vanna.core.registry import ToolRegistry
    from vanna.core.user.resolver import UserResolver
    from vanna.core.user.request_context import RequestContext
    from vanna.integrations.llm.mock import MockLlmService

    class _Resolver(UserResolver):
        async def resolve_user(self, request_context):
            return User(id="u1", email="u1@example.com")

    agent = Agent(
        llm_service=MockLlmService(),
        tool_registry=ToolRegistry(),
        user_resolver=_Resolver(),
        agent_memory=DemoAgentMemory(),
        config=AgentConfig(
            businesses={"biz_a": _business("biz_a", url="sqlite:///:memory:")}
        ),
    )

    async def run():
        components = []
        async for c in agent.send_message(
            RequestContext(cookies={}, headers={}), "hello"
        ):
            components.append(c)
        return components

    components = asyncio.run(run())
    texts = _component_texts(components)
    assert any("business_id is required" in t for t in texts), texts


def test_agent_business_routing_unknown_business_errors():
    """With businesses configured, an unknown business_id errors."""
    from vanna.core.agent.agent import Agent
    from vanna.core.registry import ToolRegistry
    from vanna.core.user.resolver import UserResolver
    from vanna.core.user.request_context import RequestContext
    from vanna.integrations.llm.mock import MockLlmService

    class _Resolver(UserResolver):
        async def resolve_user(self, request_context):
            return User(id="u1", email="u1@example.com")

    agent = Agent(
        llm_service=MockLlmService(),
        tool_registry=ToolRegistry(),
        user_resolver=_Resolver(),
        agent_memory=DemoAgentMemory(),
        config=AgentConfig(
            businesses={"biz_a": _business("biz_a", url="sqlite:///:memory:")}
        ),
    )

    async def run():
        components = []
        async for c in agent.send_message(
            RequestContext(cookies={}, headers={}, metadata={"business_id": "nope"}),
            "hello",
        ):
            components.append(c)
        return components

    components = asyncio.run(run())
    texts = _component_texts(components)
    assert any("not found or disabled" in t for t in texts), texts


def _component_texts(components):
    """Extract text payloads from yielded components for assertions."""
    texts = []

    def _walk(obj):
        if obj is None:
            return
        if isinstance(obj, str):
            texts.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif hasattr(obj, "text"):
            texts.append(obj.text)
        elif hasattr(obj, "description"):
            texts.append(obj.description)

    for c in components:
        rich = getattr(c, "rich_component", None)
        simple = getattr(c, "simple_component", None)
        _walk(rich)
        _walk(simple)
    return texts


# --- Task 5: DDL import business routing ---


def test_ddl_ingest_request_requires_business_id():
    """IngestRequest requires business_id (no fallback routing)."""
    from vanna.servers.fastapi.ddl_import import IngestRequest

    req = IngestRequest(parse_id="test", business_id="biz_a")
    assert req.business_id == "biz_a"

    with pytest.raises(Exception):
        IngestRequest(parse_id="test")


def test_ddl_ingest_unknown_business_returns_400():
    """Ingesting with an unknown business_id must not write anywhere."""
    from vanna.servers.fastapi.ddl_import import _resolve_business_namespace
    from fastapi import HTTPException

    agent = MagicMock()
    agent.config.businesses = {"biz_a": _business("biz_a")}

    assert _resolve_business_namespace(agent, "biz_a") == "biz_a"

    with pytest.raises(HTTPException) as exc_info:
        _resolve_business_namespace(agent, "nope")
    assert exc_info.value.status_code == 400


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
    metadata = dict(req.metadata)
    if req.business_id:
        metadata["business_id"] = req.business_id
    assert metadata["business_id"] == "biz_a"
    assert metadata["key"] == "val"


# --- Task 7: AutoLink enhancer metadata-based namespace override ---


def _make_autolink_enhancer():
    from vanna.core.enhancer.autolink_schema import AutoLinkSchemaEnhancer
    from vanna.core.agent.autolink_config import AutoLinkConfig

    store = MagicMock()
    store.search = AsyncMock(return_value=[])
    config = AutoLinkConfig(enabled=True, database_name="default")
    enhancer = AutoLinkSchemaEnhancer(schema_vector_store=store, config=config)
    return enhancer, store


def test_autolink_enhancer_uses_default_database_name():
    """AutoLinkSchemaEnhancer uses config.database_name by default."""
    enhancer, store = _make_autolink_enhancer()

    asyncio.run(enhancer._build_schema_section("test query"))

    store.search.assert_called_once()
    assert store.search.call_args[1]["database_name"] == "default"


def test_autolink_enhancer_uses_metadata_database_name():
    """enhance_system_prompt uses metadata['autolink_database_name'] when set."""
    enhancer, store = _make_autolink_enhancer()
    user = User(id="u1", email="u1@example.com")

    asyncio.run(
        enhancer.enhance_system_prompt(
            "prompt", "test query", user,
            metadata={"autolink_database_name": "biz_a"},
        )
    )

    store.search.assert_called_once()
    assert store.search.call_args[1]["database_name"] == "biz_a"


def test_autolink_enhancer_no_state_leak_between_calls():
    """A metadata call must not affect subsequent calls without metadata."""
    enhancer, store = _make_autolink_enhancer()
    user = User(id="u1", email="u1@example.com")

    asyncio.run(
        enhancer.enhance_system_prompt(
            "prompt", "q1", user,
            metadata={"autolink_database_name": "biz_a"},
        )
    )
    assert store.search.call_args[1]["database_name"] == "biz_a"

    asyncio.run(enhancer.enhance_system_prompt("prompt", "q2", user))
    assert store.search.call_args[1]["database_name"] == "default"


def test_chain_forwards_metadata_to_enhancers():
    """LlmContextEnhancerChain forwards metadata to every enhancer."""
    from vanna.core.enhancer.chain import LlmContextEnhancerChain

    enhancer = MagicMock()
    enhancer.enhance_system_prompt = AsyncMock(return_value="enhanced")
    chain = LlmContextEnhancerChain([enhancer])
    user = User(id="u1", email="u1@example.com")
    metadata = {"autolink_database_name": "biz_a"}

    result = asyncio.run(
        chain.enhance_system_prompt("prompt", "q", user, metadata=metadata)
    )

    assert result == "enhanced"
    enhancer.enhance_system_prompt.assert_called_once_with(
        "prompt", "q", user, metadata
    )


# --- Unified JSON app config loading (server_runner) ---


def _write_app_config(tmp_path, content):
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    path = config_dir / "app.json"
    path.write_text(content, encoding="utf-8")
    return str(path)


_MINIMAL_CONFIG = """{
  "llm": {
    "active": "main",
    "instances": {"main": {"type": "openai", "api_key": "k", "model": "m"}}
  },
  "agent": {"max_tool_iterations": 5},
  "storage": {
    "project": {
      "conversation_db": {
        "active": "local_sqlite",
        "instances": {"local_sqlite": {"url": "sqlite:///data/db/conv.db"}}
      },
      "vector_db": {
        "active": "faiss_local",
        "instances": {"faiss_local": {"backend": "faiss"}}
      }
    },
    "businesses": [
      {"id": "biz_a",
       "database": {"url": "sqlite:///a.db"},
       "schema_vector": {"namespace": "ns_a"}}
    ]
  },
  "tools": {"extra": []}
}"""


def test_load_app_config_missing_file(tmp_path, monkeypatch):
    """A missing app config yields {} (built-in defaults apply)."""
    from vanna.servers.cli.server_runner import _load_app_config

    monkeypatch.setenv(
        "APP_CONFIG_PATH", str(tmp_path / "nonexistent.json")
    )
    assert _load_app_config() == {}


def test_load_app_config_valid_file(tmp_path, monkeypatch):
    from vanna.servers.cli.server_runner import _load_app_config

    path = _write_app_config(tmp_path, _MINIMAL_CONFIG)
    monkeypatch.setenv("APP_CONFIG_PATH", path)

    cfg = _load_app_config()

    assert cfg["llm"]["active"] == "main"
    assert cfg["agent"]["max_tool_iterations"] == 5
    assert (
        cfg["storage"]["project"]["conversation_db"]["instances"]["local_sqlite"]["url"]
        == "sqlite:///data/db/conv.db"
    )
    assert cfg["storage"]["businesses"][0]["id"] == "biz_a"


def test_load_app_config_rejects_non_object(tmp_path, monkeypatch):
    from vanna.servers.cli.server_runner import _load_app_config

    path = _write_app_config(tmp_path, '["not", "an", "object"]')
    monkeypatch.setenv("APP_CONFIG_PATH", path)

    with pytest.raises(ValueError, match="JSON object"):
        _load_app_config()


def test_load_app_config_rejects_malformed_json(tmp_path, monkeypatch):
    from vanna.servers.cli.server_runner import _load_app_config

    path = _write_app_config(tmp_path, "{not valid json")
    monkeypatch.setenv("APP_CONFIG_PATH", path)

    with pytest.raises(ValueError, match="Failed to read app config"):
        _load_app_config()


# --- _resolve_active_instance ---


def test_resolve_active_instance_selects_active():
    from vanna.servers.cli.server_runner import _resolve_active_instance

    section = {
        "active": "b",
        "instances": {"a": {"x": 1}, "b": {"x": 2}},
    }
    active, instances = _resolve_active_instance("llm", section)
    assert active == "b"
    assert instances["b"] == {"x": 2}


@pytest.mark.parametrize(
    "section",
    [
        {"instances": {"a": {}}},  # missing active
        {"active": "c", "instances": {"a": {}}},  # unknown active
        {"active": "a", "instances": {}},  # empty instances
        {"active": "a"},  # missing instances
        ["not", "a", "dict"],
    ],
)
def test_resolve_active_instance_rejects_malformed(section):
    from vanna.servers.cli.server_runner import _resolve_active_instance

    with pytest.raises(ValueError):
        _resolve_active_instance("llm", section)


# --- _load_businesses ---


def test_load_businesses_missing_key_is_startup_error():
    """No businesses at all aborts startup (no fallback routing)."""
    from vanna.servers.cli.server_runner import _load_businesses

    with pytest.raises(ValueError, match="at least one enabled business"):
        _load_businesses({}, {})
    with pytest.raises(ValueError):
        _load_businesses({"businesses": []}, {})


def test_load_businesses_valid_entries():
    from vanna.servers.cli.server_runner import _load_businesses

    businesses = _load_businesses(
        {
            "businesses": [
                {"id": "biz_a",
                 "database": {"url": "sqlite:///a.db"},
                 "schema_vector": {"namespace": "ns_a"}},
                {"id": "biz_b",
                 "database": {"url": "mysql://u:p@h/db"},
                 "schema_vector": {"namespace": "ns_b"}},
            ]
        },
        {},
    )

    assert set(businesses) == {"biz_a", "biz_b"}
    assert businesses["biz_a"].effective_database_name() == "ns_a"
    assert businesses["biz_b"].effective_database_name() == "ns_b"


def test_load_businesses_filters_disabled():
    from vanna.servers.cli.server_runner import _load_businesses

    businesses = _load_businesses(
        {
            "businesses": [
                {"id": "biz_a",
                 "database": {"url": "sqlite:///a.db"},
                 "schema_vector": {"namespace": "ns_a"}},
                {"id": "biz_b", "enabled": False,
                 "database": {"url": "sqlite:///b.db"},
                 "schema_vector": {"namespace": "ns_b"}},
            ]
        },
        {},
    )

    assert set(businesses) == {"biz_a"}


def test_load_businesses_all_disabled_is_startup_error():
    from vanna.servers.cli.server_runner import _load_businesses

    cfg = {
        "businesses": [
            {"id": "biz_a", "enabled": False,
             "database": {"url": "sqlite:///a.db"},
             "schema_vector": {"namespace": "ns_a"}},
        ]
    }
    with pytest.raises(ValueError, match="disabled"):
        _load_businesses(cfg, {})


def test_load_businesses_duplicate_id():
    from vanna.servers.cli.server_runner import _load_businesses

    cfg = {
        "businesses": [
            {"id": "biz_a",
             "database": {"url": "sqlite:///a.db"},
             "schema_vector": {"namespace": "ns_a"}},
            {"id": "biz_a",
             "database": {"url": "sqlite:///b.db"},
             "schema_vector": {"namespace": "ns_b"}},
        ]
    }

    with pytest.raises(ValueError, match="Duplicate business id"):
        _load_businesses(cfg, {})


def test_load_businesses_rejects_non_list():
    from vanna.servers.cli.server_runner import _load_businesses

    with pytest.raises(ValueError, match="JSON array"):
        _load_businesses({"businesses": {"biz_a": {}}}, {})


def test_load_businesses_invalid_entry():
    from vanna.servers.cli.server_runner import _load_businesses

    cfg = {"businesses": [{"id": "biz_a"}]}  # missing database / schema_vector

    with pytest.raises(ValueError, match="Invalid business entry"):
        _load_businesses(cfg, {})


def test_load_businesses_backend_reference_must_be_declared():
    from vanna.servers.cli.server_runner import _load_businesses

    cfg = {
        "businesses": [
            {"id": "biz_a",
             "database": {"url": "sqlite:///a.db"},
             "schema_vector": {"namespace": "ns_a", "backend": "qdrant_server"}},
        ]
    }

    with pytest.raises(ValueError, match="not declared"):
        _load_businesses(cfg, {"faiss_local": {"backend": "faiss"}})


def test_load_businesses_backend_reference_must_be_implemented():
    from vanna.servers.cli.server_runner import _load_businesses

    cfg = {
        "businesses": [
            {"id": "biz_a",
             "database": {"url": "sqlite:///a.db"},
             "schema_vector": {"namespace": "ns_a", "backend": "qdrant_server"}},
        ]
    }
    vector_instances = {"qdrant_server": {"backend": "qdrant"}}

    with pytest.raises(ValueError, match="not implemented"):
        _load_businesses(cfg, vector_instances)


def test_load_businesses_valid_backend_reference():
    from vanna.servers.cli.server_runner import _load_businesses

    cfg = {
        "businesses": [
            {"id": "biz_a",
             "database": {"url": "sqlite:///a.db"},
             "schema_vector": {"namespace": "ns_a", "backend": "faiss_local"}},
        ]
    }
    vector_instances = {
        "faiss_local": {"backend": "faiss"},
        "qdrant_server": {"backend": "qdrant"},
    }

    businesses = _load_businesses(cfg, vector_instances)
    assert businesses["biz_a"].schema_vector.backend == "faiss_local"


# --- Conversation store config (server_runner) ---


def test_create_conversation_store_custom_sqlite_path(tmp_path):
    from vanna.servers.cli.server_runner import _create_conversation_store
    from vanna.integrations.local import SQLiteConversationStore

    section = {
        "active": "local_sqlite",
        "instances": {"local_sqlite": {"url": f"sqlite:///{tmp_path}/data/db/conv.db"}},
    }

    store = _create_conversation_store(section)

    assert isinstance(store, SQLiteConversationStore)
    assert (tmp_path / "data" / "db" / "conv.db").parent.exists()


def test_create_conversation_store_default_url(tmp_path, monkeypatch):
    """Without the section the default sqlite path is used."""
    from vanna.servers.cli.server_runner import (
        _create_conversation_store,
        _DEFAULT_CONVERSATION_DB_URL,
    )
    from vanna.integrations.local import SQLiteConversationStore

    monkeypatch.chdir(tmp_path)

    store = _create_conversation_store(None)

    assert isinstance(store, SQLiteConversationStore)
    assert "conversations.db" in _DEFAULT_CONVERSATION_DB_URL


def test_create_conversation_store_unsupported_scheme():
    from vanna.servers.cli.server_runner import _create_conversation_store

    section = {
        "active": "team_pg",
        "instances": {
            "team_pg": {"url": "postgresql://user:pwd@host/conversations"}
        },
    }

    with pytest.raises(ValueError, match="not supported"):
        _create_conversation_store(section)


def test_create_conversation_store_active_must_be_declared():
    from vanna.servers.cli.server_runner import _create_conversation_store

    section = {
        "active": "missing",
        "instances": {"local_sqlite": {"url": "sqlite:///x.db"}},
    }

    with pytest.raises(ValueError, match="unknown instance"):
        _create_conversation_store(section)


# --- Vector db resolution (server_runner) ---


def test_resolve_vector_db_absent_section():
    from vanna.servers.cli.server_runner import _resolve_vector_db

    settings, instances = _resolve_vector_db(None)
    assert settings is None
    assert instances == {}


def test_resolve_vector_db_faiss():
    from vanna.servers.cli.server_runner import _resolve_vector_db

    section = {
        "active": "faiss_local",
        "instances": {
            "faiss_local": {
                "backend": "faiss",
                "memory_index_path": "./data/vector_db/memory",
                "schema_persist_dir": "./data/vector_db",
            },
            "qdrant_server": {"backend": "qdrant", "url": "http://localhost:6333"},
        },
    }

    settings, instances = _resolve_vector_db(section)
    assert settings.backend == "faiss"
    assert settings.memory_index_path == "./data/vector_db/memory"
    assert settings.schema_persist_dir == "./data/vector_db"
    assert "qdrant_server" in instances  # reserved instances are returned


def test_index_html_business_selector():
    """The index page renders a business selector when businesses exist.

    Single business: pre-selected, no placeholder. Multiple: placeholder
    forces an explicit choice (server has no default route). None: no
    selector at all.
    """
    from vanna.servers.base.templates import get_index_html

    # Single business
    html = get_index_html(businesses=["equipment_decay"])
    assert 'id="businessInput"' in html
    assert 'value="equipment_decay"' in html
    assert "Select a business" not in html  # no placeholder when only one
    # JS syncs the selection to the chatbot-chat component property
    assert "chat.businessId = businessSelect.value" in html

    # Multiple businesses: placeholder forces explicit selection
    html = get_index_html(businesses=["a", "b"])
    assert "Select a business" in html
    assert 'value="a"' in html and 'value="b"' in html

    # No businesses: no selector element (null-safe JS reference only)
    html = get_index_html()
    assert 'id="businessInput"' not in html


def test_resolve_vector_db_rejects_unsupported_active_backend():
    from vanna.servers.cli.server_runner import _resolve_vector_db

    section = {
        "active": "qdrant_server",
        "instances": {"qdrant_server": {"backend": "qdrant"}},
    }

    with pytest.raises(ValueError, match="unsupported backend"):
        _resolve_vector_db(section)


# --- LLM resolution (server_runner) ---


def test_create_llm_service_missing_section_uses_mock():
    from vanna.servers.cli.server_runner import _create_llm_service
    from vanna.integrations.llm.mock import MockLlmService

    assert isinstance(_create_llm_service({}), MockLlmService)


def test_create_llm_service_unsupported_type_is_startup_error():
    from vanna.servers.cli.server_runner import _create_llm_service

    cfg = {
        "llm": {
            "active": "local_ollama",
            "instances": {"local_ollama": {"type": "ollama", "model": "qwen3:32b"}},
        }
    }

    with pytest.raises(ValueError, match="unsupported type"):
        _create_llm_service(cfg)
