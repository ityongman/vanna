# Agent 工具自动装配与用户组体系移除 Spec

## Why

当前默认 Agent 的工具注册表为空（`create_basic_agent` 中 `tool_registry = ToolRegistry()`），text-to-sql 链路断裂；工具注册完全依赖手工调用，且与提示词体系脱节。同时项目中的用户组权限体系（access_groups/UiFeatures/admin 检查）对当前阶段是负担。需要将工具注入改为"能力/配置驱动自动装配"，让提示词分支随注册自动激活，实现 `.env` 一行配置跑通 text-to-sql。

## What Changes

### 工具三分类自动装配

工具按依赖特征分三类，注入方式如下：

| 类别 | 工具 | 注入方式 |
|---|---|---|
| 第 1 类：vector db 工具 | 记忆工具 ×3（search_saved_correct_tool_uses、save_question_tool_args、save_text_memory）+ explore_schema_links | Agent 检测到 `agent_memory` / `schema_vector_store` 能力存在即自动注册（工具均为零构造依赖、ToolContext 运行时绑定） |
| 第 2 类：db 工具 | run_sql + visualize_data | 配置驱动：`AgentConfig.database.url` 的 scheme → 工厂派生对应 SqlRunner；无配置时打 warning 提示 text-to-sql 能力缺失 |
| 第 3 类：其它工具 | 文件系统、Python 等 | `extra_tools: List[Tool]` 参数 + `.env` 字符串名单（EXTRA_TOOLS） |

### 核心机制变更

- `AgentConfig` 新增：`DatabaseConfig(url)` 配置节、`auto_register_tools: bool = True` 开关、`vector_backend` 配置
- Agent 内部新增 SqlRunner 工厂：URL scheme → Runner 实例映射（覆盖现有 12 个 Runner 实现）
- Agent 装配优先级：① 显式 `sql_runner` 实例参数（测试 mock 用）→ ② `config.database` 配置 → ③ 皆无则 warning
- `vector_backend` 一次声明同时派生 `FAISSAgentMemory` + `FAISSSchemaVectorStore`（消除双重声明）
- 注册逻辑位于 `Agent.__init__` 私有方法 `_auto_register_tools()`（所有装配路径统一受益）
- **BREAKING**：`ToolRegistry.register_local_tool(tool, access_groups)` → `register(tool)`，移除权限参数

### 用户组体系整体移除（**BREAKING**）

- `User.group_memberships` 字段删除；`Tool.access_groups` 属性、`ToolSchema.access_groups` 字段删除
- `ToolRegistry`：`_LocalToolWrapper`、`_validate_tool_permissions`、`get_schemas` 用户过滤、`execute()` 权限拦截全部删除
- `UiFeatures` 组权限体系删除，5 个 UI 特性改为固定开启行为
- workflow `/status` `/memories` `/delete` 移除 admin 检查，全员可用；starter 卡片合并为单一版本
- 审计：`TOOL_ACCESS_CHECK`、`UI_FEATURE_ACCESS_CHECK`、`ACCESS_DENIED` 事件类型及 `user_groups` 字段删除
- 保留与用户组正交的 `transform_args` / `ToolRejection` 行级安全机制
- 文档标注 TODO：权限体系已移除，后期有需要时重新设计

### .env 配置入口（纯解析桥接）

```env
DATABASE_URL=sqlite:///Chinook.sqlite   # scheme 工厂自动派生 Runner
EXTRA_TOOLS=list_files,read_file        # 字符串名单，内置目录解析
VECTOR_BACKEND=faiss                    # 一次声明派生双 store
```

### 范围外（本次不做）

- 前端设置页面/工具管理 UI（后期统一做页面时实现，本次仅在结构上预留兼容性）
- 提示词体系改造（SystemPromptBuilder 已按工具存在性动态生成，自动注册后分支自动激活，无需改动）

## Impact

- Affected code:
  - 核心：`src/vanna/core/agent/agent.py`、`src/vanna/core/agent/config.py`、`src/vanna/core/registry.py`、`src/vanna/core/tool/{base,models}.py`、`src/vanna/core/user/models.py`、`src/vanna/core/workflow/default.py`、`src/vanna/core/audit/{models,base}.py`
  - 装配：`src/vanna/agents/__init__.py`、`src/vanna/servers/cli/server_runner.py`
  - 连带：`src/vanna/legacy/adapter.py`、`src/vanna/tools/agent_memory.py`、`src/vanna/core/__init__.py`、`src/vanna/core/audit/__init__.py`、examples 若干
  - 测试：`tests/test_tool_permissions.py`（权限部分删除，transform_args 部分保留）、`tests/test_workflow.py`、`tests/test_memory_tools.py`、`tests/test_legacy_adapter.py`、`tests/test_agents.py` 等断言重写
  - 文档：`docs/源码解析/` 下 8 篇（权限概念 133 处提及）、`MIGRATION_GUIDE.md`、`docs/Debug操作指南.md`（.env 新配置项）
- 新增文件：SqlRunner 工厂模块（URL 解析 + scheme 映射）

## ADDED Requirements

### Requirement: 能力驱动的工具自动注册

Agent SHALL 在 `auto_register_tools=True`（默认）时，根据自身持有的能力实例自动注册对应工具：

- 检测到 `agent_memory` → 注册记忆工具 ×3（SearchSavedCorrectToolUsesTool、SaveQuestionToolArgsTool、SaveTextMemoryTool）
- 检测到 `schema_vector_store` → 注册 ExploreSchemaLinksTool
- 解析出 sql_runner（实例参数或配置派生）→ 注册 RunSqlTool + VisualizeDataTool
- `extra_tools` 列表逐个注册
- 已存在于注册表中的工具名不重复注册

#### Scenario: 提供记忆能力自动激活提示词
- **WHEN** Agent 构造时传入 agent_memory 且注册表中无同名记忆工具
- **THEN** 记忆工具 ×3 被自动注册，SystemPromptBuilder 的 MEMORY SYSTEM 分支自动激活（无需提示词侧改动）

#### Scenario: 关闭自动注册
- **WHEN** `AgentConfig(auto_register_tools=False)`
- **THEN** 不发生任何自动注册，注册表保持调用方传入的原状

### Requirement: DatabaseConfig 配置驱动的 SqlRunner 创建

Agent SHALL 按 URL scheme 从工厂映射创建 SqlRunner 实例，覆盖现有 12 个实现（sqlite/mysql/postgresql/mssql/oracle/duckdb/bigquery/clickhouse/hive/presto/snowflake 等）。

#### Scenario: sqlite 配置
- **WHEN** `AgentConfig(database=DatabaseConfig(url="sqlite:///Chinook.sqlite"))`
- **THEN** Agent 内部创建 `SqliteRunner(database_path="Chinook.sqlite")` 并注册 run_sql + visualize_data 工具

#### Scenario: 显式实例优先
- **WHEN** 同时传入 `sql_runner=MockRunner()` 与 `config.database`
- **THEN** 使用显式实例，忽略配置派生（供单测注入 mock）

#### Scenario: 无数据库配置时明示缺陷
- **WHEN** 未提供 sql_runner 且 config.database 为空
- **THEN** 启动时输出 warning 日志提示 text-to-sql 能力缺失（不抛错）

### Requirement: vector_backend 一次声明派生双 store

Agent/装配层 SHALL 支持以单一 backend 声明（如 `VECTOR_BACKEND=faiss`）同时创建 AgentMemory 与 SchemaVectorStore 两个能力实例。

#### Scenario: faiss 声明
- **WHEN** 配置 vector_backend=faiss
- **THEN** 同时派生 FAISSAgentMemory 与 FAISSSchemaVectorStore，无需分别声明两次

### Requirement: .env 配置桥接

server_runner SHALL 纯解析 .env 配置项填充 AgentConfig，不承担任何创建逻辑：`DATABASE_URL` → config.database、`EXTRA_TOOLS` → 工具名单（经内置 name→factory 目录解析）、`VECTOR_BACKEND` → vector_backend。

#### Scenario: 零代码切换数据库
- **WHEN** .env 中 DATABASE_URL 从 sqlite 改为 mysql 连接串
- **THEN** 重启服务即使用 MySQLRunner，零代码改动

## REMOVED Requirements

### Requirement: 用户组权限体系
**Reason**: 用户决策——当前阶段无多租户权限需求，体系增加装配复杂度（权限组配置、admin 分支、审计事件）且 legacy adapter 中 save_question_tool_args 的 admin 限制与记忆学习循环冲突。
**Migration**: `register_local_tool(tool, access_groups)` → `register(tool)`；测试中权限断言重写为全员可见；文档标注 TODO（后期有需要时重新设计）。

### Requirement: UiFeatures 组访问控制
**Reason**: 依赖用户组体系，5 个特性（SHOW_TOOL_NAMES 等）的组过滤随之失去载体。
**Migration**: 5 个 UI 特性改为固定开启行为，`ui_features` 配置项与相关审计事件删除。

### Requirement: 工作流命令 admin 门禁
**Reason**: /status、/memories、/delete 的 admin 检查依赖 group_memberships。
**Migration**: 命令全员可用，starter 卡片合并为单一版本（内容取现 admin 版的完整信息）。

### Requirement: 访问控制审计事件
**Reason**: TOOL_ACCESS_CHECK / UI_FEATURE_ACCESS_CHECK / ACCESS_DENIED 事件随权限体系失去触发条件。
**Migration**: 事件类型、AuditEvent.user_groups 字段、相关 audit logger 方法删除，`__init__.py` 导出清单同步。

### Requirement: User.group_memberships 数据字段
**Reason**: 唯一消费方是权限判定，体系移除后成为死字段。
**Migration**: 全部构造点清理（examples、tests、document_generator 内部用户、evaluation dataset 序列化）；借助全局 grep 验证零残留（注意 User 模型 `extra="allow"` 会静默容忍漏改）。
