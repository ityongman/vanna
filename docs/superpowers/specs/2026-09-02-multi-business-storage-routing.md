# 多业务存储介质路由设计文档

日期：2026-09-02

## 背景与目标

vanna 当前的存储架构分为两类：

1. **项目自身存储**：会话历史（ConversationStore）、LLM 分析结果（AgentMemory）—— 按用户隔离或全局共享，项目自行管理
2. **三方业务数据**：业务关系型数据库（SqlRunner）、表字段向量索引（SchemaVectorStore）—— 当前在 Agent 初始化时一次性绑定，无法按业务动态切换

问题场景：业务A使用数据库AAA，业务B使用数据库BBB，每个业务有独立的表结构需要向量化存储。当前架构无法支持这种多业务路由。

## 决策记录

| 决策点 | 选择 | 理由 |
|---|---|---|
| 业务配置位置 | `AgentConfig.businesses` 字典 | 与现有 `database`、`autolink_config` 平级，配置集中 |
| SqlRunner 路由方式 | ToolContext 增加 `sql_runner` 字段，请求级覆盖 | 最小侵入，RunSqlTool 一行改动 |
| SchemaVectorStore 路由 | 复用现有 `database_name` 命名空间 | 各后端已实现按 database_name 隔离，无需改接口 |
| SqlRunner 缓存 | Agent 实例级缓存 `_business_sql_runners` | 避免每次请求创建新连接 |
| 业务标识来源 | `request_context.metadata["business_id"]` | 复用现有 metadata 机制，无需改 UserResolver |

## 存储介质分类

### 1. 项目自身需要（不改动）

| 类型 | 用途 | 存储位置 | 隔离方式 |
|------|------|----------|----------|
| ConversationStore | 会话历史 | `./data/db/conversations.db` | 按 user.id 隔离 |
| AgentMemory | LLM 分析结果 | `./data/vector_db/memory` | 全局共享 |

### 2. 三方业务数据（需要按业务路由）

| 类型 | 用途 | 配置字段 | 隔离方式 |
|------|------|----------|----------|
| SqlRunner | 查询业务数据 | `BusinessConfig.database_url` | 按 business_id 路由 |
| SchemaVectorStore | 表字段向量信息 | `BusinessConfig.database_name` | 按 database_name 命名空间 |

## 架构

### 新增组件

1. **`BusinessConfig`**（`src/vanna/core/agent/config.py`）
   - 字段：`id`、`database_url`、`database_name`（默认回退到 id）
   - 方法：`effective_database_name() -> str`

2. **`AgentConfig.businesses`**（`src/vanna/core/agent/config.py`）
   - 类型：`Dict[str, BusinessConfig]`
   - key 为 business_id

3. **`ToolContext.sql_runner`**（`src/vanna/core/tool/models.py`）
   - 类型：`Optional[SqlRunner]`，默认 None
   - 当有值时，RunSqlTool 优先使用它

### 修改组件

1. **`RunSqlTool.execute`**（`src/vanna/tools/run_sql.py`）
   - `runner = context.sql_runner or self.sql_runner`

2. **`Agent._send_message`**（`src/vanna/core/agent/agent.py`）
   - 从 `request_context.metadata` 解析 `business_id`
   - 匹配到业务时，创建/缓存 SqlRunner，注入 ToolContext
   - 同时设置 `metadata["autolink_database_name"]` 为业务的 database_name

3. **`ddl_import.py`**（`src/vanna/servers/fastapi/ddl_import.py`）
   - `IngestRequest` 增加 `business_id` 字段
   - `ddl_ingest` 路由支持从 business_id 解析 database_name
   - 页面 HTML 增加业务选择下拉框

4. **`routes.py`**（`src/vanna/servers/fastapi/routes.py`）
   - 聊天请求支持 `business_id` 参数，传递到 RequestContext.metadata

### 数据流

```
请求(business_id="biz_a")
    ↓
Agent._send_message 解析 business_id
    ↓
从 config.businesses["biz_a"] 获取配置
    ↓
创建/缓存 SqlRunner("mysql://biz_a_db...")
设置 metadata["autolink_database_name"] = "biz_a"
    ↓
ToolContext(sql_runner=..., metadata={...})
    ↓
run_sql → context.sql_runner（动态路由）
explore_schema_links → database_name="biz_a"（动态命名空间）
```

### DDL 导入流程

```
业务A上传 DDL.csv → /ddl/parse → 解析 → 暂存 parse_id
    ↓
/dll/ingest {parse_id, business_id="biz_a"}
    ↓
config.businesses["biz_a"].effective_database_name() → "biz_a"
    ↓
store.ingest_schema(tables, relations, "biz_a")
    ↓
查询时 business_id="biz_a" → search(..., "biz_a") 命中
```

## 约束与兼容性

1. **向后兼容**：`businesses` 默认为空 dict，不配置时行为与现有完全一致
2. **单业务模式**：`config.database` 和 `config.autolink_config` 继续工作，作为无 business_id 时的默认行为
3. **SqlRunner 缓存**：按 business_id 缓存在 Agent 实例上，避免重复创建连接
4. **SchemaVectorStore 无需改动**：各后端（FAISS/Chroma/Milvus/Qdrant）已通过 database_name 实现命名空间隔离

## 测试

- **单元测试**：
  - BusinessConfig 模型实例化、effective_database_name 回退逻辑
  - RunSqlTool 优先使用 context.sql_runner
  - Agent 业务路由：有 business_id 时注入 sql_runner，无时回退默认
  - DDL ingest 支持 business_id 参数
- **集成验证**：
  - 配置两个业务，分别导入不同 DDL.csv
  - 请求指定 business_id，验证 run_sql 和 explore_schema_links 路由正确

## 修改范围

| 文件 | 改动类型 | 影响面 |
|------|----------|--------|
| `core/agent/config.py` | 新增 BusinessConfig + businesses 字段 | 配置层，无副作用 |
| `core/tool/models.py` | ToolContext 增加 Optional 字段 | 默认 None，不影响现有代码 |
| `tools/run_sql.py` | execute 方法一行改动 | 优先级逻辑，回退到原行为 |
| `core/agent/agent.py` | 新增路由逻辑 + SqlRunner 缓存 | 核心改动，需仔细测试 |
| `servers/fastapi/ddl_import.py` | IngestRequest 增加字段 + 页面下拉框 | 向后兼容 |
| `servers/fastapi/routes.py` | 聊天请求增加 business_id | 向后兼容 |

## 成功标准

1. 不配置 businesses 时，行为与现有完全一致
2. 配置多业务后，请求指定 business_id 可路由到正确的数据库
3. DDL 导入支持按业务区分，导入后查询可命中对应命名空间
4. 单元测试通过，无回归
