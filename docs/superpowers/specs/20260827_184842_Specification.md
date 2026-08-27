# Specification.md —— Vanna 集成改造详细规格说明书

> **文档版本**: v3.2  
> **创建日期**: 2026-08-24  
> **目标仓库**: vanna-ai/vanna  
> **外部能力**: wzy416/AutoLink  
> **配套文档**: IntegrationPlan.md（同目录）

---

## 1. 模块整体设计

### 1.1 核心设计原则

AutoLink 的每个子能力应映射到 Vanna 现有的架构扩展点体系，而非作为独立模块在 Agent 主循环外调用。同时必须注意：**AutoLink 原始代码消费的输入是 Spider2 数据集现成的 per-table JSON（含 description、sample_rows），并不含 DDL→文档环节**。我们的业务输入是 DDL.csv，因此需要在入库链路前端补齐「DDL 解析 → 列级文档生成」，AutoLink 中 Spider2 特有的分区表合并/嵌套列展开逻辑不移植。

| AutoLink 能力 | 映射到 Vanna 扩展点 | 新增文件 |
|--------------|-------------------|----------|
| **DDL 解析 + 列级文档生成**（AutoLink 无此环节，本次补齐） | `DdlParser` + `SchemaDocumentGenerator`（`schema_vector_store` 模块内） | `capabilities/schema_vector_store/ddl_parser.py`、`document_generator.py` |
| Schema 文档嵌入索引（对应 `embedding_docs.py`） | `SchemaVectorStore` 能力（扩展 `capabilities/` 体系，多后端可插拔） | `capabilities/schema_vector_store/`；`integrations/vector/faiss/schema_vector_store.py`（开发/逻辑验证后端）；`integrations/vector/chroma|milvus|qdrant/schema_vector_store.py`（生产后端） |
| 向量检索 Top-K 相关列（对应 `retrieve_topk_schema.py`） | `AutoLinkSchemaEnhancer(LlmContextEnhancer)` | `core/enhancer/autolink_schema.py` |
| Agent 迭代探索（对应 `complete_schema.py`） | `ExploreSchemaLinksTool(VannaTool)` | `tools/explore_schema_links.py` |
| 启发式 ID 补全（对应 `add_id.py`） | DDL 解析 PK/FK 为主 + 启发式兜底 | 集成在 `AutoLinkSchemaEnhancer` 检索逻辑中 |
| 配置管理 | `AutoLinkConfig` + `AgentConfig.autolink_config` | `core/agent/autolink_config.py` |

### 1.2 SchemaVectorStore 模块

#### 目录结构

```
src/vanna/capabilities/schema_vector_store/
├── __init__.py                          # 导出 SchemaVectorStore、DdlParser、SchemaDocumentGenerator 等
├── base.py                              # 抽象基类
├── models.py                            # SchemaColumn, SchemaTable, SchemaSearchResult, SchemaRelation
├── ddl_parser.py                        # DdlParser：解析 DDL.csv/DDL 文本（sqlparse）
└── document_generator.py                # SchemaDocumentGenerator：列级文档生成（含可选 LLM 描述）

src/vanna/integrations/vector/faiss/
├── schema_vector_store.py               # FAISSSchemaVectorStore（新增，开发/逻辑验证后端）
├── agent_memory.py                      # 现有 FAISSAgentMemory（不改动）

src/vanna/integrations/vector/chroma/
├── schema_vector_store.py               # ChromaSchemaVectorStore（一期可选实现，中小规模生产）
├── agent_memory.py                      # 现有 ChromaAgentMemory（不改动）

src/vanna/integrations/vector/milvus/
├── schema_vector_store.py               # MilvusSchemaVectorStore（接口预留，大规模生产）

src/vanna/integrations/vector/qdrant/
├── schema_vector_store.py               # QdrantSchemaVectorStore（接口预留，云原生）
```

#### 新增类与职责

| 类名 | 文件 | 职责 |
|------|------|------|
| `SchemaColumn` | `models.py` | 列元数据：column_name, table_name, data_type, description, sample_values |
| `SchemaTable` | `models.py` | 表元数据：table_name, database_name, columns, primary_keys, foreign_keys |
| `SchemaSearchResult` | `models.py` | 检索结果：column, similarity_score, rank |
| `SchemaRelation` | `models.py` | 表间/列间关系：from_table, from_column, to_table, to_column, relation_type（PK/FK） |
| `DdlParser` | `ddl_parser.py` | 解析 DDL.csv/DDL 文本 → List[SchemaTable] + List[SchemaRelation]（提取表、列、类型、主键、外键） |
| `SchemaDocumentGenerator` | `document_generator.py` | SchemaTable → 列级文档字符串；可选 LLM 生成列描述、可选采样值 |
| `SchemaVectorStore` | `base.py` | 抽象基类：`ingest_schema()` 入库，`search()` 检索；接口与向量后端解耦 |
| `FAISSSchemaVectorStore` | `integrations/vector/faiss/schema_vector_store.py` | 开发/逻辑验证后端：SentenceTransformer 编码 + IndexFlatL2 + 持久化（对齐 AutoLink 原版） |
| `ChromaSchemaVectorStore` | `integrations/vector/chroma/schema_vector_store.py` | 一期可选实现：中小规模生产；嵌入式或 C/S 模式；自带元数据过滤 |
| `MilvusSchemaVectorStore` | `integrations/vector/milvus/schema_vector_store.py` | 接口预留与默认实现骨架：大规模生产、高并发 |
| `QdrantSchemaVectorStore` | `integrations/vector/qdrant/schema_vector_store.py` | 接口预留与默认实现骨架：云原生部署 |

#### 文字版类图

```
┌──────────────────────────────┐
│       SchemaColumn           │  (Pydantic BaseModel)
├──────────────────────────────┤
│ + column_name: str           │
│ + table_name: str            │
│ + data_type: str             │
│ + description: Optional[str] │
│ + sample_values: List[str]   │
└──────────────────────────────┘

┌──────────────────────────────┐
│       SchemaTable            │  (Pydantic BaseModel)
├──────────────────────────────┤
│ + table_name: str            │
│ + database_name: str         │
│ + columns: List[SchemaColumn]│
│ + primary_keys: List[str]    │
│ + foreign_keys: List[dict]   │
└──────────────────────────────┘

┌──────────────────────────────┐
│      SchemaRelation          │  (Pydantic BaseModel)
├──────────────────────────────┤
│ + from_table: str            │
│ + from_column: str           │
│ + to_table: str              │
│ + to_column: str             │
│ + relation_type: str         │  # "pk" | "fk"
└──────────────────────────────┘

┌───────────────────────────────────────┐
│   SchemaVectorStore (ABC)            │
│   (capabilities/schema_vector_store/ │
│    base.py)                           │
├───────────────────────────────────────┤
│ + async ingest_schema(               │
│     tables: List[SchemaTable],        │
│     relations: List[SchemaRelation],  │
│     database_name: str                │
│   ) -> None                           │
│ + async search(                       │
│     query: str,                       │
│     database_name: str,               │
│     top_k: int = 20                   │
│   ) -> List[SchemaSearchResult]       │
│ + async get_column_by_name(           │
│     column_name: str,                 │
│     table_name: str,                  │
│     database_name: str                │
│   ) -> Optional[SchemaColumn]         │
│ + async get_relations(                │
│     table_names: List[str],           │
│     database_name: str                │
│   ) -> List[SchemaRelation]           │
└───────────────────────────────────────┘
              △
              │ 实现（多后端可插拔，上层只依赖抽象接口）
              │
┌───────────────────────────────────────┐
│  FAISSSchemaVectorStore              │
│  (integrations/vector/faiss/         │
│   schema_vector_store.py)            │
│   ── 开发/逻辑验证后端                │
├───────────────────────────────────────┤
│ - embedding_model: SentenceTransformer│
│ - indexes: Dict[str, faiss.Index]     │
│ - metadata: Dict[str, dict]           │
│ - persist_dir: str                    │
├───────────────────────────────────────┤
│ + async ingest_schema(...)            │
│   └─ 编码 → IndexFlatL2 → 持久化     │
│ + async search(...)                   │
│   └─ 编码查询 → FAISS search → 排序  │
│ + async get_column_by_name(...)       │
│   └─ 精确/模糊匹配 metadata           │
│ + async get_relations(...)            │
│   └─ 从 metadata relations 过滤       │
│ + _build_embedding_text(col) -> str   │
│   └─ "{table}.{column}: {description}"│
└───────────────────────────────────────┘

┌───────────────────────────────────────┐
│  ChromaSchemaVectorStore             │
│  (integrations/vector/chroma/        │
│   schema_vector_store.py)            │
│   ── 一期可选/生产后端                │
├───────────────────────────────────────┤
│ 同一 SchemaVectorStore 四接口语义；   │
│ 复用 [all] 已含 chromadb 依赖；       │
│ collection 按 database_name 隔离      │
└───────────────────────────────────────┘

┌───────────────────────────────────────┐
│  Milvus / QdrantSchemaVectorStore    │
│  (integrations/vector/milvus|qdrant/ │
│   ...) ── 接口预留，按需开发          │
├───────────────────────────────────────┤
│ 同一 SchemaVectorStore 四接口语义；   │
│ 走各自 extra 依赖组（pymilvus /       │
│ qdrant-client）                        │
└───────────────────────────────────────┘
```

#### 入库前置：DDL 解析与列级文档生成（本次新增）

```
DDL.csv (表名、DDL 文本)
  │
  ▼
DdlParser.parse_csv(csv_path)               [1] 解析 DDL
  ├─ 逐行读取（跳过 SKIP_TABLES 语义的 sqlite_sequence 等系统表）
  ├─ sqlparse 解析每条 DDL
  │     ├─ 表名
  │     ├─ 列：名称、类型、NOT NULL 等约束
  │     ├─ PRIMARY KEY (col1, ...)
  │     └─ FOREIGN KEY (col) REFERENCES other_table(other_col)
  ├─ 解析失败的表：记录 warning 并跳过，不影响其余表
  └─ 输出: List[SchemaTable] + List[SchemaRelation]
  │
  ▼
SchemaDocumentGenerator.generate(tables, relations)   [2] 生成列级文档
  ├─ 对每个 SchemaTable.column:
  │     ├─ 描述来源优先级:
  │     │     ① 用户显式传入的 description
  │     │     ② 可选 LLM 依据列名+类型+表名生成（批量调用，失败重用空描述）
  │     │     ③ 无 → 退化为纯列名+类型文档（不阻断入库）
  │     ├─ 可选择性填充 sample_values（数据库连接采样）
  │     └─ 格式化文档文本:
  │           "column name: {column}\ncolumn type: {type}
  │            \ntable name: {table}\ndescription: {desc}"
  ├─ 单条文档粒度 = 一个列（与 AutoLink 一致）
  └─ 输出: List[str] 列级文档（顺序与列一一对应）
  │
  ▼
SchemaVectorStore.ingest_schema(tables, relations, database_name)  [3] 入库（后端不感知）
  │
  ├─ 内部调用 SchemaDocumentGenerator 生成文档
  ├─ SentenceTransformer 批量编码（跨后端共享的嵌入组件）
  ├─ 按配置路由到具体后端 Adapter（AutoLinkConfig.vector_store_backend，默认 "faiss"）:
  │     ① FAISSSchemaVectorStore（开发/逻辑验证）
  │        - 构建/重建 IndexFlatL2 (dimension=1024, metric=L2)
  │        - 持久化: index.faiss + metadata.json → {persist_dir}/{database_name}/
  │        - metadata.json 写入 columns / embedding_texts / relations
  │     ② ChromaSchemaVectorStore（一期可选/中小规模生产）
  │        - collection 按 database_name 隔离；写入列文档 + 元数据
  │     ③ Milvus / QdrantSchemaVectorStore（接口预留）
  │        - 同一四接口语义，按需实现
  └─ relations（PK/FK 关系）随元数据一并持久化（来自 DDL 解析，非启发式）
```

> 说明：AutoLink `generate_docs.py` 的消费对象是 Spider2 per-table JSON（`table_fullname`/`description`/`sample_rows` 等），我们业务输入是 DDL.csv，故 DDL 解析 + 列文档生成是本方案**新增的前置环节**，而不是照搬 AutoLink 的 JSON→文档逻辑。

### 1.3 AutoLinkSchemaEnhancer 模块

#### 文件

`src/vanna/core/enhancer/autolink_schema.py`

#### 类设计

```python
class AutoLinkSchemaEnhancer(LlmContextEnhancer):
    """通过 SchemaVectorStore（后端不感知）检索相关 schema 列并注入到 system prompt。

    实现 AutoLink 的 retrieve_topk_schema 检索逻辑，
    关键列补全优先使用 DDL 解析的 PK/FK relations（add_id.py 启发式仅作兜底）。
    在 enhance_system_prompt() 中：
    1. 对用户问题语义检索 top-k 相关列
    2. 关键列补全：优先 PK/FK relations，无 relations 时启发式补 *id/*name/*code
    3. 格式化为 prompt 片段
    4. 追加到 system_prompt
    """

    def __init__(self, schema_vector_store, config):
        self.schema_vector_store = schema_vector_store
        self.config = config

    async def enhance_system_prompt(self, system_prompt, user_message, user):
        if not self.config.enabled:
            return system_prompt
        try:
            results = await self.schema_vector_store.search(
                query=user_message,
                database_name=self.config.database_name,
                top_k=self.config.top_k_columns,
            )
            if not results:
                return system_prompt
            results = await self._add_key_columns(results)
            schema_context = self._format_schema_context(results)
            return system_prompt + "\n\n" + schema_context
        except Exception as e:
            logger.warning(f"AutoLinkSchemaEnhancer failed: {e}")
            return system_prompt  # 降级

    async def _add_key_columns(self, results):
        """关键列补全：DDL 解析 PK/FK 为主，启发式为兜底"""
        # [1] 主路径: 调用 schema_vector_store.get_relations(table_names)
        #     获取已检索表的 PK/FK 关系，补全关系涉及的列
        # [2] 兜底: 若 relations 为空且 config.enable_key_column_hints=True
        #     遍历已检索表的 key_column_patterns 匹配列（*id/*name/*code）自动补充
        ...

    def _format_schema_context(self, results):
        """格式化为 LLM 可读的 schema prompt"""
        # 输出格式:
        # ============================================================
        # DATABASE SCHEMA (Auto-Discovered):
        # ============================================================
        # ###Table: orders (Database: sales_db)
        # [id (Type: INTEGER; Sample: [...])]
        # [customer_id (Type: INTEGER; Sample: [...])]
        ...
```

#### 与 DefaultLlmContextEnhancer 的链式组合

当前 `Agent.__init__()` 中（`src/vanna/core/agent/agent.py` 第 127 行）只接受单个 `llm_context_enhancer`。改为 enhancer 链：

```python
# 原代码（第 127 行）:
if llm_context_enhancer is None:
    llm_context_enhancer = DefaultLlmContextEnhancer(agent_memory)
self.llm_context_enhancer = llm_context_enhancer

# 改造后:
self.llm_context_enhancers: List[LlmContextEnhancer] = []
if agent_memory is not None:
    self.llm_context_enhancers.append(DefaultLlmContextEnhancer(agent_memory))
if config.autolink_config.enabled and schema_vector_store is not None:
    self.llm_context_enhancers.append(
        AutoLinkSchemaEnhancer(schema_vector_store, config.autolink_config)
    )
```

在 `_send_message()` 中（约第 604 行）链式调用：

```python
# 原代码:
system_prompt = await self.llm_context_enhancer.enhance_system_prompt(
    system_prompt, message, user
)

# 改造后:
for enhancer in self.llm_context_enhancers:
    system_prompt = await enhancer.enhance_system_prompt(
        system_prompt, message, user
    )
```

### 1.4 ExploreSchemaLinksTool 模块

#### 文件

`src/vanna/tools/explore_schema_links.py`

#### 类设计

```python
class ExploreSchemaLinksInput(BaseModel):
    table_name: Optional[str] = None
    column_name: Optional[str] = None
    search_query: Optional[str] = None

class ExploreSchemaLinksTool(VannaTool[ExploreSchemaLinksInput]):
    """Schema 链接探索工具。

    允许 LLM 在工具调用循环中主动探索数据库 schema，
    发现表间关联、JOIN 列。对应 AutoLink 的 complete_schema.py 逻辑。
    """

    def __init__(self, schema_vector_store):
        self.schema_vector_store = schema_vector_store

    @property
    def name(self) -> str:
        return "explore_schema_links"

    @property
    def description(self) -> str:
        return (
            "Explore the database schema to discover table relationships, "
            "join columns, and relevant columns for a query."
        )

    async def execute(self, context, input):
        # 三种检索模式：
        # 1. 精确查找: column_name + table_name
        # 2. 语义检索: search_query
        # 3. 按表检索: table_name only
        ...
```

#### ToolContext 扩展

`src/vanna/core/tool/models.py` 中 `ToolContext` 新增字段：

```python
schema_vector_store: Optional["SchemaVectorStore"] = Field(
    default=None,
    description="Optional SchemaVectorStore for schema exploration (AutoLink)"
)
```

### 1.5 observability 模块现状

完全相同于 v1 版本。保留抽象接口，删除所有业务调用。

### 1.6 frontends 前端模块设计

完全相同于 v1 版本。

---

## 2. 完整数据流

### 2.1 主链路数据流（含 AutoLink 分支）

```
用户输入: "Show me total sales by product category for Q1 2026"
  │
  ▼
┌──────────────────────────────────────────────────────────────────┐
│ FastAPI Routes (src/vanna/servers/fastapi/routes.py:43)          │
│ POST /api/vanna/v2/chat_sse → chat_sse()                          │
└──────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────┐
│ ChatHandler.handle_stream()                                       │
│ (src/vanna/servers/base/chat_handler.py:26)                       │
└──────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────┐
│ Agent.send_message() (src/vanna/core/agent/agent.py:142)          │
│                                                                   │
│ Step 1-5: 用户解析 → 工作流检查 → 对话加载 → 上下文富化 → 工具schema│
│                                                                   │
│ Step 6: SystemPromptBuilder.build_system_prompt()                  │
│   (src/vanna/core/system_prompt/default.py:34)                    │
│   输出: system_prompt                                             │
│   ★ 当 explore_schema_links 工具可用时，注入 AUTO-LINK 指令        │
│                                                                   │
│ Step 7: LlmContextEnhancer chain                                   │
│   ├─ DefaultLlmContextEnhancer: 注入 AgentMemory 文本记忆          │
│   └─ AutoLinkSchemaEnhancer:                                      │
│       ★ 语义检索 top-k 相关列                                      │
│       ★ 关键列补全：优先 PK/FK relations，无则启发式兜底             │
│       ★ 格式化为 "DATABASE SCHEMA (Auto-Discovered)" 片段          │
│       ★ 追加到 system_prompt                                      │
│                                                                   │
│ Step 8: _build_llm_request() → 组装 LLM 请求                      │
│                                                                   │
│ Step 9: LLM 调用                                                  │
│                                                                   │
│ Step 10: Tool Loop                                                 │
│   ├─ run_sql: 执行 SQL                                            │
│   ├─ visualize_data: 生成图表                                     │
│   ├─ search_saved_correct_tool_uses: 检索记忆                     │
│   ├─ save_question_tool_args: 保存工具使用                        │
│   ├─ save_text_memory: 保存文本记忆                               │
│   ★ explore_schema_links: 探索 schema 关联（新增）                 │
│       └─ LLM 主动调用 → SchemaVectorStore.search() → 返回相关列    │
│                                                                   │
│ Step 11-12: 保存对话 → after_message hook                         │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 AutoLink 子链路详细数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                    离线：Schema 入库（新增 DDL 前置环节）          │
│                                                                  │
│ DDL.csv (表名、DDL 文本)  ← 业务真实输入                          │
│   │                                                              │
│   ▼                                                              │
│ DdlParser.parse_csv()                                            │
│   ├─ sqlparse 解析 → 表、列、类型、PK/FK                          │
│   └─ 失败表跳过并告警                                              │
│   │                                                              │
│   ▼                                                              │
│ SchemaDocumentGenerator.generate()                               │
│   ├─ 列级文档: "column name/type/table name/description"         │
│   ├─ 描述可选 LLM 生成；采样值可选                                 │
│   └─ 无描述时退化纯列名+类型文档                                   │
│   │                                                              │
│   ▼                                                              │
│ SchemaVectorStore.ingest_schema()（后端按 vector_store_backend 路由）│
│   ├─ SentenceTransformer 批量编码 → (N, 1024) 向量                 │
│   ├─ FAISS 后端: 构建 IndexFlatL2 + 持久化 index.faiss/metadata   │
│   ├─ Chroma/Milvus/Qdrant 后端: 写入对应向量库                     │
│   ├─ metadata 写入 relations（来自 DDL 解析 PK/FK）；后端负责持久化 │
│   └─ 默认后端: FAISS（开发/逻辑验证）                              │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    在线：Schema 检索与增强                         │
│                                                                  │
│ 用户问题                                                          │
│   │                                                              │
│   ▼                                                              │
│ AutoLinkSchemaEnhancer.enhance_system_prompt()                   │
│   ├─ [1] 语义检索: SchemaVectorStore.search(query, top_k=20)     │
│   │      └─ 编码问题 → 后端 Adapter 检索 → top-k 结果（后端不感知）│
│   ├─ [2] 关键列补全: _add_key_columns()                          │
│   │      ├─ 主路径: get_relations() → 补全 PK/FK 涉及列           │
│   │      └─ 兜底: key_column_patterns (*id/*name/*code)          │
│   ├─ [3] 格式化: _format_schema_context()                        │
│   │      └─ 输出 "DATABASE SCHEMA (Auto-Discovered)" 片段        │
│   └─ [4] 追加到 system_prompt                                    │
│                                                                  │
│   ▼                                                              │
│ LLM 在工具循环中可主动调用 explore_schema_links 工具               │
│   ├─ explore_schema_links(table_name="orders") → 返回表的所有列   │
│   ├─ explore_schema_links(search_query="customer info") → 语义检索│
│   └─ explore_schema_links(column_name="id", table_name="orders")  │
│       → 精确查找列信息                                            │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 observability 埋点跳过说明

所有原来标记为 observability_span 的步骤，在剥离后不再创建 Span/调用 Metric。业务流程完全不受影响。

---

## 3. 全部配置项定义

### 3.1 AutoLinkConfig 新增配置

在 `src/vanna/core/agent/autolink_config.py` 中定义：

```python
class AutoLinkConfig(BaseModel):
    enabled: bool = Field(default=False)
    database_name: str = Field(default="default")
    embedding_model: str = Field(default="BAAI/bge-large-en-v1.5")
    top_k_columns: int = Field(default=20, ge=1, le=200)
    fallback_on_error: bool = Field(default=True)
    enable_key_column_hints: bool = Field(default=True)
    key_column_patterns: List[str] = Field(
        default_factory=lambda: ["*id*", "*name*", "*code*"]
    )
    ddl_csv_path: Optional[str] = Field(
        default=None,
        description="DDL.csv 路径；提供后 Agent 初始化时可自动调用 ingest_schema() 入库",
    )
    llm_description_enabled: bool = Field(
        default=False,
        description="是否调用 LLM 为列生成语义描述（DDL 本身不含描述）",
    )
    vector_store_backend: str = Field(
        default="faiss",
        description="SchemaVectorStore 后端选择：faiss（开发/逻辑验证）/ chroma / milvus / qdrant",
    )
```

在 `src/vanna/core/agent/config.py` 中 `AgentConfig` 新增：

```python
autolink_config: AutoLinkConfig = Field(default_factory=AutoLinkConfig)
```

### 3.2 配置项汇总表

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `autolink_config.enabled` | bool | `False` | AutoLink 总开关 |
| `autolink_config.database_name` | str | `"default"` | 目标数据库名 |
| `autolink_config.embedding_model` | str | `"BAAI/bge-large-en-v1.5"` | 嵌入模型 |
| `autolink_config.top_k_columns` | int | `20` | 检索列数上限 |
| `autolink_config.fallback_on_error` | bool | `True` | 异常时降级 |
| `autolink_config.enable_key_column_hints` | bool | `True` | 启发式 ID/Name/Code 补全兜底（无 PK/FK relations 时生效） |
| `autolink_config.ddl_csv_path` | Optional[str] | `None` | DDL.csv 路径，提供后初始化自动入库 |
| `autolink_config.llm_description_enabled` | bool | `False` | LLM 生成列语义描述开关 |
| `autolink_config.vector_store_backend` | str | `"faiss"` | SchemaVectorStore 后端：`faiss`（开发/逻辑验证）/ `chroma` / `milvus` / `qdrant` |
| `observability_provider` | Optional | `None` | 【预留暂未实现】 |
| `max_tool_iterations` | int | `10` | 不改动 |
| `stream_responses` | bool | `True` | 不改动 |

---

## 4. Python API 变更规格

### 4.1 原有 API 保持兼容

`Agent` 类的所有现有参数和方法签名保持不变。未传入 `autolink_config` 或 `schema_vector_store` 时，AutoLink 完全关闭。

### 4.2 新增参数

#### `Agent.__init__` 新增

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `schema_vector_store` | `Optional[SchemaVectorStore]` | `None` | Schema 向量存储实例 |

### 4.3 调用示例

#### 示例 1：原生 Vanna 模式（关闭 AutoLink，完全向后兼容）

```python
from vanna.core.agent import Agent
from vanna.core.agent.config import AgentConfig

config = AgentConfig(max_tool_iterations=10, stream_responses=True)
agent = Agent(
    llm_service=my_llm_service,
    tool_registry=my_tool_registry,
    user_resolver=my_user_resolver,
    agent_memory=my_agent_memory,
    config=config,
    # schema_vector_store 不传入，AutoLink 不生效
)
# 行为与改造前完全一致
```

#### 示例 2：开启 AutoLink（DDL.csv 入库 + 检索 + 工具探索）

```python
from vanna.core.agent import Agent
from vanna.core.agent.config import AgentConfig, AutoLinkConfig
from vanna.capabilities.schema_vector_store.ddl_parser import DdlParser
from vanna.integrations.vector.faiss.schema_vector_store import FAISSSchemaVectorStore
from vanna.tools.explore_schema_links import ExploreSchemaLinksTool

# 1. 解析 DDL.csv（业务真实输入），得到表结构 + PK/FK 关系
parser = DdlParser()
tables, relations = parser.parse_csv("./schema/sales_db/DDL.csv")

# 2. 创建 SchemaVectorStore 并入库（内部生成列级文档 → 编码 → 入库）
#    开发/逻辑验证用 FAISS 后端（零外部依赖、本地文件）；
#    生产可切换: ChromaSchemaVectorStore / MilvusSchemaVectorStore / QdrantSchemaVectorStore
store = FAISSSchemaVectorStore(
    persist_dir="./schema_index",
    embedding_model="BAAI/bge-large-en-v1.5",
)
await store.ingest_schema(
    tables=tables,
    relations=relations,          # PK/FK 关系随 metadata 一并落库
    database_name="sales_db",
)

# 3. 配置 AutoLink
autolink_config = AutoLinkConfig(
    enabled=True,
    database_name="sales_db",
    top_k_columns=20,
)

config = AgentConfig(
    max_tool_iterations=10,
    stream_responses=True,
    autolink_config=autolink_config,
)

# 4. 注册 explore_schema_links 工具
tool_registry = my_tool_registry
tool_registry.register(ExploreSchemaLinksTool(schema_vector_store=store))

# 5. 创建 Agent
agent = Agent(
    llm_service=my_llm_service,
    tool_registry=tool_registry,
    user_resolver=my_user_resolver,
    agent_memory=my_agent_memory,
    config=config,
    schema_vector_store=store,  # 注入 SchemaVectorStore
)

# 6. 提问
# AutoLinkSchemaEnhancer 自动在 system_prompt 中注入相关 schema 列
# LLM 可主动调用 explore_schema_links 工具探索关联
async for component in agent.send_message(
    request_context,
    "Show total sales by customer name"
):
    print(component)
```

#### 示例 3：仅入库 Schema（无 DDL 解析，直接提供 SchemaTable）

```python
# 只做 schema 入库，不在问答链路中使用
# 后端可替换：生产可切 ChromaSchemaVectorStore/MilvusSchemaVectorStore/QdrantSchemaVectorStore，
# ingest_schema()/search() 调用方式完全一致
store = FAISSSchemaVectorStore(persist_dir="./schema_index")
await store.ingest_schema(
    tables=[SchemaTable(table_name="orders", database_name="sales_db", columns=[...])],
    relations=[...],
    database_name="sales_db",
)

# 后续可手动检索
results = await store.search("customer orders", database_name="sales_db")
```

---

## 5. Remote FastAPI 接口变更规格

### 5.1 接口协议不变

| 端点 | 方法 | 请求体 | 响应体 | 变更 |
|------|------|--------|--------|------|
| `/api/vanna/v2/chat_sse` | POST | `ChatRequest` | SSE Stream | 无变更 |
| `/api/vanna/v2/chat_websocket` | WebSocket | JSON | JSON Stream | 无变更 |
| `/api/vanna/v2/chat_poll` | POST | `ChatRequest` | `ChatResponse` | 无变更 |
| `/` | GET | — | HTML | 仅修改 HTML 内容（品牌剥离） |
| `/health` | GET | — | `{"status": "healthy"}` | 无变更 |

### 5.2 新增可选请求字段

`ChatRequest` 可新增 `autolink_enabled: Optional[bool]` 字段，为 None 时使用 AgentConfig 默认值。

---

## 6. Prompt 模板改造规格

### 6.1 AutoLinkSchemaEnhancer 注入的 Prompt 片段

```
============================================================
DATABASE SCHEMA (Auto-Discovered):
============================================================
The following tables and columns are automatically identified as relevant to your question.

###Table: orders (Database: sales_db)
[id (Type: INTEGER; Sample: [1001, 1002, 1003])]
[customer_id (Type: INTEGER; Sample: [201, 202, 203])]
[total_amount (Type: DECIMAL; Sample: [99.99, 149.50, 200.00])]

###Table: customers (Database: sales_db)
[id (Type: INTEGER; Sample: [201, 202, 203])]
[name (Type: VARCHAR; Sample: ['Alice', 'Bob', 'Charlie'])]

###Relations (from DDL foreign keys):
[orders.customer_id -> customers.id]

IMPORTANT: Use these columns when constructing your query. Prefer the explicit
Relations above when writing JOIN conditions.
```

### 6.2 SystemPromptBuilder 新增指令

在 `src/vanna/core/system_prompt/default.py` 的 `build_system_prompt()` 中，当 `explore_schema_links` 工具可用时追加：

```
============================================================
AUTO-LINK SCHEMA EXPLORATION:
============================================================
When you need to understand the database schema for a query:
1. First, check the DATABASE SCHEMA section above for auto-discovered relevant columns
2. If you need more information about a specific table, use the explore_schema_links tool
3. If you need to find columns related to a concept, use explore_schema_links with a search_query
4. Always verify JOIN conditions by matching column names and types across tables
```

### 6.3 前端改造后 system_prompt 品牌文案调整

`DefaultSystemPromptBuilder.build_system_prompt()` 中品牌文案改为通用版本：

```python
# 原代码:
f"You are Vanna, an AI data analyst assistant created to help users..."

# 改造后:
f"You are an AI data analyst assistant. Help users with data analysis tasks..."
```

---

## 7. observability_provider 剥离详细规格

与 v1 版本完全相同。保留抽象接口，删除所有业务调用。

---

## 8. frontends 前端页面详细规格

与 v1 版本完全相同。

---

## 9. 异常与降级逻辑全量说明

### 9.1 AutoLink 异常降级

| 异常场景 | 处理方式 | 日志级别 |
|----------|----------|----------|
| SentenceTransformer 加载失败 | 跳过，AutoLinkSchemaEnhancer 不注入 | `logger.warning()` |
| DDL.csv 不存在 / 无法解析 | 入库前置失败，跳过入库，提示用户 | `logger.error()` |
| 单表 DDL 解析失败 | 跳过该表，其余表正常入库 | `logger.warning()` |
| LLM 列描述生成失败 | 退化纯列名+类型文档，不阻断入库 | `logger.warning()` |
| 采样值获取失败（无数据库连接） | 不采样，入库仍可用 | `logger.info()` |
| FAISS 后端索引文件不存在（开发后端） | 跳过 | `logger.info()` |
| Chroma/Milvus/Qdrant 服务连接失败（生产后端） | 连接失败后端不可用时抛明确异常；如有 fallback_on_error 且未禁用，退化跳过入库；不静默切换后端 | `logger.error()` / `logger.warning()` |
| 检索过程异常 | 跳过，返回原始 prompt | `logger.warning()` |
| SchemaVectorStore 未初始化 | 跳过 | `logger.info()` |
| 嵌入模型不可用 | 跳过 | `logger.warning()` |

### 9.2 observability 不存在业务报错

剥离后，`self.observability_provider` 为 None 或任意实例都不会引发异常。

### 9.3 前端异常处理

与 v1 版本相同。

---

## 10. 单元测试 & 回归测试规格

### 10.1 Schema 入库链路测试

#### DdlParser 测试（DP-*）

| 用例 ID | 场景 | 预期输出 |
|---------|------|----------|
| DP-001 | 解析正常 DDL.csv | 提取表名、列名、列类型 |
| DP-002 | 解析 PRIMARY KEY | SchemaTable.primary_keys 正确 |
| DP-003 | 解析 FOREIGN KEY | SchemaRelation（fk）正确生成 |
| DP-004 | 单行 DDL 非法 | 跳过该表并告警，其余表正常解析 |
| DP-005 | 空 DDL.csv | 返回空列表，不报错 |

#### SchemaDocumentGenerator 测试（DG-*）

| 用例 ID | 场景 | 预期输出 |
|---------|------|----------|
| DG-001 | 显式 description 存在 | 文档含 description，LLM 不被调用 |
| DG-002 | 无 description 且 LLM 开启 | 调用 LLM 批量生成描述 |
| DG-003 | 无 description 且 LLM 失败/关闭 | 退化纯列名+类型文档，不阻断 |
| DG-004 | 文档格式 | 符合 "column name/type/table name/description" 模板 |

#### SchemaVectorStore 测试（SV-*）

| 用例 ID | 场景 | 预期输出 |
|---------|------|----------|
| SV-001 | `ingest_schema()` 正常入库 | 后端无关：FAISS 后端时索引文件创建、metadata.json 可读 |
| SV-002 | `search()` 语义检索 | 返回与 query 语义相关的列 |
| SV-003 | 索引持久化与恢复 | 重启后 `search()` 正常 |
| SV-004 | 多数据库独立索引 | 不同 database_name 不互相干扰 |
| SV-005 | 空 schema 入库 | 不报错，search 返回空列表 |
| SV-006 | `get_column_by_name()` 精确查找 | 返回正确列信息 |
| SV-007 | 重复入库 | 幂等，覆盖旧索引 |
| SV-008 | relations 落库 | 元数据 relations 可被 `get_relations()` 读取 |
| SV-009 | 后端切换（默认 faiss → chroma） | `vector_store_backend` 配置切换后，同一 `ingest_schema()`/`search()` 调用语义一致 |
| SV-010 | 多后端接口一致性 | 同一组 schema 数据经不同后端入库后，`search()` 返回语义一致的列集合（一期用 FAISS 与 Chroma 骨架对比） |

### 10.2 AutoLinkSchemaEnhancer 测试

| 用例 ID | 场景 | 预期输出 |
|---------|------|----------|
| SE-001 | AutoLink 关闭 | system_prompt 不变 |
| SE-002 | AutoLink 开启，有检索结果 | system_prompt 包含 "DATABASE SCHEMA (Auto-Discovered)" 片段 |
| SE-003 | relations 存在时关键列补全 | PK/FK 涉及列被补充，Relations 片段出现在 prompt |
| SE-004 | 无 relations 时启发式兜底 | *id/*name/*code 列被自动补充 |
| SE-005 | 检索结果为空 | system_prompt 不变 |
| SE-006 | 检索异常 | 降级，返回原始 prompt，输出 warning |
| SE-007 | SchemaVectorStore 为 None | 跳过，不报错 |

### 10.3 ExploreSchemaLinksTool 测试

| 用例 ID | 场景 | 预期输出 |
|---------|------|----------|
| ET-001 | 工具注册 | 正确注册到 ToolRegistry |
| ET-002 | 按表名检索 | 返回该表所有列 |
| ET-003 | 语义检索 | 返回相关列 |
| ET-004 | 精确列查找 | 返回指定列信息 |
| ET-005 | 工具执行失败 | 返回友好错误信息 |

### 10.4 Vanna 原有能力回归测试

与 v1 版本相同。

### 10.5 observability 剥离验证

与 v1 版本相同。

### 10.6 frontends 前端功能测试

与 v1 版本相同。

---

## 11. 使用示例代码片段

### 示例 1：原生 Vanna 模式（关闭 AutoLink）

```python
from vanna.agents import create_basic_agent

agent = create_basic_agent(
    llm_service=my_llm_service,
    tool_registry=my_tool_registry,
    user_resolver=my_user_resolver,
    agent_memory=my_agent_memory,
)

async for component in agent.send_message(
    request_context, "Show total revenue by region"
):
    print(component.simple_component.text if component.simple_component else "")
```

### 示例 2：开启 AutoLink（DDL.csv → 入库 → 检索 → 工具探索）

```python
from vanna.core.agent import Agent
from vanna.core.agent.config import AgentConfig, AutoLinkConfig
from vanna.capabilities.schema_vector_store.ddl_parser import DdlParser
from vanna.integrations.vector.faiss.schema_vector_store import FAISSSchemaVectorStore
from vanna.tools.explore_schema_links import ExploreSchemaLinksTool

# Step 1: 解析 DDL.csv → 表结构与 PK/FK 关系（业务真实输入）
tables, relations = DdlParser().parse_csv("./schema/db/DDL.csv")

# Step 2: Schema 入库（列级文档生成 → 编码 → 入库）
#    开发/逻辑验证用 FAISS 后端；生产可切换 Chroma/Milvus/Qdrant（调用方式一致）
store = FAISSSchemaVectorStore(persist_dir="./schema_index")
await store.ingest_schema(
    tables=tables,
    relations=relations,          # PK/FK 随 metadata 落库
    database_name="db",
)

# Step 3: 注册工具
tool_registry = create_default_tool_registry()
tool_registry.register(ExploreSchemaLinksTool(schema_vector_store=store))

# Step 4: 创建 Agent
config = AgentConfig(
    max_tool_iterations=10,
    stream_responses=True,
    autolink_config=AutoLinkConfig(enabled=True, database_name="db"),
)

agent = Agent(
    llm_service=my_llm_service,
    tool_registry=tool_registry,
    user_resolver=my_user_resolver,
    agent_memory=my_agent_memory,
    config=config,
    schema_vector_store=store,
)

async for component in agent.send_message(
    request_context, "Show orders with customer names"
):
    print(component)
```

### 示例 3：后续重新注入自定义 observability provider

与 v1 版本相同。

---

## 12. integrations 目录重构详细规格（v3.2 新增）

> 本章为目录重构的落地规格。方案背景与动机见 IntegrationPlan.md 第 8 章；本章给出可直接执行的目录结构、映射关系、兼容层模板与验证标准。

### 12.1 目标目录结构（能力分类 + 数据库形态细分）

```
src/vanna/integrations/
├── __init__.py                  # 顶层导出不变（内部导入改新路径）
├── local/                       # 本地内置实现（原地保留：存储/文件系统/审计/内存记忆）
│   └── agent_memory/            # DemoAgentMemory（InMemory）
├── llm/                         # LlmService 实现（按厂商）
│   ├── anthropic/  azureopenai/  google/  ollama/  openai/  mock/
├── vector/                      # AgentMemory + SchemaVectorStore 向量库实现（按产品）
│   ├── faiss/                   # FAISSAgentMemory（原有）+ FAISSSchemaVectorStore（新增）
│   ├── chroma/                  # ChromaAgentMemory（原 chromadb 更名）+ ChromaSchemaVectorStore（新增）
│   ├── qdrant/                  # QdrantAgentMemory + QdrantSchemaVectorStore（新增）
│   ├── milvus/                  # MilvusAgentMemory + MilvusSchemaVectorStore（新增）
│   ├── weaviate/  pinecone/  marqo/  opensearch/  azuresearch/
├── databases/                   # SqlRunner 实现（按数据库形态细分）
│   ├── relational/              # 传统关系型 + 嵌入式
│   │   ├── mysql/  postgres/  sqlite/  oracle/  mssql/  duckdb/
│   └── warehouse/               # 大数据引擎 / 数据仓库
│       ├── bigquery/  snowflake/  clickhouse/  hive/  presto/
├── visualization/               # 可视化
│   └── plotly/                  # PlotlyChartGenerator
└── premium/                     # Vanna 云服务（原地保留）

# 兼容层说明：被移动的旧包路径（如 integrations/anthropic/）原地保留
# 仅含 __init__.py re-export shim（见 12.4），不复制业务代码
```

### 12.2 归类规则（新增后端时按此决策）

| 接口 / 产品类型 | 归类路径 | 判据 |
|----------------|---------|------|
| 实现 `LlmService` | `integrations/llm/<provider>/` | 提供 LLM 对话/流式能力 |
| 实现 `AgentMemory` 或 `SchemaVectorStore` | `integrations/vector/<product>/` | 提供向量编码/检索能力 |
| 实现 `SqlRunner`（关系型/嵌入式） | `integrations/databases/relational/<db>/` | 面向行存、事务型负载 |
| 实现 `SqlRunner`（OLAP/分布式/数仓） | `integrations/databases/warehouse/<db>/` | 面向分析型负载 |
| 实现 `ChartGenerator` | `integrations/visualization/<tool>/` | 图表面板能力 |
| 本地无外部依赖的内置实现 | `integrations/local/` | FileSystem/Audit/内存 ConversationStore |
| Vanna 官方云服务 | `integrations/premium/` | 现状保留 |

Edge case：`duckdb` 分析能力与嵌入式特性并存，归入 `relational/duckdb/` 以保持 `duckdb` 单一 extra 依赖与导入简洁。

### 12.3 全量包移动映射表

| 原路径 | 新路径 | 公开类 |
|--------|--------|--------|
| `integrations/anthropic` | `integrations/llm/anthropic` | `AnthropicLlmService` |
| `integrations/azureopenai` | `integrations/llm/azureopenai` | `AzureOpenAILlmService` |
| `integrations/google` | `integrations/llm/google` | `GeminiLlmService` |
| `integrations/ollama` | `integrations/llm/ollama` | `OllamaLlmService` |
| `integrations/openai` | `integrations/llm/openai` | `OpenAILlmService`、`OpenAIResponsesService` |
| `integrations/mock` | `integrations/llm/mock` | `MockLlmService` |
| `integrations/azuresearch` | `integrations/vector/azuresearch` | `AzureAISearchAgentMemory` |
| `integrations/chromadb` | `integrations/vector/chroma`（更名） | `ChromaAgentMemory`、`get_device`、`create_sentence_transformer_embedding_function` |
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
| `integrations/local` | 原地保留 | `MemoryConversationStore`、`LocalFileSystem` 等 |
| `integrations/premium` | 原地保留 | `CloudAgentMemory` |

### 12.4 兼容层规格（re-export shim）

每个被移动的旧包路径创建 shim 包（仅 `__init__.py`），统一模板：

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

约束：
- shim 只放 `__init__.py`，不复制任何业务代码
- shim 中 `__all__` 与目标模块保持一致，保证类对象唯一（避免双重导入破坏 `isinstance`）
- 顶层 `integrations/__init__.py` 的既有导入（local/mock/plotly/sqlite）改用新路径，保证 `from vanna.integrations import MemoryConversationStore` 等 KeepSameAPI 不变
- 迁移完成后 1~2 个 minor 版本内保留 shim，之后删除

### 12.5 受影响引用更新动作

| 引用方 | 更新动作 |
|--------|----------|
| 顶层 `src/vanna/__init__.py`（`from .integrations import ...`） | 跟随 `integrations/__init__.py` 新路径，行为不变 |
| `src/vanna/core/agent/agent.py`（延迟导入 `vanna.integrations.local`） | local 原地保留，无需改动 |
| `src/vanna/agents/__init__.py`（`DemoAgentMemory`） | local 原地保留，无需改动 |
| `src/vanna/tools/visualize_data.py` | 改为 `vanna.integrations.visualization.plotly` |
| `src/vanna/tools/run_sql.py` | local 原地保留，无需改动 |
| `tests/conftest.py`（fixture 统一切换） | 改为 `vanna.integrations.databases.relational.sqlite` |
| `tests/test_database_sanity.py`、`test_agent_memory*.py` 等 | 批量替换为新路径 |
| `tests/test_azureopenai_llm.py`（`@patch("vanna.integrations.azureopenai.llm.AzureOpenAI")`） | patch 字符串同步改为新路径 |
| `examples/`（19 个示例） | 改为新路径 |
| `README.md`、`MIGRATION_GUIDE.md`、`tox.ini`（导入检查）、`notebooks/quickstart.ipynb` | 改为新路径 |

### 12.6 与本次三类改造的耦合关系

1. **AutoLink 集成**：新增 `SchemaVectorStore` 后端文件直接创建在新路径 `integrations/vector/{faiss,chroma,milvus,qdrant}/schema_vector_store.py`，避免先建旧路径再移动。本规格第 1.2 节目录结构、类职责表、类图与全部示例代码均已按新路径编写。
2. **observability 剥离**：`local/audit.py` 的 `LoggingAuditLogger` 原地保留，不因目录重构产生新耦合。
3. **frontends 重构**：`visualization/plotly` 的移动只影响 `tools/visualize_data.py` 的 import，不改变浏览器端输出协议。

### 12.7 目录重构验证标准

1. **新路径无警告**：`from vanna.integrations.llm.openai import OpenAILlmService` 等全部新路径导入成功且不触发 DeprecationWarning
2. **旧路径兼容**：`from vanna.integrations.openai import OpenAILlmService` 触发 DeprecationWarning，且返回的类对象与新路径为同一对象（`is` 相等）
3. **反射逻辑正常**：`core/validation.py` 的 `validate_pydantic_models_in_package` 在新嵌套结构下执行无异常
4. **`__all__` 完整**：每个新包的 `__all__` 与对应 shim 的导出集合一致
5. **无旧路径残留**：全仓库 `rg "integrations\.(anthropic|openai|...)($|[^.\w])"` 除 shim 目录外无业务代码引用旧路径

---

> **文档结束** —— 配套 IntegrationPlan.md 见同目录下另一文档。