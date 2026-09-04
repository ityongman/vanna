# Vanna AI 源码深度解析文档

## 5. Debug专用：核心类&核心函数速查表

本章以表格形式汇总 Vanna 2.0 所有核心类/函数，供日常 Debug 快速定位。按模块分组，标注源码路径、入参出参、常见报错场景及推荐断点位置。

---

### 5.1 Agent 核心调度层

| 函数/类名称 | 所属文件路径 | 入参 | 返回值 | 核心功能 | 常见报错场景 | 推荐调试断点位置 |
|------------|-------------|------|--------|---------|-------------|----------------|
| `Agent` | [core/agent/agent.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/agent/agent.py#L80-L230) | `llm_service`, `tool_registry`, `user_resolver`, `conversation_store`, + 10+ 可选组件 | `Agent` 实例 | 总调度器，管理 LLM 调用、工具循环、流式响应 | 依赖注入缺少必填参数 → `TypeError` | `__init__` 末尾，检查注入的组件是否正确 |
| `Agent.send_message()` | [core/agent/agent.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/agent/agent.py#L231-L260) | `request_context`, `message`, `conversation_id?`, `user?`, `metadata?` | `AsyncGenerator[UiComponent]` | 主入口，接收用户消息返回流式 UI 组件 | 用户消息为空 → 无响应；`user_resolver` 返回 None → `AttributeError` | 函数入口，检查 `message` 和 `request_context` 内容 |
| `Agent._send_message()` | [core/agent/agent.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/agent/agent.py#L262-L600) | 同 `send_message` | `AsyncGenerator[UiComponent]` | 核心实现：用户解析→工作流拦截→会话加载→Prompt构建→RAG增强→LLM循环→工具执行 | 工具循环死循环 → 超出 `max_tool_iterations`；会话加载失败 → `ConversationNotFoundError` | ①用户解析后 ②工作流拦截后 ③每轮工具循环前 |
| `Agent._build_llm_request()` | [core/agent/agent.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/agent/agent.py#L334-L380) | `conversation`, `tool_schemas`, `user`, `system_prompt` | `LlmRequest` | 将 System Prompt + 历史消息 + 工具列表组装为 LLM 请求 | 消息历史过长 → Token 超限；工具 Schema 格式错误 → LLM 返回异常 | 返回前，检查 `LlmRequest` 的 `messages` 和 `tools` 字段 |
| `Agent._handle_streaming_response()` | [core/agent/agent.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/agent/agent.py#L450-L510) | `request: LlmRequest` | `AsyncGenerator[LlmStreamChunk]` | 处理 LLM 流式响应，逐步 yield 文本和工具调用 | 流中断 → 部分响应丢失；tool_calls JSON 解析失败 → 工具调用失败 | ①每个 stream chunk ②最终 tool_calls 组装 |
| `AgentConfig` | [core/agent/config.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/agent/config.py#L10-L30) | `temperature`, `max_tokens`, `max_tool_iterations`, `stream_responses`, `enable_cache`, `model` | `AgentConfig` 实例 | Agent 全局配置 | `max_tool_iterations` 过小 → 工具循环提前终止；`temperature` 过高 → SQL 不稳定 | 在 `Agent.__init__` 中检查 `self.config` |

---

### 5.2 LLM 对接层

| 函数/类名称 | 所属文件路径 | 入参 | 返回值 | 核心功能 | 常见报错场景 | 推荐调试断点位置 |
|------------|-------------|------|--------|---------|-------------|----------------|
| `LlmService` (ABC) | [core/llm/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/llm/base.py) | - | - | LLM 服务抽象接口 | 子类未实现 `send_request` → `TypeError` | - |
| `LlmRequest` | [core/llm/models.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/llm/models.py) | `system_prompt`, `messages`, `tools`, `temperature`, `max_tokens`, `stream` | `LlmRequest` 实例 | LLM 请求数据模型 | `tools` 字段格式不兼容 → 厂商 API 报错 | 构建后检查 `system_prompt` 长度和 `messages` 数量 |
| `LlmResponse` | [core/llm/models.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/llm/models.py) | `content`, `tool_calls`, `finish_reason`, `usage` | `LlmResponse` 实例 | LLM 响应数据模型 | `tool_calls` 为空但 `finish_reason="tool_calls"` → 厂商返回异常 | - |
| `OpenAILlmService` | [integrations/openai/llm.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/openai/llm.py#L27-L267) | `model`, `api_key`, `organization`, `base_url`, `**extra` | `OpenAILlmService` 实例 | OpenAI LLM 实现 | ①API Key 无效 → `AuthenticationError` ②`base_url` 错误 → `ConnectionError` ③`openai` 未安装 → `ImportError` | `__init__` 末尾检查 `self._client` |
| `OpenAILlmService._build_payload()` | [integrations/openai/llm.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/openai/llm.py#L190-L242) | `request: LlmRequest` | `Dict[str, Any]` | 将内部 `LlmRequest` 转为 OpenAI API 格式 | `tools` 参数 JSON Schema 不合法 → OpenAI 400 错误 | 返回前，检查 `messages` 和 `tools` 的序列化结果 |
| `OpenAILlmService.send_request()` | [integrations/openai/llm.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/openai/llm.py#L68-L98) | `request: LlmRequest` | `LlmResponse` | 非流式 LLM 调用 | ①超时 → `APITimeoutError` ②速率限制 → `RateLimitError` ③上下文过长 → `ContextLengthExceededError` | `resp.choices[0]` 处，检查 `finish_reason` |
| `OpenAILlmService.stream_request()` | [integrations/openai/llm.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/openai/llm.py#L100-L178) | `request: LlmRequest` | `AsyncGenerator[LlmStreamChunk]` | 流式 LLM 调用 | ①流中断 → 不完整 tool_calls ②tool_calls arguments JSON 不完整 → 解析失败 | `tc_builders` 累积后，检查 JSON 解析 |
| `OpenAILlmService._extract_tool_calls_from_message()` | [integrations/openai/llm.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/openai/llm.py#L244-L267) | `message` (OpenAI message object) | `List[ToolCall]` | 从 OpenAI 响应中提取工具调用 | `arguments` JSON 解析失败 → 降级为 `{"_raw": args_raw}` | `json.loads(args_raw)` 处 |
| `AnthropicLlmService` | [integrations/anthropic/llm.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/anthropic/llm.py) | `model`, `api_key` | `AnthropicLlmService` 实例 | Anthropic Claude LLM 实现 | API Key 无效 → 401；工具格式适配错误 → 400 | `_build_payload` 返回前 |
| `OllamaLlmService` | [integrations/ollama/llm.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/ollama/llm.py) | `model`, `host`, `base_url` | `OllamaLlmService` 实例 | Ollama 本地 LLM 实现 | ①Ollama 服务未启动 → `ConnectionError` ②模型未下载 → 404 | `send_request` 中 HTTP 请求处 |

---

### 5.3 工具注册与执行层

| 函数/类名称 | 所属文件路径 | 入参 | 返回值 | 核心功能 | 常见报错场景 | 推荐调试断点位置 |
|------------|-------------|------|--------|---------|-------------|----------------|
| `ToolRegistry` | [core/registry.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/registry.py) | - | `ToolRegistry` 实例 | 工具注册、参数校验、执行调度 | 工具未注册 → 返回 `ToolResult(success=False, error="Tool ... not found")` | `__init__` 后检查 `self._tools` |
| `ToolRegistry.register()` | [core/registry.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/registry.py#L37-L48) | `tool: Tool` | `None` | 注册工具；同名重复注册抛 `ValueError` | 重复注册同名工具 → `ValueError` | 注册后检查 `self._tools[tool.name]` |
| `ToolRegistry.get_schemas()` | [core/registry.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/registry.py#L58-L60) | 无 | `List[ToolSchema]` | 获取全部已注册工具的 Schema 列表（不按用户过滤） | 注册表为空 → LLM 无工具可调用，只返回纯文本 | 返回前检查 `schemas` 列表长度 |
| `ToolRegistry.execute()` | [core/registry.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/registry.py#L93-L184) | `tool_call: ToolCall`, `context: ToolContext` | `ToolResult` | 工具执行主流程：查找→校验→转换→审计→执行→审计 | ①参数校验失败 → `ToolResult(success=False)` ②transform_args 拒绝 → `ToolRejection` | ①参数校验后 ②工具执行前后 |
| `ToolRegistry.transform_args()` | [core/registry.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/registry.py#L62-L91) | `tool`, `args`, `user`, `context` | `args` or `ToolRejection` | 参数转换（支持 RLS 行级安全注入） | 自定义转换逻辑错误 → `ToolRejection` | 转换前后对比 `args` 变化 |
| `Tool` (ABC) | [core/tool/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/tool/base.py) | - | - | 工具抽象基类 | `name`/`description` 未实现 → `TypeError` | - |
| `ToolCall` | [core/tool/models.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/tool/models.py) | `id`, `name`, `arguments` | `ToolCall` 实例 | LLM 生成的工具调用 | `arguments` 类型不匹配 → Pydantic 校验失败 | - |
| `ToolResult` | [core/tool/models.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/tool/models.py) | `success`, `result_for_llm`, `ui_component?`, `error?`, `metadata?` | `ToolResult` 实例 | 工具执行结果 | `result_for_llm` 为空 → LLM 无上下文 | - |
| `ToolContext` | [core/tool/models.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/tool/models.py) | `user`, `conversation_id`, `request_id`, `agent_memory`, `schema_vector_store?`, `metadata?` | `ToolContext` 实例 | 工具执行上下文 | `agent_memory` 为 None 但工具需要 → `AttributeError` | - |

---

### 5.4 RAG 向量知识库层

| 函数/类名称 | 所属文件路径 | 入参 | 返回值 | 核心功能 | 常见报错场景 | 推荐调试断点位置 |
|------------|-------------|------|--------|---------|-------------|----------------|
| `AgentMemory` (ABC) | [capabilities/agent_memory/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/capabilities/agent_memory/base.py) | - | - | Agent 记忆抽象接口 | 子类未实现必需方法 → `TypeError` | - |
| `ChromaAgentMemory` | [integrations/chromadb/agent_memory.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/chromadb/agent_memory.py#L42-L488) | `persist_directory`, `collection_name`, `embedding_function?` | `ChromaAgentMemory` 实例 | ChromaDB 向量存储实现 | ①chromadb 未安装 → `ImportError` ②目录权限不足 → `PermissionError` ③embedding 模型下载失败 → 网络错误 | `__init__` 末尾 |
| `ChromaAgentMemory._get_collection()` | [integrations/chromadb/agent_memory.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/chromadb/agent_memory.py#L141-L158) | 无 | ChromaDB Collection | 懒加载获取/创建 Collection | ①首次创建下载 ~80MB ONNX 模型 → 长时间阻塞 ②embedding 函数不一致 → 查询结果异常 | `client.get_collection` 和 `client.create_collection` 处 |
| `ChromaAgentMemory.save_tool_usage()` | [integrations/chromadb/agent_memory.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/chromadb/agent_memory.py#L166-L199) | `question`, `tool_name`, `args`, `context`, `success`, `metadata?` | `None` | 保存工具使用模式到向量库 | ①`args` 不可序列化 → `TypeError` ②存储空间不足 → ChromaDB 写入错误 | `collection.upsert` 调用前，检查 `memory_data` |
| `ChromaAgentMemory.search_similar_usage()` | [integrations/chromadb/agent_memory.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/chromadb/agent_memory.py#L201-L265) | `question`, `context`, `limit`, `similarity_threshold`, `tool_name_filter?` | `List[ToolMemorySearchResult]` | 向量相似度检索历史工具使用模式 | ①无匹配结果 → 空列表 ②阈值过高 → 过滤掉所有结果 ③L2 距离→相似度转换精度问题 | ①`collection.query` 返回后 ②相似度过滤后 |
| `ChromaAgentMemory.save_text_memory()` | [integrations/chromadb/agent_memory.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/chromadb/agent_memory.py#L333-L354) | `content`, `context` | `TextMemory` | 保存文本记忆 | `content` 过长 → 向量化失败 | `collection.upsert` 前 |
| `ChromaAgentMemory.search_text_memories()` | [integrations/chromadb/agent_memory.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/chromadb/agent_memory.py#L356-L403) | `query`, `context`, `limit`, `similarity_threshold` | `List[TextMemorySearchResult]` | 搜索文本记忆 | 同 `search_similar_usage` | 同 `search_similar_usage` |
| `DefaultLlmContextEnhancer` | [core/enhancer/default.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/enhancer/default.py) | `agent_memory?` | `DefaultLlmContextEnhancer` 实例 | 自动从 AgentMemory 检索文本记忆增强 System Prompt | `agent_memory` 为 None → 不做增强（静默跳过） | `enhance_system_prompt` 中 `memory` 检索后 |
| `DefaultLlmContextEnhancer.enhance_system_prompt()` | [core/enhancer/default.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/enhancer/default.py#L41-L101) | `system_prompt`, `user_message`, `user` | `str` | 检索相关文本记忆并拼接到 System Prompt | 检索结果过多 → Prompt 超长 → Token 超限 | 返回前检查增强后的 `system_prompt` 长度 |
| `SaveQuestionToolArgsTool` | [tools/agent_memory.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/tools/agent_memory.py#L60-L117) | (通过 `execute` 接收) `context`, `args: SaveQuestionToolArgsParams` | `ToolResult` | 保存成功的工具调用模式 | `context.agent_memory` 为 None → `AttributeError` | `execute` 中 `save_tool_usage` 调用前后 |
| `SearchSavedCorrectToolUsesTool` | [tools/agent_memory.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/tools/agent_memory.py#L120-L266) | (通过 `execute` 接收) `context`, `args: SearchSavedCorrectToolUsesParams` | `ToolResult` | 搜索相似历史工具模式（Few-shot 召回） | ①无结果 → LLM 无 Few-shot 参考 ②结果过多 → LLM 上下文过长 | `execute` 中 `search_similar_usage` 结果处 |
| `SaveTextMemoryTool` | [tools/agent_memory.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/tools/agent_memory.py#L269-L322) | (通过 `execute` 接收) `context`, `args: SaveTextMemoryParams` | `ToolResult` | 保存文本知识 | 同 `save_text_memory` | `execute` 中 `save_text_memory` 调用前后 |

---

### 5.5 SQL 执行与数据库适配层

| 函数/类名称 | 所属文件路径 | 入参 | 返回值 | 核心功能 | 常见报错场景 | 推荐调试断点位置 |
|------------|-------------|------|--------|---------|-------------|----------------|
| `SqlRunner` (ABC) | [capabilities/sql_runner/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/capabilities/sql_runner/base.py) | - | - | 数据库执行器抽象接口 | 子类未实现 `run_sql` → `TypeError` | - |
| `RunSqlTool` | [tools/run_sql.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/tools/run_sql.py) | `sql_runner`, `file_system?` | `RunSqlTool` 实例 | SQL 执行工具，封装结果格式化 | `sql_runner` 为 None → `AttributeError` | - |
| `RunSqlTool.execute()` | [tools/run_sql.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/tools/run_sql.py#L56-L165) | `context`, `args: RunSqlToolArgs` | `ToolResult` | 执行 SQL 并格式化结果 | ①SQL 语法错误 → 数据库异常 → `ToolResult(success=False)` ②结果过长 → 截断到 1000 字符 ③CSV 序列化失败 → `Exception` | ①`run_sql` 调用前后 ②CSV 截断处 ③异常捕获处 |
| `PostgresRunner` | [databases/relational/postgres/sql_runner.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/databases/relational/postgres/sql_runner.py) | `connection_string?`, `**connection_params` | `PostgresRunner` 实例 | PostgreSQL 执行器 | ①psycopg2 未安装 → `ImportError` ②连接字符串错误 → `OperationalError` | `__init__` 末尾 |
| `PostgresRunner.run_sql()` | [databases/relational/postgres/sql_runner.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/databases/relational/postgres/sql_runner.py) | `args: RunSqlToolArgs`, `context: ToolContext` | `pd.DataFrame` | 执行 SQL 并返回 DataFrame | ①表不存在 → `UndefinedTable` ②列不存在 → `UndefinedColumn` ③权限不足 → `InsufficientPrivilege` ④连接超时 → `OperationalError` | ①`cursor.execute` 处 ②`fetchall` 处 |
| `SqliteRunner` | [integrations/sqlite/sql_runner.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/sqlite/sql_runner.py) | `db_path` | `SqliteRunner` 实例 | SQLite 执行器 | ①db_path 不存在（非 :memory:）→ 自动创建 ②文件权限不足 → `OperationalError` | `__init__` 末尾 |
| `MysqlRunner` | [integrations/mysql/sql_runner.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/mysql/sql_runner.py) | `connection_string?`, `**connection_params` | `MysqlRunner` 实例 | MySQL 执行器 | ①mysql-connector-python 未安装 → `ImportError` ②字符集问题 → 乱码 | `__init__` 末尾 |
| `DuckDBRunner` | [integrations/duckdb/sql_runner.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/integrations/duckdb/sql_runner.py) | `db_path` | `DuckDBRunner` 实例 | DuckDB 执行器（支持 :memory:） | duckdb 未安装 → `ImportError` | `__init__` 末尾 |

---

### 5.6 System Prompt 与工作流层

| 函数/类名称 | 所属文件路径 | 入参 | 返回值 | 核心功能 | 常见报错场景 | 推荐调试断点位置 |
|------------|-------------|------|--------|---------|-------------|----------------|
| `SystemPromptBuilder` (ABC) | [core/system_prompt/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/system_prompt/base.py) | - | - | System Prompt 构建器接口 | 子类未实现 `build_system_prompt` → `TypeError` | - |
| `DefaultSystemPromptBuilder` | [core/system_prompt/default.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/system_prompt/default.py) | - | `DefaultSystemPromptBuilder` 实例 | 默认 System Prompt 构建器 | 工具列表为空 → Prompt 中无工具提示 | - |
| `DefaultSystemPromptBuilder.build_system_prompt()` | [core/system_prompt/default.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/system_prompt/default.py#L34-L157) | `user`, `tools: List[ToolSchema]` | `str` | 动态构建 System Prompt（含内存工作流指令） | 未检测到 `search_saved_correct_tool_uses` → 缺少 "先搜索" 指令 → LLM 不先检索 | 返回前检查完整 Prompt 文本 |
| `WorkflowHandler` (ABC) | [core/workflow/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/workflow/base.py) | - | - | 工作流处理器接口 | 子类未实现 `try_handle` → `TypeError` | - |
| `DefaultWorkflowHandler` | [core/workflow/default.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/workflow/default.py) | - | `DefaultWorkflowHandler` 实例 | 默认工作流处理器（/help, /status, /memories, /clear） | 命令匹配逻辑错误 → 不拦截但 LLM 也无法理解 | - |
| `DefaultWorkflowHandler.try_handle()` | [core/workflow/default.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/workflow/default.py#L24-L67) | `agent`, `user`, `conversation`, `message` | `WorkflowResult` | 拦截系统命令，跳过 LLM 调用 | 命令匹配失败 → `should_skip_llm=False` → 正常 LLM 流程 | 各命令 `if` 分支处 |

---

### 5.7 Web 服务与会话管理层

| 函数/类名称 | 所属文件路径 | 入参 | 返回值 | 核心功能 | 常见报错场景 | 推荐调试断点位置 |
|------------|-------------|------|--------|---------|-------------|----------------|
| `ChatHandler` | [servers/base/chat_handler.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/servers/base/chat_handler.py) | `agent: Agent` | `ChatHandler` 实例 | 框架无关的聊天处理核心 | `agent` 为 None → `AttributeError` | `__init__` 末尾 |
| `ChatHandler.handle_stream()` | [servers/base/chat_handler.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/servers/base/chat_handler.py#L26-L46) | `request: ChatRequest` | `AsyncGenerator[ChatStreamChunk]` | 委托 Agent 处理消息，转换 UiComponent 为 ChatStreamChunk | ①Agent 抛异常 → SSE 流中断 ②`conversation_id` 无效 → 创建新会话 | `agent.send_message` 调用前后 |
| `ChatRequest` | [servers/base/models.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/servers/base/models.py) | `message`, `conversation_id?`, `request_id?`, `request_context?`, `metadata?` | `ChatRequest` 实例 | 聊天请求数据模型 | `message` 为空 → 无意义请求 | - |
| `ChatStreamChunk` | [servers/base/models.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/servers/base/models.py) | `type`, `component`, `conversation_id`, `request_id`, `is_final` | `ChatStreamChunk` 实例 | SSE 流式响应块 | 序列化 `component` 失败 → JSON 编码错误 | - |
| `ConversationStore` (ABC) | [core/storage/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/storage/base.py) | - | - | 会话存储接口 | 子类未实现必需方法 → `TypeError` | - |
| `Conversation` | [core/storage/models.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/storage/models.py) | `id`, `user`, `messages`, `created_at`, `updated_at` | `Conversation` 实例 | 会话数据模型 | `messages` 列表过大 → 内存/序列化问题 | - |
| `Message` | [core/storage/models.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/storage/models.py) | `role`, `content`, `tool_calls?`, `tool_call_id?` | `Message` 实例 | 消息数据模型 | `tool_calls` 序列化失败 → `TypeError` | - |
| `create_app()` | [servers/fastapi/app.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/servers/fastapi/app.py) | `agent`, `**kwargs` | `FastAPI` | 创建 FastAPI 应用 | ①CORS 配置错误 → 浏览器跨域拒绝 ②端口占用 → `OSError` | `app` 创建后 |
| `chat_sse()` | [servers/fastapi/routes.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/servers/fastapi/routes.py#L46-L85) | `chat_request: ChatRequest`, `http_request: Request` | `StreamingResponse` | SSE 流式端点 | ①客户端断连 → 流中断 ②`request_context` 构建失败 → 用户解析失败 | `_stream_sse` 生成器入口 |

---

### 5.8 用户身份与审计层

| 函数/类名称 | 所属文件路径 | 入参 | 返回值 | 核心功能 | 常见报错场景 | 推荐调试断点位置 |
|------------|-------------|------|--------|---------|-------------|----------------|
| `UserResolver` (ABC) | [core/user/resolver.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/user/resolver.py) | - | - | 用户身份解析器接口 | 子类未实现 `resolve_user` → `TypeError` | - |
| `UserResolver.resolve_user()` | [core/user/resolver.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/user/resolver.py#L29-L42) | `request_context: RequestContext` | `User` | 从 RequestContext 解析用户身份 | ①Cookie/Header 缺失 → 认证失败 ②Token 过期 → 认证失败 | 返回前检查 `User` 对象字段 |
| `User` | [core/user/models.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/user/models.py) | `id`, `username?`, `email?`, `metadata?` | `User` 实例 | 用户数据模型（`metadata` 可携带任意扩展信息） | - | - |
| `RequestContext` | [core/user/request_context.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/user/request_context.py) | `cookies?`, `headers?`, `remote_addr?`, `query_params?`, `metadata?` | `RequestContext` 实例 | HTTP 请求上下文 | `headers` 中 Authorization 缺失 → 用户解析失败 | - |
| `AuditLogger` (ABC) | [core/audit/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/audit/base.py) | - | - | 审计日志接口 | 子类未实现方法 → `TypeError` | - |

---

### 5.9 可观测性与错误恢复层

| 函数/类名称 | 所属文件路径 | 入参 | 返回值 | 核心功能 | 常见报错场景 | 推荐调试断点位置 |
|------------|-------------|------|--------|---------|-------------|----------------|
| `ObservabilityProvider` (ABC) | [core/observability/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/observability/base.py) | - | - | 可观测性接口 | 子类未实现方法 → `TypeError` | - |
| `Span` | [core/observability/models.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/observability/models.py) | `name`, `attributes?` | `Span` 实例 | 追踪 Span | `end_time` 未设置 → 耗时统计异常 | - |
| `ErrorRecoveryStrategy` (ABC) | [core/recovery/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/recovery/base.py) | - | - | 错误恢复策略接口 | 默认实现直接返回 FAIL → 无重试 | - |
| `ErrorRecoveryStrategy.handle_tool_error()` | [core/recovery/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/recovery/base.py#L50-L66) | `error`, `context`, `attempt` | `RecoveryAction` | 处理工具执行错误 | 返回 FAIL → 工具错误直接终止 | `attempt` 计数处 |
| `ErrorRecoveryStrategy.handle_llm_error()` | [core/recovery/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/recovery/base.py#L68-L83) | `error`, `request`, `attempt` | `RecoveryAction` | 处理 LLM 调用错误 | 返回 FAIL → LLM 错误直接终止 | `attempt` 计数处 |
| `LlmMiddleware` (ABC) | [core/middleware/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/middleware/base.py) | - | - | LLM 中间件接口 | 中间件链中某个抛出异常 → 后续中间件不执行 | `before_llm_request` / `after_llm_response` |
| `LlmMiddleware.before_llm_request()` | [core/middleware/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/middleware/base.py#L46-L55) | `request: LlmRequest` | `LlmRequest` | 请求发送前拦截 | 修改 `system_prompt` 导致格式错误 → LLM 返回异常 | 返回前检查修改后的 `request` |
| `LlmMiddleware.after_llm_response()` | [core/middleware/base.py](file:///d:/workspace/sourceWorkspace/vanna/src/vanna/core/middleware/base.py#L57-L69) | `request`, `response` | `LlmResponse` | 响应返回后拦截 | 修改 `tool_calls` 导致工具不存在 → `ToolNotFoundError` | 返回前检查修改后的 `response` |

---

### 5.10 快速排查索引

按报错现象快速定位排查入口：

| 报错现象 | 直接排查入口 | 深层排查 |
|---------|-------------|---------|
| 页面无法访问 / 404 | `servers/fastapi/routes.py` 路由注册 | `servers/fastapi/app.py` 应用创建 |
| SSE 流中断 / 无响应 | `ChatHandler.handle_stream()` | `Agent.send_message()` 异常 |
| LLM 调用超时 | `OpenAILlmService.send_request()` | 网络/API Key/速率限制 |
| LLM 不调用工具 | `Agent._build_llm_request()` 检查 `tools` 字段 | `ToolRegistry.get_schemas()` 返回列表是否为空 |
| LLM 生成 SQL 语法错误 | `RunSqlTool.execute()` 异常捕获 | 数据库 `run_sql()` 具体错误 |
| 向量检索无结果 | `ChromaAgentMemory.search_similar_usage()` | `similarity_threshold` 阈值 / collection 是否为空 |
| 向量检索结果不相关 | `ChromaAgentMemory._get_collection()` embedding 函数 | 是否使用了不同 embedding 函数的 collection |
| 会话历史丢失 | `ConversationStore` 实现 | 内存存储重启丢失 / 文件系统路径错误 |
| 内存保存失败 | `SaveQuestionToolArgsTool.execute()` | `AgentMemory.save_tool_usage()` 异常 |
| 用户身份解析失败 | `UserResolver.resolve_user()` | `RequestContext` 中 Cookie/Header 缺失 |