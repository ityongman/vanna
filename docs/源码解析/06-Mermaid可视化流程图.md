# Vanna AI 源码深度解析文档

## 6. Mermaid可视化流程图

本章输出三类可直接渲染的 Mermaid 图表，覆盖系统架构、业务时序、RAG 知识库全流程。

---

### 6.1 整体系统架构分层图

```mermaid
graph TB
    subgraph UserLayer["第1层：用户接入层"]
        Browser["浏览器 / HTTP Client"]
        SSE["SSE 流式端点<br/>POST /api/vanna/v2/chat_sse"]
        WS["WebSocket 端点<br/>/api/vanna/v2/chat_websocket"]
        HTTP["HTTP 轮询端点<br/>POST /api/vanna/v2/chat_poll"]
        HTML["HTML 聊天界面<br/>GET /"]
    end

    subgraph SessionLayer["第2层：会话管理层"]
        CH["ChatHandler<br/>servers/base/chat_handler.py"]
        CS["ConversationStore<br/>core/storage/"]
        Conv["Conversation<br/>id, user, messages"]
    end

    subgraph RAGLayer["第3层：RAG知识库检索层"]
        LCE["LlmContextEnhancer<br/>core/enhancer/default.py"]
        AM["AgentMemory<br/>capabilities/agent_memory/"]
        VecDB["向量数据库<br/>ChromaDB / FAISS / Pinecone / Qdrant<br/>Weaviate / Milvus / Marqo / OpenSearch"]
    end

    subgraph SQLLayer["第4层：SQL生成内核层"]
        Agent["Agent 核心调度器<br/>core/agent/agent.py"]
        SPB["SystemPromptBuilder<br/>core/system_prompt/default.py"]
        WH["WorkflowHandler<br/>core/workflow/default.py"]
        LLM["LlmService 抽象层<br/>core/llm/base.py"]
        LLMImpl["LLM 厂商实现<br/>OpenAI / Anthropic / Azure / Ollama / Gemini"]
    end

    subgraph SecurityLayer["第5层：SQL校验安全层"]
        TR["ToolRegistry<br/>core/registry.py"]
        UF["UiFeatures<br/>UI 权限控制"]
        AL["AuditLogger<br/>core/audit/"]
    end

    subgraph DBExecLayer["第6层：数据库执行层"]
        RST["RunSqlTool<br/>tools/run_sql.py"]
        SR["SqlRunner 抽象接口<br/>capabilities/sql_runner/"]
        DB["数据库<br/>PostgreSQL / MySQL / SQLite<br/>Snowflake / BigQuery / DuckDB<br/>MSSQL / Oracle / ClickHouse / Hive / Presto"]
    end

    subgraph ResultLayer["第7层：结果解析复盘层"]
        UIC["UiComponent<br/>components/"]
        DF["DataFrameComponent"]
        Chart["ChartComponent"]
        RT["RichTextComponent"]
        MemTool["内存工具<br/>save_question_tool_args<br/>search_saved_correct_tool_uses"]
    end

    Browser --> SSE
    Browser --> WS
    Browser --> HTTP
    Browser --> HTML
    SSE --> CH
    WS --> CH
    HTTP --> CH
    CH --> Agent
    CH --> CS
    CS --> Conv
    Agent --> LCE
    LCE --> AM
    AM --> VecDB
    Agent --> SPB
    Agent --> WH
    Agent --> LLM
    LLM --> LLMImpl
    Agent --> TR
    TR --> UF
    TR --> AL
    TR --> RST
    RST --> SR
    SR --> DB
    RST --> UIC
    Agent --> UIC
    UIC --> DF
    UIC --> Chart
    UIC --> RT
    Agent --> MemTool
    MemTool --> AM

    style UserLayer fill:#e1f5fe,stroke:#0288d1
    style SessionLayer fill:#e8f5e9,stroke:#388e3c
    style RAGLayer fill:#fff3e0,stroke:#f57c00
    style SQLLayer fill:#f3e5f5,stroke:#7b1fa2
    style SecurityLayer fill:#fce4ec,stroke:#c62828
    style DBExecLayer fill:#e0f2f1,stroke:#00695c
    style ResultLayer fill:#fff8e1,stroke:#f9a825
```

---

### 6.2 自然语言转SQL完整业务时序流程图

**含正常流程 + 异常纠错分支**

```mermaid
sequenceDiagram
    actor User as 用户
    participant Browser as 浏览器 / Client
    participant FastAPI as FastAPI 路由层<br/>routes.py
    participant CH as ChatHandler<br/>chat_handler.py
    participant Agent as Agent 核心<br/>agent.py
    participant UR as UserResolver<br/>resolver.py
    participant CS as ConversationStore<br/>storage/
    participant WH as WorkflowHandler<br/>workflow/default.py
    participant SPB as SystemPromptBuilder<br/>system_prompt/default.py
    participant LCE as LlmContextEnhancer<br/>enhancer/default.py
    participant AM as AgentMemory<br/>向量库
    participant LLM as LlmService<br/>LLM API
    participant TR as ToolRegistry<br/>registry.py
    participant RST as RunSqlTool<br/>tools/run_sql.py
    participant SR as SqlRunner<br/>数据库执行器
    participant DB as 数据库

    User->>Browser: 输入 "Show Q4 sales by region"
    Browser->>FastAPI: POST /api/vanna/v2/chat_sse<br/>{message, conversation_id?}
    FastAPI->>FastAPI: 构建 RequestContext<br/>(cookies, headers, remote_addr)
    FastAPI->>CH: handle_stream(chat_request)

    CH->>CH: 生成 conversation_id + request_id
    CH->>Agent: send_message(request_context, message, conversation_id)

    rect rgb(240, 248, 255)
        Note over Agent,UR: Step 1: 用户身份解析
        Agent->>UR: resolve_user(request_context)
        UR-->>Agent: User(id, email, group_memberships)
    end

    rect rgb(240, 255, 240)
        Note over Agent,CS: Step 2: 加载会话
        Agent->>CS: get_conversation(conversation_id, user)
        CS-->>Agent: Conversation(id, messages[])
        Agent->>Agent: 追加 Message(role="user", content="Show Q4 sales...")
    end

    rect rgb(255, 248, 240)
        Note over Agent,WH: Step 3: 工作流命令拦截
        Agent->>WH: try_handle(agent, user, conversation, message)
        alt 命令匹配 (/help, /status, /memories, /clear)
            WH-->>Agent: WorkflowResult(should_skip_llm=true)
            Agent-->>CH: UiComponent(系统命令响应)
            CH-->>FastAPI: ChatStreamChunk
            FastAPI-->>Browser: SSE data: {chunk}
            Browser-->>User: 显示命令结果
        else 非命令，正常流程
            WH-->>Agent: WorkflowResult(should_skip_llm=false)
        end
    end

    rect rgb(255, 240, 255)
        Note over Agent,TR: Step 4: 构建 ToolContext + 获取工具列表
        Agent->>Agent: 构建 ToolContext(user, conversation_id, agent_memory)
        Agent->>TR: get_schemas(user)
        TR->>TR: 权限过滤(group_memberships ∩ access_groups)
        TR-->>Agent: List[ToolSchema]<br/>(run_sql, search_saved_correct_tool_uses, save_question_tool_args, ...)
    end

    rect rgb(255, 255, 240)
        Note over Agent,SPB: Step 5: 构建 System Prompt
        Agent->>SPB: build_system_prompt(user, tool_schemas)
        SPB->>SPB: 动态注入工具列表 + 内存工作流指令
        SPB-->>Agent: system_prompt (基础)
    end

    rect rgb(255, 245, 230)
        Note over Agent,AM: Step 6: RAG 增强 System Prompt
        Agent->>LCE: enhance_system_prompt(system_prompt, message, user)
        LCE->>AM: search_text_memories(query="Show Q4 sales...", limit=5)
        AM->>AM: 向量检索 (text → embedding → L2相似度)
        AM-->>LCE: List[TextMemorySearchResult]
        LCE->>LCE: 拼接到 System Prompt 末尾
        LCE-->>Agent: 增强后的 system_prompt
    end

    rect rgb(240, 255, 255)
        Note over Agent,LLM: Step 7: LLM 工具调用循环 (最多 10 轮)
        Agent->>Agent: 构建 LlmRequest(system_prompt, messages, tools)

        loop 每轮工具调用 (tool_iterations < max_tool_iterations)
            Agent->>LLM: send_request(LlmRequest) / stream_request()
            LLM->>LLM: OpenAI/Anthropic/Ollama API 调用
            LLM-->>Agent: LlmResponse(content?, tool_calls?)

            alt response.is_tool_call() == true
                Agent->>Agent: tool_iterations++

                loop 每个 tool_call
                    Agent->>TR: execute(tool_call, context)

                    rect rgb(255, 235, 235)
                        Note over TR,AL: 安全校验
                        TR->>TR: 查找工具 (get_tool)
                        TR->>TR: 权限校验 (group_memberships ∩ access_groups)
                        alt 权限拒绝
                            TR-->>Agent: ToolResult(success=false, "Insufficient group access")
                        end
                        TR->>TR: Pydantic 参数校验 (model_validate)
                        TR->>TR: 参数转换 (transform_args - RLS注入)
                        TR->>AL: log_tool_invocation (审计)
                    end

                    alt tool_call.name == "run_sql"
                        TR->>RST: execute(context, RunSqlToolArgs(sql))
                        RST->>SR: run_sql(args, context)
                        SR->>DB: 执行 SQL

                        alt 数据库执行成功
                            DB-->>SR: 查询结果
                            SR-->>RST: pd.DataFrame
                            RST->>RST: 格式化: CSV截断(1000字符) + DataFrameComponent
                            RST-->>TR: ToolResult(success=true, result_for_llm, ui_component)
                        else 数据库执行失败
                            DB-->>SR: Exception (syntax error / table not found / ...)
                            SR-->>RST: Exception
                            RST-->>TR: ToolResult(success=false, "Error executing query: {error}")
                            Note over Agent: 错误信息追加到对话历史<br/>LLM 下一轮将看到错误并自动修正
                        end

                    else tool_call.name == "search_saved_correct_tool_uses"
                        TR->>AM: search_similar_usage(question, limit, threshold)
                        AM-->>TR: List[ToolMemorySearchResult]
                        TR-->>Agent: ToolResult(success=true, result_for_llm="Found N similar patterns...")

                    else tool_call.name == "save_question_tool_args"
                        TR->>AM: save_tool_usage(question, tool_name, args)
                        AM->>AM: 向量化存储 (question → embedding → ChromaDB)
                        AM-->>TR: None
                        TR-->>Agent: ToolResult(success=true, "Saved to memory")
                    end

                    Agent->>Agent: 追加 Message(role="tool", content=result_for_llm)
                    Agent->>CH: yield UiComponent (状态栏更新 / 数据表格)
                    CH->>FastAPI: ChatStreamChunk
                    FastAPI-->>Browser: SSE data: {chunk}
                    Browser-->>User: 实时更新 UI
                end

                Agent->>Agent: 重建 LlmRequest (含新的 tool 消息)
                Note over Agent: 继续下一轮循环

            else tool_iterations >= max_tool_iterations
                Agent->>Agent: 超出最大迭代次数
                Agent->>CH: yield UiComponent("I've reached the maximum number of tool iterations...")
                Note over Agent: break 退出循环

            else response.is_tool_call() == false
                Note over Agent: LLM 完成最终回复
                Agent->>CH: yield UiComponent(最终文本总结)
                Note over Agent: break 退出循环
            end
        end
    end

    rect rgb(245, 255, 245)
        Note over Agent,Browser: Step 8: 结果整合与流式返回
        Agent->>CH: yield UiComponent(最终回复)
        Agent->>CH: yield UiComponent(chat_input_update enabled=true)
        Agent->>CH: yield UiComponent(空, is_final=true)
        CH->>FastAPI: ChatStreamChunk (done)
        FastAPI-->>Browser: SSE data: {"type":"done"}
        Browser-->>User: 显示最终结果 (表格 + 图表 + 文本)
    end

    rect rgb(250, 250, 250)
        Note over Agent,CS: Step 9: 会话持久化
        Agent->>CS: save_conversation(conversation)
        CS->>CS: 持久化消息历史
        CS-->>Agent: None
    end
```

---

### 6.3 RAG知识库构建与检索流程图

#### 6.3.1 知识库构建流程（Save）

```mermaid
flowchart TB
    subgraph Trigger["触发方式"]
        T1["LLM 主动调用<br/>save_question_tool_args 工具"]
        T2["LLM 主动调用<br/>save_text_memory 工具"]
        T3["代码直接调用<br/>AgentMemory.save_tool_usage()"]
        T4["代码直接调用<br/>AgentMemory.save_text_memory()"]
    end

    subgraph ToolLayer["工具层处理"]
        SST["SaveQuestionToolArgsTool<br/>tools/agent_memory.py"]
        STMT["SaveTextMemoryTool<br/>tools/agent_memory.py"]
    end

    subgraph MemoryLayer["AgentMemory 抽象层"]
        AMI["AgentMemory 接口<br/>capabilities/agent_memory/base.py"]
    end

    subgraph ChromaImpl["ChromaAgentMemory 实现"]
        direction TB
        CC["ChromaAgentMemory<br/>integrations/chromadb/agent_memory.py"]
        C1["_get_collection()<br/>懒加载 ChromaDB Collection"]
        C2["save_tool_usage()<br/>构建 memory_data 字典"]
        C3["save_text_memory()<br/>构建 memory_data 字典"]
        C4["ThreadPoolExecutor<br/>异步执行"]
        C5["collection.upsert()<br/>写入 ChromaDB"]
    end

    subgraph VectorDB["向量数据库层"]
        direction TB
        V1["ChromaDB PersistentClient"]
        V2["DefaultEmbeddingFunction<br/>(all-MiniLM-L6-v2 ONNX)"]
        V3["document → embedding<br/>question/content → 384维向量"]
        V4["持久化存储<br/>persist_directory/"]
    end

    subgraph DataStruct["存储数据结构"]
        D1["ToolMemory<br/>question, tool_name<br/>args_json, success<br/>timestamp, metadata_json"]
        D2["TextMemory<br/>content, timestamp<br/>is_text_memory=True"]
    end

    T1 --> SST
    T2 --> STMT
    T3 --> AMI
    T4 --> AMI
    SST --> AMI
    STMT --> AMI
    AMI --> CC
    CC --> C1
    C1 --> C2
    C1 --> C3
    C2 --> C4
    C3 --> C4
    C4 --> C5
    C5 --> V1
    V1 --> V2
    V2 --> V3
    V3 --> V4
    V4 --> D1
    V4 --> D2

    style Trigger fill:#e8f5e9,stroke:#388e3c
    style ToolLayer fill:#fff3e0,stroke:#f57c00
    style MemoryLayer fill:#e1f5fe,stroke:#0288d1
    style ChromaImpl fill:#f3e5f5,stroke:#7b1fa2
    style VectorDB fill:#fce4ec,stroke:#c62828
    style DataStruct fill:#fff8e1,stroke:#f9a825
```

#### 6.3.2 知识库检索流程（Search）

```mermaid
flowchart TB
    subgraph TriggerS["检索触发方式"]
        S1["自动触发：每次 LLM 调用前<br/>LlmContextEnhancer.enhance_system_prompt()"]
        S2["主动触发：LLM 调用<br/>search_saved_correct_tool_uses 工具"]
    end

    subgraph Path1["路径1：自动增强 System Prompt"]
        direction TB
        P1A["Agent._send_message()"]
        P1B["LlmContextEnhancer.enhance_system_prompt()<br/>core/enhancer/default.py"]
        P1C["构建临时 ToolContext"]
        P1D["AgentMemory.search_text_memories()<br/>query=用户消息, limit=5"]
        P1E["检索结果拼接到 System Prompt 末尾<br/>'## Relevant Context from Memory'"]
        P1F["增强后的 System Prompt → LlmRequest"]
    end

    subgraph Path2["路径2：LLM 主动检索 Few-shot"]
        direction TB
        P2A["Agent 工具循环"]
        P2B["LLM 决定调用 search_saved_correct_tool_uses"]
        P2C["SearchSavedCorrectToolUsesTool.execute()<br/>tools/agent_memory.py"]
        P2D["AgentMemory.search_similar_usage()<br/>question=用户问题, limit=10, threshold=0.7"]
        P2E["过滤条件：success=True + tool_name_filter"]
        P2F["结果格式化：'Found N similar tool usage patterns...'"]
        P2G["返回 ToolResult → LLM 参考 → 生成 SQL"]
    end

    subgraph ChromaSearch["ChromaAgentMemory 检索实现"]
        direction TB
        CS1["_get_collection()<br/>获取已有 Collection"]
        CS2["collection.query()<br/>query_texts=[question], n_results=limit, where=filter"]
        CS3["DefaultEmbeddingFunction<br/>question → 384维向量"]
        CS4["L2 距离计算<br/>similarity_score = max(0, 1 - distance)"]
        CS5["相似度过滤<br/>similarity_score >= threshold (0.7)"]
        CS6["JSON 反序列化<br/>args_json → Dict, metadata_json → Dict"]
        CS7["返回 ToolMemorySearchResult / TextMemorySearchResult"]
    end

    S1 --> Path1
    S2 --> Path2

    P1A --> P1B
    P1B --> P1C
    P1C --> P1D
    P1D --> ChromaSearch
    ChromaSearch --> P1E
    P1E --> P1F

    P2A --> P2B
    P2B --> P2C
    P2C --> P2D
    P2D --> P2E
    P2E --> ChromaSearch
    ChromaSearch --> P2F
    P2F --> P2G

    CS1 --> CS2
    CS2 --> CS3
    CS3 --> CS4
    CS4 --> CS5
    CS5 --> CS6
    CS6 --> CS7

    style TriggerS fill:#e8f5e9,stroke:#388e3c
    style Path1 fill:#e1f5fe,stroke:#0288d1
    style Path2 fill:#fff3e0,stroke:#f57c00
    style ChromaSearch fill:#f3e5f5,stroke:#7b1fa2
```

#### 6.3.3 持续学习闭环（完整生命周期）

```mermaid
flowchart LR
    subgraph Cycle["持续学习闭环"]
        direction LR
        A["用户提问"] --> B["RAG 检索<br/>search_saved_correct_tool_uses<br/>查找相似历史模式"]
        B --> C["Few-shot 增强<br/>历史 SQL 模式 → LLM 参考"]
        C --> D["LLM 生成 SQL<br/>调用 run_sql 工具"]
        D --> E{"SQL 执行结果"}
        E -->|成功| F["结果返回用户<br/>DataFrame + 图表"]
        E -->|失败| G["错误信息 → LLM<br/>LLM 自动修正 SQL"]
        G --> D
        F --> H["保存成功模式<br/>save_question_tool_args<br/>question + tool_name + args → 向量库"]
        H --> B
    end

    subgraph Storage["向量存储"]
        V["ChromaDB / FAISS / Pinecone<br/>question → embedding → 384维向量<br/>L2 距离相似度检索"]
    end

    B -.-> V
    H -.-> V

    style Cycle fill:#f5f5f5,stroke:#333
    style Storage fill:#fce4ec,stroke:#c62828
    style A fill:#e8f5e9,stroke:#388e3c
    style F fill:#e8f5e9,stroke:#388e3c
    style G fill:#ffebee,stroke:#c62828
    style H fill:#fff3e0,stroke:#f57c00
```

---

### 6.4 补充：工具权限校验流程图

```mermaid
flowchart TB
    Start["ToolRegistry.execute()<br/>接收 ToolCall"] --> Find["1. 查找工具<br/>get_tool(tool_call.name)"]
    Find --> Found{"工具存在?"}
    Found -->|否| Err1["ToolResult(success=false,<br/>error='Tool not found')"]
    Found -->|是| PermCheck["2. 权限校验<br/>_validate_tool_permissions()"]

    PermCheck --> HasAccess{"tool.access_groups<br/>∩ user.group_memberships<br/>非空?"}
    HasAccess -->|否| AuditDeny["审计日志: log_tool_access_check<br/>(access_granted=false)"]
    AuditDeny --> Err2["ToolResult(success=false,<br/>error='Insufficient group access')"]

    HasAccess -->|是| AuditAllow["审计日志: log_tool_access_check<br/>(access_granted=true)"]
    AuditAllow --> Validate["3. Pydantic 参数校验<br/>args_model.model_validate(tool_call.arguments)"]
    Validate --> ValidPass{"校验通过?"}
    ValidPass -->|否| Err3["ToolResult(success=false,<br/>error='Validation error: {details}')"]
    ValidPass -->|是| Transform["4. 参数转换<br/>transform_args(tool, args, user, context)"]

    Transform --> TransformResult{"转换结果?"}
    TransformResult -->|ToolRejection| Err4["ToolResult(success=false,<br/>error=rejection.reason)"]
    TransformResult -->|转换后 args| AuditInvoke["5. 审计日志<br/>log_tool_invocation()"]

    AuditInvoke --> Execute["6. 执行工具<br/>start_time = perf_counter()<br/>tool.execute(context, final_args)"]
    Execute --> ExecResult{"执行结果?"}
    ExecResult -->|成功| AuditSuccess["7. 审计日志<br/>log_tool_result(success=true)"]
    ExecResult -->|失败| AuditFail["7. 审计日志<br/>log_tool_result(success=false)"]

    AuditSuccess --> ReturnSuccess["返回 ToolResult(success=true)"]
    AuditFail --> ReturnFail["返回 ToolResult(success=false)"]

    style Start fill:#e1f5fe,stroke:#0288d1
    style Err1 fill:#ffebee,stroke:#c62828
    style Err2 fill:#ffebee,stroke:#c62828
    style Err3 fill:#ffebee,stroke:#c62828
    style Err4 fill:#ffebee,stroke:#c62828
    style ReturnSuccess fill:#e8f5e9,stroke:#388e3c
    style ReturnFail fill:#ffebee,stroke:#c62828
```

---

### 6.5 补充：多轮对话完整上下文管理流程

```mermaid
sequenceDiagram
    participant User as 用户
    participant Agent as Agent
    participant CS as ConversationStore
    participant LLM as LLM

    Note over User,LLM: 第1轮对话
    User->>Agent: "Show Q4 sales by region"
    Agent->>CS: get_conversation(conv_id, user)
    CS-->>Agent: 新 Conversation(messages=[])
    Agent->>Agent: messages += [Message(role="user", content="Show Q4 sales...")]
    Agent->>LLM: LlmRequest(messages=[<br/>  system_prompt,<br/>  Message(role="user", "Show Q4 sales...")<br/>])
    LLM-->>Agent: tool_calls=[run_sql(sql="SELECT ...")]
    Agent->>Agent: messages += [Message(role="assistant", tool_calls=[run_sql])]
    Agent->>Agent: 执行 run_sql → 成功
    Agent->>Agent: messages += [Message(role="tool", content="region,total_sales\nNorth,150000...")]
    Agent->>LLM: LlmRequest(messages=[..., Message(role="tool", content="region,total_sales...")])
    LLM-->>Agent: content="Here are the Q4 sales by region..."
    Agent->>Agent: messages += [Message(role="assistant", content="Here are the Q4...")]
    Agent->>CS: save_conversation(conv)

    Note over User,LLM: 第2轮对话（利用历史上下文）
    User->>Agent: "Now filter to only North region"
    Agent->>CS: get_conversation(conv_id, user)
    CS-->>Agent: 已有 Conversation(messages=[...全部第1轮历史...])
    Agent->>Agent: messages += [Message(role="user", content="Now filter to only North region")]
    Agent->>LLM: LlmRequest(messages=[<br/>  ...全部第一轮历史...,<br/>  Message(role="user", "Now filter to only North region")<br/>])
    Note over LLM: LLM 看到完整历史上下文<br/>知道上一轮查询了 Q4 sales<br/>自动推断需要在 SQL 中加 WHERE region='North'
    LLM-->>Agent: tool_calls=[run_sql(sql="SELECT ... WHERE region='North'")]
    Agent->>Agent: 执行 run_sql → 成功
    Agent->>Agent: messages += [Message(role="assistant", content="North region Q4 sales: $150,000")]
    Agent->>CS: save_conversation(conv)
```