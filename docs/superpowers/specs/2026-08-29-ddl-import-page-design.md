# DDL 导入页设计文档

日期：2026-08-29

## 背景与目标

vanna 当前具备 schema 向量化的全部底层能力：

- `DdlParser`（`src/vanna/capabilities/schema_vector_store/ddl_parser.py`）：解析 DDL.csv / 原始 DDL / SQLite 连接，产出 `SchemaTable` + `SchemaRelation`（含主外键），多方言、按表错误隔离；
- `SchemaVectorStore.ingest_schema()`：faiss / chroma / milvus / qdrant 四个后端实现，幂等覆盖写入；
- Agent 装配链：`create_basic_agent(..., vector_backend="faiss")` 自动派生 `schema_vector_store`，AutoLink 检索链路（`explore_schema_links` 工具 + `AutoLinkSchemaEnhancer`）已就绪。

缺失的是一键接入入口：目前"DDL.csv → 解析 → 入库"需要用户手写三行代码拼装，没有可视化操作方式。本设计为现有 FastAPI 服务增加一个内置页面，让用户上传 DDL.csv → 预览解析结果 → 确认写入向量库，全程不需要写代码。

## 决策记录

| 决策点 | 选择 | 理由 |
|---|---|---|
| 页面承载形式 | 服务内置页面（FastAPI 路由 + HTML） | 复用现有服务与 agent 实例，无独立部署负担 |
| 写入目标 | 服务当前装配的 `agent.schema_vector_store` | 入库后 AutoLink 检索立即可用同一份索引 |
| 操作流程 | 解析预览 → 用户确认 → 入库 | 可审计、可回退，写错可重新上传覆盖 |
| database_name | 页面上填写（默认 `default`） | 灵活性优先，提示需与 `AutoLinkConfig.database_name` 一致 |

## 架构

### 新增组件

1. **`src/vanna/servers/fastapi/ddl_import.py`**（新增模块）
   - `register_ddl_import_routes(app, agent)`：注册页面路由与 API 路由
   - `_INDEX_HTML`：导入页模板（内联 CSS/JS，无前端框架依赖）

2. **`src/vanna/servers/fastapi/app.py`**（修改）
   - `VannaFastAPIServer.create_app()` 末尾调用 `register_ddl_import_routes(app, self.agent)`

### 路由

| 路由 | 方法 | 说明 |
|---|---|---|
| `/ddl-import` | GET | 导入页 HTML |
| `/api/vanna/v1/ddl/parse` | POST (multipart) | 上传 CSV → 解析 → 暂存 → 返回预览 JSON |
| `/api/vanna/v1/ddl/ingest` | POST (JSON) | `{parse_id, database_name}` → 写入向量库 |

### 数据流

```
浏览器上传 DDL.csv
  → POST /api/vanna/v1/ddl/parse（多文件支持可选，单文件足够）
    → DdlParser().parse_csv()
    → 结果暂存 parse_id ↔ (tables, relations)
    → 返回预览：表数、列数、关系数、每表列清单、失败表警告
  → 用户确认
  → POST /api/vanna/v1/ddl/ingest {parse_id, database_name}
    → agent.schema_vector_store.ingest_schema(tables, relations, database_name)
    → 返回成功统计 / 失败信息
```

### 页面内容

- 文件选择框（accept=".csv"）+ 解析按钮
- `database_name` 输入框（默认值 `default`，附提示文字）
- 解析预览区：统计卡片（表/列/关系数量）、警告列表（解析失败的表）、可展开的表→列明细
- 确认入库按钮 + 反馈区域（成功绿 / 失败红）
- 顶部入口说明（本页用途、与 AutoLink 的关系一句话）

## 约束与错误处理

1. **未装配 schema_vector_store**：`register_ddl_import_routes` 检查 `agent.schema_vector_store is None` 时，页面加载即显示提示、parse 可正常返回预览、ingest 返回 HTTP 503 + JSON 错误信息
2. **CSV 格式兼容**：带表头 / 无表头由 `DdlParser.parse_csv` 自动识别；多方言 DDL 解析/失败由 parser 现有逻辑保证
3. **幂等覆盖**：同名 database_name 重复 ingest 覆盖旧索引（各 store 已实现），前端先提示再执行
4. **暂存策略**：CSV base64 存在内存 dict；仅在解析成功且用户确认后写入向量库；无 parse 结果时 ingest 返回 400 + 提示重新解析
5. **vector db 写失败**：ingest 异常需返给前端展示，附错误信息；后端日志 warning

## 测试

- **单元测试** `tests/test_ddl_import.py`：
  - parse API 成功 / 无 CSV / 空 CSV
  - parse 返回带 preview 的 JSON（表数、列数、关系数）
  - ingest 成功 / 未解析 / 无 store (503)
  - 页面 GET 200 + HTML 包含标题
- **E2E 验证**：`VECTOR_BACKEND=faiss` 启动服务 → 打开 `/ddl-import` 上传 DDL.csv → 预览 → 入库 → AutoLink 检索新 namespace 生效

## 修改范围

不改动 `agent.py`、`ddl_parser.py`、各 store 实现；新增 1 模块 + 改 1 行注册 + 新测试文件。原聊天页 `/` 不受影响。

## 成功标准

1. 页面可上传/解析 DDL.csv，预览表/列/关系统计与解析警告
2. 确认后 schema 写入当前服务的向量库，AutoLink 检索（`explore_schema_links`）能命中刚导入的 schema
3. `VECTOR_BACKEND=faiss` 未配置时页面提示不崩溃，ingest 返回 503
4. 单元测试通过