# Vanna Debug 操作指南

## 一、环境准备

### 1.1 安装 debugpy

```bash
pip install debugpy
```

### 1.2 确认 VS Code Python 扩展

确保已安装 VS Code 扩展：**Python Debugger**（`ms-python.debugpy`）

---

## 二、VS Code Debug 配置（已配置）

配置文件位置：`.vscode/launch.json`

已预置 13 个 debug 配置，按 `F5` 或点击 VS Code 左侧 "Run and Debug" 面板选择即可。

### 2.1 服务启动类

| 配置名称 | 说明 | 适用场景 |
|---|---|---|
| `Vanna FastAPI` | 启动 FastAPI 服务（dev 模式） | 调试 API 路由、SSE 流 |
| `Vanna Flask` | 启动 Flask 服务（dev 模式） | 调试 Flask 路由 |
| `Vanna FastAPI + mock_quickstart` | 启动 FastAPI + mock 示例 | 无需真实 LLM API Key 的调试 |
| `Vanna FastAPI + claude_sqlite` | 启动 FastAPI + Claude + SQLite | 调试真实 LLM + 数据库交互 |
| `Vanna FastAPI + openai` | 启动 FastAPI + OpenAI | 调试 OpenAI 模型调用 |
| `Vanna FastAPI (custom static folder)` | 自定义静态文件路径 | 前端联调 |

### 2.2 示例运行类

| 配置名称 | 说明 |
|---|---|
| `Run example: mock_quickstart` | 调试 mock 快速入门 |
| `Run example: openai_quickstart` | 调试 OpenAI 示例 |
| `Run example: minimal_example` | 调试最小化示例 |
| `Run example: evaluation_example` | 调试评估示例 |
| `Run example: visualization_example` | 调试可视化示例 |

### 2.3 通用调试

| 配置名称 | 说明 |
|---|---|
| `Debug current file` | 调试当前打开的文件 |
| `Attach to remote debugpy (port 5678)` | 附加到远程运行的 debugpy 进程 |

---

## 三、Debug 操作流程

### 3.1 基础操作

```
1. 在代码中点击行号左侧设置断点（红色圆点）
2. 按 F5 或点击 "Run and Debug" → 选择配置 → 绿色播放按钮
3. 程序暂停在断点处
```

### 3.2 调试面板快捷键

| 操作 | 快捷键 | 说明 |
|---|---|---|
| 继续 (Continue) | `F5` | 运行到下一个断点 |
| 单步跳过 (Step Over) | `F10` | 执行当前行，不进入函数内部 |
| 单步进入 (Step Into) | `F11` | 进入函数内部 |
| 单步跳出 (Step Out) | `Shift+F11` | 跳出当前函数 |
| 重启 (Restart) | `Ctrl+Shift+F5` | 重新开始调试 |
| 停止 (Stop) | `Shift+F5` | 停止调试 |

### 3.3 调试时查看变量

- **Variables 面板**：查看当前作用域所有变量值
- **Watch 面板**：添加自定义表达式，如 `self.agent_memory._collection`
- **Debug Console**：直接输入 Python 表达式求值，如 `len(tool_schemas)`

---

## 四、典型 Debug 场景

### 4.1 调试 Agent 工具调用流程

**目标**：追踪 LLM 如何决定调用工具

**断点位置**：

| 文件 | 行号 | 说明 |
|---|---|---|
| `src/vanna/core/agent/agent.py` | `~646` | 工具循环入口 `while tool_iterations < max_tool_iterations` |
| `src/vanna/core/agent/agent.py` | `~658` | `if response.is_tool_call()` 判断 |
| `src/vanna/core/registry.py` | `~144` | `ToolRegistry.execute()` 工具执行入口 |

**操作步骤**：
1. 选择 `Vanna FastAPI + mock_quickstart` 配置启动
2. 在浏览器访问 `http://localhost:8000`，发送一条测试消息
3. 观察 `tool_call.name` 和 `tool_call.arguments` 的值

### 4.2 调试数据查询结果

**断点位置**：

| 文件 | 行号 | 说明 |
|---|---|---|
| `src/vanna/tools/run_sql.py` | `~60` | `df = await self.sql_runner.run_sql(...)` 执行 SQL |
| `src/vanna/integrations/chromadb/agent_memory.py` | `~212` | 向量检索 `collection.query(...)` |

### 4.3 调试 System Prompt 生成

**断点位置**：

| 文件 | 行号 | 说明 |
|---|---|---|
| `src/vanna/core/system_prompt/default.py` | `~157` | `return "\n".join(prompt_parts)` 最终系统提示词 |
| `src/vanna/core/enhancer/default.py` | `~76` | `search_text_memories(...)` 文本记忆检索 |
| `src/vanna/core/agent/agent.py` | `~600` | `build_system_prompt(...)` 调用入口 |

### 4.4 调试前端 UI 组件渲染

**后端断点**：

| 文件 | 行号 | 说明 |
|---|---|---|
| `src/vanna/servers/base/chat_handler.py` | SSE 流处理 | `ChatStreamChunk.from_component(...)` |

**前端联调**：
1. 终端1: `cd frontends/webcomponent && npm run dev`
2. 终端2: 选择 `Vanna FastAPI (custom static folder)` 启动
3. 浏览器访问 `http://localhost:8000`

---

## 五、远程调试（Docker/服务器）

### 5.1 在目标代码中启动 debugpy 服务

```python
import debugpy
debugpy.listen(("0.0.0.0", 5678))
print("Waiting for debugger attach...")
debugpy.wait_for_client()
```

### 5.2 VS Code 中附加

1. 选择 `Attach to remote debugpy (port 5678)` 配置
2. 修改 `connect.host` 为目标服务器 IP
3. 按 `F5` 启动附加

---

## 六、命令行调试

### 6.1 直接使用 debugpy 启动

```bash
# 调试服务启动
python -m debugpy --listen 5678 --wait-for-client -m vanna.servers --framework fastapi --port 8000 --dev

# 调试示例
python -m debugpy --listen 5678 --wait-for-client -m vanna.examples mock_quickstart
```

### 6.2 使用 pdb（无需 VS Code）

```python
# 在代码中插入断点
import pdb; pdb.set_trace()
```

运行时进入交互式调试，支持命令：
- `n` (next) - 下一行
- `s` (step) - 进入函数
- `c` (continue) - 继续运行
- `p <var>` - 打印变量值
- `l` (list) - 显示当前代码
- `q` (quit) - 退出

---

## 七、常用调试技巧

### 7.1 条件断点

右键断点 → "Edit Breakpoint" → 输入条件表达式：
```
tool_call.name == "run_sql"
response.is_tool_call() == True
```

### 7.2 日志断点（Logpoint）

右键断点 → "Edit Breakpoint" → 选择 "Logpoint" → 输入日志模板：
```
Tool call: {tool_call.name}, args: {tool_call.arguments}
```

不暂停执行，只打印日志到 Debug Console。

### 7.3 异常断点

VS Code 左侧 "Run and Debug" → "Breakpoints" 面板 → 勾选 "Raised Exceptions"：
- 捕获所有异常并暂停（包括被 try/except 处理的）
- 适合排查静默吞掉的异常

### 7.4 justMyCode 设置

`launch.json` 中 `"justMyCode": false` 允许进入第三方库源码：
- `true`：只调试本项目代码
- `false`：可进入 pydantic、chromadb 等库内部

---

## 八、关键入口速查

| 入口 | 命令 |
|---|---|
| 启动服务 | `python -m vanna.servers --framework fastapi --port 8000` |
| 运行示例 | `python -m vanna.examples <example_name>` |
| 列出示例 | `python -m vanna.servers --list-examples` |
| CLI 命令 | `vanna --framework fastapi --port 8000` |