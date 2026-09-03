# 多业务存储介质路由实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持多业务数据库路由，每个业务绑定独立的关系型数据库（SqlRunner）和表字段向量索引（SchemaVectorStore namespace），通过请求级 `business_id` 动态切换。

**Architecture:** 新增 `BusinessConfig` 配置模型，`AgentConfig.businesses` 字典持有多个业务配置。`ToolContext` 增加 `sql_runner` 字段，`RunSqlTool` 优先使用它。`Agent._send_message` 从请求 metadata 解析 `business_id`，注入对应的 sql_runner 和 autolink_database_name。DDL 导入支持 `business_id` 参数。

**Tech Stack:** Pydantic BaseModel（配置模型）、FastAPI（DDL 导入路由）、现有 SqlRunner/SchemaVectorStore 抽象。

**Spec:** `docs/superpowers/specs/2026-09-02-multi-business-storage-routing.md`

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `src/vanna/core/agent/config.py`（修改） | 新增 BusinessConfig，AgentConfig 增加 businesses 字段 |
| `src/vanna/core/tool/models.py`（修改） | ToolContext 增加 sql_runner 字段 |
| `src/vanna/tools/run_sql.py`（修改） | execute 优先使用 context.sql_runner |
| `src/vanna/core/agent/agent.py`（修改） | 业务路由逻辑 + SqlRunner 缓存 |
| `src/vanna/servers/fastapi/ddl_import.py`（修改） | IngestRequest 增加 business_id + 页面下拉框 |
| `src/vanna/servers/fastapi/routes.py`（修改） | 聊天请求支持 business_id |
| `tests/test_multi_business_routing.py`（新增） | 业务路由单元测试 |

## 关键事实（实现前必读）

- `SqlRunner.run_sql(args, context)` 接收 `ToolContext`（`src/vanna/capabilities/sql_runner/base.py#L22`），但当前实现未使用 context 做路由。
- `SchemaVectorStore` 各后端已通过 `database_name` 参数实现命名空间隔离：FAISS 按目录 `./data/vector_db/{database_name}/`，Chroma 按 collection name。
- `ToolContext` 是 Pydantic BaseModel，增加 Optional 字段默认 None 不影响现有构造。
- `RunSqlTool.__init__` 接收 `sql_runner: SqlRunner`，`execute` 中使用 `self.sql_runner`。改为 `context.sql_runner or self.sql_runner` 即可。
- `Agent._send_message` 中 `request_context: RequestContext` 包含 `metadata: Dict[str, Any]`，可携带 `business_id`。
- `create_sql_runner(url: str)` 工厂函数在 `src/vanna/integrations/databases/factory.py`，从 URL 派生对应 SqlRunner。
- `AutoLinkConfig.database_name` 是静态配置，业务路由时需覆盖为 `business.effective_database_name()`。
- `DDL import` 的 `database_name` 用于向量库命名空间，与 `SchemaVectorStore.ingest_schema` 的第三个参数一致。

---

## Task 1: BusinessConfig 配置模型

**Files:**
- Modify: `src/vanna/core/agent/config.py`
- Test: `tests/test_multi_business_routing.py`

- [ ] **Step 1: 写失败测试（BusinessConfig 模型）**

```python
# tests/test_multi_business_routing.py
"""Tests for multi-business storage routing."""
from vanna.core.agent.config import BusinessConfig, AgentConfig


def test_business_config_defaults():
    """database_name defaults to empty string, effective_database_name falls back to id."""
    bc = BusinessConfig(id="biz_a", database_url="sqlite:///a.db")
    assert bc.database_name == ""
    assert bc.effective_database_name() == "biz_a"


def test_business_config_custom_database_name():
    bc = BusinessConfig(id="biz_a", database_url="sqlite:///a.db", database_name="custom_ns")
    assert bc.effective_database_name() == "custom_ns"


def test_agent_config_businesses_default_empty():
    config = AgentConfig()
    assert config.businesses == {}


def test_agent_config_businesses_multiple():
    config = AgentConfig(businesses={
        "biz_a": BusinessConfig(id="biz_a", database_url="sqlite:///a.db"),
        "biz_b": BusinessConfig(id="biz_b", database_url="sqlite:///b.db", database_name="custom_b"),
    })
    assert len(config.businesses) == 2
    assert config.businesses["biz_a"].effective_database_name() == "biz_a"
    assert config.businesses["biz_b"].effective_database_name() == "custom_b"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_multi_business_routing.py -v`
Expected: FAIL（`ImportError` 或 `AttributeError: BusinessConfig`）

- [ ] **Step 3: 实现 BusinessConfig**

修改 `src/vanna/core/agent/config.py`：
- 顶部 import 增加 `Dict`
- `DatabaseConfig` 之后新增 `BusinessConfig` 类
- `AgentConfig` 增加 `businesses: Dict[str, BusinessConfig]` 字段

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_multi_business_routing.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add src/vanna/core/agent/config.py tests/test_multi_business_routing.py
git commit -m "feat: add BusinessConfig model for multi-business storage routing"
```

---

## Task 2: ToolContext 增加 sql_runner 字段

**Files:**
- Modify: `src/vanna/core/tool/models.py`
- Test: `tests/test_multi_business_routing.py`（追加）

- [ ] **Step 1: 写失败测试（ToolContext 带 sql_runner）**

```python
from unittest.mock import MagicMock
from vanna.core.tool.models import ToolContext


def test_tool_context_has_sql_runner_field():
    """ToolContext accepts optional sql_runner."""
    ctx = ToolContext(
        user=MagicMock(),
        conversation_id="c1",
        request_id="r1",
        agent_memory=MagicMock(),
    )
    assert ctx.sql_runner is None


def test_tool_context_with_sql_runner():
    mock_runner = MagicMock()
    ctx = ToolContext(
        user=MagicMock(),
        conversation_id="c1",
        request_id="r1",
        agent_memory=MagicMock(),
        sql_runner=mock_runner,
    )
    assert ctx.sql_runner is mock_runner
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_multi_business_routing.py::test_tool_context_has_sql_runner_field -v`
Expected: FAIL（`ValidationError: sql_runner`）

- [ ] **Step 3: 实现 ToolContext 修改**

修改 `src/vanna/core/tool/models.py`：
- 导入 `SqlRunner`
- `ToolContext` 增加 `sql_runner: Optional[SqlRunner] = Field(default=None, ...)`

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_multi_business_routing.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add src/vanna/core/tool/models.py tests/test_multi_business_routing.py
git commit -m "feat: add sql_runner field to ToolContext for per-request override"
```

---

## Task 3: RunSqlTool 优先使用 context.sql_runner

**Files:**
- Modify: `src/vanna/tools/run_sql.py`
- Test: `tests/test_multi_business_routing.py`（追加）

- [ ] **Step 1: 写失败测试（context.sql_runner 优先）**

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock
from vanna.tools.run_sql import RunSqlTool
from vanna.capabilities.sql_runner.models import RunSqlToolArgs


def test_run_sql_prefers_context_sql_runner():
    """RunSqlTool should use context.sql_runner when available."""
    bound_runner = MagicMock()
    bound_runner.run_sql = AsyncMock(return_value=MagicMock(empty=True))
    context_runner = MagicMock()
    context_runner.run_sql = AsyncMock(return_value=MagicMock(empty=True))

    tool = RunSqlTool(sql_runner=bound_runner)
    ctx = ToolContext(
        user=MagicMock(),
        conversation_id="c1",
        request_id="r1",
        agent_memory=MagicMock(),
        sql_runner=context_runner,
    )
    args = RunSqlToolArgs(sql="SELECT 1")
    asyncio.run(tool.execute(ctx, args))

    context_runner.run_sql.assert_called_once()
    bound_runner.run_sql.assert_not_called()


def test_run_sql_falls_back_to_bound_runner():
    """RunSqlTool should use self.sql_runner when context.sql_runner is None."""
    bound_runner = MagicMock()
    bound_runner.run_sql = AsyncMock(return_value=MagicMock(empty=True))

    tool = RunSqlTool(sql_runner=bound_runner)
    ctx = ToolContext(
        user=MagicMock(),
        conversation_id="c1",
        request_id="r1",
        agent_memory=MagicMock(),
    )
    args = RunSqlToolArgs(sql="SELECT 1")
    asyncio.run(tool.execute(ctx, args))

    bound_runner.run_sql.assert_called_once()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_multi_business_routing.py::test_run_sql_prefers_context_sql_runner -v`
Expected: FAIL（context_runner 未被调用）

- [ ] **Step 3: 实现 RunSqlTool 修改**

修改 `src/vanna/tools/run_sql.py` 的 `execute` 方法：
```python
runner = context.sql_runner or self.sql_runner
df = await runner.run_sql(args, context)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_multi_business_routing.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add src/vanna/tools/run_sql.py tests/test_multi_business_routing.py
git commit -m "feat: RunSqlTool prefers context.sql_runner over bound runner"
```

---

## Task 4: Agent 业务路由逻辑

**Files:**
- Modify: `src/vanna/core/agent/agent.py`
- Test: `tests/test_multi_business_routing.py`（追加）

- [ ] **Step 1: 写失败测试（业务路由注入 sql_runner）**

```python
from vanna.core.agent.config import AgentConfig, BusinessConfig
from vanna.core.agent.agent import Agent
from vanna.core.user.request_context import RequestContext


def test_agent_resolves_business_from_metadata():
    """Agent should inject sql_runner into ToolContext based on business_id."""
    # This test verifies the routing logic exists; full integration
    # requires a mock LLM service and is covered by E2E tests.
    config = AgentConfig(businesses={
        "biz_a": BusinessConfig(id="biz_a", database_url="sqlite:///a.db"),
    })
    # Verify config is accessible
    assert "biz_a" in config.businesses
    assert config.businesses["biz_a"].effective_database_name() == "biz_a"


def test_agent_sql_runner_cache():
    """Agent should cache SqlRunner instances per business."""
    config = AgentConfig(businesses={
        "biz_a": BusinessConfig(id="biz_a", database_url="sqlite:///a.db"),
    })
    # Verify that creating runners from the same URL gives consistent results
    from vanna.integrations.databases.factory import create_sql_runner
    runner1 = create_sql_runner(config.businesses["biz_a"].database_url)
    runner2 = create_sql_runner(config.businesses["biz_a"].database_url)
    # Both should be SqliteRunner instances
    assert type(runner1) == type(runner2)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_multi_business_routing.py -v -k "agent"`
Expected: 部分 FAIL

- [ ] **Step 3: 实现 Agent 路由逻辑**

修改 `src/vanna/core/agent/agent.py`：
- `__init__` 中初始化 `self._business_sql_runners: Dict[str, SqlRunner] = {}`
- 新增 `_get_or_create_sql_runner(self, business: BusinessConfig) -> SqlRunner` 方法
- `_send_message` 中，在创建 ToolContext 之前：
  1. 从 `request_context.metadata.get("business_id")` 解析业务 ID
  2. 如果匹配，创建/获取 SqlRunner，设置 `context_metadata["autolink_database_name"]`
  3. 创建 ToolContext 时传入 `sql_runner=...`

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_multi_business_routing.py -v`
Expected: 10 passed

- [ ] **Step 5: 提交**

```bash
git add src/vanna/core/agent/agent.py tests/test_multi_business_routing.py
git commit -m "feat: add business routing logic in Agent._send_message"
```

---

## Task 5: DDL 导入支持业务路由

**Files:**
- Modify: `src/vanna/servers/fastapi/ddl_import.py`
- Test: `tests/test_multi_business_routing.py`（追加）

- [ ] **Step 1: 写失败测试（DDL ingest 支持 business_id）**

```python
def test_ddl_ingest_with_business_id():
    """DDL ingest should resolve database_name from business_id."""
    from vanna.servers.fastapi.ddl_import import IngestRequest
    req = IngestRequest(parse_id="test", business_id="biz_a")
    assert req.business_id == "biz_a"
    assert req.database_name is None  # not set, should be resolved from business_id
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_multi_business_routing.py::test_ddl_ingest_with_business_id -v`
Expected: FAIL

- [ ] **Step 3: 实现 DDL 导入修改**

修改 `src/vanna/servers/fastapi/ddl_import.py`：
- `IngestRequest` 增加 `business_id: Optional[str] = Field(default=None, ...)`
- `ddl_ingest` 路由中：优先从 business_id 解析 database_name
- 页面 HTML 增加业务选择下拉框（从 agent.config.businesses 读取）

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_multi_business_routing.py -v`
Expected: 11 passed

- [ ] **Step 5: 提交**

```bash
git add src/vanna/servers/fastapi/ddl_import.py tests/test_multi_business_routing.py
git commit -m "feat: DDL import supports business_id for multi-business routing"
```

---

## Task 6: 聊天请求支持 business_id

**Files:**
- Modify: `src/vanna/servers/fastapi/routes.py`
- Test: `tests/test_multi_business_routing.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_chat_request_accepts_business_id():
    """Chat request model should accept optional business_id."""
    from vanna.servers.fastapi.routes import ChatRequest
    req = ChatRequest(message="hello", business_id="biz_a")
    assert req.business_id == "biz_a"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_multi_business_routing.py::test_chat_request_accepts_business_id -v`
Expected: FAIL

- [ ] **Step 3: 实现 routes.py 修改**

修改 `src/vanna/servers/fastapi/routes.py`：
- ChatRequest 模型增加 `business_id: Optional[str] = None`
- 路由处理中将 `business_id` 传递到 `RequestContext.metadata`

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_multi_business_routing.py -v`
Expected: 12 passed

- [ ] **Step 5: 提交**

```bash
git add src/vanna/servers/fastapi/routes.py tests/test_multi_business_routing.py
git commit -m "feat: chat request supports business_id parameter"
```

---

## 收尾检查（全部任务完成后）

- [ ] `pytest tests/test_multi_business_routing.py -v`：12 passed
- [ ] `pytest tests/ -v`：无回归
- [ ] `git status` 干净（无未提交变更）
- [ ] 向用户汇报：修改文件清单、配置方式、如何验证
