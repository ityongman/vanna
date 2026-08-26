# IntegrationPlan.md —— Vanna 集成改造计划文档

> **文档版本**: v3.2  
> **创建日期**: 2026-08-24  
> **目标仓库**: vanna-ai/vanna（本地路径 `d:\workspace\sourceWorkspace\vanna`）  
> **外部能力**: wzy416/AutoLink（本地路径 `d:\workspace\sourceWorkspace\AutoLink`）

---

## 1. 改造业务总目标

### 1.1 AutoLink 集成 —— 解决的痛点与收益

**痛点**:
- Vanna 当前 Text-to-SQL 流水线中，LLM 通过 `SystemPromptBuilder` 和 `LlmContextEnhancer` 获取数据库 schema 上下文，但**没有自动化的多表 JOIN 关系推理机制**。
- 当用户问题涉及多表关联查询时，LLM 需要自行推断表间 JOIN 条件，容易产生**遗漏 JOIN、错误 JOIN 条件、或笛卡尔积**等问题。
- 在大规模 schema（数百列）场景下，全量 schema 输入会超出 LLM 上下文窗口限制，导致性能下降。

**收益**:
- AutoLink 提供**基于 LLM Agent 迭代式 Schema Linking**，能自动检索与问题相关的表列子集，降低噪声。
- 通过 Agent 探索（含 `@sql_execution` 工具）动态发现表间关联列，提高 JOIN 条件正确率。
- 作为**可选开关**，默认关闭，不影响现有用户行为。

### 1.2 observability_provider 剥离 —— 目的

**目的**:
- 移除 Vanna 当前所有 `self.observability_provider` 的**实际业务埋点调用**（create_span / end_span / record_metric）。
- 当前 Vanna 没有提供任何 concrete `ObservabilityProvider` 实现，所有埋点调用实际上都是空操作（no-op）。
- 本次剥离移除这些无效调用，**保留抽象接口占位**，后续外部可重新注入实现该能力。

### 1.3 frontends 前端重构 —— 目标

**目标**:
- 将 `frontends/webcomponent/` 目录下的 Lit Web Components 从 Vanna 品牌专属页面，改造为**通用业务 ChatBot 对话页面**。
- 完全移除 `vanna` 品牌标识：名称、logo、CSS 变量前缀、宣传文案。
- 保留核心能力：对话输入、消息历史、SQL 结果表格渲染、Plotly 图表渲染、错误提示。
- 不改动后端接口协议，前端继续复用现有 FastAPI API。

### 1.4 integrations 目录重构 —— 目的

**现状问题**:
- `src/vanna/integrations/` 下 28 个子包**按集成产品名平铺**，LLM 服务、向量库（AgentMemory 后端）、关系型数据库、大数据/数仓（SQL Runner）、本地内置实现、云服务、可视化混在同一层，无法从目录名判断集成类型。
- 同一能力的不同实现没有聚合：既有 `LlmService` 实现（anthropic/openai/ollama/google/mock/azureopenai），也有 `AgentMemory` 向量库实现（faiss/chromadb/qdrant/milvus/weaviate/...），还有 `SqlRunner` 数据库实现（postgres/mysql/bigquery/...），三类接口的实现混杂一处。
- 未来新增后端（如 SchemaVectorStore 的 Chroma 后端）无处归类，目录会继续膨胀。

**目标**:
- 在 `integrations/` 内**按能力分类、数据库再按形态细分**：`llm/`、`vector/`、`databases/relational/`、`databases/warehouse/`、`local/`、`visualization/`、`premium/`。
- 保持所有类的 `import` 路径可迁移：旧包路径保留 **re-export 兼容层**（`DeprecationWarning`），全仓库引用同步更新为新路径。
- 目录命名意图自解释：看到 `integrations/vector/` 即知是 AgentMemory / SchemaVectorStore 的向量库实现，看到 `databases/` 即知是 SqlRunner 实现。

---

## 2. AutoLink 能力深度分析与集成策略

### 2.1 AutoLink 完整流水线理解

AutoLink 并非一个简单的"输入问题 → 输出 JOIN 条件"的函数，而是两阶段流水线：

#### 阶段一：离线 Schema 入库（DDL.csv → 列级文档 → Vector DB）

首先澄清 AutoLink 原始代码的边界：AutoLink 的 `generate_docs.py` 并不读取 DDL.csv，它消费的是 **Spider2 数据集自带的 per-table JSON**（每个表一个 JSON 文件，内含 `table_fullname`、`column_names`、`column_types`、`description`、`sample_rows`），DDL.csv 只是 Spider2 数据集的上游产物。因此不能原样照搬 AutoLink 流水线——我们的**业务起点是 DDL.csv**，需要在其前端补齐「DDL 解析 → 列级文档」环节，再执行向量化入库；AutoLink 中 Spider2 特有的**分区表合并 / 嵌套列展开逻辑不移植**（那是为处理数据集噪声而生，我们的 DDL 是干净的单表定义）。

```
DDL.csv (表名、列名、类型、主键、外键)          ← 业务侧真实输入
  │
  ├─ [1] SchemaDocumentGenerator（新增，替代 generate_docs.py）
  │     a. 解析 DDL.csv/DDL 文本，提取表、列、主键、外键（sqlparse）
  │     b. 可选：LLM 依据列名+类型+表名生成列语义描述
  │     c. 可选：采样真实数据，产出列级 sample_values
  │     d. 格式化列级文档: "{table}.{column}\ncolumn type: {type}
  │        \ntable name: {table}\ndescription: {desc}"
  │
  ├─ [2] ingest_schema()（对应 embedding_docs.py）
  │     SentenceTransformer 编码 → SchemaVectorStore 后端 Adapter 写入（多后端可插拔）
  │     开发/逻辑验证: FAISSSchemaVectorStore（index.faiss + metadata.json）
  │     生产可切换: Chroma / Milvus / Qdrant（见 2.5 节）
  │     ★ 补全 v2 方案缺失的关键前置步骤（输入不再是现成 JSON）
  │
  └─ [3] 主键/外键关系（来自 DDL 解析，而非启发式补全）
        写入 metadata.json 的 relations 字段，供检索结果随列一并输出
        说明：AutoLink 的 add_id.py 启发式补 *id/*name/*code 列，
        是因为其 JSON 元数据没有 PK/FK 标注；我们的 DDL 直接含 PK/FK，
        采用「DDL 解析 PK/FK 为主 + 启发式补全为兜底」的合理设计
```

#### 阶段二：在线 Schema Linking（问题 → 相关 Schema 子集 → Agent 探索 → JOIN 关联）

```
用户问题
  │
  ├─ [3] retrieve_topk_schema.py: 向量检索 top-k 相关列
  │     输出: initial_candidates.json（列名 + 表名 + 类型 + 采样值 + 距离）
  │
  ├─ [4] add_id.py: 启发式补充 *id/*name/*code 关键列
  │     输出: filled_pre_rule.json
  │     （注意：AutoLink 因元数据无 PK/FK 才做启发式；我们的 DDL 含 PK/FK，
  │      集成时改为「DDL 解析 PK/FK 为主 + 该启发式为兜底」）
  │
  ├─ [5] generate_schema.py: 格式化为 LLM prompt
  │
  ├─ [6] complete_schema.py: Agent 迭代探索（核心）
  │     LLM 循环：@schema_retrieval / @sql_execution / @sql_draft / @stop()
  │     输出: 扩展后的候选 schema
  │
  └─ [7] postprocess.py: 合并初始检索 + Agent 探索结果
```

### 2.2 核心设计原则：融入 Vanna 扩展点，而非简单移植

AutoLink 的每个子模块应该自然地映射到 Vanna 现有的架构扩展点，而不是作为独立模块在 Agent 主循环外调用。

| AutoLink 能力 | 映射到 Vanna 扩展点 | 说明 |
|--------------|-------------------|------|
| **DDL 解析 + 列级文档生成**（AutoLink 无此环节，因它消费现成 JSON；我们补齐） | **新的 `SchemaDocumentGenerator`**（`schema_vector_store` 模块内） | 从 DDL.csv 提取表列、PK/FK；可选 LLM 生成列描述、采样数据；输出列级文档 |
| Schema 文档嵌入索引（对应 `embedding_docs.py`） | **新的 `SchemaVectorStore` 能力**（扩展 `capabilities/` 体系，多后端可插拔） | 将列级文档向量化存入向量数据库，作为 Vanna 的一种"Schema Memory"；遵循 Vanna `AgentMemory` 多实现模式（FAISS/ChromaDB/Milvus/Qdrant） |
| 向量检索 Top-K 相关列（对应 `retrieve_topk_schema.py`） | **`LlmContextEnhancer` 实现 `AutoLinkSchemaEnhancer`** | 在 `enhance_system_prompt()` 中检索相关列并格式化为 prompt 注入 |
| Agent 迭代探索（对应 `complete_schema.py`） | **注册为 Vanna Tool `explore_schema_links`** | LLM 可在工具调用循环中主动探索 schema 关联，类似现有 `search_saved_correct_tool_uses` |
| 启发式 ID 补全（对应 `add_id.py`） | **DDL 解析 PK/FK 为主 + 启发式兜底** | DDL 含主外键定义，直接用解析结果；启发式仅作兜底 |

**移植原则（AutoLink 代码「保留 / 改造 / 不移植」清单）**:

| AutoLink 代码 | 处置 | 理由 |
|---------------|------|------|
| `embedding_docs.py`（编码+建索引） | 保留核心逻辑 | 编码/批次逻辑与后端无关；索引构建下沉到各后端 Adapter（FAISS/Chroma/Milvus/Qdrant） |
| `retrieve_topk_schema.py`（向量检索） | 保留核心逻辑 | 通用向量检索 |
| `add_id.py`（启发式 ID 补全） | 改造为兜底策略 | DDL 的 PK/FK 信息更可靠，启发式降级为可选兜底 |
| `generate_docs.py`（JSON→文档） | **不移植** | 依赖 Spider2 per-table JSON 特化格式；由 SchemaDocumentGenerator（DDL 入口）替代 |
| 分区表合并、嵌套列展开 | **不移植** | 处理 Spider2 数据集噪声的专用逻辑，业务 DDL 无此场景 |
| `complete_schema.py`（Agent 探索） | 改造为 Vanna Tool | 探索循环由 Tool Calling 机制承接 |
| `postprocess.py` / `sql_*` / `generate_schema.py` | 不移植 | Vanna 已有对应职责（enhancer 格式化、LLM 生成、run_sql 执行） |

### 2.3 候选方案对比

#### 方案 A：深度融入 Vanna 扩展点（推荐）

| 维度 | 说明 |
|------|------|
| **做法** | 1. 新增 `SchemaDocumentGenerator` + 多后端可插拔 `SchemaVectorStore` 能力（DDL 解析 → 列级文档 → 向量库入库）；2. 实现 `AutoLinkSchemaEnhancer(LlmContextEnhancer)` 注入检索结果；3. 注册 `explore_schema_links` Vanna Tool 供 Agent 探索；4. 在 `DefaultSystemPromptBuilder` 中追加 schema 探索工作流指令 |
| **优点** | 完全遵循 Vanna 架构范式；向量后端可插拔（开发用 FAISS，生产切 Chroma/Milvus/Qdrant）；每个能力可独立开关；与其他 `LlmContextEnhancer` 可链式组合；LLM 自主决定是否探索 schema |
| **缺点** | 需要深入理解 Vanna 架构；设计和实现更复杂 |
| **依赖** | `sentence_transformers` 为可选依赖；向量后端按需安装：`faiss-cpu` 已在 `[all]` 中，`chromadb` 已在 `[all]` 中，Milvus/Qdrant 走各自 extra 组 |

#### 方案 B：Simple Adapter 模式（v1 方案，不推荐）

| 维度 | 说明 |
|------|------|
| **做法** | 在 `Agent._send_message()` 中直接调用 `AutoLinkAdapter.infer_joins()`，一次性完成检索+探索+输出 |
| **优点** | 实现简单，改动点少 |
| **缺点** | 不符合 Vanna 架构范式；无法利用 Tool Calling 机制；Schema 入库逻辑缺失；无法与现有 `LlmContextEnhancer` 链式组合 |

#### 推荐方案：方案 A

**理由**:
1. Vanna 2.x 的 Agent 架构本身就是通过 Tool Calling 实现 LLM 自主决策，AutoLink 的 Agent 探索循环天然适合作为 Vanna Tool。
2. Vanna 已有 `AgentMemory` 体系（FAISS、ChromaDB、Qdrant、Milvus 等实现），SchemaVectorStore 完全复用该多后端可插拔模式，验证阶段用本地 FAISS 快速跑通，生产无缝切换成熟向量库。
3. `LlmContextEnhancer` 是设计好的扩展点，`DefaultLlmContextEnhancer` 已经在此处注入 AgentMemory 检索结果，Schema 检索是同一模式。
4. 方案 B 的"黑盒适配器"模式违背了 Vanna 的模块化架构设计，且缺少 Schema 入库链路。

### 2.4 Schema 入库链路设计决策

| 决策点 | 设计选择 | 理由 |
|--------|----------|------|
| **入库输入** | `DDL.csv`（或等价 DDL 文本）为唯一入口 | 业务真实数据源是 DDL；AutoLink 消费的 Spider2 per-table JSON 在我们的场景中不存在 |
| **向量后端** | 抽象 `SchemaVectorStore` 接口 + 多后端实现（FAISS/ChromaDB/Milvus/Qdrant） | 开发/逻辑验证用 FAISS（零外部依赖、本地文件）；生产按规模/运维选择成熟向量库；复用 Vanna `AgentMemory` 多实现模式 |
| **DDL 解析器** | `sqlparse`（Vanna 已有依赖，见 pyproject.toml） | 提取表名、列名、列类型、PK/FK；避免引入重量级 SQL 解析器 |
| **列描述生成** | LLM 根据列名+类型+表名生成，可选/可批处理 | DDL 不含语义描述；列级文档必须含描述才能保证检索质量（AutoLink 依赖数据集自带 description） |
| **采样值** | 可选，由用户提供 DB 连接时采样 | 提升聚类与 LLM 理解；无连接时不采样，入库仍可用 |
| **PK/FK 关系** | 从 DDL 解析获得，写入向量库元数据的 `relations` 字段 | DDL 直接含主外键；替代 AutoLink `add_id.py` 纯启发式补全（启发式降级为可选兜底开关 `enable_key_column_hints`） |
| **文档粒度** | 列级（一条文档 = 一列） | 继承 AutoLink 设计；检索结果直接对应"哪些列相关"，便于 LLM 生成准确列引用 |
| **描述可靠时跳过分区合并** | 不移植 AutoLink 分区表合并逻辑 | 业务 DDL 是干净的单表定义，无 Spider2 噪声 |

### 2.5 SchemaVectorStore 向量后端可插拔架构

Vanna `AgentMemory` 体系已有成熟的多后端可插拔先例（`FAISSAgentMemory`/`ChromaDBAgentMemory`/`QdrantAgentMemory`/`MilvusAgentMemory`），`SchemaVectorStore` 遵循同一模式：抽象基类定义统一接口，各后端 Adapter 负责「编码 + 写入 + 检索 + 元数据存储」。**AutoLink 原版 FAISS 硬编码实现在本方案中仅作为开发/逻辑验证后端**（零外部服务依赖、本地文件即可跑通），生产环境按需切换：

| 后端 | 实现类（新增） | 适用场景 | 说明 |
|------|---------------|----------|------|
| FAISS（本地文件） | `FAISSSchemaVectorStore` | 开发、逻辑验证、单机小规模 | 对齐 AutoLink 原实现（IndexFlatL2 + index.faiss + metadata.json）；无外部服务依赖 |
| ChromaDB | `ChromaSchemaVectorStore`（一期可选实现） | 中小规模生产 | Vanna `[all]` 已含 chromadb；嵌入式或 C/S 模式；自带元数据过滤 |
| Milvus | `MilvusSchemaVectorStore`（接口预留） | 大规模生产、高并发 | 用 Vanna 已有 `pymilvus` extra；分布式向量检索 |
| Qdrant | `QdrantSchemaVectorStore`（接口预留） | 云原生部署 | 用 Vanna 已有 `qdrant-client` extra；支持 payload 过滤与云端托管 |

**后端切换原则**:
1. 统一接口：`ingest_schema()` / `search()` / `get_column_by_name()` / `get_relations()` 四接口语义一致，业务上层（AutoLinkSchemaEnhancer、ExploreSchemaLinksTool）不感知后端差异
2. `AutoLinkConfig.vector_store_backend` 配置项选择后端；不传则默认 `faiss`（开发验证）
3. 一期（逻辑验证）只交付 `FAISSSchemaVectorStore`；ChromaDB 实现可作为二期优先项；Milvus/Qdrant 预留接口与文档，按需开发
4. 嵌入模型（SentenceTransformer）作为跨后端共享组件，由后端 Adapter 内部懒加载，接口不变

---

## 3. Vanna 主干调用链完整梳理

### 3.1 Agent.send_message() 完整调用链路

```
用户 HTTP 请求
  │
  ▼
FastAPI Routes (src/vanna/servers/fastapi/routes.py:43)
  │ POST /api/vanna/v2/chat_sse, chat_sse()
  │
  ▼
ChatHandler.handle_stream() (src/vanna/servers/base/chat_handler.py:26)
  │
  ▼
Agent.send_message() (src/vanna/core/agent/agent.py:142)
  │
  ├─ [1] UserResolver.resolve_user()  ─── 解析用户身份
  │
  ├─ [2] WorkflowHandler.try_handle()  ── 处理 /help 等命令
  │
  ├─ [3] ConversationStore.get_conversation()  ── 加载对话
  │
  ├─ [4] ToolContextEnricher.enrich_context()  ── 富化上下文
  │
  ├─ [5] ToolRegistry.get_schemas()  ── 获取工具 schema
  │      ★ 包含新增的 explore_schema_links 工具 schema
  │
  ├─ [6] SystemPromptBuilder.build_system_prompt()  ── 构建系统 prompt
  │      │  (src/vanna/core/system_prompt/default.py:34)
  │      ★ 新增 AUTO-LINK SCHEMA EXPLORATION 指令章节
  │
  ├─ [7] LlmContextEnhancer.enhance_system_prompt()  ── 增强 prompt
  │      │  (src/vanna/core/enhancer/default.py:41)
  │      │  现有 DefaultLlmContextEnhancer: 注入 AgentMemory 文本记忆
  │      ★ 新增 AutoLinkSchemaEnhancer: 注入 SchemaVectorStore 检索的 schema 列上下文（后端不感知）
  │      ★ 两个 Enhancer 可链式组合（enhancer 链）
  │
  ├─ [8] _build_llm_request()  ── 组装 LLM 请求
  │      │  (src/vanna/core/agent/agent.py:1159)
  │      ├─ ConversationFilter.filter_messages() ── 过滤历史
  │      └─ LlmContextEnhancer.enhance_user_messages()
  │
  ├─ [9] _send_llm_request() / _handle_streaming_response()  ── 调用 LLM
  │      │  (src/vanna/core/agent/agent.py:1240, 1315)
  │      ├─ LlmMiddleware.before_llm_request() ── 中间件
  │      ├─ LlmService.send_request() / stream_request() ── LLM API
  │      └─ LlmMiddleware.after_llm_response() ── 中间件
  │
  ├─ [10] Tool Loop (while tool_iterations < max_tool_iterations)
  │      │  (src/vanna/core/agent/agent.py:646)
  │      ├─ LifecycleHook.before_tool()
  │      ├─ ToolRegistry.execute()  ── 执行工具
  │      │   ├─ run_sql: 执行 SQL
  │      │   ├─ visualize_data: 生成图表
  │      │   ├─ search_saved_correct_tool_uses: 检索记忆
  │      │   ├─ save_question_tool_args: 保存工具使用
  │      │   ├─ save_text_memory: 保存文本记忆
  │      │   ★ explore_schema_links: 检索 schema 关联信息（新增）
  │      │       ├─ 内部调用 SchemaVectorStore.search() 语义检索
  │      │       └─ 返回相关列和潜在 JOIN 关联
  │      ├─ LifecycleHook.after_tool()
  │      └─ 重新构建 LLM 请求（含 tool results）→ 回到步骤 9
  │
  ├─ [11] ConversationStore.update_conversation()  ── 保存对话
  │
  └─ [12] LifecycleHook.after_message()
```

### 3.2 AutoLink 能力在 Vanna 中的注入点

| 注入点 | 文件 | 函数/位置 | 注入内容 |
|--------|------|----------|----------|
| **注入点 1** | `src/vanna/core/agent/agent.py` | `Agent.__init__()` 约第 96 行 | 新增 `schema_vector_store` 参数（SchemaVectorStore 实例） |
| **注入点 2** | `src/vanna/core/agent/agent.py` | `Agent.__init__()` 约第 127 行 | 将 `AutoLinkSchemaEnhancer` 追加到 `llm_context_enhancer` 链 |
| **注入点 3** | `src/vanna/core/system_prompt/default.py` | `build_system_prompt()` 约第 61 行 | 当 `explore_schema_links` 工具可用时，注入 AUTO-LINK SCHEMA EXPLORATION 指令 |
| **注入点 4** | `src/vanna/core/enhancer/default.py` | `enhance_system_prompt()` 约第 41 行 | 不修改此文件；新增独立 `AutoLinkSchemaEnhancer` 类 |
| **注入点 5** | `src/vanna/agents/__init__.py` | `create_basic_agent()` | 可选创建 `SchemaVectorStore` 并注入 |
| **注入点 6** | `src/vanna/core/agent/config.py` | `AgentConfig` | 新增 `autolink_config` 配置字段 |

### 3.3 observability_provider 埋点调用位置全量清单

所有埋点均位于 `src/vanna/core/agent/agent.py`，涉及以下模式：

| 模式 | 位置（行号） | 说明 |
|------|-------------|------|
| `send_message` 异常捕获 | 175-196 | 错误 span + metric |
| `_send_message` 用户解析 | 250-267 | create_span + end_span + record_metric |
| starter UI 处理 | 276-332 | 工作流 span |
| 生命周期 before_message | 364-388 | hook span |
| 对话加载 | 409-436 | conversation span |
| 工作流处理 | 440-508 | workflow span |
| 上下文富化 | 544-562 | enrichment span |
| 工具 schema 获取 | 565-582 | schema span |
| 系统 prompt 构建 | 592-636 | prompt span |
| LLM 上下文增强 | 604-626 | enhancement span |
| 对话过滤 | 1169-1191 | filter span |
| 用户消息增强 | 1204-1228 | enhancement span |
| LLM 中间件 before | 1243-1264, 1317-1343 | middleware span |
| LLM 请求 | 1266-1286 | llm span |
| LLM 流式响应 | 1348-1372 | stream span |
| LLM 中间件 after | 1288-1311, 1379-1405 | middleware span |
| 工具执行前 hook | 788-814 | hook span |
| 工具执行 | 817-845 | tool span |
| 工具执行后 hook | 848-878 | hook span |
| 对话保存 | 1089-1107 | save span |
| 生命周期 after_message | 1110-1131 | hook span |
| 整体消息 span 结束 | 1133-1153 | 记录总耗时 metric |

**额外引用**:
- `src/vanna/core/tool/models.py:38-41` — `ToolContext.observability_provider` 字段定义
- `src/vanna/core/__init__.py:22` — `ObservabilityProvider` 公共导出
- `src/vanna/core/observability/__init__.py:8-9` — 模块导出

### 3.4 frontends 前端与后端 FastAPI 接口交互关系

```
┌──────────────────────────────────────────────────────────────┐
│  frontends/webcomponent/src/                                 │
│                                                              │
│  vanna-chat.ts (VannaChat)                                   │
│    │ 属性: apiBaseUrl, sseEndpoint, wsEndpoint, pollEndpoint │
│    │                                                         │
│    ├─ services/api-client.ts (VannaApiClient)                │
│    │   ├─ streamChat() → POST /api/vanna/v2/chat_sse (SSE)  │
│    │   ├─ createWebSocketConnection() → /api/vanna/v2/chat_ws│
│    │   └─ sendPollMessage() → POST /api/vanna/v2/chat_poll  │
│    │                                                         │
│    └─ components/                                            │
│        ├─ vanna-message.ts (聊天消息气泡)                     │
│        ├─ vanna-status-bar.ts (状态栏)                       │
│        ├─ vanna-progress-tracker.ts (进度跟踪)               │
│        ├─ plotly-chart.ts (Plotly 图表)                      │
│        ├─ dataframe (数据表格渲染)                            │
│        └─ rich-component-system.ts (16 种富组件管理)          │
│                                                              │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  src/vanna/servers/fastapi/routes.py                         │
│                                                              │
│  POST /api/vanna/v2/chat_sse    → ChatHandler.handle_stream()│
│  WS   /api/vanna/v2/chat_websocket → ChatHandler.handle_stream│
│  POST /api/vanna/v2/chat_poll   → ChatHandler.handle_poll()  │
│  GET  /                         → 返回 HTML 聊天界面          │
│  GET  /health                   → 健康检查                   │
│                                                              │
│  templates.py (get_index_html)  → 生成包含 <vanna-chat>      │
│                                    自定义元素的 HTML 页面     │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. 修改影响范围清单

### 4.1 需要新增的文件

#### AutoLink 集成 —— Schema 入库链路

| 文件路径 | 说明 |
|----------|------|
| `src/vanna/capabilities/schema_vector_store/__init__.py` | SchemaVectorStore 模块入口 |
| `src/vanna/capabilities/schema_vector_store/base.py` | `SchemaVectorStore` 抽象基类：定义 `ingest_schema()`、`search()` 接口 |
| `src/vanna/capabilities/schema_vector_store/models.py` | 数据模型：`SchemaColumn`、`SchemaTable`、`SchemaSearchResult`、`SchemaRelation` |
| `src/vanna/capabilities/schema_vector_store/ddl_parser.py` | `DdlParser`：解析 DDL.csv/DDL 文本，提取表、列、类型、PK/FK（基于 sqlparse） |
| `src/vanna/capabilities/schema_vector_store/document_generator.py` | `SchemaDocumentGenerator`：列描述生成（可选 LLM）、采样值（可选）、列级文档格式化 |
| `src/vanna/integrations/vector/faiss/schema_vector_store.py` | `FAISSSchemaVectorStore`：开发/逻辑验证后端（FAISS + SentenceTransformer，对应 AutoLink `embedding_docs.py`）；生产后端可替换 |
| `src/vanna/integrations/vector/chroma/schema_vector_store.py` | `ChromaSchemaVectorStore`：一期可选实现（中小规模生产；复用 `[all]` 已含 chromadb） |
| `src/vanna/integrations/vector/milvus/schema_vector_store.py` | `MilvusSchemaVectorStore`：接口预留与默认实现骨架（大规模生产；按需开发） |
| `src/vanna/integrations/vector/qdrant/schema_vector_store.py` | `QdrantSchemaVectorStore`：接口预留与默认实现骨架（云原生；按需开发） |

#### AutoLink 集成 —— Schema 检索与增强链路

| 文件路径 | 说明 |
|----------|------|
| `src/vanna/core/enhancer/autolink_schema.py` | `AutoLinkSchemaEnhancer`：实现 `LlmContextEnhancer`，在 `enhance_system_prompt()` 中检索相关 schema 列并注入（对应 AutoLink `retrieve_topk_schema.py` + `add_id.py` 兜底） |
| `src/vanna/tools/explore_schema_links.py` | `ExploreSchemaLinksTool`：Vanna Tool，供 LLM 在工具调用循环中主动探索 schema 关联（承接 AutoLink `complete_schema.py` 探索职责） |

#### AutoLink 集成 —— 配置

| 文件路径 | 说明 |
|----------|------|
| `src/vanna/core/agent/autolink_config.py` | `AutoLinkConfig` Pydantic 配置模型 |

#### 测试文件

| 文件路径 | 说明 |
|----------|------|
| `tests/test_schema_vector_store.py` | SchemaVectorStore 单元测试（ingest/search/持久化） |
| `tests/test_ddl_parser.py` | DdlParser 单元测试（DDL.csv 解析、PK/FK 提取） |
| `tests/test_schema_document_generator.py` | SchemaDocumentGenerator 单元测试（列文档生成） |
| `tests/test_autolink_schema_enhancer.py` | AutoLinkSchemaEnhancer 单元测试 |
| `tests/test_explore_schema_links_tool.py` | ExploreSchemaLinksTool 单元测试 |

### 4.2 需要修改的后端源码文件

#### AutoLink 改造

| 文件路径 | 修改内容 | 影响程度 |
|----------|----------|----------|
| `src/vanna/core/agent/agent.py` | `Agent.__init__()` 新增 `schema_vector_store` 参数；`_send_message()` 中组装 enhancer 链 | 中 |
| `src/vanna/core/agent/config.py` | `AgentConfig` 新增 `autolink_config: AutoLinkConfig` 字段 | 低 |
| `src/vanna/core/system_prompt/default.py` | `build_system_prompt()` 中：当 `explore_schema_links` 工具可用时，注入 AUTO-LINK SCHEMA EXPLORATION 指令 | 中 |
| `src/vanna/core/__init__.py` | 导出 `SchemaVectorStore`、`AutoLinkConfig` 等 | 低 |
| `src/vanna/__init__.py` | 导出新增公共类 | 低 |
| `src/vanna/agents/__init__.py` | `create_basic_agent()` 可选创建 SchemaVectorStore 并注入 | 低 |
| `src/vanna/capabilities/__init__.py` | 导出 SchemaVectorStore 相关类 | 低 |
| `pyproject.toml` | 新增 `sentence_transformers` 为可选依赖（`autolink` 组） | 低 |

#### observability 剥离

| 文件路径 | 修改内容 | 影响程度 |
|----------|----------|----------|
| `src/vanna/core/agent/agent.py` | 删除所有 `if self.observability_provider:` 条件块内的 span/metric 调用（约 24 处）；保留 `self.observability_provider = observability_provider` 赋值 | 高 |
| `src/vanna/core/tool/models.py` | `ToolContext.observability_provider` 字段标记为【预留暂未实现】 | 低 |

### 4.3 frontends 目录修改/重写文件清单

| 文件路径 | 操作 | 说明 |
|----------|------|------|
| `frontends/webcomponent/src/components/vanna-chat.ts` | **重写** | 重命名为 `chatbot-chat.ts`；移除 Vanna 品牌标题、文案；替换 `--vanna-` CSS 变量 |
| `frontends/webcomponent/src/components/vanna-message.ts` | **重写** | 重命名为 `chatbot-message.ts` |
| `frontends/webcomponent/src/components/vanna-status-bar.ts` | **重写** | 重命名为 `chatbot-status-bar.ts` |
| `frontends/webcomponent/src/components/vanna-progress-tracker.ts` | **重写** | 重命名为 `chatbot-progress-tracker.ts` |
| `frontends/webcomponent/src/services/api-client.ts` | **修改** | 重命名 `VannaApiClient` 为 `ChatbotApiClient`；移除日志中的 Vanna 字样 |
| `frontends/webcomponent/src/styles/vanna-design-tokens.ts` | **重写** | 重命名为 `chatbot-design-tokens.ts`；`--vanna-` 前缀改为 `--chatbot-` |
| `frontends/webcomponent/src/index.ts` | **修改** | 更新导出名称和日志 |
| `frontends/webcomponent/package.json` | **修改** | 更新 name、description、keywords |
| `frontends/webcomponent/src/components/*.stories.ts` | **修改** | 更新 Storybook 标题 |
| `src/vanna/servers/base/templates.py` | **修改** | 移除 Vanna 品牌 HTML；更新组件标签名 |
| `src/vanna/servers/fastapi/app.py` | **修改** | 更新 app title/description |

### 4.4 完全不改动的文件列表

| 文件路径 | 原因 |
|----------|------|
| `src/vanna/core/observability/base.py` | 保留抽象接口占位 |
| `src/vanna/core/observability/models.py` | 保留 Span/Metric 模型 |
| `src/vanna/core/observability/__init__.py` | 保留模块导出 |
| `src/vanna/core/llm/*` | 不涉及改造 |
| `src/vanna/core/storage/*` | 不涉及改造 |
| `src/vanna/core/user/*` | 不涉及改造 |
| `src/vanna/integrations/*` | 不涉及改造（仅需按第 8 章目录重构后新增 SchemaVectorStore 各后端 Adapter 文件） |
| `src/vanna/tools/run_sql.py` | 不涉及改造 |
| `src/vanna/tools/visualize_data.py` | 不涉及改造 |
| `src/vanna/tools/agent_memory.py` | 不涉及改造 |
| `src/vanna/legacy/*` | 不涉及改造 |
| `src/vanna/servers/fastapi/routes.py` | 接口协议不变 |
| `src/vanna/servers/base/chat_handler.py` | 不涉及改造 |
| `src/vanna/servers/base/models.py` | 接口协议不变 |
| `frontends/webcomponent/src/components/plotly-chart.ts` | 通用图表组件，无需改动 |
| `frontends/webcomponent/src/components/rich-component-system.ts` | 富组件系统，仅可能修改 CSS 变量引用 |
| `frontends/webcomponent/src/components/rich-card.ts` | 通用组件 |
| `frontends/webcomponent/src/components/rich-progress-bar.ts` | 通用组件 |
| `frontends/webcomponent/src/components/rich-task-list.ts` | 通用组件 |

---

## 5. 风险清单与缓解策略

### 5.1 AutoLink 集成风险

| 风险 | 等级 | 缓解策略 |
|------|------|----------|
| 依赖冲突：`sentence_transformers` 与现有依赖冲突 | 低 | 作为可选依赖，不强制安装；faiss-cpu 已在 `[all]` 中 |
| DDL 方言差异：DDL.csv 中 DDL 语句含复杂注释、类型修饰符 | 中 | sqlparse 容错解析 + 失败表跳过并告警；提供测试样例覆盖常见方言（PG/MySQL/SQLite/Spark） |
| 列描述生成质量差：LLM 生成描述不准确 | 中 | 描述可选生成；已有 description 时覆盖为空；LLM 失败时退化纯列名+类型文档 |
| Schema 元数据缺失：列描述、采样值缺失 | 中 | 提供友好的 warning 日志；入库公开字段属于可选填充；类内保留纯列名退化路径 |
| 性能退化：每次调用 enhancer 都需要向量检索 | 中 | 检索结果缓存（按 question hash）；索引持久化避免重复加载；默认关闭 |
| 后端切换成本：由 FAISS 切到生产向量库需重新入库 | 低 | 统一 `SchemaVectorStore` 接口 + 同一 `ingest_schema()` 入口，重放入库脚本即可迁移；ChromaDB 一期预留迁移脚本 |
| 后端功能差异：过滤/命名空间等能力各后端不一致 | 中 | 接口只暴露各后端共有能力（ingest/search/元数据读写），不引入后端专属特性 |
| 嵌入模型加载：首次加载 SentenceTransformer 耗时 | 低 | 懒加载；提供轻量模型选项 |
| 与现有 Enhancer 链冲突：多个 enhancer 的输出可能互相覆盖 | 低 | 每个 enhancer 返回追加后的 prompt，链式组合 |
| Schema 入库链路复杂：用户需要先执行 ingest 才能检索 | 中 | 提供 Python API 和 CLI 命令；文档说明清晰；未入库时自动跳过 |

### 5.2 observability 剥离风险

| 风险 | 等级 | 缓解策略 |
|------|------|----------|
| 误删业务代码：span 创建与业务逻辑耦合 | 中 | 仅删除 `if self.observability_provider:` 条件块内的调用，不删除条件块外的业务逻辑 |
| 破坏扩展接口：误删 `ObservabilityProvider` 抽象类 | 低 | 已明确保留 `observability/` 目录全部文件，仅删除 `agent.py` 中的调用 |
| 影响 ToolContext：`ToolContext.observability_provider` 为 None | 低 | 该字段标记为 Optional，现有代码已处理 None 情况 |

### 5.3 前端重构风险

| 风险 | 等级 | 缓解策略 |
|------|------|----------|
| 前端接口兼容破坏：修改组件属性名导致 API 不兼容 | 中 | 保留所有 public 属性签名；仅修改内部实现 |
| 原有功能丢失：修改过程中误删功能 | 中 | 保留所有核心功能（对话、SQL 展示、表格、图表）；逐功能回归测试 |
| CSS 变量重命名遗漏：部分组件仍引用 `--vanna-` 变量 | 低 | 全局搜索替换；lint 检查 |
| 后端 templates.py 不兼容：修改组件标签名后 HTML 页面无法渲染 | 中 | 同步更新 `templates.py` 中的自定义元素标签名 |

### 5.4 整体向后兼容性风险

| 风险 | 等级 | 缓解策略 |
|------|------|----------|
| AutoLink 默认关闭，不影响现有行为 | 低 | 通过 `AutoLinkConfig.enabled = False` 默认值保证 |
| observability 剥离后 API 参数仍存在但不执行 | 低 | 传入 `observability_provider` 参数不会报错，也不会执行任何操作 |
| 前端组件重命名后旧代码引用失效 | 中 | 在 `index.ts` 中保留旧组件名的别名导出 |

### 5.5 integrations 目录重构风险

| 风险 | 等级 | 缓解策略 |
|------|------|----------|
| 引用遗漏：200+ 处引用中漏改导致 import 错误 | 中 | 全量 `rg` 检索旧路径；CI 增加导入冒烟检查（import 每个新路径与兼容 shim） |
| shim 与 mock/patch 路径冲突：`@patch("vanna.integrations.azureopenai.llm.AzureOpenAI")` 等字符串路径未同步 | 中 | 8.6 引用清单穷举全部 patch 字符串；测试文件中 patch 目标同步改为新路径 |
| 反射逻辑失效：`core/validation.py` 的 `pkgutil.iter_modules` 在嵌套新结构下扫描异常 | 低 | 目录重构后回归执行 `validate_pydantic_models_in_package` 验证反射正常 |
| 外部用户代码依赖旧路径：发布后直接 import 旧路径报错 | 低 | 旧路径 shim 保留 1~2 个 minor 版本并触发 DeprecationWarning，再彻底删除 |
| 更名副作用：chromadb→chroma 后文档/extra 依赖名不一致 | 低 | 同步更新 README/tox.ini/pyproject extras 说明；extra 名称保持不变 |
| 重复类对象：新路径与 shim 双重导入造成 isinstance 判断失败 | 低 | shim 只做 re-export 不复制业务代码；`__all__` 保持一致，保证类对象唯一 |

---

## 6. 分阶段可执行实施里程碑

### 阶段 1：代码调研与设计确认（已完成）

- [x] 梳理 Vanna 完整调用链路
- [x] 确认所有 observability 埋点位置
- [x] 深度分析 AutoLink 完整流水线（generate_docs → embedding_docs → retrieve → agent → postprocess）
- [x] 确认 AutoLink 能力如何映射到 Vanna 扩展点（Enhancer + Tool + SystemPromptBuilder）
- [x] 确认前端改造范围
- [x] 输出 IntegrationPlan.md 和 Specification.md（v3.2）

### 阶段 2：integrations 目录重构

1. 按第 8 章目标结构执行 `git mv` 移动所有 `integrations/*` 子包（能力分类 + 数据库细分）
2. 在旧包原路径创建 re-export 兼容 shim（`from vanna.integrations.vector.chroma import ChromaAgentMemory` + `DeprecationWarning`）
3. 全量更新仓库内新旧引用为新路径（src/tests/examples/notebooks/README/MIGRATION_GUIDE/tox.ini）
4. 更新 `src/vanna/integrations/__init__.py` 的本地导入路径（local/mock/plotly/sqlite）
5. 运行全部测试与 `tox` 导入检查，确认无回归
6. 验证：旧路径触发 DeprecationWarning 且功能正常；新路径无警告

### 阶段 3：observability_provider 剥离改造

1. 修改 `src/vanna/core/agent/agent.py`：删除所有 `if self.observability_provider:` 条件块内的 create_span/end_span/record_metric 调用
2. 保留 `self.observability_provider = observability_provider` 赋值
3. 修改 `src/vanna/core/tool/models.py`：`ToolContext.observability_provider` 添加注释标记【预留暂未实现】
4. 运行现有测试，确认没有回归
5. 验证：确认没有监控上报调用，业务流程正常

### 阶段 4：AutoLink Schema 入库链路开发（DDL → 列级文档 → Vector DB，多后端可插拔）

1. 创建 `src/vanna/capabilities/schema_vector_store/` 模块：
   - `models.py`：`SchemaColumn`、`SchemaTable`、`SchemaSearchResult`、`SchemaRelation` 数据模型
   - `ddl_parser.py`：`DdlParser`，解析 DDL.csv/DDL 文本，提取表、列、列类型、PK/FK（基于 sqlparse，容错跳过失败表）
   - `document_generator.py`：`SchemaDocumentGenerator`，生成列级文档（可选 LLM 列描述、可选采样值、文档格式化）
   - `base.py`：`SchemaVectorStore` 抽象基类（`ingest_schema()`、`search()`，接口与后端解耦）
2. 一期交付开发/逻辑验证后端 `src/vanna/integrations/vector/faiss/schema_vector_store.py`：
   - `FAISSSchemaVectorStore` 实现
   - 移植 AutoLink `embedding_docs.py` 核心逻辑：SentenceTransformer 编码 + FAISS IndexFlatL2 构建
   - 支持持久化（index.faiss + metadata.json）
   - 支持按数据库多索引；metadata 写入 PK/FK relations
3. 预留生产后端骨架（接口与一期一起定稿，按需开发）：
   - `integrations/vector/chroma/schema_vector_store.py`：`ChromaSchemaVectorStore` 骨架（二期优先实现）
   - `integrations/vector/milvus/schema_vector_store.py`、`integrations/vector/qdrant/schema_vector_store.py`：接口预留
4. 在 `pyproject.toml` 中新增 `sentence_transformers` 为可选依赖（`autolink` 组）
5. 编写单元测试：DdlParser 解析（含方言样例、容错）、SchemaDocumentGenerator、FAISSSchemaVectorStore（ingest、search、持久化、异常处理）、后端接口一致性测试（同一组数据经 `ingest_schema()` 后各后端检索语义一致）

### 阶段 5：AutoLink Schema 检索与增强链路开发

1. 创建 `src/vanna/core/enhancer/autolink_schema.py`：
   - `AutoLinkSchemaEnhancer(LlmContextEnhancer)` 实现
   - 在 `enhance_system_prompt()` 中：对用户问题编码 → `SchemaVectorStore.search()`（后端不感知）检索 top-k 相关列 → 格式化为 prompt 片段 → 追加到 system_prompt
   - 移植 AutoLink 的 `retrieve_topk_schema.py` 检索逻辑
   - 关键列补全：优先使用 DDL 解析出的 PK/FK relations，未提供时才启用 `add_id.py` 启发式兜底（*id/*name/*code）
2. 创建 `src/vanna/tools/explore_schema_links.py`：
   - `ExploreSchemaLinksTool(VannaTool)` 实现（承接 AutoLink `complete_schema.py` 探索职责，由 Tool Calling 机制驱动）
   - 参数：`table_name`（可选）、`column_name`（可选）、`search_query`（可选）
   - 执行：调用 `SchemaVectorStore` 检索相关列，返回格式化的 schema 子集
   - 支持 LLM 在工具调用循环中主动探索
3. 修改 `src/vanna/core/agent/agent.py`：
   - `Agent.__init__()` 新增 `schema_vector_store` 参数
   - 当 `autolink_config.enabled=True` 时，自动创建 `AutoLinkSchemaEnhancer` 并注入 enhancer 链
4. 修改 `src/vanna/core/system_prompt/default.py`：
   - 当检测到 `explore_schema_links` 工具可用时，在 system_prompt 中追加 AUTO-LINK SCHEMA EXPLORATION 指令
5. 创建 `src/vanna/core/agent/autolink_config.py`：
   - `AutoLinkConfig` 配置模型
6. 修改 `src/vanna/core/agent/config.py`：
   - `AgentConfig` 新增 `autolink_config: AutoLinkConfig` 字段
7. 实现降级逻辑：所有异常自动回退原生 Vanna 逻辑，仅输出 warning 日志
8. 编写单元测试：开关开启/关闭场景、降级场景

### 阶段 6：frontends 前端重构

1. 重命名所有组件文件（`vanna-*` → `chatbot-*`）
2. 重写 `vanna-design-tokens.ts` → `chatbot-design-tokens.ts`（`--vanna-` → `--chatbot-`）
3. 修改 `vanna-chat.ts`：移除品牌标题、文案；更新 CSS 变量引用
4. 修改 `api-client.ts`：重命名 `VannaApiClient` → `ChatbotApiClient`
5. 更新 `index.ts` 导出
6. 修改 `package.json` 元数据
7. 修改 `templates.py`：移除品牌 HTML；更新组件标签名
8. 更新 Storybook 标题
9. 验证：页面无 Vanna 品牌信息；对话、SQL 展示、图表正常

### 阶段 7：测试与验证

1. 运行全部现有测试套件，确认无回归
2. DdlParser + SchemaDocumentGenerator 测试：DDL.csv 解析、描述生成、容错
3. SchemaVectorStore 测试：ingest、search、持久化、多数据库
4. AutoLinkSchemaEnhancer 测试：检索结果正确注入 prompt
5. ExploreSchemaLinksTool 测试：工具调用返回正确 schema 子集
6. AutoLink 开关开启/关闭场景测试
7. AutoLink 降级场景测试（异常输入、元数据缺失、嵌入模型不可用）
8. observability 剥离验证：确认没有埋点调用
9. 前端功能测试：对话、SQL 展示、表格渲染、图表渲染
10. API 向后兼容测试：旧参数调用不报错

---

## 7. 完整测试验证清单

### 7.1 Vanna 原有能力回归测试

- [ ] `Agent.send_message()` 正常对话流程
- [ ] 工具执行（RunSqlTool）正常返回 DataFrame
- [ ] 图表生成（visualize_data）正常
- [ ] SSE 流式响应正常
- [ ] WebSocket 实时通信正常
- [ ] 轮询模式正常
- [ ] 对话存储与恢复正常
- [ ] 工作流命令（/help 等）正常
- [ ] 生命周期钩子正常执行
- [ ] 上下文增强器正常注入（DefaultLlmContextEnhancer）
- [ ] AgentMemory 工具（search_saved_correct_tool_uses 等）正常
- [ ] `create_basic_agent()` 工厂函数正常

### 7.2 AutoLink Schema 入库测试

- [ ] `DdlParser` 正常解析 DDL.csv：提取表名、列名、列类型
- [ ] `DdlParser` 提取 PK/FK：主键、外键关系写入 SchemaRelation
- [ ] `DdlParser` 容错：非法 DDL 跳过并告警，不影响其余表
- [ ] `SchemaDocumentGenerator` 生成列级文档：列名+类型+描述正确格式化
- [ ] `SchemaDocumentGenerator` 无 LLM 时退化：纯列名+类型文档仍可入库
- [ ] `SchemaVectorStore.ingest_schema()` 正常入库：从列级文档构建向量索引（一期用 FAISS 后端）
- [ ] `SchemaVectorStore.search()` 正常检索：按问题语义返回相关列
- [ ] FAISS 后端索引持久化：重启后索引可恢复
- [ ] 多数据库支持：每个数据库独立索引
- [ ] 后端接口一致性：同一组 schema 数据经不同后端 `ingest_schema()` 后，`search()` 返回语义一致的列集合（一期 FAISS 与 Chroma 骨架对比）
- [ ] 空 schema 处理：入库空 schema 不报错
- [ ] 重复入库：幂等性，覆盖旧索引

### 7.3 AutoLink Schema 检索与增强测试

- [ ] AutoLinkSchemaEnhancer 在 `enhance_system_prompt()` 中注入检索结果
- [ ] 关键列补全：优先 PK/FK relations，无 relations 时启发式兜底（*id/*name/*code）
- [ ] 检索结果格式化：正确的 prompt 片段格式
- [ ] AutoLink 关闭（默认）：enhancer 不注入额外内容
- [ ] AutoLink 开启但 SchemaVectorStore 未初始化：跳过，不报错
- [ ] AutoLink 异常降级：检索异常时自动跳过，不中断问答

### 7.4 ExploreSchemaLinksTool 测试

- [ ] 工具 schema 正确注册到 ToolRegistry
- [ ] 工具调用 `explore_schema_links(table_name="orders")` 返回正确结果
- [ ] 工具调用 `explore_schema_links(question="sales by region")` 返回语义检索结果
- [ ] LLM 能通过 Tool Calling 主动调用该工具
- [ ] 工具执行失败时返回友好错误信息

### 7.5 observability 剥离验证

- [ ] 确认 `agent.py` 中不再有 `await self.observability_provider.create_span(` 调用
- [ ] 确认 `agent.py` 中不再有 `await self.observability_provider.end_span(` 调用
- [ ] 确认 `agent.py` 中不再有 `await self.observability_provider.record_metric(` 调用
- [ ] `Agent.__init__` 中 `observability_provider` 参数保留且可正常传入
- [ ] `ObservabilityProvider` 抽象基类保留
- [ ] `Span`、`Metric` 模型保留
- [ ] 传入 `observability_provider` 不会报错
- [ ] 原始业务流程（对话、工具执行、SQL 生成）正常

### 7.6 frontends 前端功能测试

- [ ] 对话输入框正常输入和发送
- [ ] 用户消息和助手消息正常展示
- [ ] SQL 代码块正常展示
- [ ] DataFrame 表格正常渲染
- [ ] Plotly 图表正常渲染
- [ ] 错误提示正常展示
- [ ] 无 Vanna 品牌名称、logo、宣传文案
- [ ] CSS 变量前缀为 `--chatbot-` 而非 `--vanna-`
- [ ] 页面标题为非 Vanna 通用标题
- [ ] 与后端 API 通信正常

### 7.7 integrations 目录重构验证

- [ ] 新路径导入无警告：`vanna.integrations.llm.openai`、`vanna.integrations.vector.chroma`、`vanna.integrations.databases.relational.postgres` 等均可正常导入
- [ ] 旧路径兼容：`vanna.integrations.openai` 触发 `DeprecationWarning` 且类对象相同（`is` 同一对象）
- [ ] `pkgutil.iter_modules` 类反射逻辑（如 `validate_pydantic_models_in_package`）在新嵌套结构下正常
- [ ] 各 `__init__.py` 的 `__all__` 导出完整，原有公开名均可从新路径访问
- [ ] 全仓库无旧路径引用残留（rg `vanna.integrations.(anthropic|openai|faiss|chromadb|sqlite|...)`）

---

## 8. integrations 目录重构方案（新增改造项）

### 8.1 现状诊断

`src/vanna/integrations/` 现有 28 个子包按**集成产品名平铺**，混杂 6 类能力，无法从目录名判断集成类型：

| 集成产品包 | 实现的 Vanna 接口 | 能力类别 |
|-----------|-------------------|----------|
| `anthropic` / `azureopenai` / `google`(Gemini) / `ollama` / `openai` / `mock` | `LlmService` | LLM 服务 |
| `azuresearch` / `chromadb` / `faiss` / `marqo` / `milvus` / `opensearch` / `pinecone` / `qdrant` / `weaviate` / `premium`(Cloud) | `AgentMemory` | 向量库（记忆后端） |
| `mysql` / `postgres` / `sqlite` / `oracle` / `mssql` / `duckdb` | `SqlRunner` | 关系型/嵌入式数据库 |
| `bigquery` / `snowflake` / `clickhouse` / `hive` / `presto` | `SqlRunner` | 大数据引擎 / 数据仓库 |
| `local` | `ConversationStore` / `FileSystem` / `Audit` / 内存 `AgentMemory` | 本地内置实现 |
| `plotly` | `ChartGenerator`（工具链） | 可视化 |

问题：同一接口（`AgentMemory` 向量后端）与不同接口（`LlmService` vs `SqlRunner`）混在同一层；未来新增 SchemaVectorStore 后端（AutoLink 入库）无处归类，目录将持续膨胀。

### 8.2 目标目录结构（能力分类 + 数据库形态细分）

```
src/vanna/integrations/
├── __init__.py                  # 顶层导出不变（内部导入改新路径）
├── local/                       # 本地内置实现（原地保留：存储/文件系统/审计/内存记忆）
│   ├── agent_memory/            # DemoAgentMemory（InMemory）
│   ├── audit.py / file_system.py / storage.py / file_system_conversation_store.py
├── llm/                         # LlmService 实现（按厂商）
│   ├── anthropic/               # AnthropicLlmService
│   ├── azureopenai/             # AzureOpenAILlmService
│   ├── google/                  # GeminiLlmService
│   ├── ollama/                  # OllamaLlmService
│   ├── openai/                  # OpenAILlmService / OpenAIResponsesService
│   └── mock/                    # MockLlmService
├── vector/                      # AgentMemory + SchemaVectorStore 向量库实现（按产品）
│   ├── faiss/                   # FAISSAgentMemory（原有）+ FAISSSchemaVectorStore（新增）
│   ├── chroma/                  # ChromaAgentMemory（原有 chromadb 目录更名）+ ChromaSchemaVectorStore（新增）
│   ├── qdrant/                  # QdrantAgentMemory + QdrantSchemaVectorStore（新增）
│   ├── milvus/                  # MilvusAgentMemory + MilvusSchemaVectorStore（新增）
│   ├── weaviate/                # WeaviateAgentMemory
│   ├── pinecone/                # PineconeAgentMemory
│   ├── marqo/                   # MarqoAgentMemory
│   ├── opensearch/              # OpenSearchAgentMemory
│   └── azuresearch/             # AzureAISearchAgentMemory
├── databases/                   # SqlRunner 实现（按数据库形态细分）
│   ├── relational/              # 传统关系型
│   │   ├── mysql/  postgres/  sqlite/  oracle/  mssql/
│   │   └── duckdb/              # 嵌入式（也归属 relational，单一 `duckdb extra` 简化导入）
│   └── warehouse/               # 大数据引擎 / 数据仓库
│       ├── bigquery/  snowflake/  clickhouse/  hive/  presto/
├── visualization/               # 可视化
│   └── plotly/                  # PlotlyChartGenerator
└── premium/                     # Vanna 云服务（现状保留）
    └── agent_memory/            # CloudAgentMemory

# 兼容层说明：被移动的旧包路径（如 integrations/anthropic/）原地保留
# 仅含 __init__.py re-export shim（详见 8.5），不复制业务代码
```

### 8.3 归类规则（新增后端时按此决策）

| 接口 / 产品类型 | 归类路径 | 判据 |
|----------------|---------|------|
| 实现 `LlmService` | `integrations/llm/<provider>/` | 提供 LLM 对话/流式能力 |
| 实现 `AgentMemory` 或 `SchemaVectorStore` | `integrations/vector/<product>/` | 提供向量编码/检索能力 |
| 实现 `SqlRunner`（关系型/嵌入式） | `integrations/databases/relational/<db>/` | 面向行存、事务型负载 |
| 实现 `SqlRunner`（OLAP/分布式/数仓） | `integrations/databases/warehouse/<db>/` | 面向分析型负载 |
| 实现 `ChartGenerator` | `integrations/visualization/<tool>/` | 图表面板能力 |
| 本地无外部依赖的内置实现 | `integrations/local/` | FileSystem/Audit/内存 ConversationStore |
| Vanna 官方云服务 | `integrations/premium/` | 现状保留 |

Edge case 说明：`duckdb` 分析能力与嵌入式特性并存，归入 `relational/duckdb/` 以保持 `duckdb` 单一 extra 依赖与导入简洁；若未来引入面向服务化的元数据目录产品，可在 `databases/` 下新增子类（如 `databases/engines/`）。

### 8.4 全量包移动映射表

| 原路径 | 新路径 | 公开类 |
|--------|--------|--------|
| `integrations/anthropic` | `integrations/llm/anthropic` | `AnthropicLlmService` |
| `integrations/azureopenai` | `integrations/llm/azureopenai` | `AzureOpenAILlmService` |
| `integrations/google` | `integrations/llm/google` | `GeminiLlmService` |
| `integrations/ollama` | `integrations/llm/ollama` | `OllamaLlmService` |
| `integrations/openai` | `integrations/llm/openai` | `OpenAILlmService`、`OpenAIResponsesService` |
| `integrations/mock` | `integrations/llm/mock` | `MockLlmService` |
| `integrations/azuresearch` | `integrations/vector/azuresearch` | `AzureAISearchAgentMemory` |
| `integrations/chromadb` | `integrations/vector/chroma` | `ChromaAgentMemory`、`get_device`、`create_sentence_transformer_embedding_function` |
| `integrations/faiss` | `integrations/vector/faiss` | `FAISSAgentMemory`（另新增 `FAISSSchemaVectorStore`） |
| `integrations/marqo` | `integrations/vector/marqo` | `MarqoAgentMemory` |
| `integrations/milvus` | `integrations/vector/milvus` | `MilvusAgentMemory` |
| `integrations/opensearch` | `integrations/vector/opensearch` | `OpenSearchAgentMemory` |
| `integrations/pinecone` | `integrations/vector/pinecone` | `PineconeAgentMemory` |
| `integrations/qdrant` | `integrations/vector/qdrant` | `QdrantAgentMemory` |
| `integrations/weaviate` | `integrations/vector/weaviate` | `WeaviateAgentMemory` |
| `integrations/mysql` | `integrations/databases/relational/mysql` | `MySQLRunner` |
| `integrations/postgres` | `integrations/databases/relational/postgres` | `PostgresRunner` |
| `integrations/sqlite` | `integrations/databases/relational/sqlite` | `SqliteRunner` |
| `integrations/oracle` | `integrations/databases/relational/oracle` | `OracleRunner` |
| `integrations/mssql` | `integrations/databases/relational/mssql` | `MSSQLRunner` |
| `integrations/duckdb` | `integrations/databases/relational/duckdb` | `DuckDBRunner` |
| `integrations/bigquery` | `integrations/databases/warehouse/bigquery` | `BigQueryRunner` |
| `integrations/snowflake` | `integrations/databases/warehouse/snowflake` | `SnowflakeRunner` |
| `integrations/clickhouse` | `integrations/databases/warehouse/clickhouse` | `ClickHouseRunner` |
| `integrations/hive` | `integrations/databases/warehouse/hive` | `HiveRunner` |
| `integrations/presto` | `integrations/databases/warehouse/presto` | `PrestoRunner` |
| `integrations/plotly` | `integrations/visualization/plotly` | `PlotlyChartGenerator` |
| `integrations/local` | `integrations/local`（原地保留） | `MemoryConversationStore`、`LocalFileSystem` 等 |
| `integrations/premium` | `integrations/premium`（原地保留） | `CloudAgentMemory` |

不移动：`integrations/premium/`（含云服务密钥/端点语义，独立于向量产品侧）、`integrations/local/`。`chromadb` 目录在移动时更名为 `chroma`（与 `AgentMemory` 家族命名一致），旧名由兼容层接管。

### 8.5 兼容层设计（re-export shim）

每个被移动的旧包路径创建一个 shim 包（如 `src/vanna/integrations/anthropic/__init__.py`），内容模式：

```python
"""
Deprecated: use vanna.integrations.llm.anthropic instead.
"""
import warnings
from vanna.integrations.llm.anthropic import *  # noqa: F401,F403
from vanna.integrations.llm.anthropic import __all__  # noqa: F401

warnings.warn(
    "vanna.integrations.anthropic is deprecated; "
    "import from vanna.integrations.llm.anthropic",
    DeprecationWarning,
    stacklevel=2,
)
```

约束（避免 `import *` 绕过 lint 检查与双份类对象）:
- shim 只放 `__init__.py`，不复制任何业务代码
- shim 中 `__all__` 与目标模块保持一致
- 顶层 `integrations/__init__.py` 的既有导入（local/mock/plotly/sqlite）改用新路径，保证 `from vanna.integrations import MemoryConversationStore` 等 KeepSameAPI 不变
- 迁移完成后 1~2 个 minor 版本内保留 shim，之后删除

### 8.6 受影响引用清单（引用 → 更新动作）

| 引用方 | 现状 | 更新动作 |
|--------|------|----------|
| 顶层 `src/vanna/__init__.py`（`from .integrations import MemoryConversationStore, MockLlmService`） | 间接依赖旧子包 | 跟随 `integrations/__init__.py` 新路径，行为不变 |
| `src/vanna/core/agent/agent.py`（延迟导入 `vanna.integrations.local`） | local 目录原地保留 | 无需改动 |
| `src/vanna/agents/__init__.py`（`DemoAgentMemory`） | local 子包 | local 原地保留，无需改动 |
| `src/vanna/tools/visualize_data.py`、`plotly` | plotly 移动 | 改为 `vanna.integrations.visualization.plotly` |
| `src/vanna/tools/run_sql.py`、`local` | local 原地保留 | 无需改动 |
| `tests/conftest.py`（fixture 统一切换） | sqlite | 改为 `vanna.integrations.databases.relational.sqlite` |
| `tests/test_database_sanity.py`、`test_agent_memory*.py` 等 | 各数据库/向量后端/LLM | 批量替换为新路径 |
| `tests/test_azureopenai_llm.py`（`@patch("vanna.integrations.azureopenai.llm.AzureOpenAI")`） | 注意 patch 目标字符串 | patch 字符串同步改为新路径 |
| `examples/`（19 个示例） | anthropic/sqlite/openai/ollama/google/local/... | 改为新路径 |
| `README.md`、`MIGRATION_GUIDE.md`、`tox.ini`（导入检查）、`notebooks/quickstart.ipynb` | 文档/CI | 改为新路径 |

### 8.7 与本次三类改造的耦合关系

1. **AutoLink 集成**：新增 `SchemaVectorStore` 后端文件的位置应为 `integrations/vector/{faiss,chroma,milvus,qdrant}/schema_vector_store.py`（而非旧的 `integrations/{faiss,...}` 平铺路径），即在重构后的目录结构里新增文件，避免二次移动。
2. **observability 剥离**：`local/audit.py` 的 `LoggingAuditLogger` 原地保留；不因目录重构产生新耦合。
3. **frontends 重构**：`visualization/plotly` 的移动影响 `tools/visualize_data.py` 的 import，不改动浏览器端输出协议。

---

## 9. 实施顺序约束

1. **先目录重构，后新增文件**：SchemaVectorStore 后端 Adapter 应直接创建在新路径 `integrations/vector/*/`，避免先建旧路径再移动。
2. **兼容层先行一步**：shim 与移动同一提交完成，保证任一时刻旧/新路径至少一个可用。
3. **observability 剥离独立性**：observability 剥离（阶段 3）与目录重构（阶段 2）互不依赖，可并行。
4. **AutoLink 阶段顺序**：目录重构（阶段 2）必须在 Schema 入库链路开发（阶段 4）之前完成。

---

> **文档结束** —— 配套 Specification.md 见同目录下另一文档。