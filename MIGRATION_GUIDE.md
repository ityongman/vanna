# Migration Guide: Vanna 0.x to Vanna 2.0+

This guide will help you migrate from Vanna 0.x (legacy) to Vanna 2.0+, the new user-aware agent framework.

## Table of Contents
- [Overview of Changes](#overview-of-changes)
- [Quick Migration Path](#quick-migration-path)
- [Migration Strategies](#migration-strategies)
  - [Strategy 1: Using the Legacy Adapter (Recommended for Quick Migration)](#strategy-1-using-the-legacy-adapter-recommended-for-quick-migration)
  - [Strategy 2: Full Migration to New Architecture](#strategy-2-full-migration-to-new-architecture)
- [Key Architectural Differences](#key-architectural-differences)
- [用户组权限体系移除](#用户组权限体系移除)
- [工具自动装配](#工具自动装配)
- [API Mapping](#api-mapping)
- [Common Migration Scenarios](#common-migration-scenarios)
- [Breaking Changes](#breaking-changes)
- [FAQ](#faq)

---

## Overview of Changes

Vanna 2.0+ represents a fundamental architectural shift from a simple LLM wrapper to a full-fledged **user-aware agent framework**. Here are the major changes:

### What's New in 2.0+
- ✅ **User awareness** - Identity and metadata flow through every layer
- ✅ **Web component** - Pre-built UI with streaming responses
- ✅ **Tool registry** - Modular, extensible tool system
- ✅ **Rich UI components** - Tables, charts, status cards (not just text)
- ✅ **Streaming by default** - Progressive responses via SSE
- ✅ **Enterprise features** - Audit logs, rate limiting, observability
- ✅ **FastAPI/Flask servers** - Production-ready backends included

### What Changed from 0.x
- ❌ Direct method calls (`vn.ask()`) → Agent-based workflow
- ❌ Monolithic `VannaBase` class → Modular tool system
- ❌ No user context → User-aware at every layer
- ❌ Simple text responses → Rich streaming UI components

---

## Quick Migration Path

**Can't migrate immediately?** Use the Legacy Adapter to get started quickly:

```python
# Assume you already have a working vn object from your Vanna 0.x code:
# vn = MyVanna(config={"model": "gpt-4"})
# vn.connect_to_postgres(...)
# vn.train(ddl="...")

# NEW: Just add these imports and wrap your existing vn object
from vanna import Agent, AgentConfig
from vanna.servers.fastapi import VannaFastAPIServer
from vanna.core.user import UserResolver, User, RequestContext
from vanna.legacy.adapter import LegacyVannaAdapter
from vanna.integrations.llm.anthropic import AnthropicLlmService

# Define simple user resolver
class SimpleUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        user_email = request_context.get_cookie('vanna_email')
        return User(id=user_email, email=user_email)

# Wrap your existing vn with the adapter
tools = LegacyVannaAdapter(vn)

# Create agent with new LLM service
llm = AnthropicLlmService(model="claude-haiku-4-5")
agent = Agent(llm_service=llm, tool_registry=tools, user_resolver=SimpleUserResolver())

# Run server
server = VannaFastAPIServer(agent)
server.run(host='0.0.0.0', port=8000)

# Now it works with the new Agent framework!
# (See Strategy 1 below for complete example)
```

---

## Migration Strategies

### Strategy 1: Using the Legacy Adapter (Recommended for Quick Migration)

**Best for:** Teams that want to adopt Vanna 2.0+ gradually while maintaining existing code.

#### Step 1: Install Vanna 2.0+

```bash
pip install 'vanna[flask,anthropic]'
```

#### Step 2: Wrap Your Existing VannaBase Instance

```python
from vanna import Agent, AgentConfig
from vanna.servers.fastapi import VannaFastAPIServer
from vanna.core.user import UserResolver, User, RequestContext
from vanna.legacy.adapter import LegacyVannaAdapter
from vanna.integrations.llm.anthropic import AnthropicLlmService

# Assume you already have a working vn object from your existing code:
# vn = MyVanna(config={'model': 'gpt-4', 'api_key': 'your-key'})
# vn.connect_to_postgres(...)
# vn.train(ddl="...")
# etc.

# NEW: Define user resolution (required in 2.0+)
class SimpleUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        user_email = request_context.get_cookie('vanna_email')
        if not user_email:
            raise ValueError("Missing 'vanna_email' cookie")

        # Admin users are tagged via metadata
        if user_email == "admin@example.com":
            return User(id="admin_user", email=user_email, metadata={'role': 'admin'})

        # Regular users are tagged via metadata
        return User(id=user_email, email=user_email, metadata={'role': 'user'})

# NEW: Wrap with legacy adapter
# This automatically registers run_sql and memory tools from your VannaBase instance
tools = LegacyVannaAdapter(vn)

# NEW: Set up LLM for the new Agent framework
llm = AnthropicLlmService(
    model="claude-haiku-4-5",
    api_key="YOUR_ANTHROPIC_API_KEY"
)

# NEW: Create agent with legacy adapter as tool registry
agent = Agent(
    llm_service=llm,
    tool_registry=tools,  # LegacyVannaAdapter is a ToolRegistry
    user_resolver=SimpleUserResolver(),
    config=AgentConfig()
)

# NEW: Create and run server
server = VannaFastAPIServer(agent)

if __name__ == "__main__":
    # Run with: python your_script.py
    # Or: uvicorn your_module:server --host 0.0.0.0 --port 8000
    server.run(host='0.0.0.0', port=8000)
```

**What the LegacyVannaAdapter does:**
- Automatically wraps `vn.run_sql()` as the `run_sql` tool
- Exposes training data from `vn.get_training_data()` as searchable memory (via `search_saved_correct_tool_uses` tool)
- Optionally allows saving new training data (via `save_question_tool_args` tool)
- Maintains your existing database connection and training data

**Pros:**
- ✅ Minimal code changes
- ✅ Preserve existing training data
- ✅ Gradual migration path
- ✅ Get new features (web UI, streaming) immediately

**Cons:**
- ⚠️ Limited user awareness (all requests use same VannaBase instance)
- ⚠️ Can't leverage row-level security
- ⚠️ Missing some advanced features

---

### Strategy 2: Full Migration to New Architecture

**Best for:** New projects or teams ready for a complete rewrite.

#### Before (Vanna 0.x)

```python
from vanna import VannaBase
from vanna.openai_chat import OpenAI_Chat
from vanna.chromadb import ChromaDB_VectorStore

class MyVanna(ChromaDB_VectorStore, OpenAI_Chat):
    def __init__(self, config=None):
        ChromaDB_VectorStore.__init__(self, config=config)
        OpenAI_Chat.__init__(self, config=config)

vn = MyVanna(config={'model': 'gpt-4', 'api_key': 'your-key'})
vn.connect_to_postgres(...)

# Train
vn.train(ddl="CREATE TABLE customers ...")
vn.train(question="Top customers?", sql="SELECT ...")

# Ask
sql = vn.generate_sql("Who are the top customers?")
df = vn.run_sql(sql)
print(df)
```

#### After (Vanna 2.0+)

```python
from vanna import Agent, AgentConfig
from vanna.servers.fastapi import VannaFastAPIServer
from vanna.core.registry import ToolRegistry
from vanna.core.user import UserResolver, User, RequestContext
from vanna.integrations.llm.anthropic import AnthropicLlmService
from vanna.tools import RunSqlTool
from vanna.integrations.databases.relational.postgres import PostgresRunner

# 1. Define user resolution
class MyUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        # Extract from your auth system (JWT, cookies, etc.)
        token = request_context.get_header('Authorization')
        user_data = await self.validate_token(token)

        return User(
            id=user_data['id'],
            email=user_data['email'],
            metadata={'role': user_data['role']}
        )

# 2. Set up tools
tools = ToolRegistry()
postgres_runner = PostgresRunner(
    host="localhost",
    dbname="mydb",
    user="user",
    password="password",
    port=5432
)
tools.register(RunSqlTool(sql_runner=postgres_runner))

# 3. Create agent
llm = AnthropicLlmService(model="claude-sonnet-4-5")
agent = Agent(
    llm_service=llm,
    tool_registry=tools,
    user_resolver=MyUserResolver(),
    config=AgentConfig(stream_responses=True)
)

# 4. Create server
server = VannaFastAPIServer(agent)
app = server.create_app()

# Run with: uvicorn main:app --host 0.0.0.0 --port 8000
# Visit http://localhost:8000 for web UI
```

**Pros:**
- ✅ Full access to new features
- ✅ True user awareness
- ✅ Auditable tool execution
- ✅ Production-ready architecture

**Cons:**
- ⚠️ Requires rewriting code
- ⚠️ Need to migrate training data approach
- ⚠️ Steeper learning curve

---

## Key Architectural Differences

| Feature | Vanna 0.x | Vanna 2.0+ |
|---------|-----------|------------|
| **User Context** | None | `User` object (`id`, `username`, `email`, `metadata`) flows through the request lifecycle |
| **Interaction Model** | Direct method calls (`vn.ask()`) | Agent-based with streaming components |
| **Tools** | Monolithic methods | Modular `Tool` classes with schemas, auto-registered from injected capabilities |
| **Responses** | Plain text/DataFrames | Rich UI components (tables, charts, code) |
| **Training** | `vn.train()` with vector DB | System prompts, context enrichers, RAG tools |
| **Database Connection** | `vn.connect_to_postgres()` | `SqlRunner` implementations as dependencies (or derived via `config.database.url` scheme factory) |
| **Web UI** | None (custom implementation) | Built-in web component + backend |
| **Streaming** | None | Server-Sent Events by default |
| **Audit Logs** | None | Built-in audit logging system (tool invocations, results, AI responses) |

---

## 用户组权限体系移除

Vanna 2.0+ 在本次重构中**整体移除了用户组权限体系**（TODO：后期有需要时重新设计）。以下是完整的 BREAKING 变更清单：

### 删除的字段与属性

| 位置 | 变更 |
|------|------|
| `User` 模型 | 删除 `group_memberships` 字段；用户扩展信息统一走 `metadata`（`id` / `username?` / `email?` / `metadata`） |
| `Tool` 基类 | 删除 `access_groups` 属性；工具不再声明访问组 |
| `ToolSchema` | 删除 `access_groups` 字段 |
| `AgentConfig` | 删除 `ui_features` 配置与整个 UI 特性权限控制体系（原 5 个 UI 特性开关：tool_names / tool_arguments / tool_error / tool_invocation_message_in_chat / memory_detailed_results 固定开启） |

### 删除的方法与逻辑

| 位置 | 变更 |
|------|------|
| `ToolRegistry.register_local_tool(tool, access_groups=[...])` | **删除**，统一改为 `register(tool)`；同名重复注册抛 `ValueError` |
| `ToolRegistry._validate_tool_permissions()` | 删除；`execute()` 流程不再做权限拦截 |
| `ToolRegistry._LocalToolWrapper` | 删除 |
| `ToolRegistry.get_schemas()` | 不再接收 `user` 参数，不再按用户组过滤，返回全部已注册工具的 Schema |
| `AuditLogger.log_tool_access_check()` / `log_ui_feature_access()` | 删除；`TOOL_ACCESS_CHECK` / `UI_FEATURE_ACCESS_CHECK` / `ACCESS_DENIED` 审计事件删除，`AuditEvent.user_groups` 字段删除 |
| 工作流命令 | `/status` `/memories` `/delete` 不再有 admin 门禁，所有用户可直接使用 |

### 迁移动作（旧代码 → 新代码）

```python
# 旧：用户带组
User(id="u1", email="a@b.com", group_memberships=["admin"])
# 新：使用 metadata 携带扩展信息
User(id="u1", email="a@b.com", metadata={"role": "admin"})

# 旧：注册工具并指定访问组
tools.register_local_tool(RunSqlTool(sql_runner=runner), access_groups=["admin"])
# 新：直接注册（同名重复注册抛 ValueError）
tools.register(RunSqlTool(sql_runner=runner))

# 旧：按用户过滤获取工具 Schema
tools.get_schemas(user)
# 新：无参数，返回全部工具 Schema
tools.get_schemas()
```

> [!NOTE] 权限语义边界：以上删除仅针对**用户组权限体系**。数据库账号授权（如 PG `permission denied`、MySQL 授权）、文件系统权限（如 ChromaDB `persist_directory` 权限不足）与 SQL 注入防护（`transform_args()` RLS 注入、`RunSqlTool` 子类安全规则）等非用户组语义的"权限"仍然有效。

---

## 工具自动装配

Vanna 2.0+ 的 Agent 不再需要手工逐个注册内置工具：`Agent.__init__` 末尾会调用 `_auto_register_tools()`，按注入的能力组件自动注册对应工具（`AgentConfig.auto_register_tools=True` 时，默认开启）。

### 三分类装配规则

1. **vector-db 工具**：注入 `agent_memory` → 注册 3 个记忆工具：`search_saved_correct_tool_uses`、`save_question_tool_args`、`save_text_memory`（运行时经 `ToolContext` 绑定实际记忆实现）；注入 `schema_vector_store` → 再注册 `explore_schema_links`（AutoLink schema 链接）。
2. **db 工具**：注入 `sql_runner` → 注册 `run_sql` + `visualize_data`（text-to-SQL）；未注入 `sql_runner` 但设置了 `config.database.url` → 经 `create_sql_runner(url)` scheme 工厂派生 SqlRunner 后再注册。工厂支持 10 种 scheme：`sqlite` / `duckdb` / `mysql` / `postgresql` / `postgres` / `mssql` / `oracle` / `clickhouse` / `hive` / `presto`；BigQuery / Snowflake / Databricks 等凭证书/项目认证的引擎需显式构造 runner 传入。两者皆无时记录 warning，text-to-SQL 不可用。
3. **其他场景工具**：`extra_tools` 列表中的自定义工具逐个原样注册。

每个注册均经 `_register_if_absent()`，同名工具已存在时捕获 `ValueError` 静默跳过（不会被覆盖）；`auto_register_tools=False` 可整体关闭自动装配，改用手工 `register()`。

### 代码示例

```python
from vanna.core import AgentConfig
from vanna.core.agent.config import DatabaseConfig
from vanna.agents import create_basic_agent

# 只指定数据库 URL：SqlRunner 与 run_sql/visualize_data 自动装配
agent = create_basic_agent(
    llm_service=llm,
    config=AgentConfig(
        stream_responses=True,
        database=DatabaseConfig(url="sqlite:///Chinook.sqlite"),
    ),
    # vector_backend="faiss" 时自动派生 FAISSAgentMemory + FAISSSchemaVectorStore
    # （faiss 不可用（ImportError）时回退默认内存实现）
)

# 或显式注入 runner 与附加工具
from vanna.integrations.databases.factory import create_sql_runner

runner = create_sql_runner("postgresql://user:pwd@localhost:5432/analytics")
agent = create_basic_agent(
    llm_service=llm,
    sql_runner=runner,            # → 自动注册 run_sql + visualize_data
    extra_tools=[MyCustomTool()], # → 逐个注册
)
```

### 服务端 .env 桥接（`server_runner.py`）

| 环境变量 | 作用 |
|---------|------|
| `DATABASE_URL` | 映射为 `config.database`（经 `create_sql_runner` scheme 工厂派生 SqlRunner） |
| `EXTRA_TOOLS` | 逗号分隔的工具名名单，从内置目录（7 个工具：list_files / read_file / write_file / edit_file / search_files / run_python_file / pip_install）解析并注入 `extra_tools`；未知名抛 `ValueError` 并列出可用名 |
| `VECTOR_BACKEND` | 设为 `faiss` 时同时派生 `FAISSAgentMemory` 与 `FAISSSchemaVectorStore`（ImportError 回退默认记忆实现 / schema store 置 None） |

---

## Summary

| If you want to... | Use this strategy |
|-------------------|-------------------|
| Migrate quickly with minimal changes | **Strategy 1: Legacy Adapter** |
| Get full access to new features | **Strategy 2: Full Migration** |
| Support both legacy and new code | **Strategy 1** initially, then gradual migration |
| Start a new project | **Strategy 2: Full Migration** |

**Recommended Path:**
1. Start with Legacy Adapter for quick migration
2. Gradually rewrite critical paths to native 2.0+ architecture
3. Eventually remove Legacy Adapter once fully migrated

Good luck with your migration! 🚀
