# 前端应用化改造设计文档

日期：2026-09-02（2026-09-03 按多业务路由合并后的代码全面修订）

## 背景与目标

项目已用 sqlite（关系）+ faiss（向量）跑通完整后端链路，且已支持**多业务存储路由**（`config/app.json` 统一配置、按 `business_id` 路由 SqlRunner 与 schema 向量命名空间、无兜底）。前端现状：

- 主对话页（`src/vanna/servers/base/templates.py`）：Tailwind 品牌化宿主页 + `frontends/webcomponent/` 的 Lit 聊天组件；登录表单含 **Business 下拉选择器**（单业务预选、多业务强制显式选择）
- DDL 导入页（`src/vanna/servers/fastapi/ddl_import.py`）：内嵌字符串的原生 HTML 工具页，含目标业务下拉框，与对话页风格不统一
- 无前端路由、无应用外壳，两个页面互相孤立

目标：将两个孤立页面整合为一个完整应用，统一设计语言，新增会话历史与 Schema 管理能力，并按角色区分用户区/管理区：

- **用户区**：对话页 + 会话历史页
- **管理区**：DDL 导入页 + Schema 管理页
- 普通用户仅见用户区；管理员账号（`config/app.json` 配置）可同时访问全部 4 个功能
- 全流程保留多业务维度：登录选业务 → 对话/DDL 导入/Schema 管理均按所选业务路由

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
| 配置来源 | **`config/app.json` 统一配置**（新增 `server.admin_emails` 字段），不再使用 `.env` | 项目已确立"所有配置收敛到单一 JSON"的硬约束（llm/agent/storage/tools 四个顶层 key）；管理员邮箱同样收敛，避免 `.env` 与 app.json 双轨 |
| 角色区分 | app.json `server.admin_emails`（数组），后端判定角色并下发 `is_admin` | 无需引入完整用户体系，衔接现有 `chatbot_email` cookie + `UserResolver` 机制 |
| 业务选择 | 登录页沿用现有交互：单业务预选、多业务强制显式选择（无默认路由）；所选 `business_id` 随 chat/DDL/Schema 请求下发 | 与后端"无兜底业务路由"硬约束一致：缺少/未知 business_id 的请求必须显式报错，绝不静默落到其他业务 |
| 聊天组件复用 | `<chatbot-chat>` Lit Web Component 直接嵌入 React 对话页（透传 `business-id` 属性） | Web Component 原生跨框架兼容，消息渲染/SSE 逻辑零改动 |
| 品牌命名 | 中性占位名（"智能数据问答"），项目重构后统一替换 | 项目正在重构，设计不绑定原始项目名 |

## 架构

### 新增前端工程 `frontends/web/`

```
frontends/web/
├── src/
│   ├── app/
│   │   ├── chat/            # 对话页（所有登录用户）
│   │   ├── admin/           # 管理后台布局
│   │   │   ├── ddl-import/  # DDL 导入（迁移现有两步式流程 + 业务选择）
│   │   │   └── schema/      # Schema 管理（按业务命名空间）
│   │   └── login/           # 登录页（邮箱 + 业务选择）
│   ├── components/          # shadcn/ui + 业务组件
│   ├── lib/
│   │   ├── api/             # API 客户端（REST + SSE 封装）
│   │   └── auth.tsx         # AuthContext：用户信息 + is_admin + businesses + 路由守卫
│   └── main.tsx
├── vite.config.ts           # dev: proxy /api → FastAPI；build: 输出 dist/
└── package.json
```

### 后端修改 `src/vanna/servers/fastapi/`

- `app.py`：挂载 `frontends/web/dist/` 为静态资源（构建产物存在时），SPA fallback 到 `index.html`；根路由 `/` 由静态产物接管（替换 `templates.py` 直出页，`dev_mode` 下仍可指向 Vite dev server）
- 新增 `auth.py`：管理员判定（读 app.json `server.admin_emails`）+ request context/resolve 辅助
- 新增 `auth_routes.py`：登录/角色接口（响应含 `businesses`）
- 新增 `conversation_routes.py`：会话历史 REST（复用 `core/storage/base.py` 的 `list/get/delete_conversations`，目前尚未暴露路由）
- 新增 `schema_routes.py`：Schema 管理数据接口（按 business_id 解析命名空间）

### 配置修改 `src/vanna/servers/cli/server_runner.py`

- `_APP_CONFIG_KEYS` 增加 `server` 顶层 key
- 新增 `server.admin_emails: string[]` 字段的解析与校验，注入 auth 模块

### 路由与页面

| 路由 | 页面 | 可见角色 |
|---|---|---|
| `/login` | 登录页（邮箱输入/选择 + 业务选择） | 所有人 |
| `/` | 对话页：ChatGPT 式布局 + 会话历史侧栏 | 所有登录用户 |
| `/admin/ddl-import` | DDL 导入（parse → ingest 两步式，UI 重做，含目标业务选择） | 仅管理员 |
| `/admin/schema` | Schema 管理（业务切换、表清单、向量库状态、删除） | 仅管理员 |

### 新增后端 API

| 方法 | 路由 | 说明 |
|---|---|---|
| GET | `/api/auth/me` | 当前用户信息 + `is_admin`（读 app.json `server.admin_emails` 判定）+ `businesses`（启用的业务 ID 列表，来自 `agent.config.businesses`） |
| GET | `/api/conversations` | 会话列表（按用户过滤，复用现有存储层） |
| GET | `/api/conversations/{id}` | 会话详情（历史消息回放） |
| DELETE | `/api/conversations/{id}` | 删除会话 |
| GET | `/api/schema/tables?business_id=xxx` | 指定业务的已导入表清单 + 向量库状态 |
| DELETE | `/api/schema/tables/{table}?business_id=xxx` | 从指定业务的向量命名空间移除指定表 DDL |

约定：

- **管理类 API（schema/*、ddl/*）在后端统一校验角色**，非管理员返回 403，防止直接调接口越权
- **schema 系 API 的 `business_id` 为必填**：后端复用 `ddl_import.py` 中 `_resolve_business_namespace` 的同款逻辑，从 `agent.config.businesses` 解析 `effective_database_name()` 作为向量命名空间；未知/禁用的 business_id 返回 400（无兜底路由，与 DDL ingest 行为一致）
- 现有 chat SSE/WebSocket/Polling 与 DDL parse/ingest 接口完全不动（DDL ingest 已要求 `business_id`）
- 旧 `/ddl-import` 页面路由在新前端上线后移除（页面功能由 `/admin/ddl-import` 接管，parse/ingest API 保持不变）

## 数据流

- **登录**：输入邮箱 + 选择业务（多业务时强制选择）→ 写入 `chatbot_email` cookie + 前端状态持有 `business_id` → `GET /api/auth/me` 返回 `{email, is_admin, businesses}` → AuthContext 持有 → 路由守卫拦截无权限访问
- **对话页**：侧栏 `GET /api/conversations` 拉取会话；点击历史会话 → `GET /api/conversations/{id}` → 回放到 `<chatbot-chat>`；新消息走现有 SSE 通道并携带 `business_id`（`conversation_id` 由组件管理），后端将 `business_id` 合入请求 metadata 完成路由
- **DDL 导入**：沿用现有 parse（multipart → parse_id 暂存）→ ingest（`{parse_id, business_id}`，业务下拉必选）流程，仅 UI 用 shadcn 重做；namespace 由后端从业务配置解析
- **Schema 管理**：业务切换器选择 `business_id` → `GET /api/schema/tables?business_id=xxx` 读取该业务的 schema 向量库索引 → 表格展示 → 删除操作调用 DELETE 接口（携带 `business_id`）

## 错误处理

- API 401 → 统一跳转 `/login`
- 管理 API 403 → 提示无权限并返回对话页
- `business_id` 缺失/未知 → 后端 400（明确列出可用业务），前端在业务选择器处提示
- SSE 断流沿用 `<chatbot-chat>` 组件现有重连逻辑
- DDL parse 失败表：管理页以警告列表展示（沿用现有解析错误隔离行为）
- 前端构建产物不存在时：`app.py` 回退到现有 `templates.py` 直出页，保证后端单独启动仍可用

## 测试策略

- 前端：Vitest 组件测试（AuthContext 角色渲染、路由守卫、业务选择器）+ Playwright 冒烟（登录选业务 → 对话 → 管理员流程）
- 后端：pytest 覆盖新增 REST 路由（角色校验 403、会话 CRUD、schema 表清单/删除的 business_id 校验 400/正常路由）

## 实施顺序建议

1. 前端工程脚手架 + FastAPI 静态托管（跑通"一个服务"部署模式）
2. app.json `server.admin_emails` 配置解析 + 登录角色机制（`/api/auth/me` → 路由守卫）
3. 对话页（嵌入 `<chatbot-chat>`，透传 business-id）+ 会话历史 API 与侧栏
4. DDL 导入页迁移（含目标业务选择）
5. Schema 管理页（按业务命名空间）
