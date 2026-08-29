# Checklist

## 阶段 A：自动装配核心
- [x] AgentConfig 包含 DatabaseConfig、auto_register_tools（默认 True）、vector_backend
- [x] URL scheme 工厂正确派生 12 种 Runner，未知 scheme 报错明确
- [x] 显式 sql_runner 实例参数优先于 config.database 派生
- [x] 无 sql_runner 且无 config.database 时启动打 warning（不抛错）
- [x] agent_memory 存在 → 记忆工具 ×3 自动注册，SystemPromptBuilder MEMORY SYSTEM 分支激活
- [x] schema_vector_store 存在 → explore_schema_links 自动注册
- [x] sql_runner 就绪 → run_sql + visualize_data 自动注册
- [x] extra_tools 逐个注册
- [x] 同名工具不重复注册
- [x] auto_register_tools=False 关闭全部自动注册
- [x] 注册后 /status 命令可见工具数反映自动注册结果

## 阶段 B：用户组移除
- [x] ToolRegistry 无 _LocalToolWrapper / _validate_tool_permissions / execute 权限拦截
- [x] register_local_tool 简化为 register(tool)，全部调用方迁移
- [x] Tool.access_groups、ToolSchema.access_groups、User.group_memberships 字段删除
- [x] /status /memories /delete 全员可用（无 Access Denied 卡片）
- [x] starter 卡片单一版本，无 admin/user 分支
- [x] UiFeatures 体系删除，5 个 UI 特性为固定行为
- [x] 审计无 TOOL_ACCESS_CHECK / UI_FEATURE_ACCESS_CHECK / ACCESS_DENIED / user_groups
- [x] core/__init__.py 与 core/audit/__init__.py 导出清单同步（无 ImportError）
- [x] transform_args / ToolRejection 行级安全机制保留且测试通过
- [x] 全局 grep 验证：access_groups、group_memberships、_LocalToolWrapper、UiFeature、_validate_tool_permissions 零残留（src/ 与 tests/，排除 .venv）
- [x] 文档中标注 TODO：权限体系已移除，后期有需要时重新设计

## 阶段 C：测试
- [x] test_tool_permissions.py 权限部分删除，transform_args 部分适配通过
- [x] test_workflow.py / test_memory_tools.py / test_legacy_adapter.py / test_agents.py 断言重写后通过
- [x] 自动装配新测试覆盖：能力驱动、配置派生、开关、extra_tools、同名跳过
- [x] 全量相关测试通过（无新增失败；38 failed + 1 error 经基线对照证实均为预存环境/测试问题，非本重构回归）

## 阶段 D：配置桥接
- [x] .env 的 DATABASE_URL 解析进 AgentConfig.database
- [x] EXTRA_TOOLS 名单经内置目录解析注册
- [x] VECTOR_BACKEND 一次声明派生 FAISSAgentMemory + FAISSSchemaVectorStore
- [x] 切换 DATABASE_URL 的 scheme 无需改代码

## 阶段 E：文档
- [x] docs/源码解析/ 8 篇权限描述清理 + 自动装配新流程 + TODO 标注
- [x] MIGRATION_GUIDE.md 记录 BREAKING 变更
- [x] docs/Debug操作指南.md 补充 .env 新配置项

## 阶段 F：E2E
- [x] .env 配 DATABASE_URL=sqlite:///Chinook.sqlite 起服务，text-to-sql 链路可用
- [x] 服务启动日志显示自动注册的工具清单