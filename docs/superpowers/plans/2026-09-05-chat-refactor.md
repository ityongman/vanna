# 聊天界面重构 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `frontends/web` 用 antd 自研聊天界面替换 `<chatbot-chat>` webcomponent，实现历史记录/会话切换/新建会话/业务隔离，后端受控扩展 rich 组件落库、自动标题、空会话不落库。

**Architecture:** 后端 Agent/存储层 4 处受控扩展（Message.rich 落库、starter 请求不落库、首轮后 LLM 自动生成标题、会话按 business_id 标记与过滤），全部向后兼容 webcomponent；前端新增 SSE 客户端、会话状态 hook（draft 会话 + 流式消息 + 历史回放）、antd 组件集（侧栏/消息流/输入区）与 rich 组件渲染器（markdown/表格/plotly/卡片/按钮/状态卡），未知组件降级 JSON。

**Tech Stack:** Python/FastAPI/pydantic/pytest（asyncio_mode=auto）；React 19 + TypeScript + Vite 6 + antd v5 + react-markdown + remark-gfm + plotly.js-dist-min。

**设计文档:** `docs/superpowers/specs/2026-09-05-chat-refactor-design.md`

**需求来源:** `.trae/requirements/require_desc02.md`

---

## 变更文件总览

**后端（TDD，测试放根目录 `tests/`）：**

| 文件 | 动作 | 职责 |
|---|---|---|
| `src/vanna/core/storage/models.py` | 修改 | `Message` 增加 `rich: List[Dict[str, Any]]` |
| `src/vanna/core/agent/agent.py` | 修改 | rich 收集写回（C1）、删除 starter 保存（C2）、标题生成（C3）、business_id 标记（C4） |
| `src/vanna/servers/fastapi/conversation_routes.py` | 修改 | `list_conversations` 支持 `business_id` 过滤（C4） |
| `tests/test_chat_history.py` | 新建 | C1/C2/C3/C4-agent 测试（FakeStore + FakeLlmService） |
| `tests/test_conversation_routes.py` | 修改 | C4 路由过滤测试 |

**前端（`frontends/web`）：**

| 文件 | 动作 | 职责 |
|---|---|---|
| `package.json` | 修改 | 新增 react-markdown/remark-gfm/plotly.js-dist-min 与 @types |
| `src/lib/sse.ts` | 新建 | POST SSE 客户端（复刻 webcomponent `streamChat`） |
| `src/lib/api.ts` | 修改 | ConversationMeta 增加 metadata/rich；conversations 支持 business_id |
| `src/pages/Chat/types.ts` | 新建 | ChatMessage/RichComponent/ChatStreamChunk 等类型 |
| `src/pages/Chat/useChatSession.ts` | 新建 | 会话状态 hook |
| `src/pages/Chat/components/renderers/*` | 新建 | rich 组件渲染器 7 个文件 |
| `src/pages/Chat/components/ConversationSidebar.tsx` | 新建 | 会话侧栏 |
| `src/pages/Chat/components/MessageList.tsx` | 新建 | 消息流 + 自动滚动 |
| `src/pages/Chat/components/MessageBubble.tsx` | 新建 | 消息气泡 + rich 渲染 + 错误重试 |
| `src/pages/Chat/components/Composer.tsx` | 新建 | 输入区（发送/停止） |
| `src/pages/Chat/index.tsx` | 重写 | 删除 webcomponent 注入，组合新 UI |
| `src/i18n/locales/{zh-CN,zh-TW,en-US}/common.json` | 修改 | 新增 chat.* 文案 |

**执行环境约定：**

- 后端测试在仓库根目录运行；前端命令在 `frontends/web` 目录运行。
- 前端无单测基建，验证方式为 `npm run build`（tsc -b + vite build）。

---

## 后端（TDD）

### Task 1: C1 模型层 — Message.rich 字段

**Files:**
- Create: `tests/test_chat_history.py`
- Modify: `src/vanna/core/storage/models.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_chat_history.py`，先放入模型测试与共享基础设施（后续任务追加测试到同一文件）：

```python
"""Tests for chat history persistence: rich components, empty-session
skipping, title generation and business isolation (C1-C4)."""

import pytest

from vanna.core.llm import LlmService
from vanna.core.llm.models import LlmRequest, LlmResponse, LlmStreamChunk
from vanna.core.storage.base import ConversationStore
from vanna.core.storage.models import Conversation, Message
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver


class FakeStore(ConversationStore):
    """In-memory conversation store for agent tests."""

    def __init__(self):
        self._convs = {}

    async def create_conversation(self, conversation_id, user, initial_message):
        conv = Conversation(
            id=conversation_id,
            user=user,
            messages=[Message(role="user", content=initial_message)],
        )
        self._convs[conversation_id] = conv
        return conv

    async def get_conversation(self, conversation_id, user):
        return self._convs.get(conversation_id)

    async def update_conversation(self, conversation):
        self._convs[conversation.id] = conversation

    async def delete_conversation(self, conversation_id, user):
        return self._convs.pop(conversation_id, None) is not None

    async def list_conversations(self, user, limit=50, offset=0):
        convs = list(self._convs.values())
        return convs[offset : offset + limit]


class SimpleUserResolver(UserResolver):
    """Always resolves to the same test user."""

    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(id="test_user", email="test@example.com")


class FakeLlmService(LlmService):
    """Configurable fake LLM.

    ``reply`` is streamed for every chat turn; ``title`` is returned by
    ``send_request`` when the request metadata carries
    ``purpose == "conversation_title"``. ``fail_title`` makes title
    generation raise, exercising the fallback path.
    """

    def __init__(self, reply="Hello from the agent", title=None, fail_title=False):
        self.reply = reply
        self.title = title
        self.fail_title = fail_title

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        if request.metadata.get("purpose") == "conversation_title":
            if self.fail_title:
                raise RuntimeError("title LLM unavailable")
            return LlmResponse(content=self.title or "")
        return LlmResponse(content=self.reply)

    async def stream_request(self, request: LlmRequest):
        if self.reply:
            yield LlmStreamChunk(content=self.reply)

    async def validate_tools(self, tools):
        return []


def make_agent(llm_service, store):
    """Build an agent wired to the given fake store and LLM."""
    from vanna import Agent, AgentConfig
    from vanna.core.registry import ToolRegistry
    from vanna.integrations.local.agent_memory import DemoAgentMemory

    return Agent(
        llm_service=llm_service,
        tool_registry=ToolRegistry(),
        user_resolver=SimpleUserResolver(),
        agent_memory=DemoAgentMemory(max_items=1000),
        conversation_store=store,
        config=AgentConfig(),
    )


async def _run_agent(agent, message="Who is the top artist?", metadata=None):
    """Send one message through the agent, returning all components."""
    request_context = RequestContext(cookies={}, headers={}, metadata=metadata or {})
    components = []
    async for component in agent.send_message(request_context, message):
        components.append(component)
    return components


def test_message_rich_field_defaults_to_empty_list():
    msg = Message(role="assistant", content="hello")
    assert msg.rich == []


def test_message_rich_field_roundtrip_json():
    rich = [{"id": "r1", "type": "table", "data": {"columns": ["a"]}}]
    msg = Message(role="assistant", content="hello", rich=rich)
    dumped = msg.model_dump(mode="json")
    assert dumped["rich"] == rich
    reloaded = Message.model_validate(dumped)
    assert reloaded.rich == rich
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_chat_history.py -x -q`

Expected: FAIL — `AttributeError: 'Message' object has no attribute 'rich'`（旧数据无 rich 的 `Message.model_validate` 等价路径由默认值保证，测试覆盖三例）。

- [ ] **Step 3: 最小实现**

修改 `src/vanna/core/storage/models.py`，`Message` 增加 rich 字段（`Any`/`List` 已在文件头部导入）：

```python
class Message(BaseModel):
    """Single message in a conversation."""

    role: str = Field(description="Message role (user/assistant/system/tool)")
    content: str = Field(description="Message content")
    timestamp: datetime = Field(default_factory=_now_local)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tool_calls: Optional[List[ToolCall]] = Field(default=None)
    tool_call_id: Optional[str] = Field(
        default=None, description="ID if this is a tool response"
    )
    rich: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Serialized rich UI components for history replay",
    )
```

（在 `tool_call_id` 字段之后追加 `rich` 字段，其余不动。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_chat_history.py -x -q`

Expected: PASS — `4 passed`（2 个测试均通过，pytest 无其它收集项时以实际数量为准）。

- [ ] **Step 5: Commit**

```powershell
git add src/vanna/core/storage/models.py tests/test_chat_history.py
git commit -m "feat(storage): add rich field to messages"
```

---

### Task 2: C1 Agent 层 — 流式 rich 组件收集并写回最终 assistant 消息

**Files:**
- Modify: `src/vanna/core/agent/agent.py`
- Test: `tests/test_chat_history.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_chat_history.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_agent_persists_rich_components_on_assistant_message():
    store = FakeStore()
    agent = make_agent(FakeLlmService(reply="Iron Maiden sold the most."), store)

    components = await _run_agent(agent)
    assert components, "expected streamed components"

    convs = list(store._convs.values())
    assert len(convs) == 1
    assistant_msgs = [m for m in convs[0].messages if m.role == "assistant"]
    assert assistant_msgs, "expected an assistant message"

    rich = assistant_msgs[-1].rich
    assert rich, "expected rich components persisted on the assistant message"
    text_comps = [r for r in rich if r.get("type") == "text"]
    assert any(
        r.get("data", {}).get("content") == "Iron Maiden sold the most."
        for r in text_comps
    ), "expected the final text component to be persisted"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_chat_history.py -x -q`

Expected: FAIL — `AttributeError: 'Message' object has no attribute 'rich'`（`assistant_msgs[-1].rich` 访问失败）。

- [ ] **Step 3: 实现 — 收集中外层发送入口**

修改 `src/vanna/core/agent/agent.py`：

3.1 文件头部 typing 导入增加 `Any`：

```python
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, List, Optional
```

3.2 替换 `send_message` 的委托块（约 L285-290）：

```python
        try:
            # Delegate to internal method
            async for component in self._send_message(
                request_context, message, conversation_id=conversation_id
            ):
                yield component
        except Exception as e:
```

替换为：

```python
        try:
            # Ensure a conversation id exists up-front so the rich
            # components collected below can be attached to the right
            # conversation once generation completes.
            if conversation_id is None:
                conversation_id = str(uuid.uuid4())

            # Collect serialized rich components while streaming; they are
            # persisted onto the final assistant message for history replay.
            rich_components: List[Dict[str, Any]] = []

            # Delegate to internal method
            async for component in self._send_message(
                request_context, message, conversation_id=conversation_id
            ):
                if component.rich_component is not None:
                    rich_components.append(
                        component.rich_component.serialize_for_frontend()
                    )
                yield component

            if rich_components:
                try:
                    await self._attach_rich_components(
                        request_context, conversation_id, rich_components
                    )
                except Exception as e:
                    logger.error(
                        "Failed to attach rich components to conversation %s: %s",
                        conversation_id,
                        e,
                        exc_info=True,
                    )
        except Exception as e:
```

3.3 在 `get_available_tools` 方法定义前（约 L822）插入新方法：

```python
    async def _attach_rich_components(
        self,
        request_context: RequestContext,
        conversation_id: str,
        rich_components: List[Dict[str, Any]],
    ) -> None:
        """Persist serialized rich components onto the final assistant message."""
        user = await self.user_resolver.resolve_user(request_context)
        conversation = await self.conversation_store.get_conversation(
            conversation_id, user
        )
        if conversation is None:
            # Starter requests (never persisted) and aborted streams have
            # nothing to attach to.
            return

        for msg in reversed(conversation.messages):
            if msg.role == "assistant":
                msg.rich = rich_components
                break

        await self.conversation_store.update_conversation(conversation)

```

（定位：`async def get_available_tools(self, user: User) -> List[ToolSchema]:` 这行之前插入。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_chat_history.py -x -q`

Expected: PASS — 全部通过（3 个测试：2 个模型 + 1 个 agent rich 落库）。

- [ ] **Step 5: Commit**

```powershell
git add src/vanna/core/agent/agent.py tests/test_chat_history.py
git commit -m "feat(agent): persist streamed rich components on assistant messages"
```

---

### Addendum A2: Task 2 代码审查修复（经主 agent 批准）

代码质量审查对 `e1088618` 提出 Changes Requested，以下修复经批准执行：

- **I-2**：`_attach_rich_components` 开头加 `auto_save_conversations` 守卫（与 `_send_message` 末尾保存行为一致）。
- **I-1 / M-3 / M-5**：`_attach_rich_components` 仅当最后一条 assistant 消息的 content 与本轮流出的最后一个 text 组件 content 相等时才写 rich 并保存（防止 starter/workflow 短路路径覆盖上一轮 rich；避免无谓 UPDATE）。
- **I-3**：docstring 注明 read-modify-write 并发限制（预存在行为）。
- **M-2**：修正 `conversation is None` 分支注释。
- **测试**：FakeStore.update_conversation 改深拷贝 `model_copy(deep=True)`；新增 FakeWorkflowHandler 与两条回归测试（starter 请求、/help 短路均不得覆盖已有 rich）；`_run_agent` 增加可选 `conversation_id` 参数。

修复提交信息：`fix(agent): guard rich attachment against short-circuit flows and auto-save off`

---

### Addendum A3: Task 3 测试必须配置 workflow_handler（经主 agent 批准）

`agent.py` 中 starter 分支的生效条件是 `is_starter_request and self.workflow_handler`（无 workflow_handler 时 `("hi", {"starter_ui_request": True})` 会误入 LLM 路径、`("", None)` 会静默 return 不产组件）。因此 Task 3 的测试构造 agent 时必须传入 `workflow_handler=FakeWorkflowHandler()`（Addendum A2 已定义该类）：

```python
agent = make_agent(FakeLlmService(), store, workflow_handler=FakeWorkflowHandler())
```

其余测试代码与计划一致。

---

### Addendum A3b: workflow 短路路径空会话不落库（经主 agent 批准）

Task 3 代码质量审查（Approved）指出：`_send_message` 的 workflow 短路分支（`should_skip_llm`）在新会话场景下仍会保存 `messages=[]` 的空会话，与 C2 不变式同构违背。修复：

1. workflow 短路分支保存块改为仅在会话有消息时保存：

```python
                    # Save only if the workflow produced conversation content;
                    # empty sessions must not be persisted.
                    if self.config.auto_save_conversations and conversation.messages:
                        await self.conversation_store.update_conversation(conversation)
```

2. 顺手更新过时注释：starter 分支中 `# Create empty conversation (will be saved if workflow produces components)` 改为 `# In-memory only; starter requests never persist`。
3. 新增回归测试 `test_workflow_short_circuit_does_not_persist_empty_conversation`（/help 新会话 → `store._convs == {}`）。

修复提交信息：`fix(agent): skip persisting workflow short-circuit empty conversations`

---

### Task 3: C2 — starter 请求不落库

**Files:**
- Modify: `src/vanna/core/agent/agent.py`
- Test: `tests/test_chat_history.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_chat_history.py` 末尾追加：

```python
@pytest.mark.parametrize(
    "message,metadata",
    [
        ("", None),
        ("", {"starter_ui_request": True}),
        ("hi", {"starter_ui_request": True}),
    ],
)
@pytest.mark.asyncio
async def test_starter_requests_do_not_persist_conversation(message, metadata):
    store = FakeStore()
    agent = make_agent(FakeLlmService(), store)

    components = await _run_agent(agent, message=message, metadata=metadata)
    assert components, "starter UI components expected"

    assert store._convs == {}, "starter requests must not create a conversation"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_chat_history.py -x -q`

Expected: FAIL — `assert {} == {...}`（starter 分支当前无条件 `update_conversation`，store 中有一条空会话）。

- [ ] **Step 3: 实现 — 删除 starter 分支的保存**

修改 `src/vanna/core/agent/agent.py`，删除 starter 分支末尾的保存块（约 L404-408）：

```python
                # Save the conversation if it was newly created
                if self.config.auto_save_conversations:
                    await self.conversation_store.update_conversation(conversation)

                return  # Exit without calling LLM
```

替换为：

```python
                # Starter requests only stream UI components; they never
                # persist a conversation (empty sessions should not exist).
                return  # Exit without calling LLM
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_chat_history.py -x -q`

Expected: PASS — 全部通过（含 3 个新参数化用例，先前的 rich 落库与模型测试不受影响）。

- [ ] **Step 5: Commit**

```powershell
git add src/vanna/core/agent/agent.py tests/test_chat_history.py
git commit -m "fix(agent): stop persisting empty starter conversations"
```

---

### Addendum A4: Task 4 标题清洗一致性 + 行为锁定测试（经主 agent 批准）

代码质量审查（Approved）的 Minor 修复：

1. **Minor #1**：fallback 与 LLM 路径清洗一致——`_generate_conversation_title` 最终返回改为 `" ".join(first_user_message.strip().split())[:60] or "New conversation"`。
2. **Minor #2/引号**：LLM 路径标题清洗兼容单双引号——`title = (response.content or "").strip().strip("\"'").strip()`。
3. **Minor #3（部分）**：补 3 条行为锁定测试：
   - `test_title_llm_quote_cleaning`：FakeLlmService(title="'Top Artist Sales'") → 期望 `"Top Artist Sales"`（先 RED，单引号未被去除）。
   - `test_conversation_title_empty_llm_reply_falls_back`：title=""（空回复）→ 回退首条用户消息（行为锁定，当前已正确）。
   - `test_title_generated_only_once_per_conversation`：FakeLlmService 增加 `title_calls` 计数（purpose==conversation_title 时 +1），两轮对话后断言 `llm.title_calls == 1`（第二轮因 title 已在 metadata 不再发起标题请求）。
4. 其余 Minor（#4 保存前阻塞、#5 fallback 不升级）按设计接受，不修改。

修复提交信息：`fix(agent): normalize title cleaning and lock fallback behaviors with tests`

---

### Task 4: C3 — 首轮后自动生成会话标题

**Files:**
- Modify: `src/vanna/core/agent/agent.py`
- Test: `tests/test_chat_history.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_chat_history.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_conversation_title_generated_by_llm_after_first_turn():
    store = FakeStore()
    agent = make_agent(FakeLlmService(reply="42 albums", title="Top Artist Sales"), store)

    await _run_agent(agent)
    conv = next(iter(store._convs.values()))
    assert conv.metadata.get("title") == "Top Artist Sales"


@pytest.mark.asyncio
async def test_conversation_title_falls_back_to_first_user_message():
    store = FakeStore()
    agent = make_agent(FakeLlmService(reply="ok", fail_title=True), store)

    long_message = "请帮我统计每个艺人的专辑销量并按金额排序输出前十个" * 3  # > 60 chars
    await _run_agent(agent, message=long_message)

    conv = next(iter(store._convs.values()))
    assert conv.metadata.get("title") == long_message[:60]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_chat_history.py -x -q`

Expected: FAIL — `assert None == 'Top Artist Sales'`（metadata 尚无 title）。

- [ ] **Step 3: 实现**

修改 `src/vanna/core/agent/agent.py`：

3.1 在尾部保存之前插入标题生成（找到约 L814-816）：

```python
        # Save conversation if configured
        if self.config.auto_save_conversations:
            await self.conversation_store.update_conversation(conversation)
```

在其上方插入：

```python
        # Auto-generate a title after the first completed turn (assistant
        # reply produced, title not yet set). Failures fall back inline.
        if (
            self.config.auto_save_conversations
            and conversation.messages
            and "title" not in conversation.metadata
            and any(m.role == "assistant" for m in conversation.messages)
        ):
            try:
                conversation.metadata["title"] = (
                    await self._generate_conversation_title(conversation)
                )
            except Exception as e:
                logger.error(
                    "Failed to generate conversation title: %s", e, exc_info=True
                )

```

3.2 在 `_attach_rich_components` 方法之后（Task 2 插入处之后）追加新方法：

```python
    async def _generate_conversation_title(self, conversation: Conversation) -> str:
        """Generate a short title via LLM, falling back to truncation.

        The LLM is asked to return at most 6 words and nothing else; any
        failure (unconfigured LLM, provider error, empty reply) falls back
        to the first 60 characters of the first user message.
        """
        first_user_message = next(
            (m.content for m in conversation.messages if m.role == "user"), ""
        )

        try:
            request = LlmRequest(
                messages=[
                    LlmMessage(role="user", content=first_user_message),
                ],
                user=conversation.user,
                stream=False,
                temperature=0.2,
                max_tokens=32,
                system_prompt=(
                    "Generate a concise title (max 6 words) for the following "
                    "conversation. Return ONLY the title, no quotes, no extra text."
                ),
                metadata={"purpose": "conversation_title"},
            )
            response = await self._send_llm_request(request)
            title = (response.content or "").strip().strip('"').strip()
            if title:
                return " ".join(title.split())[:60]
        except Exception as e:
            logger.error("Title generation via LLM failed: %s", e, exc_info=True)

        return first_user_message.strip()[:60] or "New conversation"

```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_chat_history.py -x -q`

Expected: PASS — 全部通过（新增 2 个标题测试）。

- [ ] **Step 5: Commit**

```powershell
git add src/vanna/core/agent/agent.py tests/test_chat_history.py
git commit -m "feat(agent): auto-generate conversation titles after first turn"
```

---

### Task 5: C4 — 会话按 business_id 标记与列表过滤

**Files:**
- Modify: `src/vanna/core/agent/agent.py`
- Modify: `src/vanna/servers/fastapi/conversation_routes.py`
- Test: `tests/test_chat_history.py`、`tests/test_conversation_routes.py`

- [ ] **Step 1: 写失败测试**

5.1 在 `tests/test_chat_history.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_conversation_tagged_with_business_id():
    store = FakeStore()
    agent = make_agent(FakeLlmService(), store)

    await _run_agent(agent, metadata={"business_id": "biz_a"})

    conv = next(iter(store._convs.values()))
    assert conv.metadata.get("business_id") == "biz_a"
```

5.2 修改 `tests/test_conversation_routes.py`：

`make_client` 支持注入 store（保留原无参行为），并追加过滤测试。将原文件末尾的两个测试保留，追加以下内容：

```python
def make_client(store=None):
    app = FastAPI()
    agent = FakeAgent()
    if store is not None:
        agent.conversation_store = store
    register_conversation_routes(app, agent)
    return TestClient(app)
```

（即给原 `make_client` 增加 `store=None` 参数与注入两行。）

再在文件末尾追加：

```python
def test_list_conversations_filtered_by_business():
    store = FakeStore()
    store._convs["c1"] = Conversation(
        id="c1",
        user=User(id="anonymous", email=None),
        messages=[],
        metadata={"business_id": "b1"},
    )
    store._convs["c2"] = Conversation(
        id="c2",
        user=User(id="anonymous", email=None),
        messages=[],
        metadata={"business_id": "b2"},
    )
    store._convs["c3"] = Conversation(
        id="c3",
        user=User(id="anonymous", email=None),
        messages=[],
        metadata={},
    )

    client = make_client(store)

    resp = client.get("/api/conversations?business_id=b1")
    assert resp.status_code == 200
    assert [c["id"] for c in resp.json()] == ["c1"]

    resp_all = client.get("/api/conversations")
    assert resp_all.status_code == 200
    assert len(resp_all.json()) == 3
```

（`User` 已在文件头部 import；`Conversation` 已 import。原有 `test_list_conversations` 用无参 `make_client()`，行为不变。）

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_chat_history.py tests/test_conversation_routes.py -x -q`

Expected: FAIL — 两类失败之一（以先命中的为准）：
- `assert None == 'biz_a'`（agent 未写 metadata）
- `['c1', 'c2', 'c3'] != ['c1']`（路由未过滤）

- [ ] **Step 3: 实现**

3.1 修改 `src/vanna/core/agent/agent.py`，在会话创建/加载之后（约 L450-453，`Conversation(id=conversation_id, ...)` 新建块之后）插入：

```python
        # Tag the conversation with the requesting business so listings
        # can be filtered per business.
        request_business_id = request_context.metadata.get("business_id")
        if request_business_id:
            conversation.metadata["business_id"] = request_business_id
```

（插入位置：`conversation = Conversation(id=conversation_id, user=user, messages=[])` 这行之后、`# Try workflow handler before adding message to conversation` 注释之前。）

3.2 修改 `src/vanna/servers/fastapi/conversation_routes.py`：

文件头部 import 增加 `Optional`：

```python
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
```

`list_conversations` 增加 business_id 参数并在 Python 侧过滤：

```python
    @app.get("/api/conversations")
    async def list_conversations(
        http_request: Request,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        business_id: Optional[str] = Query(None),
    ):
        user = await resolve_user(agent, http_request)
        conversations = await store.list_conversations(user, limit=limit, offset=offset)
        if business_id is not None:
            conversations = [
                c
                for c in conversations
                if c.metadata.get("business_id") == business_id
            ]
        return [c.model_dump(mode="json") for c in conversations]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_chat_history.py tests/test_conversation_routes.py -x -q`

Expected: PASS — 全部通过（新增 agent 标记 1 例 + 路由过滤 1 例；原有 `test_list_conversations`/`test_delete_conversation` 不受影响）。

- [ ] **Step 5: Commit**

```powershell
git add src/vanna/core/agent/agent.py src/vanna/servers/fastapi/conversation_routes.py tests/test_chat_history.py tests/test_conversation_routes.py
git commit -m "feat(chat): tag conversations with business_id and support filtered listing"
```

### Addendum A5: Task 5 代码质量审查修复（经主 agent 亲自核实批准）

Task 5 首提 `63c4fe70` 通过 spec 合规审查（Approved，逐字合规）；代码质量审查 Changes Requested。主 agent 已亲自 Read 核实 src 代码（agent.py L479-483、conversation_routes.py L21-27、三个 store 实现的切片位置、FS store `_save_metadata` L55-60 及 get/list 重建段、`Conversation.metadata` 模型字段），批准以下 5 项修复；其余意见记录处理如下：

- **A5-1（I-2 误标覆盖，批准）**：agent.py 打标块改为 `conversation.metadata.setdefault("business_id", request_business_id)`，保留会话首次归属；注释更新说明。既有未打标历史会话仍可被补标。
- **A5-2（I-3 空串不对称，批准）**：conversation_routes.py 过滤条件改 `if business_id:`，与写侧 `if request_business_id:` 对齐（空串视为不过滤）。
- **A5-3（I-1 分页语义错乱，批准）**：过滤下推到 `ConversationStore.list_conversations`——抽象基类（core/storage/base.py）签名加 `business_id: Optional[str] = None`；三个实现（Memory/SQLite/FS）统一顺序：按 user 过滤 → 按 updated_at 降序 → business_id 过滤 → 切片分页（SQLite 实现：business_id 非 None 时不带 LIMIT/OFFSET 拉取该用户全量行再 Python 过滤后切片，数据量小，规格 4.4 已接受；注释注明后续可加 json_extract 索引优化）。路由删除内存过滤、改为透传 `business_id`。两个测试 FakeStore（test_chat_history.py、test_conversation_routes.py）签名同步加 `business_id=None` 并实现先过滤后切片。`examples/extensibility_example.py` 不修改——新参数有默认值，向后兼容。
- **A5-4（I-4 FS store 不持久化 metadata，批准）**：file_system_conversation_store.py `_save_metadata` 增加 `"metadata": conversation.metadata`；`get_conversation` 与 `list_conversations` 重建 Conversation 时回填 `metadata=raw.get("metadata", {})`（旧数据无该 key 时兜底空 dict），并注意局部变量不与文件内容变量重名。
- **A5-5（M-1 测试缺口，批准）**：补 4 类行为测试：
  1. test_chat_history.py：`test_existing_conversation_keeps_original_business_tag`（biz_a 建会话后携 biz_b 同 conversation_id 再发消息，仍为 biz_a）；`test_conversation_without_business_not_tagged`（不带 business_id 时不产生标记）。
  2. test_conversation_routes.py：`?business_id=`（空串）返回全部；分页+过滤顺序用例（b1 两条 c1/c4 且含其它业务会话，`?business_id=b1&limit=1&offset=1` 返回 ["c4"]——若先分页后过滤该断言失败）。
  3. 新建 `tests/test_conversation_store_filters.py`：真实 store 行为锁定——MemoryConversationStore + SQLiteConversationStore(tmp db) + FileSystemConversationStore(tmp dir) 三实现统一验证"business_id 过滤后分页"；FS 额外验证 metadata 落盘回读。
- **不修复（记录理由）**：M-2 FakeStore 不做 user 过滤是既有测试风格，本次保持；M-3 手工折行随 A5-3 重写路由代码自然消除；M-4 无害。

**执行方式**：TDD——先追加/新建上述测试并运行确认失败（RED），再最小实现，GREEN 后提交：

```powershell
git add src/vanna/core/agent/agent.py src/vanna/core/storage/base.py src/vanna/integrations/local/storage.py src/vanna/integrations/local/sqlite_conversation_store.py src/vanna/integrations/local/file_system_conversation_store.py src/vanna/servers/fastapi/conversation_routes.py tests/test_chat_history.py tests/test_conversation_routes.py tests/test_conversation_store_filters.py
git commit -m "fix(chat): keep first business tag, align empty filter, and filter conversations before pagination"
```

---

## 前端（frontends/web）

### Task 6: 安装依赖

**Files:**
- Modify: `frontends/web/package.json`（npm 自动更新）

- [ ] **Step 1: 安装运行时依赖**

Run:

```powershell
cd frontends/web; npm install react-markdown remark-gfm plotly.js-dist-min
```

Expected: `added ... packages` 且无 error。

- [ ] **Step 2: 安装类型依赖**

Run:

```powershell
cd frontends/web; npm install -D @types/plotly.js-dist-min
```

Expected: `added ... packages` 且无 error。

- [ ] **Step 3: 验证依赖**

Run:

```powershell
cd frontends/web; npm ls react-markdown remark-gfm plotly.js-dist-min @types/plotly.js-dist-min
```

Expected: 四个包各列出版本号（如 `react-markdown@10.x`），无 `missing`/`invalid`。

- [ ] **Step 4: Commit**

```powershell
git add frontends/web/package.json frontends/web/package-lock.json
git commit -m "chore(web): add markdown and chart dependencies for chat UI"
```

---

### Task 7: 类型定义 + SSE 客户端

**Files:**
- Create: `frontends/web/src/pages/Chat/types.ts`
- Create: `frontends/web/src/lib/sse.ts`

- [ ] **Step 1: 创建 `frontends/web/src/pages/Chat/types.ts`**

```ts
/** Chat message shown in the UI. */
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  /** Accumulated simple text payload of the assistant reply. */
  content: string;
  /** Rich components received for this message. */
  rich: RichComponent[];
  status: 'streaming' | 'done' | 'error';
  errorDetail?: string;
}

/** Serialized rich component from the backend (`ChatStreamChunk.rich`). */
export interface RichComponent {
  id?: string;
  type: string;
  lifecycle?: string;
  children?: string[];
  timestamp?: string;
  visible?: boolean;
  interactive?: boolean;
  data: Record<string, any>;
}

/** One SSE chunk of the POST /api/vanna/v2/chat_sse stream. */
export interface ChatStreamChunk {
  rich: RichComponent;
  simple?: Record<string, any> | null;
  conversation_id: string;
  request_id: string;
  timestamp: number;
}

/**
 * Collapse component updates sharing the same id (lifecycle create/update
 * sequences) to the latest payload for replay rendering.
 */
export function dedupeRich(rich: RichComponent[]): RichComponent[] {
  const byId = new Map<string, RichComponent>();
  for (const comp of rich) {
    byId.set(comp.id ?? `${comp.type}_${byId.size}`, comp);
  }
  return [...byId.values()];
}
```

- [ ] **Step 2: 创建 `frontends/web/src/lib/sse.ts`**

```ts
import type { ChatStreamChunk } from '../pages/Chat/types';

export interface StreamHandlers {
  onChunk: (chunk: ChatStreamChunk) => void;
}

/**
 * POST to the SSE chat endpoint and invoke `handlers.onChunk` per parsed
 * chunk. Mirrors the webcomponent `ChatbotApiClient.streamChat` protocol:
 * lines prefixed with `data: `, `[DONE]` ends the stream, unparseable
 * lines are skipped with a warning.
 */
export async function streamChat(
  body: Record<string, unknown>,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch('/api/vanna/v2/chat_sse', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    credentials: 'include',
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }

  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;

        const data = line.slice(6).trim();
        if (data === '[DONE]') return;

        try {
          handlers.onChunk(JSON.parse(data) as ChatStreamChunk);
        } catch (e) {
          console.warn('Failed to parse SSE chunk:', data, e);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
```

- [ ] **Step 3: Commit**

```powershell
git add frontends/web/src/pages/Chat/types.ts frontends/web/src/lib/sse.ts
git commit -m "feat(web): add chat types and SSE stream client"
```

---

### Task 8: 扩展 lib/api.ts

**Files:**
- Modify: `frontends/web/src/lib/api.ts`

- [ ] **Step 1: 修改会话类型与列表接口**

将 `ConversationMeta` 定义替换为（`fetchJson` 与其余 API 不动）：

```ts
export interface ConversationMessageMeta {
  role: string;
  content: string;
  rich?: Record<string, any>[];
}

export interface ConversationMeta {
  id: string;
  updated_at: string;
  metadata?: { title?: string; business_id?: string };
  messages: ConversationMessageMeta[];
}
```

将 `api.conversations` 替换为支持 business_id 的版本：

```ts
  conversations: (businessId?: string) =>
    fetchJson<ConversationMeta[]>(
      businessId
        ? `/api/conversations?business_id=${encodeURIComponent(businessId)}`
        : '/api/conversations'
    ),
```

（`api.conversation`、`deleteConversation`、schema 相关接口保持不变。）

- [ ] **Step 2: Commit**

```powershell
git add frontends/web/src/lib/api.ts
git commit -m "feat(web): expose conversation metadata and business filter in api client"
```

### Addendum A6: Task 7/8 合并审查结论（经主 agent 批准）

Task 7（`e53cb3f`）与 Task 8（`52e9dcd9`）经合并审查 **Approved**：与计划逐字一致、提交边界干净、后端协议证据充分（chat_sse 每帧 `\n\n` 结尾无残留 buffer 风险；`ChatStreamChunk.rich` 为单 dict 与前端类型对齐；conversations 列表先过滤后分页与前端语义吻合）。三个 Minor 记录如下，其中前两项移交 Task 10 处理：

- **移交 Task 10**：SSE 流中后端异常帧形状为 `{"type":"error","data":...,"conversation_id":...,"request_id":...}`（无 rich 字段），useChatSession 消费 chunk 时须先判 `type === 'error'` 再按错误处理，不得直接按 `ChatStreamChunk` 形状取值。
- **移交 Task 10**：streamChat 非 2xx 抛 `Error("HTTP {status}: ...")`，useChatSession 对 401/403 按其状态码前缀判断未认证，勿依赖文案。
- **不修复**：sse.ts/types.ts 文件末尾无换行符（纯风格，无 CI 门禁）。

---

### Addendum A7: Task 9/10 质量审查结论（经主 agent 批准）

Task 9（`cd851e2b`）与 Task 10（`23bd4118`）经代码质量审查 **Changes Requested → 主 agent 逐条亲自核实后裁决如下**：

**批准修复**

1. **I-2 businessId 切换后会话状态残留（Important，属实）**——`<Chat/>` 在 `:businessId` 参数变化时被 React Router 复用（frontends/web/src/router.tsx L56 同一 element 无 key），hook 的 messages/conversationId/sending 不重置：用户切换业务后仍见旧业务消息，续发还会携带旧业务会话 id。**修复落点 Task 12**：`Chat/index.tsx` 改用内部 `key={businessId}` 包装（见 A7-12 授权）。否决 hook 内重置方案（旧流 finally 会用旧闭包 `refreshConversations` 覆盖新业务列表，存在竞态；key 重挂载语义干净，starter 亦重拉新业务欢迎卡片）。
2. **M-4 retry 取错源消息（Minor，属实）**——`retry(failedMessageId)` 现取全局最后一条 user 消息，多轮交错时点早期失败消息的重试会重发错误内容。应定位 failedMessageId 之前最近的 user 消息。修复 useChatSession.ts（见 A7 修复提交）。
3. **M-5 starter catch 未按状态码映射 401/403（Minor，属实）**——抽模块级 `httpStatusOf(error)` 公用函数，startStream 与 starter 的 catch 均按 `HTTP {status}` 前缀判断（不依赖文案）。修复 useChatSession.ts（见 A7 修复提交）。
4. **M-7 认证错误英文文案 + 误导性重试（Minor，属实）**——`errorDetail === 'authentication required'` 为稳定标记：Task 11 MessageBubble 对该标记隐藏重试按钮并显示 i18n key `chat.authenticationRequired`（见 A7-11 授权）；Task 13 三语言 JSON 追加该 key（见 A7-13 授权）。

**驳回不修（理由）**

- **I-1 error 帧绑定 conversation_id**：对未绑定会话的请求，error 帧 `conversation_id` 恒为空串——`handle_stream`（src/vanna/servers/base/chat_handler.py L36）将新 id 存于局部变量、不回写 `ChatRequest.conversation_id`（routes.py L74 直接引用请求字段，请求字段为 None 时输出 `""`）；且 `send_message`（src/vanna/core/agent/agent.py L285-364）内层 except 已把绝大多数异常转成带 conversation_id 的 error 组件流（正常 chunk 已被前端绑定）。error 分支增加绑定是死代码；完整闭环需改后端 error 帧回写 conversation_id，不在本需求范围。
- **M-3 ChartView purge/newPlot 竞态**：仅快速切换会话时图表偶发未渲染，无崩溃路径，接受现状。
- **M-6 starter 空气泡**：后端 starter 请求恒产出 rich 卡片，空响应仅在异常路径（error 帧下已置 error 状态），无实际触发场景。
- **M-8 dedupeRich fallback 键碰撞**：后端组件均带 uuid id，实际不碰撞。
- **M-9 IGNORED_TYPES 仅拦截 3 种**：与 Task 9 计划设计一致，其余类型 JSON 降级为既定降级策略，notification 渲染器留作后续增强。
- **M-10 ActionButtons variant 未映射 primary/danger**：纯视觉差异，无功能影响。
- **M-11 每 chunk 全量 map O(n²)**：单会话消息量级下可接受，留作后续优化。

另：spec 合规审查 Approved（Task 10 中 4 行 `// A6:` 注释为主 agent 派发指令明确要求，非 implementer 私加）。

### A7 修复提交（useChatSession.ts，随本修正案派发）

**修复 1（M-4 retry 源消息定位）**——将 retry 回调替换为：

```ts
  const retry = useCallback(
    (failedMessageId: string) => {
      // Find the user message immediately preceding the failed assistant
      // message rather than the last user message in the conversation.
      const failedIndex = messages.findIndex((m) => m.id === failedMessageId);
      if (failedIndex < 0) return;
      const sourceMessage = [...messages]
        .slice(0, failedIndex)
        .reverse()
        .find((m) => m.role === 'user');
      if (!sourceMessage) return;
      setMessages((prev) => prev.filter((m) => m.id !== failedMessageId));
      void startStream(sourceMessage.content, false);
    },
    [messages, startStream]
  );
```

**修复 2（M-5 httpStatusOf 共用）**——在 `mapStoredRich` 函数之后新增模块级函数：

```ts
/**
 * Extract the HTTP status code from fetch/stream errors shaped
 * "HTTP 401: Unauthorized"; returns 0 when no status prefix is present.
 */
function httpStatusOf(error: unknown): number {
  const message = error instanceof Error ? error.message : '';
  const match = /^HTTP (\d{3})\b/.exec(message);
  return match ? Number(match[1]) : 0;
}
```

- startStream catch 的 else 分支改为：

```ts
        } else {
          // A6: detect unauthenticated responses by the HTTP status code
          // prefix (e.g. "HTTP 401: Unauthorized"), never by error text.
          const status = httpStatusOf(e);
          const authError = status === 401 || status === 403;
          patchAssistant((m) => ({
            ...m,
            status: 'error',
            errorDetail: authError ? 'authentication required' : e?.message ?? 'request failed',
          }));
        }
```

- starter 的 catch 分支改为：

```ts
      .catch((e: any) => {
        if (e?.name === 'AbortError') {
          patchStarter((m) => ({ ...m, status: 'done' }));
        } else {
          const status = httpStatusOf(e);
          patchStarter((m) => ({
            ...m,
            status: 'error',
            errorDetail:
              status === 401 || status === 403
                ? 'authentication required'
                : e?.message,
          }));
        }
      })
```

### A7-12 授权修改（Task 12 派发时应用）

`Chat/index.tsx` 计划代码中的 `function Chat() {...}` 整体替换为 `ChatContent`（props 收 businessId，删去 `useParams` 行，其余函数体逐字保持）+ 外部 key 包装：

```tsx
function ChatContent({ businessId }: { businessId: string | undefined }) {
  const { user } = useAuth();
  const chat = useChatSession(businessId);
  const [collapsed, setCollapsed] = useState(false);

  // ……（原计划 Chat 函数体内其余 JSX 逐字不变）
}

function Chat() {
  const { businessId } = useParams();
  return <ChatContent key={businessId} businessId={businessId} />;
}

export default Chat;
```

> 注（派发时一并应用）：`ChatContent` 的 props 类型为 `string | undefined`，与 `useParams` 的返回值类型（react-router v7 `Params<string>`）及 `useChatSession` 的参数类型一致，避免 TS2322。

### A7-11 授权修改（Task 11 派发时应用）

MessageBubble 计划代码中 assistant 分支的 error Alert 部分改为（其余逐字不变）：

```tsx
{message.status === 'error' && (
  <Alert
    type="error"
    showIcon
    message={
      message.errorDetail === 'authentication required'
        ? t('common', 'chat.authenticationRequired', '登录已过期，请重新登录')
        : message.content || message.errorDetail || t('common', 'chat.generationFailed', '生成失败')
    }
    action={
      onRetry &&
      message.errorDetail !== 'authentication required' && (
        <Button size="small" icon={<ReloadOutlined />} onClick={() => onRetry(message.id)}>
          {t('common', 'chat.retry', '重试')}
        </Button>
      )
    }
  />
)}
```

### A7-13 授权修改（Task 13 派发时应用）

三语言 JSON 各追加一个扁平 key：
- zh-CN：`"chat.authenticationRequired": "登录已过期，请重新登录"`
- zh-TW：`"chat.authenticationRequired": "登入已過期，請重新登入"`
- en-US：`"chat.authenticationRequired": "Session expired, please sign in again"`

### A8 修复提交（随本修正案派发，Task 11/A7 质量审查裁决）

Task 11/A7 代码质量审查（核查 `0dced89a` + `2f65d984`）返回 2 Important + 9 Minor。主 agent 逐条亲自核实后裁决：**批准修复 2 Important + 4 Minor（I-1、I-2、M-1、M-2、M-4、M-7）**，**驳回 5 Minor（M-3、M-5、M-6、M-8、M-9）**。

**批准修复（精确代码，implementer 逐字应用）：**

1. **I-1 MessageList 流式强制滚底**（`MessageList.tsx` 中第二条 useEffect 整体替换）：

```tsx
  // New chunks scroll to bottom only when the user is already near the
  // bottom, so streaming never yanks users who scrolled up to read.
  useEffect(() => {
    const el = containerRef.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 80) {
      scrollToBottom(false);
    }
  }, [messages]);
```

2. **I-2 starter 失败重试无效**（`useChatSession.ts` retry 中 `if (!sourceMessage) return;` 替换）：

```ts
      if (!sourceMessage) {
        // A8: starter card failure has no preceding user message; clearing
        // the list makes the starter effect re-run and refetch it.
        setMessages([]);
        return;
      }
```

3. **M-1 会话排序比较器**（`ConversationSidebar.tsx` 中 sorted 行替换）：

```tsx
    const sorted = [...conversations].sort(
      (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)
    );
```

4. **M-2 List rowKey**（`ConversationSidebar.tsx` 中 List 开标签加 rowKey）：

```tsx
          <List
            size="small"
            rowKey={(c) => c.id}
            dataSource={filtered}
```

5. **M-4 Composer 消费 inputHint.value**（`Composer.tsx` 整体按以下内容重写，即：接口加 `value?: string`，内部 state 改名 `draft`，加 A8 注释的 useEffect 同步，submit 改用 draft）：

```tsx
import { useEffect, useState } from 'react';
import { Button, Input } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import { t } from '../../../i18n';

export interface ComposerProps {
  sending: boolean;
  placeholder?: string;
  value?: string;
  onSend: (text: string) => void;
  onStop: () => void;
}

/** Message input: Enter to send, Shift+Enter for a newline, stop while streaming. */
export default function Composer({ sending, placeholder, value, onSend, onStop }: ComposerProps) {
  const [draft, setDraft] = useState('');

  // A8: sync backend-pushed input text (ChatInputUpdateComponent.value).
  useEffect(() => {
    if (value !== undefined) setDraft(value);
  }, [value]);

  const submit = () => {
    const text = draft.trim();
    if (!text || sending) return;
    setDraft('');
    onSend(text);
  };

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', padding: '12px 24px', borderTop: '1px solid #f0f0f0' }}>
      <Input.TextArea
        value={draft}
        autoSize={{ minRows: 1, maxRows: 6 }}
        placeholder={placeholder ?? t('common', 'chat.inputPlaceholder', '输入问题，Enter 发送，Shift+Enter 换行')}
        style={{ flex: 1, resize: 'none' }}
        onChange={(e) => setDraft(e.target.value)}
        onPressEnter={(e) => {
          if (!e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        disabled={sending}
      />
      {sending ? (
        <Button danger onClick={onStop}>
          {t('common', 'chat.stop', '停止')}
        </Button>
      ) : (
        <Button type="primary" icon={<SendOutlined />} disabled={!draft.trim()} onClick={submit}>
          {t('common', 'chat.send', '发送')}
        </Button>
      )}
    </div>
  );
}
```

6. **M-7 认证标记共享常量**：
   - `types.ts` 在 `dedupeRich` 之前追加：

```ts
/** Error detail marker for 401/403 authentication failures. */
export const AUTH_ERROR_DETAIL = 'authentication required';
```

   - `useChatSession.ts` 顶部 import 改为 `import { AUTH_ERROR_DETAIL, ChatMessage, ChatStreamChunk, RichComponent } from './types';`，并将两处 `'authentication required'` 字面量（startStream catch else 与 starter catch）改为 `AUTH_ERROR_DETAIL`。
   - `MessageBubble.tsx` 顶部 import 改为 `import { AUTH_ERROR_DETAIL, ChatMessage, dedupeRich } from '../types';`，并将两处与 `'authentication required'` 的比较改为 `AUTH_ERROR_DETAIL`。

Commit message：`fix(web): near-bottom autoscroll, starter retry fallback and shared auth error constant in chat UI`（单 commit，只含上述 6 文件）。

### A8-12 授权修改（Task 12 派发时应用）

Task 12 计划代码中 Composer 调用追加 value 传入：

```tsx
          <Composer
            sending={chat.sending}
            placeholder={chat.inputHint?.placeholder}
            value={chat.inputHint?.value}
            onSend={chat.sendMessage}
            onStop={chat.stop}
          />
```

其余逐字不变。

**驳回不修（已核实理由）：**

- **M-3** i18n key 未注册：Task 13 计划已覆盖组件用到的全部 `chat.*` key（L2327-2352），`authenticationRequired` 由 A7-13 授权兜住，无需提前修复。
- **M-5** onSendAction 无 hook 直连：Task 12 计划 L2289 已有 `onSendAction={(action: string) => chat.sendMessage(action)}` 页面胶水。
- **M-6** 流内 error frame 认证漏判：后端契约下 401/403 仅出现在 fetch 首响应（SSE 建立前的认证中间件），流内 error frame 无认证语义、原文展示属预期；若后端未来变更再单开任务。
- **M-8** retry 时序错位：仅"失败后继续发新消息再回头点旧重试"触达；历史回放消息均为 done 不渲染重试按钮；修复需 startStream 支持插入定位，风险大于收益。
- **M-9** `catch (e: any)`：审查员建议的 `instanceof Error` 方案会破坏浏览器 AbortError（DOMException 非 Error 实例）判定，导致停止按钮失效；且两处为既存代码非本次 diff，维持现状。

### A9 修复提交（随本修正案派发，Task 12/13 质量审查裁决）

Task 12/13 合并代码质量审查（核查 `2e7d8a7d` + `c90b694f` + `0a50bcbd` 合体形态）返回 1 Important + 6 Minor。主 agent 逐条亲自核实后裁决：**批准修复 I-1、M-1、M-2、M-3、M-6**，**驳回 M-4、M-5（理由见下）**。

**批准修复（精确代码，implementer 逐字应用；覆盖 3 个文件）：**

1. **I-1 + M-6 MessageList 滚动策略**（`MessageList.tsx` 中 export default 函数体内从第一条 useEffect 到第二条 useEffect 的整段按以下内容替换，注意新增 `stickRef` 与 `prevLoadingRef`）——原 A8 的"I-1 距离检查"实现由 stickRef 状态替代（语义等价且覆盖单个大 chunk 场景）：

```tsx
export default function MessageList({ messages, loading, onSendAction, onRetry }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [showScrollDown, setShowScrollDown] = useState(false);
  // A9: whether the user is following the bottom (updated on scroll).
  const stickRef = useRef(true);
  // A9: previous loading state, to detect "history finished loading".
  const prevLoadingRef = useRef<boolean | undefined>(undefined);

  const scrollToBottom = (smooth: boolean) => {
    const el = containerRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
  };

  // Track the scroll position: show the scroll-down button only while the
  // user is away from the bottom, and remember whether they follow it.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onScroll = () => {
      const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
      setShowScrollDown(dist > 80);
      stickRef.current = dist < 80;
    };
    onScroll();
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  // New chunks follow the bottom only while the user is already there, so
  // streaming never yanks users who scrolled up to read.
  useEffect(() => {
    if (stickRef.current) scrollToBottom(false);
  }, [messages]);

  // After a conversation finishes loading, always jump to the newest message.
  useEffect(() => {
    if (prevLoadingRef.current && !loading) {
      scrollToBottom(false);
    }
    prevLoadingRef.current = loading;
  }, [loading]);

  return (
    <div style={{ position: 'relative', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
```

（该函数其余部分 JSX 逐字不变。）

2. **M-1 Composer 草稿清空**（`Composer.tsx` 中 A8 加的 useEffect 整体替换）：

```tsx
  // A9: sync backend-pushed input text (ChatInputUpdateComponent.value) and
  // clear the draft when the hint resets (new chat / conversation switch).
  useEffect(() => {
    setDraft(value ?? '');
  }, [value]);
```

3. **M-2 starter effect 函数式更新 + cleanup**（`useChatSession.ts` starter effect 内两处）：
   - `setMessages([...])` 行替换为函数式：

```ts
    setMessages((prev) =>
      prev.length === 0
        ? [{ id: starterId, role: 'assistant', content: '', rich: [], status: 'streaming' }]
        : prev
    );
```

   - starter effect 末尾（`.finally(...)` 链结束之后、依赖数组之前的 `});` 之前）追加 cleanup 行，将 `  }, [conversationId, businessId, messages.length, sending]);` 之前的结构改为在链式调用后多一行：

```ts
    return () => controller.abort();
  }, [conversationId, businessId, messages.length, sending]);
```

4. **M-3 openConversation 最后点击优先**（`useChatSession.ts`）：
   - 在其他 ref 声明旁新增：`const openSeqRef = useRef(0);`
   - `openConversation` 整体替换为：

```ts
  const openConversation = useCallback(
    async (id: string) => {
      stop();
      const seq = ++openSeqRef.current;
      setLoadingConversation(true);
      try {
        const conv = await api.conversation(id);
        if (seq !== openSeqRef.current) return;
        setConversationId(conv.id);
        setMessages(
          conv.messages.map((m) => ({
            id: makeId('msg'),
            role: (m.role === 'user' ? 'user' : 'assistant') as ChatMessage['role'],
            content: m.content,
            rich: mapStoredRich(m.rich),
            status: 'done',
          }))
        );
        setInputHint(null);
      } catch {
        if (seq !== openSeqRef.current) return;
        setMessages([]);
        setConversationId(null);
      } finally {
        if (seq === openSeqRef.current) setLoadingConversation(false);
      }
    },
    [stop]
  );
```

Commit message：`fix(web): scroll to latest on load, clear draft on switch and guard rapid conversation opens`（单 commit，只含 MessageList.tsx、Composer.tsx、useChatSession.ts 3 文件）。

**驳回不修（已核实理由）：**

- **M-4** MessageBubble 未 memo：memo 需同时稳定 `retry`（依赖 [messages] 每 chunk 重建）与 `onSendAction` 回调才有效，属纯优化无正确性问题；当前会话规模下每 chunk 全量重渲染成本可控，不引入半效 memo。
- **M-5** 删除/打开会话失败静默：属网络异常边界，静默回退不破坏状态一致性（refresh 后列表/草稿恢复原状）；统一错误提示体系超出本任务范围。

---

### Task 9: rich 组件渲染器

**Files:**
- Create: `frontends/web/src/pages/Chat/components/renderers/RichRenderer.tsx`
- Create: `frontends/web/src/pages/Chat/components/renderers/MarkdownText.tsx`
- Create: `frontends/web/src/pages/Chat/components/renderers/DataFrameTable.tsx`
- Create: `frontends/web/src/pages/Chat/components/renderers/ChartView.tsx`
- Create: `frontends/web/src/pages/Chat/components/renderers/CardView.tsx`
- Create: `frontends/web/src/pages/Chat/components/renderers/ActionButtons.tsx`
- Create: `frontends/web/src/pages/Chat/components/renderers/StatusCardView.tsx`
- Create: `frontends/web/src/pages/Chat/components/renderers/UnknownComponent.tsx`

- [ ] **Step 1: 创建 `MarkdownText.tsx`**

```tsx
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Button } from 'antd';
import { CheckOutlined, CopyOutlined } from '@ant-design/icons';
import { t } from '../../../../i18n';
import type { RichComponent } from '../../types';

function CodeBlock({ children }: { children?: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  const code = String(children ?? '');

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div style={{ position: 'relative' }}>
      <Button
        size="small"
        icon={copied ? <CheckOutlined /> : <CopyOutlined />}
        onClick={copy}
        style={{ position: 'absolute', top: 8, right: 8, zIndex: 1 }}
      >
        {copied ? t('common', 'chat.copied', '已复制') : t('common', 'chat.copy', '复制')}
      </Button>
      <pre
        style={{
          margin: 0,
          background: '#f6f8fa',
          padding: 12,
          borderRadius: 6,
          overflow: 'auto',
        }}
      >
        <code>{code}</code>
      </pre>
    </div>
  );
}

/** RichTextComponent renderer: markdown via react-markdown + remark-gfm. */
export default function MarkdownText({ component }: { component: RichComponent }) {
  const data = component.data ?? {};
  const content = String(data.content ?? '');

  if (content === '') return null;

  if (!data.markdown) {
    return <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{content}</div>;
  }

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code: ({ children, className }) =>
          className || String(children ?? '').includes('\n') ? (
            <CodeBlock>{children}</CodeBlock>
          ) : (
            <code style={{ background: '#f0f0f0', padding: '2px 5px', borderRadius: 4 }}>
              {children}
            </code>
          ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
```

- [ ] **Step 2: 创建 `DataFrameTable.tsx`**

```tsx
import { Table } from 'antd';
import type { RichComponent } from '../../types';

/** DataFrameComponent renderer: rows live under `data.data` after serialization. */
export default function DataFrameTable({ component }: { component: RichComponent }) {
  const data = component.data ?? {};
  const rows: Record<string, unknown>[] = data.data ?? [];
  const columns: string[] = data.columns ?? Object.keys(rows[0] ?? {});

  return (
    <Table
      size="small"
      bordered={data.bordered !== false}
      pagination={
        data.paginated === false
          ? false
          : { pageSize: data.page_size ?? 25, showSizeChanger: false }
      }
      rowKey={(_record, index) => String(index ?? 0)}
      dataSource={rows}
      columns={columns.map((col) => ({
        title: col,
        dataIndex: col,
        key: col,
        ellipsis: true,
      }))}
      style={{ marginTop: 8 }}
    />
  );
}
```

- [ ] **Step 3: 创建 `ChartView.tsx`**

```tsx
import { useEffect, useRef } from 'react';
import type { RichComponent } from '../../types';

/**
 * ChartComponent renderer. Plotly is loaded lazily to keep it out of the
 * initial bundle. The serialized figure lives under `data.data`
 * (`{ data: traces, layout: {...} }`).
 */
export default function ChartView({ component }: { component: RichComponent }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const data = component.data ?? {};

  useEffect(() => {
    let disposed = false;
    const el = containerRef.current;
    if (!el) return;

    void import('plotly.js-dist-min').then((Plotly) => {
      if (disposed) return;
      const figure = data.data ?? {};
      void Plotly.newPlot(el, figure.data ?? [], figure.layout ?? {}, {
        displayModeBar: false,
        responsive: true,
      });
    });

    return () => {
      disposed = true;
      void import('plotly.js-dist-min').then((Plotly) => {
        Plotly.purge(el);
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(data)]);

  return <div ref={containerRef} style={{ width: '100%', minHeight: 320 }} />;
}
```

- [ ] **Step 4: 创建 `CardView.tsx`**

```tsx
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Button, Card, Space, Typography } from 'antd';
import type { RichComponent } from '../../types';

const { Paragraph } = Typography;

interface CardAction {
  label?: string;
  action?: string;
  variant?: string;
}

/** CardComponent renderer (backend starter card & status cards). */
export default function CardView({
  component,
  onSendAction,
}: {
  component: RichComponent;
  onSendAction?: (action: string) => void;
}) {
  const data = component.data ?? {};
  const actions = (data.actions ?? []) as CardAction[];

  return (
    <Card
      size="small"
      style={{ marginTop: 8 }}
      title={
        <span>
          {data.icon ? `${data.icon} ` : ''}
          {data.title ?? ''}
        </span>
      }
      extra={
        actions.length > 0 && (
          <Space>
            {actions.map((act, i) => (
              <Button
                key={i}
                size="small"
                type={act.variant === 'secondary' ? 'default' : 'primary'}
                onClick={() => {
                  if (act.action) onSendAction?.(act.action);
                }}
              >
                {act.label ?? act.action}
              </Button>
            ))}
          </Space>
        )
      }
    >
      {data.markdown ? (
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{String(data.content ?? '')}</ReactMarkdown>
      ) : (
        <Paragraph style={{ marginBottom: 0 }}>{data.content}</Paragraph>
      )}
    </Card>
  );
}
```

- [ ] **Step 5: 创建 `ActionButtons.tsx`**

```tsx
import { Button, Space } from 'antd';
import type { RichComponent } from '../../types';

function variantToType(variant?: string) {
  if (variant === 'secondary') return 'default';
  if (variant === 'ghost' || variant === 'link') return 'text';
  return 'primary';
}

/** ButtonComponent / ButtonGroupComponent renderer. */
export default function ActionButtons({
  component,
  onSendAction,
}: {
  component: RichComponent;
  onSendAction?: (action: string) => void;
}) {
  const data = component.data ?? {};
  const buttons: Record<string, any>[] =
    component.type === 'button_group'
      ? ((data.buttons ?? []) as Record<string, any>[])
      : [data as Record<string, any>];

  return (
    <Space wrap style={{ marginTop: 8 }}>
      {buttons.map((btn, i) => (
        <Button
          key={i}
          type={variantToType(btn?.variant) as any}
          size={btn?.size === 'large' ? 'large' : 'small'}
          disabled={!!btn?.disabled}
          onClick={() => {
            if (typeof btn?.action === 'string') onSendAction?.(btn.action);
          }}
        >
          {btn?.icon && btn?.icon_position !== 'right' ? `${btn.icon} ` : ''}
          {btn?.label}
          {btn?.icon && btn?.icon_position === 'right' ? ` ${btn.icon}` : ''}
        </Button>
      ))}
    </Space>
  );
}
```

- [ ] **Step 6: 创建 `StatusCardView.tsx`**

```tsx
import { Alert } from 'antd';
import type { RichComponent } from '../../types';

function statusToAlert(status?: string) {
  if (status === 'success' || status === 'completed') return 'success';
  if (status === 'warning') return 'warning';
  if (status === 'error' || status === 'failed') return 'error';
  return 'info';
}

/** StatusCardComponent renderer. */
export default function StatusCardView({ component }: { component: RichComponent }) {
  const data = component.data ?? {};
  return (
    <Alert
      style={{ marginTop: 8 }}
      type={statusToAlert(String(data.status ?? '')) as any}
      message={<span>{data.icon ? `${data.icon} ` : ''}{data.title}</span>}
      description={data.description}
    />
  );
}
```

- [ ] **Step 7: 创建 `UnknownComponent.tsx`**

```tsx
import { Collapse, Typography } from 'antd';
import type { RichComponent } from '../../types';

/** Fallback for unknown component types: collapsible JSON, never a blank screen. */
export default function UnknownComponent({ component }: { component: RichComponent }) {
  return (
    <Collapse
      size="small"
      style={{ marginTop: 8 }}
      items={[
        {
          key: 'json',
          label: (
            <Typography.Text type="secondary">
              {component.type} (unsupported component)
            </Typography.Text>
          ),
          children: (
            <pre
              style={{
                margin: 0,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                maxHeight: 240,
                overflow: 'auto',
              }}
            >
              {JSON.stringify(component.data ?? {}, null, 2)}
            </pre>
          ),
        },
      ]}
    />
  );
}
```

- [ ] **Step 8: 创建 `RichRenderer.tsx`（分发器）**

```tsx
import type { RichComponent } from '../../types';
import MarkdownText from './MarkdownText';
import DataFrameTable from './DataFrameTable';
import ChartView from './ChartView';
import CardView from './CardView';
import ActionButtons from './ActionButtons';
import StatusCardView from './StatusCardView';
import UnknownComponent from './UnknownComponent';

export interface RichRendererProps {
  component: RichComponent;
  onSendAction?: (action: string) => void;
}

/** UI-state-only components: applied live, invisible during history replay. */
const IGNORED_TYPES = new Set([
  'status_bar_update',
  'task_tracker_update',
  'chat_input_update',
]);

export default function RichRenderer({ component, onSendAction }: RichRendererProps) {
  if (component.visible === false) return null;
  if (IGNORED_TYPES.has(component.type)) return null;

  switch (component.type) {
    case 'text':
      return <MarkdownText component={component} />;
    case 'dataframe':
      return <DataFrameTable component={component} />;
    case 'chart':
      return <ChartView component={component} />;
    case 'card':
      return <CardView component={component} onSendAction={onSendAction} />;
    case 'button':
    case 'button_group':
      return <ActionButtons component={component} onSendAction={onSendAction} />;
    case 'status_card':
      return <StatusCardView component={component} />;
    default:
      return <UnknownComponent component={component} />;
  }
}
```

- [ ] **Step 9: Commit**

```powershell
git add frontends/web/src/pages/Chat/components/renderers
git commit -m "feat(web): add rich component renderers for chat history"
```

---

### Task 10: 会话状态 Hook

**Files:**
- Create: `frontends/web/src/pages/Chat/useChatSession.ts`

- [ ] **Step 1: 创建 `frontends/web/src/pages/Chat/useChatSession.ts`**

```ts
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ConversationMeta } from '../../lib/api';
import { streamChat } from '../../lib/sse';
import { ChatMessage, ChatStreamChunk, RichComponent } from './types';

function makeId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function mapStoredRich(rich?: Record<string, any>[]): RichComponent[] {
  return (rich ?? []).map((r) => ({
    id: r.id ?? makeId('rc'),
    type: r.type ?? 'unknown',
    visible: r.visible,
    data: r.data ?? {},
  }));
}

/** Live input updates pushed by the backend (ChatInputUpdateComponent). */
export interface ChatInputHint {
  placeholder?: string;
  value?: string;
}

export interface ChatSession {
  conversationId: string | null;
  messages: ChatMessage[];
  sending: boolean;
  conversations: ConversationMeta[];
  loadingConversation: boolean;
  inputHint: ChatInputHint | null;
  sendMessage: (text: string) => void;
  stop: () => void;
  newConversation: () => void;
  openConversation: (id: string) => void;
  deleteConversation: (id: string) => void;
  refreshConversations: () => void;
  retry: (failedMessageId: string) => void;
}

/**
 * Chat session state: draft conversations (conversationId === null, never
 * persisted), streaming, history loading and per-business listing.
 */
export function useChatSession(businessId: string | undefined): ChatSession {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [conversations, setConversations] = useState<ConversationMeta[]>([]);
  const [inputHint, setInputHint] = useState<ChatInputHint | null>(null);
  const [loadingConversation, setLoadingConversation] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const conversationIdRef = useRef<string | null>(null);
  conversationIdRef.current = conversationId;

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await api.conversations(businessId));
    } catch {
      setConversations([]);
    }
  }, [businessId]);

  useEffect(() => {
    void refreshConversations();
  }, [refreshConversations]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const openConversation = useCallback(
    async (id: string) => {
      stop();
      setLoadingConversation(true);
      try {
        const conv = await api.conversation(id);
        setConversationId(conv.id);
        setMessages(
          conv.messages.map((m) => ({
            id: makeId('msg'),
            role: (m.role === 'user' ? 'user' : 'assistant') as ChatMessage['role'],
            content: m.content,
            rich: mapStoredRich(m.rich),
            status: 'done',
          }))
        );
        setInputHint(null);
      } catch {
        setMessages([]);
        setConversationId(null);
      } finally {
        setLoadingConversation(false);
      }
    },
    [stop]
  );

  const newConversation = useCallback(() => {
    stop();
    setConversationId(null);
    setMessages([]);
    setInputHint(null);
  }, [stop]);

  const deleteConversation = useCallback(
    async (id: string) => {
      try {
        await api.deleteConversation(id);
        if (conversationIdRef.current === id) {
          newConversation();
        }
      } finally {
        void refreshConversations();
      }
    },
    [newConversation, refreshConversations]
  );

  const startStream = useCallback(
    async (text: string, attachUser: boolean) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setSending(true);

      const userMessage: ChatMessage = {
        id: makeId('msg'),
        role: 'user',
        content: text,
        rich: [],
        status: 'done',
      };
      const assistantId = makeId('msg');
      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        rich: [],
        status: 'streaming',
      };
      setMessages((prev) =>
        attachUser ? [...prev, userMessage, assistantMessage] : [...prev, assistantMessage]
      );

      const patchAssistant = (patch: (m: ChatMessage) => ChatMessage) => {
        setMessages((prev) => prev.map((m) => (m.id === assistantId ? patch(m) : m)));
      };

      let boundConversationId = conversationIdRef.current;

      try {
        await streamChat(
          {
            message: text,
            conversation_id: boundConversationId ?? undefined,
            business_id: businessId,
          },
          {
            onChunk: (chunk: ChatStreamChunk) => {
              if (chunk.conversation_id && !boundConversationId) {
                boundConversationId = chunk.conversation_id;
                conversationIdRef.current = chunk.conversation_id;
                setConversationId(chunk.conversation_id);
              }
              const simpleText = (chunk.simple as { text?: unknown } | null)?.text;
              if (typeof simpleText === 'string') {
                patchAssistant((m) => ({ ...m, content: m.content + simpleText }));
              }
              if (chunk.rich) {
                patchAssistant((m) => ({ ...m, rich: [...m.rich, chunk.rich] }));
                if (chunk.rich.type === 'chat_input_update') {
                  const data = chunk.rich.data ?? {};
                  setInputHint({
                    placeholder:
                      typeof data.placeholder === 'string' ? data.placeholder : undefined,
                    value: typeof data.value === 'string' ? data.value : undefined,
                  });
                }
              }
            },
          },
          controller.signal
        );
        patchAssistant((m) => ({ ...m, status: 'done' }));
      } catch (e: any) {
        if (e?.name === 'AbortError') {
          patchAssistant((m) =>
            m.content || m.rich.length > 0
              ? { ...m, status: 'done' }
              : { ...m, status: 'error', errorDetail: 'generation stopped' }
          );
        } else {
          patchAssistant((m) => ({
            ...m,
            status: 'error',
            errorDetail: e?.message ?? 'request failed',
          }));
        }
      } finally {
        setSending(false);
        abortRef.current = null;
        void refreshConversations();
      }
    },
    [businessId, refreshConversations]
  );

  // Starter UI: on a fresh draft (no conversation, no messages), request
  // the backend welcome card. Starter requests never bind a conversation
  // id (the backend does not persist them) and never persist locally.
  useEffect(() => {
    if (conversationId !== null || messages.length > 0 || sending) return;

    const controller = new AbortController();
    abortRef.current = controller;

    const starterId = makeId('msg');
    setMessages([
      { id: starterId, role: 'assistant', content: '', rich: [], status: 'streaming' },
    ]);

    const patchStarter = (patch: (m: ChatMessage) => ChatMessage) => {
      setMessages((prev) => prev.map((m) => (m.id === starterId ? patch(m) : m)));
    };

    void streamChat(
      { message: '', business_id: businessId, metadata: { starter_ui_request: true } },
      {
        onChunk: (chunk: ChatStreamChunk) => {
          if (chunk.rich) {
            patchStarter((m) => ({ ...m, rich: [...m.rich, chunk.rich] }));
          }
        },
      },
      controller.signal
    )
      .then(() => patchStarter((m) => ({ ...m, status: 'done' })))
      .catch((e: any) => {
        if (e?.name === 'AbortError') {
          patchStarter((m) => ({ ...m, status: 'done' }));
        } else {
          patchStarter((m) => ({ ...m, status: 'error', errorDetail: e?.message }));
        }
      })
      .finally(() => {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
      });
  }, [conversationId, businessId, messages.length, sending]);

  const sendMessage = useCallback(
    (text: string) => {
      void startStream(text, true);
    },
    [startStream]
  );

  const retry = useCallback(
    (failedMessageId: string) => {
      const lastUser = [...messages].reverse().find((m) => m.role === 'user');
      if (!lastUser) return;
      setMessages((prev) => prev.filter((m) => m.id !== failedMessageId));
      void startStream(lastUser.content, false);
    },
    [messages, startStream]
  );

  return {
    conversationId,
    messages,
    sending,
    conversations,
    loadingConversation,
    inputHint,
    sendMessage,
    stop,
    newConversation,
    openConversation,
    deleteConversation,
    refreshConversations,
    retry,
  };
}
```

- [ ] **Step 2: Commit**

```powershell
git add frontends/web/src/pages/Chat/useChatSession.ts
git commit -m "feat(web): add chat session state hook with streaming and history"
```

---

### Task 11: 聊天 UI 组件

**Files:**
- Create: `frontends/web/src/pages/Chat/components/ConversationSidebar.tsx`
- Create: `frontends/web/src/pages/Chat/components/MessageList.tsx`
- Create: `frontends/web/src/pages/Chat/components/MessageBubble.tsx`
- Create: `frontends/web/src/pages/Chat/components/Composer.tsx`

- [ ] **Step 1: 创建 `ConversationSidebar.tsx`**

```tsx
import { useMemo, useState } from 'react';
import { Button, Empty, Input, List, Popconfirm, Typography } from 'antd';
import { DeleteOutlined, MessageOutlined, PlusOutlined, SearchOutlined } from '@ant-design/icons';
import { ConversationMeta } from '../../../lib/api';
import { t } from '../../../i18n';

const { Text } = Typography;

function conversationTitle(conv: ConversationMeta): string {
  return (
    conv.metadata?.title ||
    conv.messages?.[0]?.content?.slice(0, 40) ||
    t('common', 'chat.defaultTitle', '新对话')
  );
}

export interface ConversationSidebarProps {
  conversations: ConversationMeta[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export default function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
}: ConversationSidebarProps) {
  const [keyword, setKeyword] = useState('');

  const filtered = useMemo(() => {
    const sorted = [...conversations].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
    const kw = keyword.trim().toLowerCase();
    if (!kw) return sorted;
    return sorted.filter((c) => conversationTitle(c).toLowerCase().includes(kw));
  }, [conversations, keyword]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: 12, gap: 12 }}>
      <Button type="primary" block icon={<PlusOutlined />} onClick={onNew}>
        {t('common', 'chat.newConversation', '新建对话')}
      </Button>
      <Input
        allowClear
        prefix={<SearchOutlined />}
        placeholder={t('common', 'chat.searchPlaceholder', '搜索会话')}
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
      />
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {filtered.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t('common', 'chat.emptyList', '暂无会话')}
          />
        ) : (
          <List
            size="small"
            dataSource={filtered}
            renderItem={(conv) => {
              const active = conv.id === activeId;
              return (
                <List.Item
                  onClick={() => onSelect(conv.id)}
                  style={{
                    cursor: 'pointer',
                    borderRadius: 8,
                    padding: '8px 12px',
                    background: active ? '#e6f4ff' : 'transparent',
                    border: 'none',
                  }}
                  actions={[
                    <Popconfirm
                      key="del"
                      title={t('common', 'chat.deleteConfirm', '确认删除该会话？')}
                      onConfirm={() => onDelete(conv.id)}
                    >
                      <Button
                        type="text"
                        size="small"
                        icon={<DeleteOutlined />}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </Popconfirm>,
                  ]}
                >
                  <List.Item.Meta
                    avatar={<MessageOutlined style={{ fontSize: 16, marginTop: 4 }} />}
                    title={
                      <Text strong={active} ellipsis={{ tooltip: conversationTitle(conv) }}>
                        {conversationTitle(conv)}
                      </Text>
                    }
                  />
                </List.Item>
              );
            }}
          />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 创建 `MessageList.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react';
import { Button, Spin } from 'antd';
import { ArrowDownOutlined } from '@ant-design/icons';
import { t } from '../../../i18n';
import { ChatMessage } from '../types';
import MessageBubble from './MessageBubble';

export interface MessageListProps {
  messages: ChatMessage[];
  loading?: boolean;
  onSendAction?: (action: string) => void;
  onRetry?: (failedMessageId: string) => void;
}

/** Chat message flow with auto-scroll and a "back to bottom" button. */
export default function MessageList({ messages, loading, onSendAction, onRetry }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [showScrollDown, setShowScrollDown] = useState(false);

  const scrollToBottom = (smooth: boolean) => {
    const el = containerRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
  };

  // Show the scroll-down button only while the user is away from the bottom.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onScroll = () => {
      setShowScrollDown(el.scrollHeight - el.scrollTop - el.clientHeight > 80);
    };
    onScroll();
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  // New chunks scroll to bottom instantly (messages grow while streaming).
  useEffect(() => {
    scrollToBottom(false);
  }, [messages]);

  return (
    <div style={{ position: 'relative', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      {loading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 16 }}>
          <Spin />
        </div>
      )}
      <div ref={containerRef} style={{ flex: 1, overflowY: 'auto', padding: '16px 24px' }}>
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} onSendAction={onSendAction} onRetry={onRetry} />
        ))}
      </div>
      {showScrollDown && (
        <Button
          shape="circle"
          icon={<ArrowDownOutlined />}
          title={t('common', 'chat.scrollToBottom', '回到底部')}
          style={{ position: 'absolute', right: 24, bottom: 16 }}
          onClick={() => {
            scrollToBottom(true);
            setShowScrollDown(false);
          }}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 3: 创建 `MessageBubble.tsx`**

```tsx
import { Alert, Avatar, Button, Space, Spin } from 'antd';
import { ReloadOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons';
import { t } from '../../../i18n';
import { ChatMessage, dedupeRich } from '../types';
import RichRenderer from './renderers/RichRenderer';

export interface MessageBubbleProps {
  message: ChatMessage;
  onSendAction?: (action: string) => void;
  onRetry?: (failedMessageId: string) => void;
}

/** Single chat bubble: user right / assistant left with rich content. */
export default function MessageBubble({ message, onSendAction, onRetry }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexDirection: isUser ? 'row-reverse' : 'row' }}>
      <Avatar
        size={32}
        icon={isUser ? <UserOutlined /> : <RobotOutlined />}
        style={{ flexShrink: 0, background: isUser ? '#1677ff' : '#52c41a' }}
      />
      <div style={{ maxWidth: '78%', minWidth: 0 }}>
        {isUser ? (
          <div
            style={{
              background: '#1677ff',
              color: '#fff',
              borderRadius: 12,
              padding: '8px 14px',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              display: 'inline-block',
            }}
          >
            {message.content}
          </div>
        ) : (
          <Space direction="vertical" size={8} style={{ width: '100%', display: 'flex' }}>
            {dedupeRich(message.rich).map((comp, i) => (
              <RichRenderer key={comp.id ?? `${comp.type}_${i}`} component={comp} onSendAction={onSendAction} />
            ))}
            {message.status === 'streaming' && <Spin size="small" />}
            {message.status === 'error' && (
              <Alert
                type="error"
                showIcon
                message={message.content || message.errorDetail || t('common', 'chat.generationFailed', '生成失败')}
                action={
                  onRetry && (
                    <Button size="small" icon={<ReloadOutlined />} onClick={() => onRetry(message.id)}>
                      {t('common', 'chat.retry', '重试')}
                    </Button>
                  )
                }
              />
            )}
          </Space>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 创建 `Composer.tsx`**

```tsx
import { useState } from 'react';
import { Button, Input } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import { t } from '../../../i18n';

export interface ComposerProps {
  sending: boolean;
  placeholder?: string;
  onSend: (text: string) => void;
  onStop: () => void;
}

/** Message input: Enter to send, Shift+Enter for a newline, stop while streaming. */
export default function Composer({ sending, placeholder, onSend, onStop }: ComposerProps) {
  const [value, setValue] = useState('');

  const submit = () => {
    const text = value.trim();
    if (!text || sending) return;
    setValue('');
    onSend(text);
  };

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', padding: '12px 24px', borderTop: '1px solid #f0f0f0' }}>
      <Input.TextArea
        value={value}
        autoSize={{ minRows: 1, maxRows: 6 }}
        placeholder={placeholder ?? t('common', 'chat.inputPlaceholder', '输入问题，Enter 发送，Shift+Enter 换行')}
        style={{ flex: 1, resize: 'none' }}
        onChange={(e) => setValue(e.target.value)}
        onPressEnter={(e) => {
          if (!e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        disabled={sending}
      />
      {sending ? (
        <Button danger onClick={onStop}>
          {t('common', 'chat.stop', '停止')}
        </Button>
      ) : (
        <Button type="primary" icon={<SendOutlined />} disabled={!value.trim()} onClick={submit}>
          {t('common', 'chat.send', '发送')}
        </Button>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Commit**

```powershell
git add frontends/web/src/pages/Chat/components
git commit -m "feat(web): add chat sidebar, message list and composer components"
```

---

### Task 12: 重写 Chat 页面（移除 webcomponent）

**Files:**
- Rewrite: `frontends/web/src/pages/Chat/index.tsx`

- [ ] **Step 1: 用以下完整内容重写 `frontends/web/src/pages/Chat/index.tsx`**

删除 script 动态加载与 `<chatbot-chat>` 创建逻辑（不再使用 `customElements`、`containerRef` 与 `useEffect`），改为组合 Sidebar/MessageList/Composer。沿用原页面的 `calc(100vh - 120px)` 高度约定（页面位于 ProLayout 内部）：

```tsx
import { useState } from 'react';
import { Button, Layout } from 'antd';
import { MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons';
import { useParams } from 'react-router';
import { t } from '../../i18n';
import { useAuth } from '../../lib/auth';
import { useChatSession } from './useChatSession';
import ConversationSidebar from './components/ConversationSidebar';
import MessageList from './components/MessageList';
import Composer from './components/Composer';

const { Sider, Content } = Layout;

function Chat() {
  const { businessId } = useParams();
  const { user } = useAuth();
  const chat = useChatSession(businessId);
  const [collapsed, setCollapsed] = useState(false);

  return (
    <Layout style={{ height: 'calc(100vh - 120px)' }}>
      <Sider
        theme="light"
        width={280}
        collapsedWidth={0}
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        trigger={null}
        style={{ borderRight: '1px solid #f0f0f0' }}
      >
        <ConversationSidebar
          conversations={chat.conversations}
          activeId={chat.conversationId}
          onSelect={(id) => void chat.openConversation(id)}
          onNew={chat.newConversation}
          onDelete={(id) => void chat.deleteConversation(id)}
        />
      </Sider>
      <Layout>
        <Content style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div style={{ padding: '4px 8px', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center' }}>
            <Button
              type="text"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed((v) => !v)}
              title={t('common', 'chat.toggleSidebar', '切换会话列表')}
            />
            <span style={{ marginLeft: 8, color: '#1677ff' }}>{user?.email || ''}</span>
          </div>
          <MessageList
            messages={chat.messages}
            loading={chat.loadingConversation}
            onSendAction={(action: string) => chat.sendMessage(action)}
            onRetry={chat.retry}
          />
          <Composer
            sending={chat.sending}
            placeholder={chat.inputHint?.placeholder}
            onSend={chat.sendMessage}
            onStop={chat.stop}
          />
        </Content>
      </Layout>
    </Layout>
  );
}

export default Chat;
```

- [ ] **Step 2: Commit**

```powershell
git add frontends/web/src/pages/Chat/index.tsx
git commit -m "feat(web): replace chatbot webcomponent with antd chat page"
```

---

### Task 13: i18n chat.* 文案

**Files:**
- Modify: `frontends/web/src/i18n/locales/zh-CN/common.json`
- Modify: `frontends/web/src/i18n/locales/zh-TW/common.json`
- Modify: `frontends/web/src/i18n/locales/en-US/common.json`

说明：现有 `t()` 按**扁平 key** 查找（`container?.[key]`），因此新增 key 必须是扁平形式 `"chat.newConversation"`，不能嵌套对象。

- [ ] **Step 1: 修改 `zh-CN/common.json`**（在 `"backHome"` 行后追加，注意逗号）

```json
{
  "login": "登录",
  "email": "邮箱",
  "business": "业务",
  "selectEmail": "请选择邮箱",
  "selectBusiness": "请选择业务",
  "continue": "继续",
  "loading": "加载中...",
  "pageNotFound": "页面未找到",
  "backHome": "返回首页",
  "chat.newConversation": "新建对话",
  "chat.searchPlaceholder": "搜索会话",
  "chat.emptyList": "暂无会话",
  "chat.defaultTitle": "新对话",
  "chat.deleteConfirm": "确认删除该会话？",
  "chat.scrollToBottom": "回到底部",
  "chat.copied": "已复制",
  "chat.copy": "复制",
  "chat.generationFailed": "生成失败",
  "chat.retry": "重试",
  "chat.inputPlaceholder": "输入问题，Enter 发送，Shift+Enter 换行",
  "chat.send": "发送",
  "chat.stop": "停止",
  "chat.toggleSidebar": "切换会话列表"
}
```

- [ ] **Step 2: 修改 `zh-TW/common.json`**

```json
{
  "login": "登錄",
  "email": "郵箱",
  "business": "業務",
  "selectEmail": "請選擇郵箱",
  "selectBusiness": "請選擇業務",
  "continue": "繼續",
  "loading": "加載中...",
  "pageNotFound": "頁面未找到",
  "backHome": "返回首頁",
  "chat.newConversation": "新建對話",
  "chat.searchPlaceholder": "搜尋會話",
  "chat.emptyList": "暫無會話",
  "chat.defaultTitle": "新對話",
  "chat.deleteConfirm": "確認刪除該會話？",
  "chat.scrollToBottom": "回到底部",
  "chat.copied": "已複製",
  "chat.copy": "複製",
  "chat.generationFailed": "生成失敗",
  "chat.retry": "重試",
  "chat.inputPlaceholder": "輸入問題，Enter 發送，Shift+Enter 換行",
  "chat.send": "發送",
  "chat.stop": "停止",
  "chat.toggleSidebar": "切換會話列表"
}
```

- [ ] **Step 3: 修改 `en-US/common.json`**

```json
{
  "login": "Login",
  "email": "Email",
  "business": "Business",
  "selectEmail": "Select email",
  "selectBusiness": "Select business",
  "continue": "Continue",
  "loading": "Loading...",
  "pageNotFound": "Page Not Found",
  "backHome": "Back Home",
  "chat.newConversation": "New Chat",
  "chat.searchPlaceholder": "Search conversations",
  "chat.emptyList": "No conversations",
  "chat.defaultTitle": "New chat",
  "chat.deleteConfirm": "Delete this conversation?",
  "chat.scrollToBottom": "Back to bottom",
  "chat.copied": "Copied",
  "chat.copy": "Copy",
  "chat.generationFailed": "Generation failed",
  "chat.retry": "Retry",
  "chat.inputPlaceholder": "Ask a question. Enter to send, Shift+Enter for a new line",
  "chat.send": "Send",
  "chat.stop": "Stop",
  "chat.toggleSidebar": "Toggle conversation list"
}
```

- [ ] **Step 4: Commit**

```powershell
git add frontends/web/src/i18n/locales
git commit -m "feat(web): add chat i18n strings (zh-CN/zh-TW/en-US)"
```

---

### Task 14: 收尾验证

**Files:** 无新增（修复问题时的相关文件）

- [ ] **Step 1: 后端全量回归**

Run: `python -m pytest -q`

Expected: PASS — 原有全部测试 + 新增 `tests/test_chat_history.py`、`tests/test_conversation_routes.py` 用例全部通过，无失败。

- [ ] **Step 2: 前端构建验证**

Run:

```powershell
cd frontends/web; npm run build
```

Expected: exit 0 — `tsc -b` 无类型错误、`vite build` 成功产出 dist（tsc 会暴露各组件/hook 间的类型不一致）。

- [ ] **Step 3: 修复构建问题**

若 build 报错：修复涉及的源文件，重复 Step 2 直至 exit 0。修复文件随本任务一起提交。

- [ ] **Step 4: Commit（仅当 Step 3 有改动时）**

```powershell
git add -A
git commit -m "fix(web): resolve build issues from chat refactor"
```

若 Step 2 一次通过则跳过本步。

---

## 覆盖自审（spec → 任务映射）

| spec 章节 | 覆盖任务 |
|---|---|
| C1 rich 历史回放（扩展后端存储） | Task 1（Message.rich 模型）、Task 2（流式收集写回） |
| C2 空会话不落库 | Task 3 |
| C3 首轮后自动标题（LLM ≤6 词 + 兜底截断） | Task 4 |
| C4 会话按业务隔离 | Task 5（agent 标记 + 路由过滤） |
| 依赖引入 | Task 6 |
| SSE 客户端 + 类型 | Task 7、Task 8（api 扩展） |
| rich 组件渲染（完整渲染 + 未知降级） | Task 9 |
| 会话状态（draft 会话/流式/回放/新建/删除/重试/starter UI） | Task 10 |
| 会话侧栏（标题/搜索/删除）/消息流/输入区 | Task 11、Task 12（页面组合，移除 webcomponent） |
| i18n 三语言 | Task 13 |
| 全量验证 | Task 14 |

计划完整覆盖设计文档全部章节；各任务含完整代码、确切命令与预期输出，无占位符；前端类型（`ChatMessage`/`RichComponent`/`ChatStreamChunk`/`ChatSession`/`ConversationMeta`）在 Task 7/8/10/11/12 间保持一致。