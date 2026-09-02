# 前端应用化改造设计文档

日期：2026-09-02

## 背景与目标

项目已用 sqlite（关系）+ faiss（向量）跑通完整后端链路，前端现状：

- 主对话页（`src/vanna/servers/base/templates.py`）：Tailwind 品牌化宿主页 + `frontends/webcomponent/` 的 Lit 聊天组件
- DDL 导入页（`src/vanna/servers/fastapi/ddl_import.py`）：内嵌字符串的原生 HTML 工具页，与对话页风格不统一
- 无前端路由、无应用外壳，两个页面互相孤立

目标：将两个孤立页面整合为一个完整应用，统一设计语言，新增会话历史与 Schema 管理能力，并按角色区分用户区/管理区：

- **用户区**：对话页 + 会话历史页
- **管理区**：DDL 导入页 + Schema 管理页
- 普通用户仅见用户区；`.env` 配置的管理员账号可同时访问全部 4 个功能

## 调研结论（决策依据）

| 参考项目 | 模式 |
|---|---|
| DB-GPT（19k+ stars） | React + Next.js + Ant Design + Tailwind，独立 `web/` 工程，构建后由 Python 后端托管静态产物 |
| WrenAI（16k+ stars） | Next.js + React + FastAPI，同样前后端分离、静态托管 |
| Vercel AI Chatbot（20.2k stars） | shadcn/ui + Tailwind，ChatGPT 式布局（左侧会话历史 + 主对话区），2026 年 AI 应用事实标准 |
| shadcn/ui 2026-06 聊天组件发布 | MessageScroller / Message / Bubble 等对话原语成为主流标准化方向 |

## 决策记录

| 决策点 | 选择 | 理由 |
|---|---|---|
| 技术路径 | React 19 + Vite + TypeScript + shadcn/ui + Tailwind CSS + React Router | DB-GPT / WrenAI / 主流 AI 应用同款；组件生态成熟，页面复杂度提升后开发效率高 |
| 部署方式 | `npm run build` 产出静态文件，FastAPI `StaticFiles` 托管 | **生产环境只启动一个后端服务**；Vite dev server 仅开发期热更新用，不参与部署 |
| 整体布局 | ChatGPT 式对话主体 + 管理员侧边栏"管理后台"入口 | 用户界面沉浸；管理能力对普通用户完全不可见 |
| 角色区分 | `.env` 配置 `ADMIN_EMAILS`，后端判定角色并下发 `is_admin` | 无需引入完整用户体系，衔接现有 `chatbot_email` cookie + `UserResolver` 机制 |
| 聊天组件复用 | `<chatbot-chat>` Lit Web Component 直接嵌入 React 对话页 | Web Component 原生跨框架兼容，消息渲染/SSE 逻辑零改动 |
| 品牌命名 | 中性占位名（"智能数据问答"），项目重构后统一替换 | 项目正在重构，设计不绑定原始项目名 |

## 架构

### 新增前端工程 `frontends/web/`

```
frontends/web/
├── src/
│   ├── app/
│   │   ├── chat/            # 对话页（所有登录用户）
│   │   ├── admin/           # 管理后台布局
│   │   │   ├── ddl-import/  # DDL 导入（迁移现有两步式流程）
│   │   │   └── schema/      # Schema 管理
│   │   └── login/           # 登录页
│   ├── components/          # shadcn/ui + 业务组件
│   ├── lib/
│   │   ├── api/             # API 客户端（REST + SSE 封装）
│   │   └── auth.tsx         # AuthContext：用户信息 + is_admin + 路由守卫
│   └── main.tsx
├── vite.config.ts           # dev: proxy /api → FastAPI；build: 输出 dist/
└── package.json
```

### 后端修改 `src/vanna/servers/fastapi/`

- `app.py`：挂载 `frontends/web/dist/` 为静态资源（构建产物存在时），SPA fallback 到 `index.html`；根路由 `/` 由静态产物接管（替换 `templates.py` 直出页，`dev_mode` 下仍可指向 Vite dev server）
- 新增 `auth_routes.py`：登录/角色接口
- 新增 `conversation_routes.py`：会话历史 REST（复用 `core/storage/base.py` 的 `list/get/delete_conversations`，目前尚未暴露路由）
- 新增 `schema_routes.py`：Schema 管理数据接口

### 路由与页面

| 路由 | 页面 | 可见角色 |
|---|---|---|
| `/login` | 登录页（邮箱输入/选择） | 所有人 |
| `/` | 对话页：ChatGPT 式布局 + 会话历史侧栏 | 所有登录用户 |
| `/admin/ddl-import` | DDL 导入（parse → ingest 两步式，UI 重做） | 仅管理员 |
| `/admin/schema` | Schema 管理（表清单、向量库状态、删除） | 仅管理员 |

### 新增后端 API

| 方法 | 路由 | 说明 |
|---|---|---|
| GET | `/api/auth/me` | 当前用户信息 + `is_admin`（后端读取 `ADMIN_EMAILS` 判定） |
| GET | `/api/conversations` | 会话列表（按用户过滤，复用现有存储层） |
| GET | `/api/conversations/{id}` | 会话详情（历史消息回放） |
| DELETE | `/api/conversations/{id}` | 删除会话 |
| GET | `/api/schema/tables` | 已导入表清单 + 向量库状态 |
| DELETE | `/api/schema/tables/{table}` | 从向量库移除指定表 DDL |

约定：管理类 API（schema/*、ddl/*）在后端统一校验角色，非管理员返回 403，防止直接调接口越权。现有 chat SSE/WebSocket/Polling 与 DDL parse/ingest 接口完全不动。旧 `/ddl-import` 页面路由在新前端上线后移除（页面功能由 `/admin/ddl-import` 接管，parse/ingest API 保持不变）。

## 数据流

- **登录**：输入邮箱 → 写入 `chatbot_email` cookie（沿用现有机制）→ `GET /api/auth/me` 返回 `{email, is_admin}` → 前端 AuthContext 持有 → 路由守卫拦截无权限访问
- **对话页**：侧栏 `GET /api/conversations` 拉取会话按今天/昨天/7 天前分组；点击历史会话 → `GET /api/conversations/{id}` → 回放到 `<chatbot-chat>`；新消息走现有 SSE 通道（`conversation_id` 由组件管理）
- **DDL 导入**：沿用现有 parse（multipart → parse_id 暂存）→ ingest（消费 parse_id 写入向量库）流程，仅 UI 用 shadcn 重做
- **Schema 管理**：`GET /api/schema/tables` 读取当前 schema 向量库索引 → 表格展示 → 删除操作调用 DELETE 接口

## 错误处理

- API 401 → 统一跳转 `/login`
- 管理 API 403 → 提示无权限并返回对话页
- SSE 断流沿用 `<chatbot-chat>` 组件现有重连逻辑
- DDL parse 失败表：管理页以警告列表展示（沿用现有解析错误隔离行为）
- 前端构建产物不存在时：`app.py` 回退到现有 `templates.py` 直出页，保证后端单独启动仍可用

## 测试策略

- 前端：Vitest 组件测试（AuthContext 角色渲染、路由守卫）+ Playwright 冒烟（登录 → 对话 → 管理员流程）
- 后端：pytest 覆盖新增 REST 路由（角色校验 403、会话 CRUD、schema 表清单/删除）

## 实施顺序建议

1. 前端工程脚手架 + FastAPI 静态托管（跑通"一个服务"部署模式）
2. 登录 + 角色机制（`.env` → `/api/auth/me` → 路由守卫）
3. 对话页（嵌入 `<chatbot-chat>`）+ 会话历史 API 与侧栏
4. DDL 导入页迁移
5. Schema 管理页
