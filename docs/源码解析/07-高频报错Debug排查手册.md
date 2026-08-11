# Vanna AI 源码深度解析文档

## 7. 高频报错Debug排查手册（结合源码定位）

本章汇总 Vanna 2.0 日常部署与调用过程中的高频问题，每一条包含：报错根源源码位置、排查步骤、源码修改修复方案、参数调整方式。

---

### 7.1 向量库检索不到表结构 / 无相似历史模式

**现象描述：** LLM 生成的 SQL 与数据库实际表结构不匹配（字段名错误、表名错误），或 `search_saved_correct_tool_uses` 始终返回空结果。

**根源源码位置：**

| 文件 | 关键行 | 说明 |
|------|--------|------|
| [integrations/chromadb/agent_memory.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/chromadb/agent_memory.py#L201-L265) | `search_similar_usage()` | 向量检索入口，`similarity_threshold` 默认 0.7 |
| [integrations/chromadb/agent_memory.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/chromadb/agent_memory.py#L236-L237) | `similarity_score = max(0, 1 - distance)` | L2 距离→相似度转换 |
| [tools/agent_memory.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/tools/agent_memory.py#L46-L47) | `similarity_threshold: float = 0.7` | 工具默认阈值参数 |
| [core/enhancer/default.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/enhancer/default.py#L41-L101) | `enhance_system_prompt()` | 自动检索，limit=5 |

**排查步骤：**

1. **检查向量库是否为空**
   ```python
   # 在 ChromaAgentMemory 中检查
   collection = memory._get_collection()
   count = collection.count()
   print(f"向量库中记忆总数: {count}")
   ```

2. **降低相似度阈值测试**
   ```python
   # 在调用 search_similar_usage 时降低阈值
   results = await memory.search_similar_usage(
       question="Show Q4 sales",
       context=context,
       similarity_threshold=0.3,  # 从 0.7 降至 0.3
   )
   ```

3. **检查 Embedding 函数一致性**
   ```python
   # 确认 collection 是否使用了与创建时一致的 embedding 函数
   # 在 ChromaAgentMemory._get_collection() 中验证
   ```

4. **手动添加测试数据**
   ```python
   # 直接调用代码添加记忆
   await memory.save_tool_usage(
       question="Show Q4 sales by region",
       tool_name="run_sql",
       args={"sql": "SELECT region, SUM(amount) FROM sales WHERE quarter='Q4' GROUP BY region"},
       context=context,
       success=True,
   )
   ```

5. **检查是否有 TextMemory 提供表结构上下文**
   ```python
   # 添加表结构知识作为文本记忆
   await memory.save_text_memory(
       content="The sales table has columns: id, region, product, amount, quarter, year. "
               "quarter uses format 'Q1', 'Q2', 'Q3', 'Q4'.",
       context=context,
   )
   ```

**参数调整方式：**

| 参数 | 默认值 | 建议调整 | 位置 |
|------|--------|---------|------|
| `similarity_threshold` | 0.7 | 降为 0.3-0.5 | `SearchSavedCorrectToolUsesParams` 默认值或调用时传入 |
| `limit` | 10 | 增大到 20-30 | 同上 |
| `search_text_memories` limit | 5 | 增大到 10-15 | `DefaultLlmContextEnhancer.enhance_system_prompt()` |

**源码修改方案（降低默认阈值）：**

```python
# 修改 tools/agent_memory.py 第46-47行
class SearchSavedCorrectToolUsesParams(BaseModel):
    similarity_threshold: Optional[float] = Field(
        default=0.5,  # 从 0.7 改为 0.5
        description="Minimum similarity score for results (0.0-1.0)"
    )
```

---

### 7.2 LLM 调用超时 / 报错

**现象描述：** LLM API 调用返回超时、ConnectionError、RateLimitError、AuthenticationError 等。

**根源源码位置：**

| 文件 | 关键行 | 说明 |
|------|--------|------|
| [integrations/openai/llm.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/openai/llm.py#L68-L98) | `send_request()` | 非流式请求入口 |
| [integrations/openai/llm.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/openai/llm.py#L100-L178) | `stream_request()` | 流式请求入口 |
| [integrations/openai/llm.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/openai/llm.py#L38-L66) | `__init__()` | API Key / base_url 读取 |
| [core/agent/agent.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/agent/agent.py#L450-L480) | `_send_llm_request()` | Agent 层 LLM 调用封装 |
| [core/recovery/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/recovery/base.py#L68-L83) | `handle_llm_error()` | 错误恢复策略 |

**排查步骤：**

1. **检查 API Key 是否有效**
   ```bash
   # 测试 API Key
   curl https://api.openai.com/v1/models \
     -H "Authorization: Bearer $OPENAI_API_KEY"
   ```

2. **检查 base_url 配置**
   ```python
   # 打印实际使用的 base_url
   print(f"OPENAI_BASE_URL: {os.getenv('OPENAI_BASE_URL')}")
   print(f"base_url param: {base_url}")
   ```

3. **检查网络连通性（代理配置）**
   ```python
   # 在 OpenAILlmService.__init__ 中添加代理
   client_kwargs["http_client"] = httpx.Client(proxy="http://proxy:8080")
   ```

4. **检查速率限制**
   ```python
   # 在 send_request 中添加重试逻辑
   from tenacity import retry, stop_after_attempt, wait_exponential

   @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
   async def send_request_with_retry(self, request):
       return await self.send_request(request)
   ```

5. **检查模型名称是否正确**
   ```python
   # 确认模型名称在 OpenAI 平台上可用
   # 默认 "gpt-5"，根据实际可用模型调整
   llm = OpenAILlmService(model="gpt-4o")  # 或其他可用模型
   ```

**参数调整方式：**

| 参数 | 默认值 | 建议调整 | 位置 |
|------|--------|---------|------|
| `model` | `"gpt-5"` | 改为 `"gpt-4o"` / `"gpt-4o-mini"` | `OpenAILlmService(model=...)` |
| `base_url` | `os.getenv("OPENAI_BASE_URL")` | 设置代理地址 | 环境变量或构造参数 |
| `max_tokens` | `None` | 设置合理上限（如 4096） | `AgentConfig(max_tokens=4096)` |
| `temperature` | `0.0` | 保持 0.0（确定性输出） | `AgentConfig(temperature=0.0)` |

**源码修改方案（添加超时配置）：**

```python
# 修改 integrations/openai/llm.py 第58-66行
import httpx
client_kwargs["timeout"] = httpx.Timeout(60.0, connect=10.0)  # 添加超时
client_kwargs["max_retries"] = 2  # 添加重试
self._client = OpenAI(**client_kwargs)
```

---

### 7.3 生成 SQL 语法错误 / 与数据库不兼容

**现象描述：** LLM 生成的 SQL 语句在目标数据库上执行失败，常见错误：表名不存在、列名拼写错误、SQL 方言不兼容、引号使用错误。

**根源源码位置：**

| 文件 | 关键行 | 说明 |
|------|--------|------|
| [tools/run_sql.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/tools/run_sql.py#L56-L165) | `execute()` | SQL 执行入口，异常捕获 |
| [tools/run_sql.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/tools/run_sql.py#L155-L165) | 异常捕获块 | 错误信息返回给 LLM |
| [core/agent/agent.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/agent/agent.py#L400-L550) | 工具循环 | 错误→LLM→重试循环 |
| [core/system_prompt/default.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/system_prompt/default.py#L34-L157) | `build_system_prompt()` | System Prompt 中缺少数据库方言提示 |

**排查步骤：**

1. **查看完整错误信息**
   ```python
   # 在 RunSqlTool.execute() 异常捕获处添加日志
   except Exception as e:
       logger.error(f"SQL execution failed: {args.sql}")
       logger.error(f"Error: {type(e).__name__}: {str(e)}")
       logger.error(f"Traceback: {traceback.format_exc()}")
   ```

2. **检查 System Prompt 中是否包含数据库方言提示**
   ```python
   # 在 DefaultSystemPromptBuilder 中添加数据库特定提示
   # 例如 PostgreSQL 使用双引号，MySQL 使用反引号
   ```

3. **检查 LLM 是否进行了自动纠错**
   ```python
   # 在 Agent._send_message() 工具循环中打印每次尝试
   logger.info(f"Tool iteration {tool_iterations}: {tool_call.name}")
   logger.info(f"SQL: {tool_call.arguments.get('sql', 'N/A')}")
   logger.info(f"Result success: {result.success}")
   if not result.success:
       logger.info(f"Error: {result.result_for_llm}")
   ```

4. **手动测试 SQL**
   ```python
   # 直接使用 SqlRunner 测试 SQL
   df = await sql_runner.run_sql(RunSqlToolArgs(sql="YOUR_SQL_HERE"), context)
   ```

**参数调整方式：**

| 参数 | 默认值 | 建议调整 | 位置 |
|------|--------|---------|------|
| `max_tool_iterations` | 10 | 增大到 15-20（给 LLM 更多纠错机会） | `AgentConfig(max_tool_iterations=20)` |
| `temperature` | 0.0 | 保持 0.0（SQL 生成需要确定性） | 不建议调整 |

**源码修改方案（增强 System Prompt 中的数据库方言提示）：**

```python
# 修改 core/system_prompt/default.py
# 在 build_system_prompt() 中添加数据库方言部分
prompt_parts.append(
    "## Database Dialect\n"
    "- You are querying a PostgreSQL database.\n"
    "- Use double quotes for identifiers if needed.\n"
    "- Use standard SQL syntax compatible with PostgreSQL.\n"
    "- Table and column names are case-sensitive.\n"
)
```

**源码修改方案（添加 SQL 预校验）：**

```python
# 在 tools/run_sql.py 的 execute() 中添加
import sqlparse

async def execute(self, context, args):
    # 预校验：SQL 语法检查
    try:
        parsed = sqlparse.parse(args.sql)
        if not parsed:
            return ToolResult(success=False, result_for_llm="SQL syntax appears invalid")
    except Exception:
        pass  # sqlparse 失败不影响执行

    # 预校验：危险操作拦截
    dangerous_keywords = ["DROP ", "TRUNCATE ", "ALTER ", "CREATE "]
    sql_upper = args.sql.upper().strip()
    for kw in dangerous_keywords:
        if sql_upper.startswith(kw):
            return ToolResult(success=False, result_for_llm=f"Dangerous SQL operation '{kw}' blocked")
    # ... 继续正常执行
```

---

### 7.4 数据库连接失败

**现象描述：** 启动时或首次查询时报数据库连接错误：`OperationalError`、`InterfaceError`、连接超时、认证失败。

**根源源码位置：**

| 文件 | 关键行 | 说明 |
|------|--------|------|
| [integrations/postgres/sql_runner.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/postgres/sql_runner.py#L65-L80) | `run_sql()` 连接部分 | PostgreSQL 连接 |
| [integrations/mysql/sql_runner.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/mysql/sql_runner.py) | `run_sql()` 连接部分 | MySQL 连接 |
| [integrations/sqlite/sql_runner.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/sqlite/sql_runner.py) | `__init__()` | SQLite 路径 |
| [tools/run_sql.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/tools/run_sql.py#L155-L165) | 异常捕获 | 连接错误传播 |

**排查步骤：**

1. **检查连接字符串格式**
   ```python
   # PostgreSQL 正确格式
   # 方式1：连接字符串
   "postgresql://user:password@host:5432/database"
   # 方式2：参数
   PostgresRunner(host="localhost", port=5432, database="mydb", user="user", password="pass")
   ```

2. **测试数据库连通性**
   ```bash
   # PostgreSQL
   psql -h host -p 5432 -U user -d database -c "SELECT 1"
   # MySQL
   mysql -h host -P 3306 -u user -p database -e "SELECT 1"
   ```

3. **检查依赖是否安装**
   ```bash
   pip install vanna[postgres]  # 安装 psycopg2
   pip install vanna[mysql]     # 安装 mysql-connector-python
   ```

4. **检查 SSL/TLS 配置**
   ```python
   # PostgreSQL SSL 连接
   PostgresRunner(connection_string="postgresql://user:pass@host/db?sslmode=require")
   ```

5. **添加连接池管理**
   ```python
   # 在 SqlRunner 中添加连接重试
   from tenacity import retry, stop_after_attempt, wait_fixed

   class RobustPostgresRunner(PostgresRunner):
       @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
       async def run_sql(self, args, context):
           return await super().run_sql(args, context)
   ```

**参数调整方式：**

| 参数 | 默认值 | 建议调整 | 位置 |
|------|--------|---------|------|
| 连接超时 | 依赖驱动默认 | `connect_timeout=10` | 连接参数 |
| 连接重试 | 无 | 添加重试逻辑 | 自定义 SqlRunner 包装 |

**源码修改方案（添加连接健康检查）：**

```python
# 修改 integrations/postgres/sql_runner.py
class PostgresRunner(SqlRunner):
    def __init__(self, connection_string=None, **connection_params):
        self.connection_string = connection_string
        self.connection_params = connection_params
        self._validate_connection()  # 初始化时验证连接

    def _validate_connection(self):
        """初始化时验证数据库连接"""
        try:
            if self.connection_string:
                conn = psycopg2.connect(self.connection_string)
            else:
                conn = psycopg2.connect(**self.connection_params)
            conn.close()
        except Exception as e:
            raise ConfigurationError(f"Database connection failed: {str(e)}")
```

---

### 7.5 Web 接口访问异常

**现象描述：** FastAPI 服务启动失败、SSE 流中断、CORS 跨域错误、前端无法连接。

**根源源码位置：**

| 文件 | 关键行 | 说明 |
|------|--------|------|
| [servers/fastapi/app.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/servers/fastapi/app.py) | 应用工厂 | FastAPI 应用创建 |
| [servers/fastapi/routes.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/servers/fastapi/routes.py#L46-L85) | `chat_sse()` | SSE 端点 |
| [servers/base/chat_handler.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/servers/base/chat_handler.py#L26-L46) | `handle_stream()` | 流式处理 |
| [servers/cli/server_runner.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/servers/cli/server_runner.py) | CLI 启动 | 服务启动入口 |

**排查步骤：**

1. **CORS 跨域错误**
   ```python
   # 在 create_app() 中添加 CORS 配置
   from fastapi.middleware.cors import CORSMiddleware

   app.add_middleware(
       CORSMiddleware,
       allow_origins=["*"],  # 生产环境应限制具体域名
       allow_credentials=True,
       allow_methods=["*"],
       allow_headers=["*"],
   )
   ```

2. **SSE 流中断**
   ```python
   # 检查 Agent 是否抛出未捕获异常
   # 在 chat_sse 中添加异常处理
   async def _stream_sse(chat_handler, chat_request):
       try:
           async for chunk in chat_handler.handle_stream(chat_request):
               yield f"data: {chunk.model_dump_json()}\n\n"
       except Exception as e:
           error_chunk = ChatStreamChunk(
               type="error",
               component={"message": str(e)},
               conversation_id=chat_request.conversation_id or "",
               request_id=chat_request.request_id or "",
           )
           yield f"data: {error_chunk.model_dump_json()}\n\n"
   ```

3. **端口占用**
   ```bash
   # 检查端口占用
   netstat -ano | findstr :8000
   # 更换端口
   uvicorn.run(app, host="0.0.0.0", port=8001)
   ```

4. **前端 Web Component 加载失败**
   ```html
   <!-- 确认 frontends/ 目录下的 JS 文件可访问 -->
   <script type="module" src="/static/vanna-chat.js"></script>
   ```

5. **WebSocket 连接失败**
   ```python
   # 检查 WebSocket 路由是否正确注册
   # servers/fastapi/routes.py 中确认 WebSocket 端点
   ```

**参数调整方式：**

| 参数 | 默认值 | 建议调整 | 位置 |
|------|--------|---------|------|
| host | `0.0.0.0` | 按需调整 | `uvicorn.run(host=...)` |
| port | `8000` | 按需调整 | `uvicorn.run(port=...)` |
| CORS origins | 无 | `["http://localhost:3000"]` | `CORSMiddleware` |

---

### 7.6 工具权限拒绝 / SQL 注入拦截误判

**现象描述：** 用户报告 "Insufficient group access" 错误，或者合法的 SQL 查询被拦截。

**根源源码位置：**

| 文件 | 关键行 | 说明 |
|------|--------|------|
| [core/registry.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/registry.py#L98-L111) | `_validate_tool_permissions()` | 权限校验逻辑 |
| [core/registry.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/registry.py#L220-L250) | `transform_args()` | 参数转换/RLS 注入 |
| [core/agent/config.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/agent/config.py#L35-L83) | `DEFAULT_UI_FEATURES` | UI 权限配置 |
| [core/tool/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/tool/base.py) | `access_groups` | 工具访问组定义 |

**排查步骤：**

1. **检查用户 group_memberships**
   ```python
   # 在 Agent._send_message() 中打印
   user = await self.user_resolver.resolve_user(request_context)
   print(f"User: {user.id}, Groups: {user.group_memberships}")
   print(f"Available tools: {[t.name for t in tool_schemas]}")
   ```

2. **检查工具 access_groups 配置**
   ```python
   # 在注册工具时检查
   tool = RunSqlTool(sql_runner=sql_runner)
   print(f"Tool '{tool.name}' access_groups: {tool.access_groups}")
   # 如果 access_groups 为空 → 所有人可访问
   # 如果 access_groups 非空 → 需要交集
   ```

3. **检查 UiFeatures 导致的前端隐藏**
   ```python
   # 在 UiFeatures 中确认
   print(f"tool_arguments visible to: {ui_features.get('tool_arguments')}")
   # 如果用户不在该组中，SQL 参数在前端不可见
   ```

4. **检查 transform_args 中的 RLS 逻辑**
   ```python
   # 在 ToolRegistry.transform_args() 中添加日志
   async def transform_args(self, tool, args, user, context):
       if hasattr(tool, 'transform_args'):
           result = await tool.transform_args(args, user, context)
           print(f"transform_args result: {result}")
           return result
       return args
   ```

**参数调整方式：**

| 参数 | 默认值 | 建议调整 | 位置 |
|------|--------|---------|------|
| `access_groups` | `None`（无限制） | 按需设置 `["analyst", "admin"]` | `Tool` 子类 `access_groups` 属性 |
| `group_memberships` | 依赖 UserResolver | 确保包含正确的组名 | `UserResolver.resolve_user()` |
| `tool_arguments` UI | `["admin"]` | 改为 `["admin", "analyst"]` | `UiFeatures` 配置 |

**源码修改方案（添加详细拒绝日志）：**

```python
# 修改 core/registry.py 第98-111行
async def _validate_tool_permissions(self, tool, user):
    if not tool.access_groups:
        return True

    user_groups = set(user.group_memberships)
    tool_groups = set(tool.access_groups)
    has_access = bool(user_groups & tool_groups)

    if not has_access:
        logger.warning(
            f"Permission denied: user '{user.id}' (groups={user_groups}) "
            f"tried to access tool '{tool.name}' (required_groups={tool_groups})"
        )
    return has_access
```

---

### 7.7 ChromaDB 向量库异常

**现象描述：** ChromaDB 初始化失败、embedding 模型下载失败、collection 查询异常。

**根源源码位置：**

| 文件 | 关键行 | 说明 |
|------|--------|------|
| [integrations/chromadb/agent_memory.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/chromadb/agent_memory.py#L102-L118) | `__init__()` | ChromaDB 初始化 |
| [integrations/chromadb/agent_memory.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/chromadb/agent_memory.py#L120-L158) | `_get_collection()` | 懒加载 Collection |
| [integrations/chromadb/agent_memory.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/chromadb/agent_memory.py#L129-L139) | `_get_embedding_function()` | 默认 embedding 函数 |

**排查步骤：**

1. **检查 chromadb 安装**
   ```bash
   pip install chromadb
   # 或
   pip install vanna[chromadb]
   ```

2. **检查 persist_directory 权限**
   ```python
   import os
   persist_dir = "./chroma_memory"
   print(f"Directory exists: {os.path.exists(persist_dir)}")
   print(f"Writable: {os.access(persist_dir, os.W_OK)}")
   ```

3. **Embedding 模型下载问题（首次使用）**
   ```python
   # 使用自定义 embedding 函数避免下载
   from chromadb.utils import embedding_functions
   ef = embedding_functions.SentenceTransformerEmbeddingFunction(
       model_name="all-MiniLM-L6-v2"
   )
   memory = ChromaAgentMemory(
       persist_directory="./chroma_memory",
       embedding_function=ef,
   )
   ```

4. **Collection 数据损坏**
   ```python
   # 重置 collection
   client = chromadb.PersistentClient(path="./chroma_memory")
   client.delete_collection("tool_memories")
   # 然后重新创建
   ```

5. **Embedding 函数不一致导致查询异常**
   ```python
   # 确认 collection 创建时的 embedding 函数
   collection = client.get_collection("tool_memories")
   print(f"Collection metadata: {collection.metadata}")
   # 如果更换了 embedding 函数，需要删除旧 collection 重建
   ```

---

### 7.8 会话存储丢失 / 对话历史不连续

**现象描述：** 重启服务后历史对话丢失，或者多轮对话中 LLM 丢失上下文。

**根源源码位置：**

| 文件 | 关键行 | 说明 |
|------|--------|------|
| [core/storage/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/storage/base.py) | `ConversationStore` 接口 | 会话存储抽象 |
| [integrations/local/storage.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/local/storage.py) | `MemoryConversationStore` | 内存存储（重启丢失） |
| [integrations/local/file_system_conversation_store.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/local/file_system_conversation_store.py) | 文件系统存储 | JSON 持久化 |
| [core/agent/agent.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/agent/agent.py#L252-L260) | 会话加载 | `get_conversation()` |

**排查步骤：**

1. **确认使用的 ConversationStore 实现**
   ```python
   # 检查是否使用了 MemoryConversationStore（默认）
   print(type(agent.conversation_store))
   # 如果是 MemoryConversationStore → 重启丢失
   ```

2. **切换到文件系统持久化**
   ```python
   from vanna.integrations.local.file_system_conversation_store import FileSystemConversationStore

   store = FileSystemConversationStore(storage_dir="./conversations")
   agent = Agent(
       llm_service=llm,
       tool_registry=registry,
       user_resolver=resolver,
       conversation_store=store,  # 使用持久化存储
   )
   ```

3. **检查 conversation_id 是否正确传递**
   ```python
   # 前端需要在后续请求中带上同样的 conversation_id
   # 检查 ChatRequest 中的 conversation_id 字段
   ```

4. **检查消息历史是否过长被截断**
   ```python
   # 在 Agent._build_llm_request 中添加
   total_chars = sum(len(m.content or "") for m in conversation.messages)
   print(f"Total conversation context: {total_chars} chars, {len(conversation.messages)} messages")
   ```

---

### 7.9 结果截断导致 LLM 分析不完整

**现象描述：** 查询结果被截断到 1000 字符，LLM 无法看到完整数据，导致分析不准确。

**根源源码位置：**

| 文件 | 关键行 | 说明 |
|------|--------|------|
| [tools/run_sql.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/tools/run_sql.py#L96-L100) | CSV 截断逻辑 | `results_preview = csv_content[:1000]` |

**源码修改方案（增大截断阈值或改为分页）：**

```python
# 修改 tools/run_sql.py 第96-100行
# 方案1：增大截断阈值
MAX_RESULT_CHARS = 4000  # 从 1000 改为 4000

# 方案2：根据 row_count 动态截断
if row_count > 50:
    results_preview = csv_content[:2000] + f"\n(Showing first 50 of {row_count} rows)"
else:
    results_preview = csv_content[:4000] + "\n(Results truncated...)" if len(csv_content) > 4000 else csv_content

# 方案3：写入完整 CSV 文件，将文件路径传给 LLM
csv_path = await self.file_system.write_file(f"query_results_{context.request_id}.csv", csv_content, context)
results_preview = f"Results saved to {csv_path}. First 1000 chars:\n{csv_content[:1000]}"
```

---

### 7.10 快速排查命令清单

```bash
# 1. 检查 Python 环境
python --version  # 需 >= 3.9

# 2. 检查核心依赖
pip list | grep -E "vanna|openai|chromadb|fastapi|pydantic"

# 3. 测试 LLM 连接
python -c "
import os
from openai import OpenAI
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
print(client.models.list().data[0].id)
"

# 4. 测试数据库连接
python -c "
import psycopg2
conn = psycopg2.connect('postgresql://user:pass@localhost:5432/db')
print('PostgreSQL connected')
conn.close()
"

# 5. 检查 ChromaDB 状态
python -c "
from vanna.integrations.chromadb import ChromaAgentMemory
memory = ChromaAgentMemory(persist_directory='./chroma_memory')
col = memory._get_collection()
print(f'Collection count: {col.count()}')
"

# 6. 启动调试模式
# 设置环境变量
# set PYTHONASYNCIODEBUG=1  # Windows
# export PYTHONASYNCIODEBUG=1  # Linux/Mac
# 启动时添加 logging
python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
# ... 启动服务
"
```