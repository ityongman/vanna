# Agent 工具自动装配与用户组体系移除 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现"能力/配置驱动"的工具自动装配（Agent 检测注入能力自动注册工具，DATABASE_URL 配置派生 SqlRunner），并整体移除用户组权限体系（文档标注 TODO 后期重新设计），最终 `.env` 一行配置跑通 text-to-sql。

**Architecture:** 三分类工具注入——第 1 类（vector db 工具）由 Agent 检测能力存在即注册；第 2 类（db 工具）由 `AgentConfig.database.url` 经 scheme 工厂派生 SqlRunner 后注册；第 3 类（其它工具）经 `extra_tools` 参数/`EXTRA_TOOLS` 配置注册。用户组体系按依赖倒序移除（消费端 → 引擎 → 模型 → 审计）。SystemPromptBuilder 已按工具存在性动态生成分支，注册后提示词自动激活，无需改动。

**Tech Stack:** Python 3.x / Pydantic v2 / pytest（已有 pytest-asyncio）/ lit-element 前端不动

**Spec:** `.trae/specs/refactor-agent-tool-auto-assembly/spec.md`

**验证命令（PowerShell，仓库根目录）：** `python -m pytest <file> -v`

**已核实的关键事实（实施者无需重新探索）：**
- 所有工具类零必填构造参数：`SearchSavedCorrectToolUsesTool()`、`SaveQuestionToolArgsTool()`、`SaveTextMemoryTool()`（`src/vanna/tools/agent_memory.py`）、`ExploreSchemaLinksTool()`（`src/vanna/tools/explore_schema_links.py`）、`VisualizeDataTool()`（`src/vanna/tools/visualize_data.py`）；`RunSqlTool(sql_runner=...)` 唯一必填
- Runner 构造签名：`SqliteRunner(database_path)`、`DuckDBRunner(database_path=":memory:")`、`MySQLRunner(host, database, user, password, port=3306)`、`PostgresRunner(connection_string=...)`、`MSSQLRunner(odbc_conn_str)`、`OracleRunner(user, password, dsn)`、`HiveRunner(host, database="default", user, password, port=10000)`、`ClickHouseRunner(host, database, user, password, port=8123)`、`PrestoRunner(host, catalog="hive", schema="default", user, password, port=443, protocol="https")`
- `ToolRegistry.register_local_tool(tool, access_groups)` 是当前唯一注册 API；重复注册抛 `ValueError`；`list_tools()` 为 async
- `Agent.__init__` 位于 `agent.py` L85-165，末尾 `logger.info("Initialized Agent")` 在 L165

---

## 阶段 A：自动装配核心（Task 1-3，纯新增）

### Task 1: AgentConfig 扩展

**Files:**
- Modify: `src/vanna/core/agent/config.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_agent_config.py`：

```python
"""Tests for AgentConfig database and auto-register settings."""
from vanna.core.agent.config import AgentConfig, DatabaseConfig


def test_database_config_defaults_to_none():
    config = AgentConfig()
    assert config.database is None


def test_database_config_accepts_url():
    config = AgentConfig(database=DatabaseConfig(url="sqlite:///Chinook.sqlite"))
    assert config.database.url == "sqlite:///Chinook.sqlite"


def test_auto_register_tools_defaults_true():
    assert AgentConfig().auto_register_tools is True


def test_auto_register_tools_can_disable():
    assert AgentConfig(auto_register_tools=False).auto_register_tools is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_agent_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'DatabaseConfig'`

- [ ] **Step 3: 实现**

在 `src/vanna/core/agent/config.py` 的 `AuditConfig` 类之前插入：

```python
class DatabaseConfig(BaseModel):
    """Target database configuration for text-to-SQL.

    The URL scheme determines which SqlRunner implementation is created
    (e.g. "sqlite:///Chinook.sqlite" -> SqliteRunner).
    """

    url: str = Field(description="Database URL, e.g. sqlite:///Chinook.sqlite")
```

在 `AgentConfig` 类中（`autolink_config` 字段之后）追加两个字段：

```python
    database: Optional[DatabaseConfig] = Field(
        default=None,
        description="Target database; when set, a SqlRunner is derived from the "
        "URL scheme and run_sql/visualize_data tools are auto-registered",
    )
    auto_register_tools: bool = Field(
        default=True,
        description="Auto-register built-in tools based on injected capabilities "
        "(agent_memory, schema_vector_store, sql_runner)",
    )
```

**注意：本任务不删除 `UiFeatures`/`DEFAULT_UI_FEATURES`**（agent.py 仍在使用，Task 4/7 处理）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_agent_config.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add src/vanna/core/agent/config.py tests/test_agent_config.py
git commit -m "feat(config): add DatabaseConfig and auto_register_tools to AgentConfig"
```

---

### Task 2: SqlRunner URL 工厂

**Files:**
- Create: `src/vanna/integrations/databases/factory.py`
- Modify: `src/vanna/integrations/databases/__init__.py`（追加导出，保留现有内容）
- Test: `tests/test_sql_runner_factory.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_sql_runner_factory.py`：

```python
"""Tests for the database URL scheme -> SqlRunner factory."""
from unittest.mock import patch

import pytest

from vanna.integrations.databases.factory import (
    SUPPORTED_SCHEMES,
    _parse_url,
    create_sql_runner,
)


def test_supported_schemes_contains_core_dbs():
    for scheme in ("sqlite", "mysql", "postgresql", "postgres", "mssql",
                   "oracle", "duckdb", "clickhouse", "hive", "presto"):
        assert scheme in SUPPORTED_SCHEMES


def test_sqlite_relative_path():
    runner = create_sql_runner("sqlite:///Chinook.sqlite")
    assert runner.database_path == "Chinook.sqlite"


def test_sqlite_absolute_path():
    runner = create_sql_runner("sqlite:////data/chinook.db")
    assert runner.database_path == "/data/chinook.db"


def test_duckdb_memory():
    runner = create_sql_runner("duckdb:///:memory:")
    assert runner.database_path == ":memory:"


def test_unknown_scheme_raises_with_supported_list():
    with pytest.raises(ValueError) as exc_info:
        create_sql_runner("mongodb://localhost/db")
    assert "sqlite" in str(exc_info.value)
    assert "create the runner explicitly" in str(exc_info.value)


def test_missing_scheme_raises():
    with pytest.raises(ValueError):
        create_sql_runner("not-a-url")


def test_parse_url_mysql():
    parsed = _parse_url("mysql://user:p%40ss@localhost:3307/chinook")
    assert parsed["host"] == "localhost"
    assert parsed["port"] == 3307
    assert parsed["user"] == "user"
    assert parsed["password"] == "p@ss"  # percent-decoded
    assert parsed["database"] == "chinook"


def test_parse_url_query_params():
    parsed = _parse_url("mssql://sa:pwd@host:1433/master?driver=ODBC+Driver+18")
    assert parsed["query"]["driver"] == "ODBC Driver 18"


def test_mysql_runner_created():
    # MySQLRunner requires pymysql; skip if not installed
    pytest.importorskip("pymysql")
    runner = create_sql_runner("mysql://user:pwd@localhost:3306/chinook")
    assert runner is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_sql_runner_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vanna.integrations.databases.factory'`

- [ ] **Step 3: 实现工厂**

创建 `src/vanna/integrations/databases/factory.py`：

```python
"""Database URL scheme -> SqlRunner factory.

Creates the appropriate SqlRunner implementation from a connection URL,
e.g. "sqlite:///Chinook.sqlite" -> SqliteRunner(database_path="Chinook.sqlite").
All Runner classes are imported lazily inside the handlers so importing
this module never triggers optional driver imports (pymysql, oracledb, ...).
"""

from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, unquote, urlparse

from vanna.capabilities.sql_runner import SqlRunner

SUPPORTED_SCHEMES = [
    "sqlite",
    "duckdb",
    "mysql",
    "postgresql",
    "postgres",
    "mssql",
    "oracle",
    "clickhouse",
    "hive",
    "presto",
]


def _parse_url(url: str) -> Dict[str, Any]:
    """Parse a standard database URL into its components.

    Percent-encoding in user/password is decoded; query string becomes a dict.
    """
    parsed = urlparse(url)
    return {
        "host": parsed.hostname,
        "port": parsed.port,
        "user": unquote(parsed.username) if parsed.username else None,
        "password": unquote(parsed.password) if parsed.password else None,
        "database": parsed.path.lstrip("/"),
        "query": dict(parse_qsl(parsed.query)),
    }


def _file_path(url: str) -> str:
    """Extract the file path from sqlite/duckdb URLs.

    Convention (same as SQLAlchemy):
    - 3 slashes -> relative path: sqlite:///foo.db => "foo.db"
    - 4 slashes -> absolute path: sqlite:////abs/foo.db => "/abs/foo.db"
    """
    rest = url.split("://", 1)[1]
    if rest.startswith("//"):
        return rest[1:]
    return rest.lstrip("/")


def _create_sqlite(url: str) -> SqlRunner:
    from vanna.integrations.databases.relational.sqlite.sql_runner import (
        SqliteRunner,
    )

    return SqliteRunner(database_path=_file_path(url))


def _create_duckdb(url: str) -> SqlRunner:
    from vanna.integrations.databases.relational.duckdb.sql_runner import (
        DuckDBRunner,
    )

    return DuckDBRunner(database_path=_file_path(url))


def _create_mysql(url: str) -> SqlRunner:
    from vanna.integrations.databases.relational.mysql.sql_runner import (
        MySQLRunner,
    )

    p = _parse_url(url)
    missing = [
        k for k in ("host", "database", "user", "password") if not p[k]
    ]
    if missing:
        raise ValueError(
            f"MySQL URL is missing required components: {missing}. "
            "Expected format: mysql://user:password@host:3306/database"
        )
    return MySQLRunner(
        host=p["host"],
        database=p["database"],
        user=p["user"],
        password=p["password"],
        port=p["port"] or 3306,
    )


def _create_postgres(url: str) -> SqlRunner:
    from vanna.integrations.databases.relational.postgres.sql_runner import (
        PostgresRunner,
    )

    # psycopg accepts "postgresql://user:pwd@host:port/db" DSNs directly.
    return PostgresRunner(connection_string=url)


def _create_mssql(url: str) -> SqlRunner:
    from vanna.integrations.databases.relational.mssql.sql_runner import (
        MSSQLRunner,
    )

    p = _parse_url(url)
    driver = p["query"].get("driver", "ODBC Driver 17 for SQL Server")
    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={p['host']},{p['port'] or 1433}",
        f"DATABASE={p['database']}",
    ]
    if p["user"]:
        parts += [f"UID={p['user']}", f"PWD={p['password'] or ''}"]
    else:
        parts.append("Trusted_Connection=yes")
    return MSSQLRunner(odbc_conn_str=";".join(parts))


def _create_oracle(url: str) -> SqlRunner:
    from vanna.integrations.databases.relational.oracle.sql_runner import (
        OracleRunner,
    )

    p = _parse_url(url)
    if not p["user"] or p["password"] is None or not p["host"]:
        raise ValueError(
            "Oracle URL is missing required components. "
            "Expected format: oracle://user:password@host:1521/sid"
        )
    dsn = f"{p['host']}:{p['port'] or 1521}/{p['database']}"
    return OracleRunner(user=p["user"], password=p["password"], dsn=dsn)


def _create_clickhouse(url: str) -> SqlRunner:
    from vanna.integrations.databases.warehouse.clickhouse.sql_runner import (
        ClickHouseRunner,
    )

    p = _parse_url(url)
    missing = [
        k for k in ("host", "database", "user", "password") if not p[k]
    ]
    if missing:
        raise ValueError(
            f"ClickHouse URL is missing required components: {missing}. "
            "Expected format: clickhouse://user:password@host:8123/database"
        )
    return ClickHouseRunner(
        host=p["host"],
        database=p["database"],
        user=p["user"],
        password=p["password"],
        port=p["port"] or 8123,
    )


def _create_hive(url: str) -> SqlRunner:
    from vanna.integrations.databases.warehouse.hive.sql_runner import (
        HiveRunner,
    )

    p = _parse_url(url)
    if not p["host"]:
        raise ValueError(
            "Hive URL is missing host. "
            "Expected format: hive://user:password@host:10000/database"
        )
    return HiveRunner(
        host=p["host"],
        database=p["database"] or "default",
        user=p["user"],
        password=p["password"],
        port=p["port"] or 10000,
    )


def _create_presto(url: str) -> SqlRunner:
    from vanna.integrations.databases.warehouse.presto.sql_runner import (
        PrestoRunner,
    )

    p = _parse_url(url)
    if not p["host"]:
        raise ValueError(
            "Presto URL is missing host. "
            "Expected format: presto://user@host:443/catalog/schema?protocol=https"
        )
    path_parts = [seg for seg in p["database"].split("/") if seg]
    catalog = path_parts[0] if path_parts else "hive"
    schema = path_parts[1] if len(path_parts) > 1 else "default"
    return PrestoRunner(
        host=p["host"],
        catalog=catalog,
        schema=schema,
        user=p["user"],
        password=p["password"],
        port=p["port"] or 443,
        protocol=p["query"].get("protocol", "https"),
    )


_HANDLERS = {
    "sqlite": _create_sqlite,
    "duckdb": _create_duckdb,
    "mysql": _create_mysql,
    "postgresql": _create_postgres,
    "postgres": _create_postgres,
    "mssql": _create_mssql,
    "oracle": _create_oracle,
    "clickhouse": _create_clickhouse,
    "hive": _create_hive,
    "presto": _create_presto,
}


def create_sql_runner(url: str) -> SqlRunner:
    """Create a SqlRunner from a database URL.

    Args:
        url: Database URL whose scheme selects the runner, e.g.
            "sqlite:///Chinook.sqlite".

    Returns:
        A SqlRunner instance for the given URL.

    Raises:
        ValueError: If the scheme is not supported. For engines with
            credential-file/project-based auth (BigQuery, Snowflake,
            Databricks), create the runner explicitly and pass it to
            ``Agent(sql_runner=...)``.
    """
    if "://" not in url:
        raise ValueError(
            f"Invalid database URL '{url}': no scheme found. "
            f"Supported schemes: {', '.join(SUPPORTED_SCHEMES)}"
        )
    scheme = url.split("://", 1)[0].lower()
    handler = _HANDLERS.get(scheme)
    if handler is None:
        raise ValueError(
            f"Unsupported database scheme '{scheme}'. "
            f"Supported schemes: {', '.join(SUPPORTED_SCHEMES)}. "
            "For other engines, create the runner explicitly and pass it "
            "via Agent(sql_runner=...)."
        )
    return handler(url)
```

- [ ] **Step 4: 导出**

在 `src/vanna/integrations/databases/__init__.py` 末尾追加（保留现有内容）：

```python
from .factory import SUPPORTED_SCHEMES, create_sql_runner

__all__ = __all__ + ["create_sql_runner", "SUPPORTED_SCHEMES"]
```

**注意：** 若该文件的 `__all__` 不存在则直接追加两行 import，不写 `__all__` 拼接。若发生循环导入（capabilities ← integrations），改为删除此步——Agent 内直接 `from vanna.integrations.databases.factory import create_sql_runner`（factory 只依赖 capabilities，无循环风险）。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_sql_runner_factory.py -v`
Expected: 9 passed（`test_mysql_runner_created` 若 pymysql 未装则 skip，可接受）

- [ ] **Step 6: 提交**

```bash
git add src/vanna/integrations/databases/factory.py src/vanna/integrations/databases/__init__.py tests/test_sql_runner_factory.py
git commit -m "feat(databases): add URL scheme factory for SqlRunner creation"
```

---

### Task 3: Agent 自动装配

**Files:**
- Modify: `src/vanna/core/agent/agent.py:85-165`（`__init__`）+ 类内新增两个方法
- Modify: `src/vanna/agents/__init__.py`（`create_basic_agent` 透传）
- Test: `tests/test_agent_auto_tools.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_agent_auto_tools.py`：

```python
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
    registry.register_local_tool(RunSqlTool(sql_runner=my_runner), [])
    agent = Agent(
        llm_service=MagicMock(),
        tool_registry=registry,
        user_resolver=MagicMock(),
        agent_memory=DemoAgentMemory(),
        config=AgentConfig(database=DatabaseConfig(url="sqlite:///Chinook.sqlite")),
    )
    tool = await agent.tool_registry.get_tool("run_sql")
    assert tool.sql_runner is my_runner
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_agent_auto_tools.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'sql_runner'`

- [ ] **Step 3: 修改 Agent.__init__**

在 `src/vanna/core/agent/agent.py`：

3a. `__init__` 签名（L85-104）在 `schema_vector_store` 参数之后追加两个参数：

```python
        schema_vector_store: Optional[SchemaVectorStore] = None,
        sql_runner: Optional[SqlRunner] = None,
        extra_tools: List[Tool] = [],
```

同时在文件头部 import 区（与现有 `from ..capabilities...` 风格一致）追加：

```python
from ...capabilities.sql_runner import SqlRunner
```

3b. 在 `self.audit_logger = audit_logger`（L158）之后、audit wiring（L160）之前插入：

```python
        # Resolve the SQL runner: explicit instance wins (test mocks), else
        # derive from config.database via the URL-scheme factory.
        if sql_runner is None and config.database is not None:
            from vanna.integrations.databases.factory import create_sql_runner

            sql_runner = create_sql_runner(config.database.url)
        self.sql_runner = sql_runner
        self.extra_tools = list(extra_tools)
```

3c. 在 `logger.info("Initialized Agent")`（L165）之前插入调用：

```python
        self._auto_register_tools()
```

3d. 在类内（`__init__` 结束后）新增两个方法：

```python
    def _auto_register_tools(self) -> None:
        """Register built-in tools based on injected capabilities.

        - agent_memory            -> memory tools (few-shot learning loop)
        - schema_vector_store    -> explore_schema_links (AutoLink)
        - sql_runner             -> run_sql + visualize_data (text-to-SQL)
        - extra_tools            -> registered as-is
        Tools already present in the registry are never overwritten.
        """
        if not self.config.auto_register_tools:
            return

        # Category 1: vector-db tools (bound at runtime via ToolContext).
        from vanna.tools.agent_memory import (
            SaveQuestionToolArgsTool,
            SaveTextMemoryTool,
            SearchSavedCorrectToolUsesTool,
        )

        for tool in (
            SearchSavedCorrectToolUsesTool(),
            SaveQuestionToolArgsTool(),
            SaveTextMemoryTool(),
        ):
            self._register_if_absent(tool)

        if self.schema_vector_store is not None:
            from vanna.tools.explore_schema_links import ExploreSchemaLinksTool

            self._register_if_absent(ExploreSchemaLinksTool())

        # Category 2: database tools (text-to-SQL).
        if self.sql_runner is not None:
            from vanna.tools.run_sql import RunSqlTool
            from vanna.tools.visualize_data import VisualizeDataTool

            self._register_if_absent(RunSqlTool(sql_runner=self.sql_runner))
            self._register_if_absent(VisualizeDataTool())
        else:
            logger.warning(
                "No sql_runner provided and no config.database set; "
                "text-to-SQL is unavailable (run_sql/visualize_data not registered)"
            )

        # Category 3: extra tools passed by the caller.
        for tool in self.extra_tools:
            self._register_if_absent(tool)

    def _register_if_absent(self, tool: "Tool") -> None:
        """Register a tool, silently skipping names already present."""
        try:
            self.tool_registry.register_local_tool(tool, [])
        except ValueError:
            logger.debug("Tool '%s' already registered; keeping existing", tool.name)
```

**注意：** `Tool` 类型已在 agent.py 现有 import 中（`ToolRegistry` 来自 `..registry`，若 `Tool` 未导入则追加 `from ..tool import Tool` 到 import 区并去掉方法签名中的引号）。

- [ ] **Step 4: 装配层透传**

修改 `src/vanna/agents/__init__.py` 的 `create_basic_agent`：签名追加 `sql_runner=None, extra_tools=None, vector_backend=None` 三个关键字参数，Agent 构造调用处追加：

```python
        sql_runner=sql_runner,
        extra_tools=extra_tools or [],
```

（`vector_backend` 参数本任务仅占位不使用，Task 11 实现；或本任务不添加该参数、Task 11 再加——推荐后者，保持每次提交最小化。）

- [ ] **Step 5: 运行新测试**

Run: `python -m pytest tests/test_agent_auto_tools.py -v`
Expected: 9 passed

- [ ] **Step 6: 运行受影响的既有测试**

Run: `python -m pytest tests/test_agents.py tests/test_workflow.py tests/test_memory_tools.py -v`

若有失败：多为测试构造 Agent 时未预期记忆工具被自动注册（如断言工具数量、`/status` 输出工具列表、system prompt 长度）。**修复原则：更新测试断言以包含自动注册的工具，而非关闭自动注册**。若某测试明确需要空注册表，改为 `AgentConfig(auto_register_tools=False)`。把每个适配的测试改到此步完成（不留到 Task 10）。

- [ ] **Step 7: 提交**

```bash
git add src/vanna/core/agent/agent.py src/vanna/agents/__init__.py tests/test_agent_auto_tools.py
git commit -m "feat(agent): auto-register tools from injected capabilities and DatabaseConfig"
```

---

## 阶段 B：用户组体系移除（Task 4-9，依赖倒序）

### Task 4: agent.py UiFeature 分支固定化（消费端先行）

**Files:**
- Modify: `src/vanna/core/agent/agent.py`（L416-422 metadata + L494-728 工具循环）

- [ ] **Step 1: 修改 context metadata 构建（L416-422）**

原代码：

```python
        ui_features_available = []
        for feature_name in self.config.ui_features.feature_group_access.keys():
            if self.config.ui_features.can_user_access_feature(feature_name, user):
                ui_features_available.append(feature_name)

        context_metadata: dict = {"ui_features_available": ui_features_available}
```

替换为：

```python
        context_metadata: dict = {}
```

- [ ] **Step 2: 重写工具执行循环（L494-728）**

将 L494-524（`SHOW_TOOL_INVOCATION_MESSAGE_IN_CHAT` 分支）简化——固定走"聊天内展示"路径：

```python
                if response.content is not None:
                    # Yield any partial content from the assistant before tool execution
                    yield UiComponent(
                        rich_component=RichTextComponent(
                            content=response.content, markdown=True
                        ),
                        simple_component=SimpleTextComponent(text=response.content),
                    )

                    # Update status to executing tools
                    yield UiComponent(  # type: ignore
                        rich_component=StatusBarUpdateComponent(
                            status="working",
                            message="Executing tools...",
                            detail=f"Running {len(response.tool_calls or [])} tools",
                        )
                    )
```

将 L526 起的 `for i, tool_call in enumerate(...)` 循环体中所有权限分支（`has_tool_names_access`、`has_tool_args_access`、`has_tool_args_access_2`、`has_tool_names_access_2`、`has_tool_error_access` 五组判定 + 六处 `log_ui_feature_access` 审计调用块）全部删除，判定块所在 `if` 直接展开为无条件执行。改写后的循环体结构：

```python
                tool_results = []
                for i, tool_call in enumerate(response.tool_calls or []):
                    # Add task for this tool execution
                    tool_task = Task(
                        title=f"Execute {tool_call.name}",
                        description=f"Running tool with provided arguments",
                        status="in_progress",
                    )
                    yield UiComponent(  # type: ignore
                        rich_component=TaskTrackerUpdateComponent.add_task(tool_task)
                    )

                    response_str = response.content

                    # Use primitive StatusCard instead of semantic ToolExecutionComponent
                    tool_status_card = StatusCardComponent(
                        title=f"Executing {tool_call.name}",
                        status="running",
                        description=f"Running tool with {len(tool_call.arguments)} arguments",
                        icon="⚙️",
                        metadata=tool_call.arguments,
                    )

                    yield UiComponent(
                        rich_component=tool_status_card,
                        simple_component=SimpleTextComponent(text=response_str or ""),
                    )

                    # Run before_tool hooks
                    tool = await self.tool_registry.get_tool(tool_call.name)
                    if tool:
                        for hook in self.lifecycle_hooks:
                            await hook.before_tool(tool, context)

                    # Execute tool
                    result = await self.tool_registry.execute(tool_call, context)

                    # Run after_tool hooks
                    for hook in self.lifecycle_hooks:
                        modified_result = await hook.after_tool(result)
                        if modified_result is not None:
                            result = modified_result

                    # Update status card to show completion
                    final_status = "success" if result.success else "error"
                    final_description = (
                        f"Tool completed successfully"
                        if result.success
                        else f"Tool failed: {result.error or 'Unknown error'}"
                    )

                    yield UiComponent(
                        rich_component=tool_status_card.set_status(
                            final_status, final_description
                        ),
                        simple_component=SimpleTextComponent(text=final_description),
                    )

                    # Update tool task to completed
                    yield UiComponent(  # type: ignore
                        rich_component=TaskTrackerUpdateComponent.update_task(
                            tool_task.id,
                            status="completed",
                            detail=f"Tool {'completed successfully' if result.success else 'return an error'}",
                        )
                    )

                    # Yield tool result
                    if result.ui_component:
                        yield result.ui_component
```

（`tool_results.append` 及其后续逻辑保持原样，只删权限分支。`ui_features_available` 相关审计 import 若仅此处使用，同步清理未用 import。）

- [ ] **Step 3: 检查残留引用并验证**

Run: `python -m pytest tests/test_agents.py -v`
Expected: PASS（若有用例断言"非 admin 只收到状态栏"类行为，改为断言收到完整组件）

- [ ] **Step 4: 提交**

```bash
git add src/vanna/core/agent/agent.py tests/test_agents.py
git commit -m "refactor(agent): make UI feature behaviors unconditional, drop ui_features gating"
```

---

### Task 5: workflow 与 memory tools 去权限

**Files:**
- Modify: `src/vanna/core/workflow/default.py`
- Modify: `src/vanna/tools/agent_memory.py`
- Test: `tests/test_workflow.py`、`tests/test_memory_tools.py`

- [ ] **Step 1: workflow/default.py 删除 admin 检查**

五处修改（行号为当前参考，以内容定位）：
1. L57-93 `/help`：删除 `is_admin = "admin" in user.group_memberships`（L59），帮助文案中命令列表无条件包含 `/status`、`/memories`、`/delete [id]`（原 L72-77 的 admin 分支展开）
2. L95-113 `/status`：删除 L98-113 的 `if "admin" not in user.group_memberships:` 整个拒绝分支，命令处理逻辑上提一级缩进
3. L115-138 `/memories`：同上删除 L122-138 拒绝分支
4. L140-158 `/delete`：同上删除 L142-158 拒绝分支
5. L176-253 starter 卡片：`get_starter_ui` 中删除 `is_admin = "admin" in user.group_memberships`（L177）与 `_generate_starter_card(analysis, is_admin)` 的分支分发（L192、L195），直接调用 `self._generate_admin_starter_card(analysis)`；删除 `_generate_starter_card` 普通版方法与 `_generate_admin_starter_card` 中 `**🔒 Admin View** - You have admin privileges...` 前缀文案（改为直接以正文开头）；卡片中 `Memory Management` 段（L244）保留（全员可管理记忆），快捷按钮 `/help` `/memories`（L238-248）保留

- [ ] **Step 2: tools/agent_memory.py 固定 detailed 视图**

删除两处 `ui_features_available` 检查（约 L153-159、L204-208）：

```python
                ui_features_available = context.metadata.get(
                    "ui_features_available", []
                )
                show_detailed_results = (
                    UiFeature.UI_FEATURE_SHOW_MEMORY_DETAILED_RESULTS
                    in ui_features_available
                )
```

两处的 `if show_detailed_results:` / `else:` 分支只保留 detailed（CardComponent）分支；同时删除 import 区的 `from vanna.core.agent.config import UiFeature`（L16）。非 detailed 的 StatusBarUpdateComponent 分支删除（确认 `StatusBarUpdateComponent` 若无其它使用则从 import 中移除）。

- [ ] **Step 3: 更新受影响测试并运行**

Run: `python -m pytest tests/test_workflow.py tests/test_memory_tools.py -v`

适配点：
- 曾断言"非 admin 用户收到 Access Denied 卡片"的用例 → 改为断言收到命令内容
- 曾用 `group_memberships=["admin"]` 构造 User 的用例 → 删除该字段（Task 7 前字段仍存在，删了也不报错，因 `extra="allow"`；但本任务直接删，减少二次修改）
- `/status` `/memories` `/delete` 的 user 构造统一为普通 User

Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add src/vanna/core/workflow/default.py src/vanna/tools/agent_memory.py tests/test_workflow.py tests/test_memory_tools.py
git commit -m "refactor(workflow): remove admin gating from slash commands and starter UI"
```

---

### Task 6: registry.py 权限引擎删除

**Files:**
- Modify: `src/vanna/core/registry.py`
- Modify: `src/vanna/core/agent/agent.py`（`_register_if_absent` 一行）

- [ ] **Step 1: 重写 registry.py**

删除 `_LocalToolWrapper` 类（L20-43）整体；`register_local_tool` 替换为 `register`；删除 `_validate_tool_permissions`（L98-111）；`get_schemas` 删除 user 过滤；`execute` 删除权限校验块与 access_check 审计块。改写后核心结构：

```python
"""
Tool registry for the Vanna Agents framework.

This module provides the ToolRegistry class for managing and executing tools.
"""

import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, TypeVar, Union

from .tool import Tool, ToolCall, ToolContext, ToolRejection, ToolResult, ToolSchema

if TYPE_CHECKING:
    from .audit import AuditLogger
    from .agent.config import AuditConfig

T = TypeVar("T")


class ToolRegistry:
    """Registry for managing tools."""

    def __init__(
        self,
        audit_logger: Optional["AuditLogger"] = None,
        audit_config: Optional["AuditConfig"] = None,
    ) -> None:
        self._tools: Dict[str, Tool[Any]] = {}
        self.audit_logger = audit_logger
        if audit_config is not None:
            self.audit_config = audit_config
        else:
            from .agent.config import AuditConfig

            self.audit_config = AuditConfig()

    def register(self, tool: Tool[Any]) -> None:
        """Register a tool.

        Args:
            tool: The tool to register

        Raises:
            ValueError: If a tool with the same name is already registered
        """
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    async def get_tool(self, name: str) -> Optional[Tool[Any]]:
        """Get a tool by name."""
        return self._tools.get(name)

    async def list_tools(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    async def get_schemas(self) -> List[ToolSchema]:
        """Get schemas for all registered tools."""
        return [tool.get_schema() for tool in self._tools.values()]

    async def transform_args(
        self,
        tool: Tool[T],
        args: T,
        user: "User",
        context: ToolContext,
    ) -> Union[T, ToolRejection]:
        """Transform and validate tool arguments based on user context.

        (docstring 保留原文)"""
        return args  # Default: no transformation (NoOp)

    async def execute(
        self,
        tool_call: ToolCall,
        context: ToolContext,
    ) -> ToolResult:
        """Execute a tool call with validation."""
        tool = await self.get_tool(tool_call.name)
        if not tool:
            msg = f"Tool '{tool_call.name}' not found"
            return ToolResult(
                success=False,
                result_for_llm=msg,
                ui_component=None,
                error=msg,
            )

        # Validate and parse arguments
        try:
            args_model = tool.get_args_schema()
            validated_args = args_model.model_validate(tool_call.arguments)
        except Exception as e:
            msg = f"Invalid arguments: {str(e)}"
            return ToolResult(
                success=False,
                result_for_llm=msg,
                ui_component=None,
                error=msg,
            )

        # Transform/validate arguments based on user context
        transform_result = await self.transform_args(
            tool=tool,
            args=validated_args,
            user=context.user,
            context=context,
        )

        if isinstance(transform_result, ToolRejection):
            return ToolResult(
                success=False,
                result_for_llm=transform_result.reason,
                ui_component=None,
                error=transform_result.reason,
            )

        # Use transformed arguments for execution
        final_args = transform_result

        # Audit tool invocation
        if (
            self.audit_logger
            and self.audit_config
            and self.audit_config.log_tool_invocations
        ):
            await self.audit_logger.log_tool_invocation(
                user=context.user,
                tool_call=tool_call,
                context=context,
                sanitize_parameters=self.audit_config.sanitize_tool_parameters,
            )

        # Execute tool with context-first signature
        try:
            start_time = time.perf_counter()
            result = await tool.execute(context, final_args)
            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Add execution time to metadata
            result.metadata["execution_time_ms"] = execution_time_ms

            # Audit tool result
            if (
                self.audit_logger
                and self.audit_config
                and self.audit_config.log_tool_results
            ):
                await self.audit_logger.log_tool_result(
                    user=context.user,
                    tool_call=tool_call,
                    result=result,
                    context=context,
                )

            return result
        except Exception as e:
            msg = f"Execution failed: {str(e)}"
            return ToolResult(
                success=False,
                result_for_llm=msg,
                ui_component=None,
                error=msg,
            )
```

**注意：** `User` import 若无其它使用可删除（transform_args 的 user 参数标注改为 TYPE_CHECKING 字符串形式或保留 Any）。`log_tool_invocation` 调用中删除了 `ui_features=ui_features_available` 参数（原 L239-243 收集逻辑已在 Task 4 删除）——**需同步检查 `AuditLogger.log_tool_invocation` 的 ui_features 形参并在 Task 8 一并删除**；本任务先保留 audit/base.py 不动，因此此处调用需与 base.py 现签名匹配：若 base.py 的 `ui_features` 有默认值则直接省略该参数即可，无默认值则 Task 8 提前到本任务执行（先看签名再定）。

- [ ] **Step 2: 迁移全部 register_local_tool 调用点**

Run（PowerShell）: `git grep -n "register_local_tool" -- src tests`

每个调用点把 `register_local_tool(tool, [...])` 改为 `register(tool)`。已知位置：
- `src/vanna/core/agent/agent.py` `_register_if_absent`（Task 3 创建，改这一行即可）
- `src/vanna/legacy/adapter.py`（3 处，Task 9 深度清理，此处先改签名）
- `src/vanna/servers/cli/server_runner.py`（若有）
- `tests/` 各处（Task 10 深度清理，此处先改签名保证通过）

- [ ] **Step 3: 检查 get_schemas 调用点**

Run: `git grep -n "get_schemas" -- src`

agent.py 中调用 `get_schemas(user)` 的位置删除 user 实参（**注意**：若调用处有 `if user is None` 分支逻辑，一并简化）。system prompt builder 接收 tool schemas 的路径确认不传 user 后仍工作。

- [ ] **Step 4: 运行核心测试**

Run: `python -m pytest tests/test_agents.py tests/test_agent_auto_tools.py tests/test_workflow.py -v`
Expected: PASS（test_agent_auto_tools.py 中 `registry.register_local_tool(RunSqlTool(...), [])` 同步改为 `registry.register(...)`）

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "BREAKING refactor(registry): remove permission engine, register_local_tool -> register"
```

---

### Task 7: 模型层与 config.py 清理

**Files:**
- Modify: `src/vanna/core/tool/base.py:31-34,69`
- Modify: `src/vanna/core/tool/models.py:76-78`
- Modify: `src/vanna/core/user/models.py:21-23`
- Modify: `src/vanna/core/agent/config.py:19-84`

- [ ] **Step 1: 删除 Tool.access_groups 属性**

`src/vanna/core/tool/base.py`：删除 L31-34 的 `access_groups` property；`get_schema()` 中删除 `access_groups=self.access_groups`（L69）这一行参数。

- [ ] **Step 2: 删除 ToolSchema.access_groups 字段**

`src/vanna/core/tool/models.py` L76-78：删除 `access_groups` 字段。

- [ ] **Step 3: 删除 User.group_memberships 字段**

`src/vanna/core/user/models.py` L21-23：删除该字段定义。

- [ ] **Step 4: 删除 UiFeatures 体系**

`src/vanna/core/agent/config.py`：删除 `UiFeature` 类（L19-24）、`DEFAULT_UI_FEATURES`（L27-34）、`UiFeatures` 类（L37-84）；`AgentConfig` 中删除 `ui_features` 字段（L124）。

- [ ] **Step 5: 清理引用并验证**

Run: `git grep -n "ui_features\|UiFeature\|group_memberships\|access_groups" -- src`

预期残留（本任务处理后应为零）：agent.py、workflow、tools/agent_memory.py 已在 Task 4/5 清理；此处处理审计层（audit/base.py 的 `user_groups` 用法归 Task 8）与任何 docstring 示例。**特别注意**：`User` 模型是 `extra="allow"`，构造点漏改不会报错，必须靠 grep 而非测试失败发现。

Run: `python -m pytest tests/ -v -k "agent or workflow or memory"` 
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "BREAKING refactor(models): remove access_groups, group_memberships, UiFeatures"
```

---

### Task 8: 审计事件清理

**Files:**
- Modify: `src/vanna/core/audit/models.py`
- Modify: `src/vanna/core/audit/base.py`
- Modify: `src/vanna/core/audit/__init__.py`
- Modify: `src/vanna/core/__init__.py:29-36,151`
- Modify: `src/vanna/core/agent/config.py`（AuditConfig）

- [ ] **Step 1: models.py**

`AuditEventType` 删除 `TOOL_ACCESS_CHECK`、`UI_FEATURE_ACCESS_CHECK`、`ACCESS_DENIED`（L20-21、L33）；删除 `ToolAccessCheckEvent`、`UiFeatureAccessCheckEvent` 类（L63-79、L103-109）；`AuditEvent` 删除 `user_groups` 字段（L48）。`ToolInvocationEvent` 删除 `ui_features_available` 字段（L85）。

- [ ] **Step 2: base.py**

`AuditLogger` 删除 `log_tool_access_check`、`log_ui_feature_access` 方法；`log_tool_invocation` 删除 `ui_features` 形参及其事件组装行；所有事件构造中的 `user_groups` 传参删除。（方法内部实现以实际文件为准，按名称定位删除。）

- [ ] **Step 3: 导出同步**

`src/vanna/core/audit/__init__.py`：import 与 `__all__` 中删除 `ToolAccessCheckEvent`、`UiFeatureAccessCheckEvent`。
`src/vanna/core/__init__.py`：L29-36 import 块与 L151 `__all__` 中同步删除。

- [ ] **Step 4: AuditConfig 清理**

`config.py` 的 `AuditConfig` 删除 `log_tool_access_checks`、`log_ui_feature_checks` 两个字段。

- [ ] **Step 5: 验证**

Run: `python -c "from vanna.core import Agent, ToolRegistry; from vanna.core.audit import AuditLogger, AuditEventType; print('imports OK')"`
Expected: `imports OK`

Run: `python -m pytest tests/ -v -k "audit or agent or registry"`
Expected: PASS（audit 相关测试引用删除事件的部分在 Task 10 统一处理；若此处已有失败且仅因事件删除导致，同步小改）

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "BREAKING refactor(audit): remove access-control events and user_groups"
```

---

### Task 9: legacy adapter 与 examples 清理

**Files:**
- Modify: `src/vanna/legacy/adapter.py`
- Modify: `examples/` 下引用 `permissions` / `group_memberships` 的文件（grep 定位）
- Modify: `src/vanna/core/workflow/base.py`（误导性 docstring）

- [ ] **Step 1: legacy/adapter.py**

Run: `git grep -n "access_groups\|group_memberships\|permissions" -- src/vanna/legacy`

删除 3 处 `register_local_tool` 的权限组参数（Task 6 已改签名的此处确认）；`save_question_tool_args` 工具的 admin 限制注释/逻辑（如有 wrapper 残留）删除；构造 `User` 时的 `group_memberships` / `permissions` 传参删除。

- [ ] **Step 2: examples**

Run: `git grep -n "group_memberships\|permissions=\[\]" -- examples`

每个命中点删除相应字段传参。

- [ ] **Step 3: workflow/base.py docstring**

`WorkflowHandler` 的类/方法 docstring 中如有"access control / admin"等过时描述（如 `try_handle` 注释提及权限），更新为当前实际语义（命令处理与短路）。

- [ ] **Step 4: 全局零残留验证**

Run: `git grep -rn "access_groups\|group_memberships\|UiFeature\|_validate_tool_permissions\|_LocalToolWrapper" -- src tests examples`
Expected: 无输出（若有，逐个清理后重跑）

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "refactor: purge group-permission remnants from legacy adapter and examples"
```

---

## 阶段 C：测试收口（Task 10）

### Task 10: 测试适配与清理

**Files:**
- Modify: `tests/test_tool_permissions.py`
- Modify: `tests/test_workflow.py`、`tests/test_memory_tools.py`、`tests/test_legacy_adapter.py`、`tests/test_agents.py`、`tests/test_explore_schema_links_tool.py`

- [ ] **Step 1: test_tool_permissions.py 分流**

读该文件（915 行），按两个目的分流：
- **删除**：所有权限相关用例（`access_groups` 注入、`_validate_tool_permissions` 行为、Insufficient group access、`get_schemas` 用户过滤、`_LocalToolWrapper` 包装）
- **保留**：`transform_args` / `ToolRejection` 行级安全用例——把其中 `register_local_tool(tool, [...])` 改为 `register(tool)`，构造 User 时删除 `group_memberships`

- [ ] **Step 2: 其余测试文件适配**

- `test_workflow.py`：`/status` `/memories` `/delete` 用例统一普通 User；starter 卡片断言合并版文案
- `test_memory_tools.py`：UiFeature 依赖（`context.metadata["ui_features_available"]`）删除，断言 detailed CardComponent 视图
- `test_legacy_adapter.py`：权限断言改全员可见
- `test_explore_schema_links_tool.py`：注册方式适配
- `test_agents.py`：工具循环断言（组件数量可能因分支固定化变化——非 admin 用户现在也收到 StatusCard/TaskTracker，断言更新）

- [ ] **Step 3: 全量回归**

Run: `python -m pytest tests/ -v`
Expected: 除已知的 Ollama 环境依赖用例外全部 PASS

- [ ] **Step 4: 提交**

```bash
git add -A
git commit -m "test: adapt suite to auto-registered tools and removed permission system"
```

---

## 阶段 D：.env 桥接（Task 11）

### Task 11: server_runner 配置桥接 + vector_backend

**Files:**
- Modify: `src/vanna/servers/cli/server_runner.py`（`_create_env_agent`）
- Modify: `src/vanna/agents/__init__.py`（`create_basic_agent` 加 `vector_backend`）
- Test: `tests/test_agent_auto_tools.py` 追加用例

- [ ] **Step 1: create_basic_agent 支持 vector_backend**

`src/vanna/agents/__init__.py` 签名追加 `vector_backend: Optional[str] = None`，`agent_memory`/`schema_vector_store` 解析逻辑改为：

```python
    # vector_backend: one declaration derives both stores ("faiss").
    if agent_memory is None:
        if vector_backend == "faiss":
            try:
                from vanna.integrations.vector.faiss import FAISSAgentMemory

                agent_memory = FAISSAgentMemory()
            except ImportError:
                agent_memory = _default_agent_memory()
        else:
            agent_memory = _default_agent_memory()

    if schema_vector_store is None and vector_backend == "faiss":
        try:
            from vanna.integrations.vector.faiss import FAISSSchemaVectorStore

            schema_vector_store = FAISSSchemaVectorStore()
        except ImportError:
            logger.info("faiss extras unavailable; schema_vector_store not derived")
```

（原有 `agent_memory = _default_agent_memory()` 的默认分支被上述逻辑吸收；`logger` 若未导入则加 `import logging; logger = logging.getLogger(__name__)`。）

- [ ] **Step 2: _create_env_agent 读 .env**

`server_runner.py` 的 `_create_env_agent()` 中（现有 LLM env 读取逻辑之后）追加：

```python
    # Tool assembly from environment (pure parsing; creation happens in Agent).
    database_url = os.getenv("DATABASE_URL")
    database = DatabaseConfig(url=database_url) if database_url else None

    extra_tools = []
    raw_tools = os.getenv("EXTRA_TOOLS", "")
    for tool_name in [t.strip() for t in raw_tools.split(",") if t.strip()]:
        if tool_name not in _TOOL_CATALOG:
            raise ValueError(
                f"EXTRA_TOOLS contains unknown tool '{tool_name}'. "
                f"Available: {', '.join(sorted(_TOOL_CATALOG))}"
            )
        extra_tools.append(_TOOL_CATALOG[tool_name]())

    vector_backend = os.getenv("VECTOR_BACKEND") or None
```

文件头部追加目录表与 import：

```python
_TOOL_CATALOG = {
    "list_files": ListFilesTool,
    "read_file": ReadFileTool,
    "write_file": WriteFileTool,
    "edit_file": EditFileTool,
    "search_files": SearchFilesTool,
    "run_python_file": RunPythonFileTool,
    "pip_install": PipInstallTool,
}
```

```python
from vanna.core.agent.config import DatabaseConfig
from vanna.tools.file_system import (
    EditFileTool,
    ListFilesTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
)
from vanna.tools.python import PipInstallTool, RunPythonFileTool
```

`Agent` / `create_basic_agent` 构造调用处透传：`config` 合并 `database=database`（若现有 config 构造方式为位置参数则调整为关键字合并）、`sql_runner=None`（省略）、`extra_tools=extra_tools`、`vector_backend=vector_backend`。

**注意：** 若 `_create_env_agent` 不经 `create_basic_agent` 而直接构造 Agent，则 `extra_tools` 传 Agent 的同名参数、`database` 并入 AgentConfig、`vector_backend` 派生逻辑参照 Step 1 内联（memory 为 None 时才派生）。以实际代码结构为准，原则：**.env 层只做字符串解析，实例创建全部下沉 Agent/工厂**。

- [ ] **Step 3: 追加测试**

`tests/test_agent_auto_tools.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_vector_backend_derives_faiss_stores():
    """create_basic_agent(vector_backend='faiss') derives both stores."""
    faiss_memory = pytest.importorskip("vanna.integrations.vector.faiss")
    from vanna.agents import create_basic_agent

    agent = create_basic_agent(
        llm_service=MagicMock(),
        vector_backend="faiss",
    )
    from vanna.integrations.vector.faiss import FAISSAgentMemory, FAISSSchemaVectorStore

    assert isinstance(agent.agent_memory, FAISSAgentMemory)
    assert isinstance(agent.schema_vector_store, FAISSSchemaVectorStore)
```

（`create_basic_agent` 若有其它必填参数如 `user_resolver`，按其签名补齐 mock。）

- [ ] **Step 4: 验证并提交**

Run: `python -m pytest tests/test_agent_auto_tools.py -v`
Expected: PASS

```bash
git add src/vanna/servers/cli/server_runner.py src/vanna/agents/__init__.py tests/test_agent_auto_tools.py
git commit -m "feat(server): bridge DATABASE_URL/EXTRA_TOOLS/VECTOR_BACKEND env to agent assembly"
```

---

## 阶段 E：文档同步（Task 12）

### Task 12: 文档更新

**Files:**
- Modify: `docs/源码解析/` 下 8 篇（02/03/04/05/08 重点）
- Modify: `MIGRATION_GUIDE.md`
- Modify: `docs/Debug操作指南.md`

- [ ] **Step 1: 源码解析系列**

Run: `git grep -ln "access_groups\|group_memberships\|用户组\|权限\|admin" -- docs/源码解析`

对每篇命中文件：
- 权限体系段落：删除或改写为"权限体系已于本次重构移除（TODO：后期有需要时重新设计）"标注
- [03-核心主干完整运行全流程.md]：工具注册流程改为"Agent 自动装配"描述（能力驱动 + DatabaseConfig 工厂 + extra_tools 三分类）
- [08-二次开发扩展点位汇总.md]：新增"工具自动装配"扩展点说明；`register_local_tool` 示例改 `register`
- [02/04/05]：架构图/模块表/速查表中 UiFeatures、audit 事件、User 字段相关行删除

- [ ] **Step 2: MIGRATION_GUIDE.md**

追加 BREAKING 变更记录章节：

```markdown
## 用户组权限体系移除

以下 API 已删除（后期有需要时将重新设计权限体系）：
- `ToolRegistry.register_local_tool(tool, access_groups)` → `ToolRegistry.register(tool)`
- `Tool.access_groups` 属性、`ToolSchema.access_groups` 字段
- `User.group_memberships` 字段
- `AgentConfig.ui_features`（UiFeatures）及其 5 个 UI 特性开关（行为固定开启）
- 审计事件 `TOOL_ACCESS_CHECK` / `UI_FEATURE_ACCESS_CHECK` / `ACCESS_DENIED` 及 `AuditEvent.user_groups`
- 工作流命令 `/status` `/memories` `/delete` 不再有 admin 门禁

## 工具自动装配

Agent 现按注入能力自动注册工具（`AgentConfig.auto_register_tools` 可关）：
- `agent_memory` → 记忆工具 ×3
- `schema_vector_store` → `explore_schema_links`
- `sql_runner`（或 `AgentConfig.database.url` 经 scheme 工厂派生）→ `run_sql` + `visualize_data`
- `extra_tools` 参数逐个注册

.env 新配置：`DATABASE_URL` / `EXTRA_TOOLS` / `VECTOR_BACKEND`
```

- [ ] **Step 3: Debug操作指南.md**

追加三个 .env 配置项说明（含义、示例值、对应行为）。

- [ ] **Step 4: 提交**

```bash
git add docs/
git commit -m "docs: update for tool auto-assembly and permission system removal"
```

---

## 阶段 F：E2E 验证（Task 13）

### Task 13: 端到端验证

- [x] **Step 1: 全量回归**

Run: `python -m pytest tests/ -v`
Expected: 除 Ollama 环境依赖用例外全部 PASS

- [x] **Step 2: 零残留终检**

Run: `git grep -rn "access_groups\|group_memberships\|UiFeature\|register_local_tool\|_LocalToolWrapper\|_validate_tool_permissions" -- src tests examples`
Expected: 无输出

Run: `git grep -rn "ui_features_available\|log_tool_access_check\|log_ui_feature_access\|ToolAccessCheckEvent\|UiFeatureAccessCheckEvent" -- src tests`
Expected: 无输出

- [x] **Step 3: E2E 手动验证（text-to-sql 链路）**

1. `.env` 追加 `DATABASE_URL=sqlite:///Chinook.sqlite`（仓库根已有 Chinook.sqlite）
2. 按现有调试配置启动后端（VS Code "Vanna FastAPI + Vite HMR" 或惯用 CLI）
3. 验收点：
   - 启动日志无 "text-to-SQL is unavailable" warning
   - 页面发消息 `which artists have the most albums?`，LLM 调用 `run_sql` 返回数据表
   - `/status` 命令显示 SQL 工具就绪
   - 重启服务后历史会话仍存在（SQLite conversation store）
4. 完成后把 `.env` 中该行按需保留（本地验证用，不入库）

- [x] **Step 4: 更新 spec checklist**

按验证结果勾选 `.trae/specs/refactor-agent-tool-auto-assembly/checklist.md` 各项。

---

# Task Dependencies

- Task 1、Task 2 无依赖，可并行
- Task 3 依赖 Task 1 + Task 2
- Task 4 依赖 Task 3（同一文件 agent.py，顺序改避免冲突）
- Task 5 独立于 Task 3/4 的语义（可与 Task 4 并行，但同文件 tests 建议顺序）
- Task 6 依赖 Task 4（registry.execute 的 audit 调用与 agent.py 解耦后再动引擎）
- Task 7 依赖 Task 4 + Task 5（模型字段删除前消费端必须已清理）
- Task 8 依赖 Task 4 + Task 6（audit 方法删除前调用点必须已删）
- Task 9 依赖 Task 6-8
- Task 10 依赖 Task 4-9（收口）
- Task 11 依赖 Task 3
- Task 12 依赖 Task 3-11（代码定稿后写文档）
- Task 13 依赖全部

# Self-Review 结论

- **Spec 覆盖**：三分类装配（Task 1-3）、scheme 工厂（Task 2）、优先级与 warning（Task 3）、vector_backend（Task 11）、权限移除含 UiFeatures/workflow/audit/User（Task 4-9）、.env 桥接（Task 11）、文档（Task 12）、checklist 勾选（Task 13）——spec 各 Requirement 均有对应任务
- **类型一致性**：`DatabaseConfig.url`、`create_sql_runner(url)`、`register(tool)`、`_register_if_absent`、`_TOOL_CATALOG` 在各任务间签名一致；`register_local_tool` 在 Task 3（旧 API）→ Task 6（新 API）的迁移点已在 Task 6 Step 2 显式列出
- **无占位符**：所有代码步骤含完整代码；文档任务（Task 12）为内容指导而非代码，附了 MIGRATION_GUIDE 的完整章节文本
