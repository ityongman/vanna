# 聊天界面重构设计与实现方案

> 日期：2026-09-05（2026-09-07 更新：侧边栏布局对齐 ChatGPT 布局规范）
> 需求来源：`.trae/requirements/require_desc02.md`

## 1. 背景与目标

当前 `frontends/web` 聊天页（`src/pages/Chat/index.tsx`）通过动态注入 `<chatbot-chat>` 自定义元素复用 `frontends/webcomponent` 的聊天 UI。webcomponent 有独立设计 token（渐变紫色头部、悬浮窗口控件），与 web 页面的 Ant Design 风格不一致。

目标：去掉 webcomponent 痕迹，用 antd 技术栈在 `frontends/web` 内原生重构聊天功能，具备主流聊天产品的核心能力：历史记录、查看之前对话、选择不同对话继续、新建对话且对话间互不干扰。

约束：

- `frontends/webcomponent` 代码**零修改**（仅作对照，偶尔仍可用于测试）
- 前后端交互协议（POST + SSE、rich chunk 协议、会话 REST）保持不变，后端只做受控扩展

## 2. 关键决策与假设

| 事项 | 决策 | 理由 |
|---|---|---|
| 目录名 | 实际为 `frontends/`（复数），需求中的 `frontend/web` 按 `frontends/web` 处理 | 与代码库实际一致 |
| 实现方式 | antd 自研，交互模式以 GitHub 开源项目 chatbot-ui（mckaywrigley/chatbot-ui）功能清单为基准 | 移植该仓库（Next.js+Tailwind）改造量超过重写；第三方聊天组件库（assistant-ui 等）与 antd 冲突，违背"只保留 web 页面风格" |
| rich 组件历史回放 | 扩展后端存储：rich 组件随消息落库，回放时恢复渲染 | 仅文本回放会丢失图表/表格，不能满足"闭环" |
| 渲染范围 | 完整渲染：markdown 文本、DataFrame 表格、plotly 图表、状态卡、按钮组 | 与 webcomponent 能力对齐（需引入 react-markdown、plotly.js-dist-min） |
| 会话与业务 | 会话按 business_id 隔离：列表接口支持 business_id 过滤，前端按当前业务请求 | 业务间互不干扰 |
| 空会话落库 | 只有产生真实聊天内容才创建/保存会话记录 | 用户指出的现状问题：打开会话即产生空记录 |
| 会话标题 | 不支持手动重命名；后端在首轮对话结束后自动生成标题（LLM 生成 ≤6 词，失败回退截取用户首条消息前 60 字） | ChatGPT/LibreChat/DeerFlow 等主流方式 |
| 欢迎卡片 | 沿用后端 starter UI：新会话向 SSE 发空消息（`metadata.starter_ui_request=true`）渲染后端下发的卡片/按钮 | 各业务欢迎内容由后端定制，与 webcomponent 行为一致 |
| 停止生成 | 前端 AbortController 中断 fetch 流，已接收内容保留 | 主流交互 |
| 传输方式 | 仅用 SSE（POST + fetch ReadableStream）；不实现 WS/轮询前端切换 | 需求允许保持现有交互方式；SSE 为唯一必需路径 |
| 页面布局 | ChatGPT 式单侧边栏：AppLayout 移除 ProLayout 菜单 Sider，会话侧边栏折叠后保留 64px 图标栏（新聊天/搜索/最近聊天） | 消除双层 Sider 嵌套与"两个隐藏侧边栏"的语义混乱；与主流聊天产品交互一致 |

## 3. 前端改动（frontends/web）

### 3.1 页面结构

整体采用 ChatGPT 式单侧边栏布局：ProLayout（AppLayout）仅保留顶部 header（语言切换、用户菜单，`menuRender={false}` 移除菜单侧边栏），页面左侧为会话侧边栏（antd Sider，width=280 / collapsedWidth=64），右侧为消息区。

**侧边栏展开态（width=280）**

```
┌──────────────────────┬──────────────────────────────┐
│ Vanna    [搜索][折叠] │ 消息区（欢迎卡片/消息流）        │
│ ✏ 新聊天              │ · 用户/AI 气泡、流式打字         │
│ 最近                  │ · rich 组件（表格/图表/卡片）    │
│  · 会话1 (选中高亮)    │ · 自动滚动 + 回到底部按钮        │
│  · 会话2              ├──────────────────────────────┤
│  · ... (按时间倒序)    │ 输入区（textarea + 发送/停止）   │
└──────────────────────┴──────────────────────────────┘
```

- 顶部一行：左侧「Vanna」标题；右侧 `[搜索图标][关闭侧边栏图标]`（搜索在关闭按钮左侧，与 ChatGPT 一致）
- 搜索：默认只显示图标，点击后在标题行下方展开搜索输入框并聚焦；Esc 或关闭时清空过滤
- 「新聊天」入口：图标 + 文字的列表行形式（FormOutlined 编辑图标）
- 「最近」分组：灰色小字分组标题 + 历史会话列表（按 updated_at 倒序、选中高亮、悬停删除）

**侧边栏折叠态（collapsedWidth=64，保留窄图标栏）**

```
┌────┬──────────────────────────────────┐
│ ✏  │ 消息区（同上）                      │
│ 🔍 │                                  │
│ ⏰ │                                  │
└────┴──────────────────────────────────┘
```

- 3 个图标按钮（带右侧 Tooltip）：新聊天（FormOutlined）、搜索（SearchOutlined，点击展开侧边栏并直接打开搜索框）、最近聊天（HistoryOutlined，点击展开侧边栏）
- 图标栏顶部为「打开侧边栏」按钮（MenuUnfoldOutlined），与展开态关闭按钮位置上下对应

文件规划（`frontends/web/src/pages/Chat/` 下重组）：

- `index.tsx`：ChatPage，组合侧栏/消息区/输入区，负责会话路由参数与数据加载；管理侧边栏 collapsed 状态
- `layouts/AppLayout.tsx`：自绘顶栏（48px，右侧语言切换 + UserMenu 头像下拉），不使用 ProLayout；UserMenu 下拉包含退出登录及管理员入口（DDL 导入、Schema 查看）；非聊天页（ddl-import/schema 等）顶栏额外显示「返回聊天」按钮，点击回到 `/:businessId/chat`
- `components/ConversationSidebar.tsx`：ChatGPT 式会话侧边栏（展开/折叠双态、搜索、新聊天入口、最近分组、删除 Popconfirm、按更新时间倒序）
- `components/MessageList.tsx` / `MessageBubble.tsx`：消息流与气泡（用户右/AI 左、流式追加、错误重试展示）
- `components/Composer.tsx`：输入区（多行自适应、发送/停止按钮、发送中禁用防重复）
- `components/renderers/`：rich 组件渲染器（见 3.4）
- `useChatSession.ts`：会话状态 hook（draft 会话、消息列表、流式状态、会话切换）
- `types.ts`：ChatMessage、RichComponent 等类型（与后端 chunk 协议对齐）
- `src/lib/sse.ts`：SSE 客户端（对外提供 `streamChat(request, handlers, signal)`）
- `src/lib/api.ts`：`conversations()` 支持传 `business_id`；`ConversationMeta` 增加 `title` 字段；会话详情消息类型增加 `rich`

删除 `src/pages/Chat/index.tsx` 现有的 `<chatbot-chat>` 注入逻辑与 `/static/chatbot-components.js` 动态脚本加载。

### 3.2 状态与数据模型

```ts
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;            // simple 文本累积结果
  rich: RichComponent[];      // 流式过程中收集的组件（后端协议 rich 字段）
  status: 'streaming' | 'done' | 'error';
}

// 新建对话：本地 draft，无 conversation_id，不落库
interface DraftSession {
  conversationId: null;
  title: '新对话';
  messages: ChatMessage[];
}
```

状态管理：React 内置 hooks + Context，不引入新状态库。

### 3.3 SSE 客户端（`src/lib/sse.ts`）

复刻 webcomponent `api-client.ts` 的 `streamChat()` 逻辑，适配 React：

- `fetch(POST /api/vanna/v2/chat_sse)`，请求体 `{message, conversation_id?, user_id?, request_id?, business_id?, metadata?}`
- 读取 `response.body`（ReadableStream），按 `data: ` 行解析 JSON chunk，`[DONE]` 结束
- chunk 结构 `{rich, simple, conversation_id, request_id, timestamp}`：`simple` 追加到当前 assistant 消息文本；`rich` 追加到 rich 组件数组
- 首个 chunk 返回的 `conversation_id` 用于绑定 draft 会话（首次发送即创建后端会话）
- 支持 `AbortController` 中断；错误 chunk（`{"type":"error",...}`）进入消息错误态
- 同源 fetch 天然携带 `chatbot_email` cookie，维持现有用户解析

### 3.4 Rich 组件渲染器

| 后端组件 | React 实现 |
|---|---|
| RichTextComponent | `react-markdown` + `remark-gfm`；代码块带复制按钮 |
| DataFrameComponent | antd Table（分页走 antd） |
| ChartComponent | `plotly.js-dist-min` 自研封装（`Plotly.newPlot`，`React.lazy` 拆包按需加载） |
| CardComponent / ButtonComponent / ButtonGroupComponent | antd Card / Button / Button.Group，按钮点击发送其 action 内容 |
| StatusCardComponent / StatusBarUpdateComponent | antd Alert / Progress |
| TaskTrackerUpdateComponent | antd 步骤/进度列表 |
| ChatInputUpdateComponent | 更新输入框占位/内容 |

未知组件类型容错：降级为折叠的 JSON 展示，保证协议扩展时不白屏。

### 3.5 会话生命周期

1. **新建**：点击「新聊天」（展开态入口行 / 折叠态图标）创建本地 draft 会话（不请求后端、不产生记录），回到初始聊天页；新 draft 挂载时发空消息请求 starter UI，渲染欢迎卡片与快捷按钮（starter 请求本身不落库，后端见 4.2）
2. **首次真实消息**：带 `business_id`、无 `conversation_id` 发送；由 SSE 首个 chunk 的 conversation_id 绑定，此后会话出现在列表顶部
3. **切换/继续**：点击会话 → `GET /api/conversations/{id}` → 恢复文本与 rich 组件到本地消息模型；之后再发送消息带上该 `conversation_id`
4. **删除**：DELETE 接口 + Popconfirm；删除当前会话后回到新的 draft
5. **列表刷新**：发送完成后刷新会话列表（标题/更新时间变化，保持按 updated_at 倒序）

### 3.6 其他交互细节

- 自动滚动到底；用户上翻时显示"回到底部"悬浮按钮
- 流式期间发送按钮变为停止按钮
- AI 消息流式失败显示错误 + 重试入口
- 侧边栏折叠/展开：展开态点关闭侧边栏图标折叠为 64px 窄图标栏；折叠态点任一图标（新聊天除外）展开侧边栏；折叠态点搜索图标会展开侧边栏并自动打开/聚焦搜索框
- 搜索为前端本地过滤（标题/首条消息包含关键字），Esc 关闭并清空
- 会话列表标题来自后端 `title` 字段；缺失显示默认文案（首条消息截断或"新聊天"）
- 新 UI 文案走现有 i18n（zh-CN/zh-TW/en-US）
- 删除现有 `pages/Chat` 中对 webcomponent 的 3 处引用及相关样式

### 3.7 新增依赖

`react-markdown`、`remark-gfm`、`plotly.js-dist-min`（图表渲染器 `React.lazy` 拆包，控制首屏体积）。

## 4. 后端改动

交互协议不变，4 处受控扩展（C1~C4），全部向后兼容 webcomponent。

### 4.1 C1：rich 组件落库

- `src/vanna/core/storage/models.py`：`Message` 增加 `rich: list[dict] = []` 字段（组件 JSON 序列化，默认空，旧数据反序列化兼容）
- `src/vanna/core/agent/agent.py`：流式生成过程中收集每个 chunk 的 `rich` 组件，assistant 消息落库时写入 `Message.rich`
- `GET /api/conversations/{id}` 返回消息时携带 `rich`；旧会话无 rich = 仅文本，前端正常显示
- sqlite_conversation_store 整体 JSON 序列化，自动兼容新字段

### 4.2 C2：空会话不落库

- agent 的 starter 分支（空 message 或 `starter_ui_request=true`）不触发 conversation 创建/保存
- 首次真实消息才创建会话并写入；对 webcomponent 同样生效（顺带修复其空记录问题）

### 4.3 C3：会话标题自动生成

- 触发时机：首轮对话结束（该会话第一条 assistant 回复流结束）后自动生成一次，写入 `conversation.metadata['title']`
- 生成策略（主流双策略）：
  1. LLM 生成：用业务 LLM 配置发起一次小请求，prompt 要求 ≤6 词、只返回标题（参照 DeerFlow：`Generate a concise title (max 6 words) ... Return ONLY the title`）
  2. 兜底：LLM 未配置/调用失败 → 截取首条用户消息前 60 字符作为标题
- `GET /api/conversations` 列表项返回 `title`（缺省时前端显示兜底文案）

### 4.4 C4：会话按业务隔离

- 会话保存时确保 `conversation.metadata['business_id']` 写入业务 ID
- `GET /api/conversations` 支持 `business_id` 查询参数：按 metadata.business_id 过滤（数据量小，Python 侧过滤即可，后续可按需加索引列）
- 未传 `business_id` 时保持现状（全量按 user 过滤），兼容 webcomponent

## 5. 兼容性与数据迁移

- 全部改动为增量字段/可选参数，不破坏 webcomponent 现有调用（其忽略未知字段）
- 旧会话：无 `rich` 仅文本回放；无 `title` 前端显示默认文案；无 `business_id` 不出现在任何业务过滤结果中（全量模式可见）
- 无数据库 schema 迁移需求（data 列整体 JSON）

## 6. 测试策略

- 后端 pytest：C1（rich 随消息存取与回读）、C2（starter/空消息不创建会话）、C3（标题生成 + 兜底截断、缺 LLM 场景）、C4（business_id 过滤、无参全量兼容）
- 前端：typecheck + 构建通过；与后端联调验证 SSE 流式、starter UI、历史回放（含 rich）、双业务隔离、停止生成

## 7. 非目标（明确不做）

- 会话手动重命名
- WS/轮询的前端切换能力
- 会话导入/导出、文件夹、会话搜索后端化（chatbot-ui 高级功能，不在需求内）
- webcomponent 的任何修改
- 后端消息级分页/lazy 加载历史

## 8. 调研参考（GitHub 主流方案结论）

- [chatbot-ui（mckaywrigley）](https://github.com/mckaywrigley/chatbot-ui)：ChatGPT 式功能清单基准（可折叠侧栏、新建、命名、GFM markdown、停止生成、搜索会话）
- [LibreChat](https://github.com/danny-avila/LibreChat)：体量大，仅参考其标题生成（首条回复后生成、失败兜底）思路
- [assistant-ui](https://github.com/assistant-ui/assistant-ui) / [Vercel AI SDK](https://github.com/vercel/ai)：Tailwind 生态，仅参考消息流交互模式，不引入
- [shadcn/ui 对话组件](https://www.infoq.cn/article/TKOvaxoX6xF5yWHJ7dYg)：MessageScroller 等无头组件理念可借鉴（滚动锚定/流式适配），UI 层不适用
- [DeerFlow 标题生成](https://blog.csdn.net/gitblog_00370/article/details/160165470)：LLM ≤6 词 + 本地 fallback 双策略的参照实现