# Tasks

## 阶段 A：Agent 自动装配核心

- [ ] Task 1: 扩展 AgentConfig（`src/vanna/core/agent/config.py`）
  - [ ] 新增 `DatabaseConfig(url: str)` 配置节
  - [ ] 新增 `auto_register_tools: bool = True` 开关
  - [ ] 新增 `vector_backend` 配置项
  - [ ] 删除 `UiFeatures` 体系、`ui_features`、`log_ui_feature_checks`（依赖倒序：先改消费端再删此处，可并入 Task 5-6）

- [ ] Task 2: 实现 SqlRunner 工厂（新文件，如 `src/vanna/integrations/databases/factory.py`）
  - [ ] URL 解析：scheme → Runner 构造（sqlite→SqliteRunner(database_path)、mysql→MySQLRunner、postgresql→PostgresRunner(connection_string) 等覆盖 12 个实现）
  - [ ] 未知 scheme 抛明确异常（列出支持的 scheme 清单）
  - [ ] 单元测试：各 scheme 派生正确、显式实例优先级、异常场景

- [ ] Task 3: Agent 自动装配（`src/vanna/core/agent/agent.py`）
  - [ ] 新增参数：`sql_runner`（可选实例，测试 mock 用）、`extra_tools: List[Tool]`
  - [ ] 装配优先级：显式 sql_runner → config.database 工厂派生 → 皆无打 warning（text-to-sql 能力缺失）
  - [ ] 私有方法 `_auto_register_tools()`：agent_memory→记忆工具×3、schema_vector_store→explore_schema_links、sql_runner→run_sql+visualize_data、extra_tools 逐个注册
  - [ ] 同名工具跳过（不重复注册）
  - [ ] `auto_register_tools=False` 时整体跳过
  - [ ] 装配层 `create_basic_agent`（`src/vanna/agents/__init__.py`）透传新参数

## 阶段 B：用户组体系移除（依赖倒序删除）

- [ ] Task 4: 消费端先行：agent.py 的 UiFeature 分支（5 处改为固定行为）、`ui_features_available` 收集逻辑
- [ ] Task 5: workflow/default.py：/help /status /memories /delete 的 admin 检查删除；starter 卡片合并为单一版本（内容取现 admin 版完整信息）；tools/agent_memory.py 的 SHOW_MEMORY_DETAILED_RESULTS 分支固定
- [ ] Task 6: 引擎删除：registry.py 的 `_LocalToolWrapper`、`_validate_tool_permissions`、`get_schemas` 用户过滤、`execute()` 权限拦截；`register_local_tool(tool, access_groups)` → `register(tool)`
- [ ] Task 7: 模型层删除：Tool.access_groups 属性、ToolSchema.access_groups 字段、User.group_memberships 字段
- [ ] Task 8: 审计清理：TOOL_ACCESS_CHECK/UI_FEATURE_ACCESS_CHECK/ACCESS_DENIED 事件、AuditEvent.user_groups、log_tool_access_check/log_ui_feature_access 方法；同步 core/__init__.py 与 core/audit/__init__.py 导出
- [ ] Task 9: 连带清理：legacy/adapter.py（3 处 access_groups）、examples 中 User(permissions=[])、group_memberships 构造点、docstring 示例、workflow/base.py 误导性文档

## 阶段 C：测试重写（与阶段 B 交替进行）

- [ ] Task 10: test_tool_permissions.py：权限测试部分删除，transform_args 行级安全部分保留并适配新签名
- [ ] Task 11: test_workflow.py / test_memory_tools.py / test_legacy_adapter.py / test_agents.py / test_explore_schema_links_tool.py 断言重写（权限断言→全员可见）
- [ ] Task 12: 新增自动装配测试：能力驱动注册、DatabaseConfig 派生、auto_register_tools 开关、extra_tools、同名跳过

## 阶段 D：.env 桥接 + vector_backend

- [ ] Task 13: server_runner（`src/vanna/servers/cli/server_runner.py`）纯解析桥接：DATABASE_URL→config.database、EXTRA_TOOLS→名单解析（内置 name→factory 目录）、VECTOR_BACKEND→vector_backend
- [ ] Task 14: vector_backend 双 store 派生：一次声明同时创建 AgentMemory + SchemaVectorStore

## 阶段 E：文档同步

- [ ] Task 15: 更新 docs/源码解析/ 8 篇（重点 02 架构、03 运行流程、04 模块解析、05 速查表、08 扩展点位）：权限体系描述移除 + TODO 标注（后期重新设计）+ 工具自动装配新流程
- [ ] Task 16: MIGRATION_GUIDE.md 记录 BREAKING 变更（register_local_tool→register、User 字段删除）；docs/Debug操作指南.md 补充 .env 新配置项说明

## 阶段 F：回归验证

- [ ] Task 17: 全量回归：跑 tests/ 下相关测试（workflow、agents、memory、legacy_adapter、explore_schema_links）
- [ ] Task 18: E2E 验证：.env 配 DATABASE_URL=sqlite:///Chinook.sqlite 起服务，确认工具自动注册、text-to-sql 链路可用、全局 grep 无权限概念残留

# Task Dependencies

- Task 2、Task 1 无依赖，可并行
- Task 3 依赖 Task 1、Task 2
- Task 4-9（用户组移除）内部按依赖倒序，Task 6 依赖 Task 4/5（先删消费端）
- Task 10-12 与 Task 4-9 交替；Task 12 依赖 Task 3
- Task 13-14 依赖 Task 3
- Task 15-16 依赖代码改动完成（Task 3-14）
- Task 17-18 依赖全部
