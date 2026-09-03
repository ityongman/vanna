# 前端应用化改造实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有两个孤立页面（主对话页 + DDL 导入页）整合为单一 React 应用，统一设计语言，新增会话历史与 Schema 管理，并按角色区分用户区/管理区；全流程保留多业务路由维度（登录选业务 → 对话/DDL/Schema 按 `business_id` 路由）。

**Architecture:** 新增 `frontends/web/`（React 19 + Vite + shadcn/ui + Tailwind），构建为纯静态文件由 FastAPI `StaticFiles` 托管（生产环境仅一个后端进程）。后端新增三条路由模块（auth / conversations / schema），管理员邮箱从 `config/app.json` 的 `server.admin_emails` 读取（不再使用 `.env`），并为 `SchemaVectorStore` 增加 `list_tables` / `remove_table` 两个可选能力。schema 系 API 必填 `business_id`，命名空间从 `agent.config.businesses` 解析（无兜底，与 DDL ingest 行为一致）。现有 chat SSE/WebSocket/Polling 与 DDL parse/ingest 接口不动（DDL ingest 已要求 `business_id`）。

**Tech Stack:** React 19、Vite、TypeScript、shadcn/ui、Tailwind CSS、React Router、FastAPI、SQLite、FAISS、pytest（asyncio）、TestClient。

**Spec:** `docs/superpowers/specs/2026-09-02-frontend-app-shell-design.md`

---

## 文件结构

**后端（修改/新增）**
- 新增 `src/vanna/core/user/cookie_email_resolver.py` — `CookieEmailUserResolver`（读 chat cookie）
- 修改 `src/vanna/core/user/__init__.py` — 导出 `CookieEmailUserResolver`（修复坏 import）
- 新增 `src/vanna/servers/fastapi/auth.py` — 管理员判定（app.json `server.admin_emails`）+ request context/resolve 辅助
- 新增 `src/vanna/servers/fastapi/auth_routes.py` — `/api/auth/me`（含 `businesses`）
- 新增 `src/vanna/servers/fastapi/conversation_routes.py` — 会话 REST
- 新增 `src/vanna/servers/fastapi/schema_routes.py` — Schema 管理 REST（按 business_id 解析命名空间）
- 修改 `src/vanna/servers/fastapi/app.py` — 注册新路由 + SPA 静态托管
- 修改 `src/vanna/servers/cli/server_runner.py` — 装配 `CookieEmailUserResolver`；解析 `server.admin_emails` 并注入 server_config
- 修改 `src/vanna/capabilities/schema_vector_store/base.py` — 增加 `list_tables` / `remove_table` 可选方法
- 修改 `src/vanna/integrations/vector/faiss/schema_vector_store.py` — 实现两个新方法
- 新增 `tests/test_cookie_email_resolver.py`、`tests/test_auth_routes.py`、`tests/test_conversation_routes.py`、`tests/test_schema_routes.py`

**前端（新增 `frontends/web/`）**
- `package.json`、`vite.config.ts`、`tsconfig.json`、`index.html`（脚手架生成）
- `src/main.tsx`、`src/App.tsx`（路由）、`src/index.css`（Tailwind + token）
- `src/lib/api.ts`、`src/lib/auth.tsx`（AuthContext + 守卫 + 业务选择状态）
- `src/app/chat/ChatPage.tsx`、`src/app/chat/ConversationSidebar.tsx`
- `src/app/login/LoginPage.tsx`（邮箱 + 业务选择）
- `src/app/admin/AdminLayout.tsx`、`src/app/admin/DdlImportPage.tsx`（含目标业务选择）、`src/app/admin/SchemaPage.tsx`（业务切换器）

---

## Phase 1 — 后端：认证与角色

### Task 1: `CookieEmailUserResolver`

**Files:**
- Create: `src/vanna/core/user/cookie_email_resolver.py`
- Modify: `src/vanna/core/user/__init__.py`
- Test: `tests/test_cookie_email_resolver.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_cookie_email_resolver.py`：

```python
from vanna.core.user import CookieEmailUserResolver
from vanna.core.user.request_context import RequestContext


def make_context(cookies=None):
    return RequestContext(cookies=cookies or {}, headers={}, query_params={})


async def test_resolves_email_from_cookie():
    resolver = CookieEmailUserResolver(cookie_name="chatbot_email")
    user = await resolver.resolve_user(
        make_context({"chatbot_email": "admin@corp.com"})
    )
    assert user.email == "admin@corp.com"
    assert user.id == "admin@corp.com"


async def test_anonymous_when_cookie_missing():
    resolver = CookieEmailUserResolver(cookie_name="chatbot_email")
    user = await resolver.resolve_user(make_context({}))
    assert user.email is None
    assert user.id == "anonymous"


async def test_uses_custom_cookie_name():
    resolver = CookieEmailUserResolver(cookie_name="vanna_email")
    user = await resolver.resolve_user(make_context({"vanna_email": "u@x.com"}))
    assert user.email == "u@x.com"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_cookie_email_resolver.py -v`
Expected: FAIL — `ImportError: cannot import name 'CookieEmailUserResolver'`

- [ ] **Step 3: 实现 resolver**

创建 `src/vanna/core/user/cookie_email_resolver.py`：

```python
"""Cookie-based email user resolver for the built-in web UI."""

from typing import Optional

from .models import User
from .request_context import RequestContext
from .resolver import UserResolver


class CookieEmailUserResolver(UserResolver):
    """Resolves a user from an email stored in a request cookie.

    Used by the built-in FastAPI web UI: the login page writes the chosen
    email into a cookie, and this resolver turns it into a ``User``. When
    the cookie is absent an anonymous ``User`` is returned (email=None).
    """

    def __init__(self, cookie_name: str = "chatbot_email"):
        self.cookie_name = cookie_name

    async def resolve_user(self, request_context: RequestContext) -> User:
        email = request_context.get_cookie(self.cookie_name)
        email = (email or "").strip() or None
        if email is None:
            return User(id="anonymous", username="anonymous", email=None)
        return User(id=email, username=email.split("@")[0], email=email)
```

修改 `src/vanna/core/user/__init__.py`，在现有导出中追加：

```python
from .cookie_email_resolver import CookieEmailUserResolver

__all__ = [
    "UserService",
    "User",
    "UserResolver",
    "RequestContext",
    "CookieEmailUserResolver",
]
```

（若现有 `__all__` 内容不同，按实际文件合并，保留原有导出项。）

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_cookie_email_resolver.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add src/vanna/core/user/cookie_email_resolver.py src/vanna/core/user/__init__.py tests/test_cookie_email_resolver.py
git commit -m "feat: add CookieEmailUserResolver for built-in web UI auth"
```

---

### Task 2: 认证辅助模块 + `/api/auth/me`

> 管理员邮箱来自 `config/app.json` 的 `server.admin_emails`（数组），由 server_runner 解析后经 server_config 注入；**不读环境变量**。响应同时返回启用的 `businesses`（来自 `agent.config.businesses`），供登录页渲染业务选择器。

**Files:**
- Create: `src/vanna/servers/fastapi/auth.py`
- Create: `src/vanna/servers/fastapi/auth_routes.py`
- Test: `tests/test_auth_routes.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_auth_routes.py`：

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vanna.core.user import CookieEmailUserResolver
from vanna.servers.fastapi.auth_routes import register_auth_routes


class FakeAgent:
    def __init__(self, resolver=None, businesses=None):
        self.user_resolver = resolver or CookieEmailUserResolver()
        self.config = type("C", (), {"businesses": businesses or {}})()


def make_client(admin_emails=("admin@corp.com",), businesses=None):
    app = FastAPI()
    register_auth_routes(
        app, FakeAgent(businesses=businesses), admin_emails=list(admin_emails)
    )
    return TestClient(app)


def test_auth_me_returns_admin_for_whitelisted_email():
    client = make_client(admin_emails=["admin@corp.com"])
    client.cookies.set("chatbot_email", "admin@corp.com")
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "admin@corp.com"
    assert body["is_admin"] is True


def test_auth_me_returns_non_admin_for_other_email():
    client = make_client(admin_emails=["admin@corp.com"])
    client.cookies.set("chatbot_email", "user@corp.com")
    body = client.get("/api/auth/me").json()
    assert body["is_admin"] is False


def test_auth_me_anonymous_when_no_cookie():
    client = make_client(admin_emails=["admin@corp.com"])
    body = client.get("/api/auth/me").json()
    assert body["email"] is None
    assert body["is_admin"] is False


def test_auth_me_exposes_enabled_businesses():
    client = make_client(businesses={"biz_a": object(), "biz_b": object()})
    body = client.get("/api/auth/me").json()
    assert sorted(body["businesses"]) == ["biz_a", "biz_b"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_auth_routes.py -v`
Expected: FAIL — `ModuleNotFoundError: ... auth_routes`

- [ ] **Step 3: 实现 auth.py**

创建 `src/vanna/servers/fastapi/auth.py`：

```python
"""Auth helpers shared by the built-in FastAPI web UI routes."""

from typing import List, Optional

from fastapi import Request

from vanna.core.user import RequestContext, User


def is_admin_email(email: Optional[str], admin_emails: List[str]) -> bool:
    """Check an email against the app.json ``server.admin_emails`` list."""
    return bool(email and email in admin_emails)


def build_request_context(http_request: Request) -> RequestContext:
    return RequestContext(
        cookies=dict(http_request.cookies),
        headers=dict(http_request.headers),
        remote_addr=http_request.client.host if http_request.client else None,
        query_params=dict(http_request.query_params),
    )


async def resolve_user(agent, http_request: Request) -> User:
    return await agent.user_resolver.resolve_user(build_request_context(http_request))
```

- [ ] **Step 4: 实现 auth_routes.py**

创建 `src/vanna/servers/fastapi/auth_routes.py`：

```python
"""FastAPI routes for the built-in web UI authentication."""

from typing import List

from fastapi import FastAPI, Request

from .auth import is_admin_email, resolve_user


def register_auth_routes(
    app: FastAPI, agent, admin_emails: List[str] | None = None
) -> None:
    admin_emails = admin_emails or []

    @app.get("/api/auth/me")
    async def auth_me(http_request: Request):
        user = await resolve_user(agent, http_request)
        businesses = list(getattr(agent.config, "businesses", {}) or {})
        return {
            "id": user.id,
            "email": user.email,
            "is_admin": is_admin_email(user.email, admin_emails),
            "businesses": businesses,
        }
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_auth_routes.py -v`
Expected: 4 passed

- [ ] **Step 6: 提交**

```bash
git add src/vanna/servers/fastapi/auth.py src/vanna/servers/fastapi/auth_routes.py tests/test_auth_routes.py
git commit -m "feat: add /api/auth/me endpoint with app.json admin_emails role check"
```

---

### Task 3: 会话 REST 路由

> 会话列表按用户过滤（现状）；`business_id` 已随 chat 请求存入会话 metadata，前端可据此时过滤/打标，本任务不改存储层。

**Files:**
- Create: `src/vanna/servers/fastapi/conversation_routes.py`
- Test: `tests/test_conversation_routes.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_conversation_routes.py`：

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vanna.core.storage.base import ConversationStore
from vanna.core.storage.models import Conversation, Message
from vanna.core.user import CookieEmailUserResolver, User
from vanna.servers.fastapi.conversation_routes import register_conversation_routes


class FakeStore(ConversationStore):
    def __init__(self):
        self._convs = {}

    async def create_conversation(self, conversation_id, user, initial_message):
        conv = Conversation(id=conversation_id, user=user,
                            messages=[Message(role="user", content=initial_message)])
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
        return convs[offset:offset + limit]


class FakeAgent:
    def __init__(self):
        self.user_resolver = CookieEmailUserResolver()
        self.conversation_store = FakeStore()


def make_client():
    app = FastAPI()
    register_conversation_routes(app, FakeAgent())
    return TestClient(app)


def test_list_conversations():
    client = make_client()
    resp = client.get("/api/conversations")
    assert resp.status_code == 200
    assert resp.json() == []


def test_delete_conversation():
    client = make_client()
    resp = client.delete("/api/conversations/nope")
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_conversation_routes.py -v`
Expected: FAIL — `ModuleNotFoundError: ... conversation_routes`

- [ ] **Step 3: 实现 conversation_routes.py**

创建 `src/vanna/servers/fastapi/conversation_routes.py`：

```python
"""FastAPI routes exposing the conversation store for the web UI."""

from fastapi import FastAPI, HTTPException, Query, Request

from .auth import resolve_user


def register_conversation_routes(app: FastAPI, agent) -> None:
    store = agent.conversation_store

    @app.get("/api/conversations")
    async def list_conversations(
        http_request: Request,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        user = await resolve_user(agent, http_request)
        conversations = await store.list_conversations(user, limit=limit, offset=offset)
        return [c.model_dump(mode="json") for c in conversations]

    @app.get("/api/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str, http_request: Request):
        user = await resolve_user(agent, http_request)
        conversation = await store.get_conversation(conversation_id, user)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conversation.model_dump(mode="json")

    @app.delete("/api/conversations/{conversation_id}")
    async def delete_conversation(conversation_id: str, http_request: Request):
        user = await resolve_user(agent, http_request)
        deleted = await store.delete_conversation(conversation_id, user)
        if not deleted:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"deleted": True}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_conversation_routes.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add src/vanna/servers/fastapi/conversation_routes.py tests/test_conversation_routes.py
git commit -m "feat: expose conversation list/get/delete REST routes"
```

---

### Task 4: `SchemaVectorStore.list_tables` / `remove_table`

**Files:**
- Modify: `src/vanna/capabilities/schema_vector_store/base.py`
- Modify: `src/vanna/integrations/vector/faiss/schema_vector_store.py`
- Test: `tests/test_schema_vector_store_manage.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_schema_vector_store_manage.py`：

```python
import numpy as np

from vanna.capabilities.schema_vector_store import SchemaColumn, SchemaTable
from vanna.integrations.vector.faiss.schema_vector_store import FAISSSchemaVectorStore


def embed_fn(texts):
    vecs = []
    for t in texts:
        v = np.zeros(4, dtype="float32")
        v[0] = float(len(t))
        vecs.append(v)
    return np.asarray(vecs, dtype="float32")


async def make_store(tmp_path):
    store = FAISSSchemaVectorStore(persist_dir=str(tmp_path), embed_fn=embed_fn)
    t1 = SchemaTable(
        table_name="users",
        columns=[SchemaColumn(column_name="id", table_name="users", data_type="INTEGER")],
    )
    t2 = SchemaTable(
        table_name="orders",
        columns=[SchemaColumn(column_name="id", table_name="orders", data_type="INTEGER")],
    )
    await store.ingest_schema([t1, t2], [], "ns_a")
    return store


async def test_list_tables(tmp_path):
    store = await make_store(tmp_path)
    tables = await store.list_tables("ns_a")
    names = {t.table_name for t in tables}
    assert names == {"users", "orders"}


async def test_remove_table(tmp_path):
    store = await make_store(tmp_path)
    removed = await store.remove_table("users", "ns_a")
    assert removed == 1
    tables = await store.list_tables("ns_a")
    assert [t.table_name for t in tables] == ["orders"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_schema_vector_store_manage.py -v`
Expected: FAIL — `AttributeError: 'FAISSSchemaVectorStore' object has no attribute 'list_tables'`

- [ ] **Step 3: 基类增加可选方法**

在 `src/vanna/capabilities/schema_vector_store/base.py` 的类末尾（`get_relations` 之后）增加两个具体方法（不 abstract，供不支持的后端继承）：

```python
    async def list_tables(self, namespace: str) -> List[SchemaTable]:
        """List tables currently indexed for a namespace (optional capability)."""
        raise NotImplementedError("This backend does not support listing tables")

    async def remove_table(self, table_name: str, namespace: str) -> int:
        """Remove a table (columns + relations); returns removed column count."""
        raise NotImplementedError("This backend does not support removing tables")
```

- [ ] **Step 4: FAISS 实现两个方法**

在 `src/vanna/integrations/vector/faiss/schema_vector_store.py` 的 `get_relations` 之后、文件末尾追加：

```python
    async def list_tables(self, namespace: str) -> List[SchemaTable]:
        """List tables by grouping persisted columns."""
        self._load_database(namespace)
        metadata = self._metadata.get(namespace) or {}
        columns = [SchemaColumn(**c) for c in metadata.get("columns", [])]
        grouped: Dict[str, List[SchemaColumn]] = {}
        for col in columns:
            grouped.setdefault(col.table_name, []).append(col)
        return [
            SchemaTable(table_name=name, database_name=namespace, columns=cols)
            for name, cols in grouped.items()
        ]

    async def remove_table(self, table_name: str, namespace: str) -> int:
        """Remove a table's columns/relations and rebuild the index."""
        self._load_database(namespace)
        index = self._indexes.get(namespace)
        metadata = self._metadata.get(namespace) or {}
        columns = [SchemaColumn(**c) for c in metadata.get("columns", [])]
        embedding_texts = metadata.get("embedding_texts", [])
        relations = [SchemaRelation(**r) for r in metadata.get("relations", [])]

        lower = table_name.lower()
        kept_indices = [i for i, c in enumerate(columns) if c.table_name.lower() != lower]
        kept_cols = [columns[i] for i in kept_indices]
        kept_texts = [embedding_texts[i] for i in kept_indices if i < len(embedding_texts)]
        kept_relations = [
            r for r in relations
            if r.from_table.lower() != lower and r.to_table.lower() != lower
        ]
        removed = len(columns) - len(kept_cols)

        def _remove() -> None:
            new_index = None
            if kept_indices and index is not None:
                vectors = index.reconstruct_n(0, index.ntotal)
                kept_vectors = np.ascontiguousarray(
                    vectors[kept_indices], dtype="float32"
                )
                new_index = faiss.IndexFlatL2(kept_vectors.shape[1])
                new_index.add(kept_vectors)
            self._indexes[namespace] = new_index
            self._metadata[namespace] = {
                "columns": [c.model_dump() for c in kept_cols],
                "embedding_texts": kept_texts,
                "relations": [r.model_dump() for r in kept_relations],
            }
            self._persist_database(namespace)

        await asyncio.get_event_loop().run_in_executor(self._executor, _remove)
        return removed
```

> 注：参数名统一为 `namespace`，对应业务配置中 `schema_vector.namespace`（即 `effective_database_name()` 的解析结果），避免与业务数据库 URL 混淆。

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_schema_vector_store_manage.py -v`
Expected: 2 passed

- [ ] **Step 6: 提交**

```bash
git add src/vanna/capabilities/schema_vector_store/base.py src/vanna/integrations/vector/faiss/schema_vector_store.py tests/test_schema_vector_store_manage.py
git commit -m "feat: add list_tables/remove_table to schema vector store (FAISS)"
```

---

### Task 5: Schema 管理 REST 路由

> `business_id` 为**必填**查询参数；命名空间复用 `ddl_import.py` 的 `_resolve_business_namespace` 同款逻辑（`agent.config.businesses[business_id].effective_database_name()`），未知/禁用返回 400（无兜底）。**不再使用** `agent.config.autolink_config.database_name` 作默认值——多业务模式下不存在全局默认命名空间。

**Files:**
- Create: `src/vanna/servers/fastapi/schema_routes.py`
- Test: `tests/test_schema_routes.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_schema_routes.py`：

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vanna.core.user import CookieEmailUserResolver
from vanna.servers.fastapi.schema_routes import register_schema_routes


class FakeStore:
    def __init__(self):
        self.tables = ["equipment", "sensors"]

    async def list_tables(self, namespace):
        return self.tables

    async def remove_table(self, table_name, namespace):
        self.tables = [t for t in self.tables if t != table_name]
        return 1


class FakeBusiness:
    def __init__(self, namespace):
        self._ns = namespace

    def effective_database_name(self):
        return self._ns


class FakeAgent:
    def __init__(self):
        self.user_resolver = CookieEmailUserResolver()
        self.schema_vector_store = FakeStore()
        self.config = type(
            "C", (), {"businesses": {"biz_a": FakeBusiness("ns_a")}}
        )()


def make_client(admin_emails=("admin@corp.com",)):
    app = FastAPI()
    register_schema_routes(app, FakeAgent(), admin_emails=list(admin_emails))
    return TestClient(app)


def test_list_tables_requires_admin():
    client = make_client()
    client.cookies.set("chatbot_email", "user@corp.com")
    resp = client.get("/api/schema/tables", params={"business_id": "biz_a"})
    assert resp.status_code == 403


def test_list_tables_requires_business_id():
    client = make_client()
    client.cookies.set("chatbot_email", "admin@corp.com")
    resp = client.get("/api/schema/tables")
    assert resp.status_code == 400


def test_list_tables_unknown_business_returns_400():
    client = make_client()
    client.cookies.set("chatbot_email", "admin@corp.com")
    resp = client.get("/api/schema/tables", params={"business_id": "nope"})
    assert resp.status_code == 400
    assert "biz_a" in resp.json()["detail"]  # 错误信息列出可用业务


def test_list_tables_as_admin():
    client = make_client()
    client.cookies.set("chatbot_email", "admin@corp.com")
    resp = client.get("/api/schema/tables", params={"business_id": "biz_a"})
    assert resp.status_code == 200
    assert resp.json()["namespace"] == "ns_a"
    assert resp.json()["tables"] == ["equipment", "sensors"]


def test_remove_table_as_admin():
    client = make_client()
    client.cookies.set("chatbot_email", "admin@corp.com")
    resp = client.delete(
        "/api/schema/tables/equipment", params={"business_id": "biz_a"}
    )
    assert resp.status_code == 200
    resp2 = client.get("/api/schema/tables", params={"business_id": "biz_a"})
    assert resp2.json()["tables"] == ["sensors"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_schema_routes.py -v`
Expected: FAIL — `ModuleNotFoundError: ... schema_routes`

- [ ] **Step 3: 实现 schema_routes.py**

创建 `src/vanna/servers/fastapi/schema_routes.py`：

```python
"""FastAPI routes for the built-in web UI schema management (admin only).

Namespace resolution follows the same no-fallback rule as DDL ingest:
business_id is required and must match an enabled business; the vector
namespace comes from the business configuration.
"""

from fastapi import FastAPI, HTTPException, Query, Request

from .auth import is_admin_email, resolve_user


def _resolve_business_namespace(agent, business_id: str) -> str:
    """Resolve the schema namespace for a business id (no fallback).

    Mirrors ``ddl_import._resolve_business_namespace``: raises 400 listing
    available businesses when the id is unknown or disabled.
    """
    businesses = getattr(getattr(agent, "config", None), "businesses", {}) or {}
    business = businesses.get(business_id)
    if business is None:
        available = ", ".join(sorted(businesses)) or "none"
        raise HTTPException(
            status_code=400,
            detail=(
                f"business_id '{business_id}' not found or disabled; "
                f"available: {available}"
            ),
        )
    return business.effective_database_name()


def register_schema_routes(app: FastAPI, agent, admin_emails=None) -> None:
    store = agent.schema_vector_store
    admin_emails = admin_emails or []

    def _guard(user) -> None:
        if not is_admin_email(user.email, admin_emails):
            raise HTTPException(status_code=403, detail="Admin access required")

    @app.get("/api/schema/tables")
    async def list_schema_tables(
        http_request: Request,
        business_id: str = Query(..., description="Target business id"),
    ):
        user = await resolve_user(agent, http_request)
        _guard(user)
        if store is None:
            raise HTTPException(status_code=503, detail="No schema vector store configured")
        namespace = _resolve_business_namespace(agent, business_id)
        tables = await store.list_tables(namespace)
        return {"business_id": business_id, "namespace": namespace, "tables": tables}

    @app.delete("/api/schema/tables/{table_name}")
    async def remove_schema_table(
        table_name: str,
        http_request: Request,
        business_id: str = Query(..., description="Target business id"),
    ):
        user = await resolve_user(agent, http_request)
        _guard(user)
        if store is None:
            raise HTTPException(status_code=503, detail="No schema vector store configured")
        namespace = _resolve_business_namespace(agent, business_id)
        try:
            removed = await store.remove_table(table_name, namespace)
        except NotImplementedError:
            raise HTTPException(status_code=501, detail="Backend does not support table removal")
        return {"removed_columns": removed, "table_name": table_name, "namespace": namespace}
```

> 实现后可将 `ddl_import.py` 中的 `_resolve_business_namespace` 改为从本模块导入，消除重复（可选，不强制）。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_schema_routes.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/vanna/servers/fastapi/schema_routes.py tests/test_schema_routes.py
git commit -m "feat: add admin-only schema list/remove routes with business routing"
```

---

### Task 6: 装配新路由 + app.json server 配置 + Cookie resolver 接线

**Files:**
- Modify: `src/vanna/servers/fastapi/app.py`
- Modify: `src/vanna/servers/cli/server_runner.py`
- Test: `tests/test_app_routes.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_app_routes.py`：

```python
from fastapi.testclient import TestClient

from vanna.core.user import CookieEmailUserResolver
from vanna.integrations.local import SQLiteConversationStore
from vanna.servers.fastapi.app import VannaFastAPIServer


class FakeBusiness:
    def effective_database_name(self):
        return "ns_a"


class FakeAgent:
    def __init__(self):
        self.user_resolver = CookieEmailUserResolver()
        self.schema_vector_store = None
        self.config = type(
            "C", (), {"businesses": {"biz_a": FakeBusiness()}}
        )()
        self.conversation_store = SQLiteConversationStore(db_path=":memory:")


def test_new_routes_registered():
    server = VannaFastAPIServer(
        agent=FakeAgent(),
        config={"admin_emails": ["admin@corp.com"]},
    )
    client = TestClient(server.create_app())
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/conversations").status_code == 200
    body = client.get("/api/auth/me").json()
    assert body["businesses"] == ["biz_a"]


def test_schema_tables_requires_business_id():
    server = VannaFastAPIServer(
        agent=FakeAgent(),
        config={"admin_emails": ["admin@corp.com"]},
    )
    client = TestClient(server.create_app())
    client.cookies.set("chatbot_email", "admin@corp.com")
    assert client.get("/api/schema/tables").status_code == 400
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_app_routes.py -v`
Expected: FAIL —新路由未注册，`/api/auth/me` 返回 404

- [ ] **Step 3: 修改 app.py 注册新路由**

在 `src/vanna/servers/fastapi/app.py` 的 `register_chat_routes` 与 `register_ddl_import_routes` 调用之后追加（import 放到模块顶部与其他 import 一起）：

```python
from .auth_routes import register_auth_routes
from .conversation_routes import register_conversation_routes
from .schema_routes import register_schema_routes

# 在 create_app() 内、register_ddl_import_routes(...) 之后：
admin_emails = self.config.get("admin_emails", [])
register_auth_routes(app, self.agent, admin_emails=admin_emails)
register_conversation_routes(app, self.agent)
register_schema_routes(app, self.agent, admin_emails=admin_emails)
```

- [ ] **Step 4: 修改 server_runner.py：`server.admin_emails` 配置 + resolver 接线**

1. `_APP_CONFIG_KEYS` 增加 `"server"`：

```python
_APP_CONFIG_KEYS = {
    "llm",
    "agent",
    "storage",
    "tools",
    "server",
}
```

2. 在 `main()` 中（`_create_config_agent()` 成功后、构建 `server_config` 处）解析并注入：

```python
server_cfg = cfg.get("server") or {}
# 注意：cfg 来自 _load_app_config()，需在 main() 内重新加载或在
# _create_config_agent() 中返回；推荐把 _load_app_config() 的结果
# 在 main() 中先取出再传给 _create_config_agent(cfg)。
admin_emails = server_cfg.get("admin_emails") or []
if not isinstance(admin_emails, list) or not all(
    isinstance(e, str) for e in admin_emails
):
    raise ValueError("App config 'server.admin_emails' must be a JSON array of strings")
server_config["admin_emails"] = admin_emails
```

3. 在 `_create_config_agent(...)` 调用（`create_basic_agent(...)`）中确保传入 cookie resolver：

```python
from vanna.core.user import CookieEmailUserResolver

# create_basic_agent(...) 参数追加：
    user_resolver=CookieEmailUserResolver(cookie_name="chatbot_email"),
```

（若该函数已有 `user_resolver` 相关逻辑，改为显式构造，保证运行中的服务解析 `chatbot_email` cookie。）

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_app_routes.py tests/test_auth_routes.py tests/test_conversation_routes.py tests/test_schema_routes.py -v`
Expected: 全部 passed

- [ ] **Step 6: 提交**

```bash
git add src/vanna/servers/fastapi/app.py src/vanna/servers/cli/server_runner.py tests/test_app_routes.py
git commit -m "feat: wire auth/conversation/schema routes with app.json admin_emails"
```

---

## Phase 2 — 前端工程

### Task 7: 脚手架 React + Vite + shadcn/ui

**Files:**
- Create: `frontends/web/` 全套脚手架

- [ ] **Step 1: 创建 Vite React-TS 工程**

```bash
npm create vite@latest frontends/web -- --template react-ts
cd frontends/web
npm install
```

Expected: 生成 `frontends/web/`（package.json、vite.config.ts、src/ 等）

- [ ] **Step 2: 初始化 Tailwind + shadcn**

```bash
cd frontends/web
npm install tailwindcss @tailwindcss/vite
npx shadcn@latest init
npx shadcn@latest add button card input table scroll-area separator badge alert dialog select
```

Expected: 生成 `src/components/ui/`、`components.json`，`src/index.css` 含 Tailwind 入口，`vite.config.ts` 加入 `@tailwindcss/vite` 插件。

- [ ] **Step 3: 安装路由与 HTTP**

```bash
cd frontends/web
npm install react-router-dom
```

- [ ] **Step 4: 提交脚手架**

```bash
git add frontends/web
git commit -m "chore: scaffold React+Vite+shadcn frontend in frontends/web"
```

---

### Task 8: API 客户端 + 认证上下文

**Files:**
- Create: `frontends/web/src/lib/api.ts`
- Create: `frontends/web/src/lib/auth.tsx`
- Test: `frontends/web/src/lib/auth.test.tsx`（Vitest）

- [ ] **Step 1: 写 api.ts**

创建 `frontends/web/src/lib/api.ts`：

```typescript
export interface AuthMe {
  id: string;
  email: string | null;
  is_admin: boolean;
  businesses: string[];
}

export interface ConversationMeta {
  id: string;
  updated_at: string;
  messages: { role: string; content: string }[];
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    if (res.status === 401) throw new Error("unauthorized");
    if (res.status === 403) throw new Error("forbidden");
    throw new Error(`request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  me: () => fetchJson<AuthMe>("/api/auth/me"),
  conversations: () => fetchJson<ConversationMeta[]>("/api/conversations"),
  conversation: (id: string) => fetchJson<ConversationMeta>(`/api/conversations/${id}`),
  deleteConversation: (id: string) =>
    fetchJson<{ deleted: boolean }>(`/api/conversations/${id}`, { method: "DELETE" }),
  schemaTables: (businessId: string) =>
    fetchJson<{ business_id: string; namespace: string; tables: any[] }>(
      `/api/schema/tables?business_id=${encodeURIComponent(businessId)}`
    ),
  deleteSchemaTable: (table: string, businessId: string) =>
    fetchJson<{ removed_columns: number }>(
      `/api/schema/tables/${encodeURIComponent(table)}?business_id=${encodeURIComponent(businessId)}`,
      { method: "DELETE" }
    ),
};
```

- [ ] **Step 2: 写 auth.tsx**

> AuthContext 额外持有当前选中的 `businessId`（登录时写入，localStorage 持久化），全应用共用。

创建 `frontends/web/src/lib/auth.tsx`：

```tsx
import {
  createContext, useContext, useEffect, useState, type ReactNode,
} from "react";
import { api, type AuthMe } from "./api";

interface AuthState {
  user: AuthMe | null;
  loading: boolean;
  businessId: string | null;
  setBusinessId: (id: string | null) => void;
  refresh: () => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthMe | null>(null);
  const [loading, setLoading] = useState(true);
  const [businessId, setBusinessIdState] = useState<string | null>(
    () => localStorage.getItem("business_id")
  );

  async function refresh() {
    setLoading(true);
    try {
      const me = await api.me();
      setUser(me);
      // 校验持久化的 businessId 仍有效；多业务且未选时保持 null（强制显式选择）
      if (me.businesses.length === 1) {
        setBusinessIdState(me.businesses[0]);
      } else if (businessId && !me.businesses.includes(businessId)) {
        setBusinessIdState(null);
      }
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  function setBusinessId(id: string | null) {
    if (id) localStorage.setItem("business_id", id);
    else localStorage.removeItem("business_id");
    setBusinessIdState(id);
  }

  function logout() {
    document.cookie = "chatbot_email=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/";
    localStorage.removeItem("business_id");
    setUser(null);
    setBusinessIdState(null);
  }

  useEffect(() => { refresh(); }, []);

  return (
    <AuthContext.Provider value={{ user, loading, businessId, setBusinessId, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function AdminGuard({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user?.is_admin) return <>{children}</>;
  return null;
}
```

- [ ] **Step 3: 写 auth 测试**

创建 `frontends/web/src/lib/auth.test.tsx`：

```tsx
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./auth";

describe("useAuth", () => {
  it("resolves admin user and single business preselection", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        id: "a", email: "admin@corp.com", is_admin: true, businesses: ["biz_a"],
      }),
    }));
    const wrapper = ({ children }) => <AuthProvider>{children}</AuthProvider>;
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user?.is_admin).toBe(true);
    expect(result.current.businessId).toBe("biz_a"); // 单业务预选
  });
});
```

- [ ] **Step 4: 安装测试依赖并运行**

```bash
cd frontends/web
npm install -D vitest @testing-library/react @testing-library/dom jsdom
npx vitest run src/lib/auth.test.tsx
```

Expected: 1 passed

（若 Vitest 缺 jsdom 配置，在 `vite.config.ts` 的 `test` 字段设 `environment: "jsdom"`。）

- [ ] **Step 5: 提交**

```bash
git add frontends/web/src/lib frontends/web/vite.config.ts frontends/web/package.json
git commit -m "feat: add api client and auth context with business selection"
```

---

### Task 9: 登录页（邮箱 + 业务选择）+ 对话页 + 会话侧栏

**Files:**
- Create: `frontends/web/src/app/login/LoginPage.tsx`
- Create: `frontends/web/src/app/chat/ConversationSidebar.tsx`
- Create: `frontends/web/src/app/chat/ChatPage.tsx`
- Modify: `frontends/web/src/App.tsx`、`frontends/web/src/main.tsx`

- [ ] **Step 1: 写登录页**

> 沿用现有 `templates.py` 的交互约定：**单业务预选、多业务强制显式选择（无默认路由）**。

创建 `frontends/web/src/app/login/LoginPage.tsx`：

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../lib/auth";

export default function LoginPage() {
  const { user, refresh, setBusinessId } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("admin@corp.com");
  const businesses = user?.businesses ?? [];
  const [business, setBusiness] = useState<string>(
    businesses.length === 1 ? businesses[0] : ""
  );

  function submit() {
    if (!email.trim()) return;
    if (businesses.length > 1 && !business) return; // 多业务强制显式选择
    document.cookie = `chatbot_email=${encodeURIComponent(email)}; path=/; max-age=31536000; SameSite=Lax`;
    setBusinessId(businesses.length ? business || businesses[0] : null);
    refresh().then(() => navigate("/"));
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="w-full max-w-sm rounded-xl border p-6 shadow-sm">
        <h1 className="text-lg font-semibold">登录</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          选择账号（管理员账号在 config/app.json 的 server.admin_emails 配置）
        </p>
        <input
          className="mt-4 w-full rounded-md border px-3 py-2 text-sm"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        {businesses.length > 0 && (
          <select
            className="mt-3 w-full rounded-md border px-3 py-2 text-sm"
            value={business}
            onChange={(e) => setBusiness(e.target.value)}
          >
            {businesses.length > 1 && <option value="">Select a business...</option>}
            {businesses.map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
        )}
        <button
          className="mt-4 w-full rounded-md bg-primary py-2 text-sm text-primary-foreground disabled:opacity-50"
          onClick={submit}
          disabled={businesses.length > 1 && !business}
        >
          进入
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 写会话侧栏**

创建 `frontends/web/src/app/chat/ConversationSidebar.tsx`：

```tsx
import { useEffect, useState } from "react";
import { api, type ConversationMeta } from "../../lib/api";

export default function ConversationSidebar({ onSelect }: { onSelect: (id: string) => void }) {
  const [convs, setConvs] = useState<ConversationMeta[]>([]);

  useEffect(() => {
    api.conversations().then(setConvs).catch(() => {});
  }, []);

  return (
    <aside className="flex h-full w-64 flex-col border-r bg-muted/40 p-3">
      <button className="mb-3 rounded-md border bg-background px-3 py-2 text-sm">+ 新对话</button>
      <nav className="flex-1 overflow-y-auto">
        {convs.map((c) => (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className="block w-full truncate rounded px-3 py-2 text-left text-sm hover:bg-muted"
          >
            {c.messages[0]?.content ?? c.id}
          </button>
        ))}
      </nav>
    </aside>
  );
}
```

- [ ] **Step 3: 写对话页（嵌入 chatbot-chat，透传 business-id）**

创建 `frontends/web/src/app/chat/ChatPage.tsx`：

```tsx
import { useEffect, useRef } from "react";
import ConversationSidebar from "./ConversationSidebar";
import { useAuth } from "../../lib/auth";

export default function ChatPage() {
  const chatRef = useRef<HTMLElement | null>(null);
  const { businessId } = useAuth();

  useEffect(() => {
    // 加载现有 webcomponent 产物（由 FastAPI 从 frontends/webcomponent/static 托管）
    if (!customElements.get("chatbot-chat")) {
      const s = document.createElement("script");
      s.type = "module";
      s.src = "/static/chatbot-components.js";
      document.head.appendChild(s);
    }
  }, []);

  return (
    <div className="flex h-screen">
      <ConversationSidebar onSelect={(id) => { /* 回放：设置组件 conversation 输入 */ }} />
      <main className="flex-1 p-4">
        <chatbot-chat
          ref={chatRef}
          sse-endpoint="/api/vanna/v2/chat_sse"
          ws-endpoint="/api/vanna/v2/chat_websocket"
          poll-endpoint="/api/vanna/v2/chat_poll"
          business-id={businessId ?? undefined}
          className="block h-full"
        />
      </main>
    </div>
  );
}
```

> 注：`business-id` 属性对应后端 `ChatRequest.business_id`（top-level 字段），路由层会将其合入请求 metadata 完成多业务路由。自定义元素属性在 React 19 中可原生透传；若构建时 TS 对 `<chatbot-chat>` 报 JSX 类型错误，在 `src/vite-env.d.ts` 追加 `declare namespace JSX { interface IntrinsicElements { "chatbot-chat": any } }`。

- [ ] **Step 4: 装配路由**

修改 `frontends/web/src/main.tsx`，把默认渲染改为：

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { AuthProvider } from "./lib/auth";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>
);
```

修改 `frontends/web/src/App.tsx`：

```tsx
import { Route, Routes, Navigate } from "react-router-dom";
import LoginPage from "./app/login/LoginPage";
import ChatPage from "./app/chat/ChatPage";
import { useAuth } from "./lib/auth";

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user?.email) return <LoginPage />;
  return (
    <Routes>
      <Route path="/" element={<ChatPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
```

- [ ] **Step 5: 构建验证**

```bash
cd frontends/web
npx tsc --noEmit
npm run build
```

Expected: 构建成功，产出 `frontends/web/dist/`

- [ ] **Step 6: 提交**

```bash
git add frontends/web/src
git commit -m "feat: add login page with business selector, chat page and sidebar"
```

---

### Task 10: 管理后台布局 + DDL 导入页 + Schema 管理页

**Files:**
- Create: `frontends/web/src/app/admin/AdminLayout.tsx`
- Create: `frontends/web/src/app/admin/DdlImportPage.tsx`
- Create: `frontends/web/src/app/admin/SchemaPage.tsx`
- Modify: `frontends/web/src/App.tsx`

- [ ] **Step 1: 写管理布局**

创建 `frontends/web/src/app/admin/AdminLayout.tsx`：

```tsx
import { NavLink, Outlet } from "react-router-dom";

export default function AdminLayout() {
  return (
    <div className="flex h-screen">
      <aside className="flex w-56 flex-col border-r bg-zinc-950 p-3 text-zinc-100">
        <div className="mb-4 text-sm font-semibold">⚙️ 管理后台</div>
        <NavLink to="/admin/ddl-import" className="rounded px-3 py-2 text-sm hover:bg-zinc-800">📥 DDL 导入</NavLink>
        <NavLink to="/admin/schema" className="rounded px-3 py-2 text-sm hover:bg-zinc-800">🗂 Schema 管理</NavLink>
        <NavLink to="/" className="mt-auto rounded px-3 py-2 text-sm hover:bg-zinc-800">← 返回对话</NavLink>
      </aside>
      <main className="flex-1 overflow-y-auto p-6">
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 2: 写 DDL 导入页（含目标业务选择）**

> ingest 请求体为 `{parse_id, business_id}`（`business_id` 必填，后端无兜底路由）。

创建 `frontends/web/src/app/admin/DdlImportPage.tsx`：

```tsx
import { useState } from "react";
import { useAuth } from "../../lib/auth";

export default function DdlImportPage() {
  const { user, businessId, setBusinessId } = useAuth();
  const businesses = user?.businesses ?? [];
  const [selected, setSelected] = useState<string>(
    businesses.length === 1 ? businesses[0] : businessId ?? ""
  );
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  async function parse() {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/vanna/v1/ddl/parse", { method: "POST", body: fd });
    if (!res.ok) { setError(await res.text()); return; }
    setPreview(await res.json());
  }

  async function ingest() {
    const res = await fetch("/api/vanna/v1/ddl/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parse_id: preview.parse_id, business_id: selected }),
    });
    if (!res.ok) { setError(await res.text()); return; }
    setPreview(null);
  }

  return (
    <div>
      <h1 className="text-xl font-semibold">DDL 导入</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        必须选择目标业务，namespace 由业务配置解析（无兜底路由）。
      </p>
      <div className="mt-3 flex items-center gap-2">
        <select
          className="rounded-md border px-3 py-2 text-sm"
          value={selected}
          onChange={(e) => { setSelected(e.target.value); setBusinessId(e.target.value || null); }}
        >
          {businesses.length > 1 && <option value="">Select a business...</option>}
          {businesses.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
        <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <button
          className="rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50"
          onClick={parse}
          disabled={!file || !selected}
        >
          解析
        </button>
      </div>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      {preview && (
        <div className="mt-4 space-y-2 text-sm">
          <p>表: {preview.tables_count} · 列: {preview.columns_count} · 关系: {preview.relations_count}</p>
          <button
            className="rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground"
            onClick={ingest}
          >
            确认写入向量库
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: 写 Schema 管理页（业务切换器）**

创建 `frontends/web/src/app/admin/SchemaPage.tsx`：

```tsx
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";

export default function SchemaPage() {
  const { user, businessId } = useAuth();
  const businesses = user?.businesses ?? [];
  const [selected, setSelected] = useState<string>(
    businesses.length === 1 ? businesses[0] : businessId ?? ""
  );
  const [data, setData] = useState<{ namespace: string; tables: any[] } | null>(null);

  function load() {
    if (!selected) { setData(null); return; }
    api.schemaTables(selected).then(setData).catch(() => {});
  }

  useEffect(load, [selected]);

  async function remove(name: string) {
    await api.deleteSchemaTable(name, selected);
    load();
  }

  return (
    <div>
      <h1 className="text-xl font-semibold">Schema 管理</h1>
      <div className="mt-2 flex items-center gap-2 text-sm">
        <select
          className="rounded-md border px-3 py-2"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
        >
          {businesses.length > 1 && <option value="">Select a business...</option>}
          {businesses.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
        {data && <span className="text-muted-foreground">命名空间：{data.namespace}</span>}
      </div>
      <div className="mt-4 space-y-2">
        {data?.tables.map((t) => (
          <div key={t.table_name ?? t} className="flex items-center justify-between rounded border p-3 text-sm">
            <span>{typeof t === "string" ? t : t.table_name}</span>
            <button
              className="rounded border px-2 py-1 text-xs text-red-600"
              onClick={() => remove(typeof t === "string" ? t : t.table_name)}
            >
              删除
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 路由接入 + 守卫**

修改 `frontends/web/src/App.tsx`，在 `<Routes>` 内追加：

```tsx
import AdminLayout from "./app/admin/AdminLayout";
import DdlImportPage from "./app/admin/DdlImportPage";
import SchemaPage from "./app/admin/SchemaPage";
import { AdminGuard } from "./lib/auth";

// Routes 内追加：
<Route path="/admin" element={<AdminGuard><AdminLayout /></AdminGuard>}>
  <Route path="ddl-import" element={<DdlImportPage />} />
  <Route path="schema" element={<SchemaPage />} />
</Route>
```

并在 `ChatPage` 侧栏加"管理后台"入口（仅 `user.is_admin` 时显示 `<Link to="/admin/ddl-import">⚙️ 管理后台</Link>`）。

- [ ] **Step 5: 构建验证**

```bash
cd frontends/web
npx tsc --noEmit && npm run build
```

Expected: 构建成功

- [ ] **Step 6: 提交**

```bash
git add frontends/web/src
git commit -m "feat: add admin layout, DDL import and schema pages with business routing"
```

---

### Task 11: FastAPI 托管 SPA 静态产物

**Files:**
- Modify: `src/vanna/servers/fastapi/app.py`
- Test: `tests/test_spa_serving.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_spa_serving.py`：

```python
import tempfile
from types import SimpleNamespace

from fastapi.testclient import TestClient

from vanna.core.user import CookieEmailUserResolver
from vanna.servers.fastapi.app import VannaFastAPIServer


class FakeAgent:
    def __init__(self):
        self.user_resolver = CookieEmailUserResolver()
        self.schema_vector_store = None
        self.conversation_store = None
        self.config = SimpleNamespace(businesses={})


def test_serves_index_when_dist_present(tmp_path):
    (tmp_path / "index.html").write_text("SPA", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    server = VannaFastAPIServer(agent=FakeAgent(), config={"web_dist": str(tmp_path)})
    client = TestClient(server.create_app())
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.text == "SPA"


def test_fallback_to_templates_when_dist_missing():
    server = VannaFastAPIServer(
        agent=FakeAgent(),
        config={"web_dist": tempfile.mkdtemp() + "/no-dist"},
    )
    client = TestClient(server.create_app())
    # / 回退到现有 templates.py 页面
    assert client.get("/").status_code == 200
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_spa_serving.py -v`
Expected: FAIL — `config` 里 `web_dist` 不受支持

- [ ] **Step 3: 实现 app.py 托管**

在 `src/vanna/servers/fastapi/app.py` 的 `create_app()` 末尾（health 路由注册前后，需在 catch-all 之前）加入：

```python
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

def _serve_spa(app, web_dist):
    web_dist = os.path.abspath(web_dist)
    index_file = os.path.join(web_dist, "index.html")
    if not os.path.exists(index_file):
        return  # 无构建产物，保留 templates.py 直出页
    assets_dir = os.path.join(web_dist, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="web-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("health"):
            raise HTTPException(status_code=404)
        candidate = os.path.join(web_dist, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(index_file)
```

在 `create_app()` 内、`/health` 路由之前调用 `_serve_spa(app, self.config.get("web_dist", "frontends/web/dist"))`。

> 注意：catch-all 路由 `@app.get("/{full_path:path}")` 必须最后注册，且不能遮蔽 `/api/*`、`/health`、`/ddl-import` 等既有具体路由。上述实现已通过前缀与文件判断排除。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_spa_serving.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add src/vanna/servers/fastapi/app.py tests/test_spa_serving.py
git commit -m "feat: serve built SPA from frontends/web/dist with fallback"
```

---

### Task 12: 端到端冒烟验证

- [ ] **Step 1: 构建前端**

```bash
cd frontends/web
npm run build
```

Expected: 产出 `frontends/web/dist/index.html`

- [ ] **Step 2: 准备配置并启动后端**

`config/app.json`（注意：管理员邮箱配置在 `server.admin_emails`，**不再使用 `.env`**）：

```json
{
  "llm": { "active": "...", "instances": { "...": {} } },
  "agent": { "max_tool_iterations": 10 },
  "storage": {
    "project": {
      "conversation_db": { "active": "local_sqlite", "instances": { "local_sqlite": { "url": "sqlite:///data/db/conversations.db" } } },
      "vector_db": { "active": "faiss_local", "instances": { "faiss_local": { "backend": "faiss" } } }
    },
    "businesses": [
      { "id": "biz_a", "enabled": true, "database": { "url": "sqlite:///data/db/biz_a.db" }, "schema_vector": { "namespace": "ns_a" } }
    ]
  },
  "server": { "admin_emails": ["admin@corp.com"] }
}
```

```bash
# 项目根
python -m vanna.servers
```

Expected: 单进程启动，启动日志显示 `✓ Multi-business routing enabled` 与 `💼 Business routing enabled: biz_a`；浏览器访问 `http://localhost:9000` 为 React 应用；`/api/auth/me` 用 `admin@corp.com` 返回 `is_admin: true`、`businesses: ["biz_a"]`。

- [ ] **Step 3: 手工冒烟清单**

- 登录页输入 `admin@corp.com` → 业务选择器（单业务预选/多业务必选）→ 跳转对话页，侧栏显示"管理后台"
- 普通邮箱 → 无"管理后台"入口；直接访问 `/admin/schema` 被守卫拦截
- 对话发消息（携带所选 business_id）→ 会话出现在侧栏；刷新后历史可见
- 管理后台 DDL 导入：选目标业务 → 上传 CSV → 预览 → 确认入库（请求体含 business_id）
- Schema 管理页：切换业务 → 列出该业务命名空间下已导入表，删除单表后索引同步更新
- 未选/传未知 business_id 调 schema API → 400 且错误信息列出可用业务

- [ ] **Step 4: 提交验证结论（如无代码改动则跳过）**

---

## Self-Review 结果

- **Spec 覆盖**：决策记录中「统一风格/会话历史/Schema 管理/角色区分/单一后端部署/ChatGPT 式布局/品牌占位/组件复用/**app.json 统一配置/业务选择**」均有对应 Task；新 API（auth/me 含 businesses、conversations、schema/tables 必填 business_id）与 `list_tables`/`remove_table` 能力补充已落地。
- **多业务对齐**：管理员邮箱改从 app.json `server.admin_emails` 读取（Task 2/6）；schema 系 API 复用 DDL ingest 的无兜底命名空间解析（Task 5）；登录/DDL/Schema 页均含业务选择器，单业务预选、多业务强制显式选择（Task 9/10，与 `templates.py` 现有交互一致）；`<chatbot-chat>` 透传 `business-id`（Task 9）。
- **落地缺口补齐**：`CookieEmailUserResolver`（Task 1）、`list_tables`/`remove_table`（Task 4）、会话 REST（Task 3）均覆盖。
- **类型一致性**：`resolve_user(agent, http_request)`、`is_admin_email(email, admin_emails)`、`store.list_tables(namespace)`/`store.remove_table(table, namespace)`、`_resolve_business_namespace(agent, business_id)` 签名在 auth / conversation / schema / ddl_import / base / faiss 间一致；前端 `api.*` 与后端响应字段对齐（`businesses`、`namespace` 等）。
- **已知取舍**：会话列表暂按用户过滤、不按业务过滤（`business_id` 已在会话 metadata 中，前端过滤/打标为后续增强）；切换 cookie resolver 后，历史会话存于旧默认用户下，新登录用户将从空历史开始（数据仍在 `data/db/conversations.db` 可迁移，不在本次范围）。
