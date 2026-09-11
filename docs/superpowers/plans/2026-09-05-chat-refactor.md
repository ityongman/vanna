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