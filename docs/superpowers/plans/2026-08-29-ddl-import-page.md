# DDL Import Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 FastAPI 服务中增加一个内置页面，上传 DDL.csv → 预览解析结果 → 确认写入服务当前装配的 `agent.schema_vector_store`。

**Architecture:** 新增 `src/vanna/servers/fastapi/ddl_import.py`，内含页面路由 `GET /ddl-import`（纯 HTML+内联 JS）、`POST /api/vanna/v1/ddl/parse`（multipart 上传→`DdlParser.parse_csv`→内存暂存→返回预览）、`POST /api/vanna/v1/ddl/ingest`（`{parse_id, database_name}`→`agent.schema_vector_store.ingest_schema`）。`VannaFastAPIServer.create_app()` 末尾注册该模块。不改动 `agent.py`、`ddl_parser.py` 与各 store 实现。

**Tech Stack:** FastAPI（UploadFile / File / HTTPException / TestClient）、标准库 csv/tempfile/uuid、pydantic BaseModel（ingest 请求体）、pytest + pytest-asyncio（已有）。

**Spec:** `docs/superpowers/specs/2026-08-29-ddl-import-page-design.md`（已提交 `29682b9b`）

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `src/vanna/servers/fastapi/ddl_import.py`（新增） | 页面 HTML 模板 + 2 个 API 路由 + 解析暂存表 |
| `src/vanna/servers/fastapi/app.py`（修改，1 行注册） | `create_app()` 注册 ddl_import 路由 |
| `tests/test_ddl_import.py`（新增） | FakeStore + 假 agent 的 API 单元测试 |

## 关键事实（实现前必读）

- `DdlParser.parse_csv(csv_path: Union[str, Path], database_name="default") -> (List[SchemaTable], List[SchemaRelation])`，同步、需真实文件路径（用得 `tempfile.NamedTemporaryFile(delete=False, suffix=".csv")` 落盘）。CSV 带表头（`table_name,ddl`）或无表头自动识别；坏行内部 `logger.warning` 跳过、不抛异常（见 `src/vanna/capabilities/schema_vector_store/ddl_parser.py#L294-L392`）。
- `SchemaTable` 字段：`table_name`、`database_name`、`columns: List[SchemaColumn]`、`primary_keys`、`foreign_keys`；`SchemaColumn` 字段：`column_name`、`table_name`、`data_type`、`description`、`sample_values`（见 `src/vanna/capabilities/schema_vector_store/models.py`）。
- `SchemaVectorStore.ingest_schema(tables, relations, database_name)` 为抽象方法（`src/vanna/capabilities/schema_vector_store/base.py#L23-L38`），幂等覆盖。
- `agent.schema_vector_store` 可能为 `None`（未配置向量后端时）——ingest 需返回 503。
- `python-multipart` 已安装（FastAPI `File`/`UploadFile` 必需）；fastapi TestClient 可用（StarletteDeprecationWarning 可忽略）。
- FastAPI 0.x 中 `TestClient(app)` 默认 `raise_server_exceptions=True`，路由内所有异常都会冒泡，测试断言用 `with pytest.raises(Exception)` 或改用 TestClient 直连——**本计划统一在路由内 try/except 捕获并转成 HTTP 错误**，因此测试直接断言 `response.status_code == 4xx/5xx` 即可。

---

## Task 1: 页面模块骨架 + 页面路由

**Files:**
- Create: `src/vanna/servers/fastapi/ddl_import.py`
- Test: `tests/test_ddl_import.py`

- [ ] **Step 1: 写失败测试（页面路由）**

```python
# tests/test_ddl_import.py
"""Tests for the DDL import page (parse/ingest into schema vector store)."""
import io
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vanna.capabilities.schema_vector_store.base import SchemaVectorStore
from vanna.servers.fastapi.ddl_import import register_ddl_import_routes


class FakeStore(SchemaVectorStore):
    """Records ingest calls; no real vector backend needed."""

    def __init__(self):
        self.ingested = []

    async def ingest_schema(self, tables, relations, database_name):
        self.ingested.append(
            {"tables": tables, "relations": relations, "database_name": database_name}
        )

    async def search(self, query, database_name, top_k=20):
        return []

    async def get_column_by_name(self, column_name, table_name, database_name):
        return None

    async def get_relations(self, table_names, database_name):
        return []


class FakeAgent:
    def __init__(self, schema_vector_store=None):
        self.schema_vector_store = schema_vector_store


def make_client(agent=None):
    app = FastAPI()
    register_ddl_import_routes(app, agent or FakeAgent(FakeStore()))
    return TestClient(app)


def test_page_served():
    response = make_client().get("/ddl-import")
    assert response.status_code == 200
    assert "DDL" in response.text
    assert "database_name" in response.text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_ddl_import.py::test_page_served -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'vanna.servers.fastapi.ddl_import'`）

- [ ] **Step 3: 写最小实现**

```python
# src/vanna/servers/fastapi/ddl_import.py
"""
DDL import page: upload DDL.csv, preview parsed schema, ingest into the
agent's schema vector store.
"""

from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse

_INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>DDL Schema 导入</title>
</head>
<body>
<h1>DDL Schema 导入</h1>
<p>上传 DDL.csv，解析预览后写入当前服务的向量库（database_name 需与 AutoLinkConfig.database_name 一致）。</p>
<input type="file" id="ddl-file" accept=".csv">
<input type="text" id="database-name" value="default" placeholder="database_name">
<button id="parse-btn">解析</button>
<div id="preview"></div>
<div id="result"></div>
<script>
// JS 在 Task 4 完整实现
</script>
</body>
</html>
"""


def register_ddl_import_routes(app: FastAPI, agent) -> None:
    """Register the DDL import page and API routes."""

    @app.get("/ddl-import", response_class=HTMLResponse)
    async def ddl_import_page() -> str:
        return _INDEX_HTML
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_ddl_import.py::test_page_served -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/vanna/servers/fastapi/ddl_import.py tests/test_ddl_import.py
git commit -m "feat: add DDL import page skeleton route in fastapi server"
```

---

## Task 2: parse API（上传→解析→暂存→预览）

**Files:**
- Modify: `src/vanna/servers/fastapi/ddl_import.py`
- Test: `tests/test_ddl_import.py`（追加）

- [ ] **Step 1: 写失败测试（parse 成功 / 空 CSV / 坏行警告 / 缺文件）**

在 `tests/test_ddl_import.py` 追加：

```python
GOOD_CSV = (
    "table_name,ddl\n"
    'orders,"CREATE TABLE orders (\n'
    "    id INTEGER PRIMARY KEY,\n"
    "    customer_id INTEGER,\n"
    '    FOREIGN KEY (customer_id) REFERENCES customers(id)\n'
    ')"\n'
    'customers,"CREATE TABLE customers (\n'
    "    id INTEGER PRIMARY KEY,\n"
    '    name VARCHAR(100)\n'
    ')"\n'
)


def test_parse_success_returns_preview():
    client = make_client()
    response = client.post(
        "/api/vanna/v1/ddl/parse",
        files={"file": ("DDL.csv", io.BytesIO(GOOD_CSV.encode("utf-8")), "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tables_count"] == 2
    assert data["columns_count"] == 3  # orders: id, customer_id; customers: id, name
    assert data["relations_count"] == 1
    assert data["database_name"] == "default"
    assert data["parse_id"]
    assert data["warnings"] == []
    assert {t["table_name"] for t in data["tables"]} == {"orders", "customers"}
    orders = next(t for t in data["tables"] if t["table_name"] == "orders")
    assert [c["column_name"] for c in orders["columns"]] == ["id", "customer_id"]


def test_parse_empty_csv_returns_400():
    client = make_client()
    response = client.post(
        "/api/vanna/v1/ddl/parse",
        files={"file": ("DDL.csv", io.BytesIO(b""), "text/csv")},
    )
    assert response.status_code == 400
    assert "table" in response.json()["detail"].lower()


def test_parse_unknown_encoding_or_path_never_crashes():
    # 由 parse_csv 兜底：不存在的路径不会发生（我们落盘了）；此用例验证坏行警告。
    bad_csv = (
        "table_name,ddl\n"
        'bad_table,"CREATE TABLE bad_table (id INTEGER"\n'
        'good_table,"CREATE TABLE good_table (id INTEGER, name TEXT);"\n'
    )
    client = make_client()
    response = client.post(
        "/api/vanna/v1/ddl/parse",
        files={"file": ("DDL.csv", io.BytesIO(bad_csv.encode("utf-8")), "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tables_count"] == 1
    assert data["tables"][0]["table_name"] == "good_table"
    assert "bad_table" in data["warnings"]


def test_parse_missing_file_returns_422():
    client = make_client()
    response = client.post("/api/vanna/v1/ddl/parse")
    assert response.status_code == 422
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_ddl_import.py -v`
Expected: `test_page_served` PASS；parse 相关 4 个 FAIL（404 Not Found）

- [ ] **Step 3: 实现 parse 路由**

修改 `ddl_import.py` 顶部 imports 与 `register_ddl_import_routes`：

```python
import csv
import io
import os
import tempfile
import uuid
from typing import Any, Dict, List, Tuple

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from vanna.capabilities.schema_vector_store import DdlParser
from vanna.capabilities.schema_vector_store.models import (
    SchemaRelation,
    SchemaTable,
)

# parse_id -> (tables, relations)；确认入库后移除（一次性消费）
_PENDING_PARSES: Dict[str, Tuple[List[SchemaTable], List[SchemaRelation]]] = {}


def _preview(tables: List[SchemaTable], relations: List[SchemaRelation]) -> Dict[str, Any]:
    """Build the preview payload from parsed schema objects."""
    return {
        "tables_count": len(tables),
        "columns_count": sum(len(t.columns) for t in tables),
        "relations_count": len(relations),
        "tables": [t.model_dump() for t in tables],
        "relations": [r.model_dump() for r in relations],
    }


def _diff_unparsed_tables(csv_text: str, tables: List[SchemaTable]) -> List[str]:
    """Heuristic: table_name rows in the CSV that produced no parsed table.

    Only applies to CSVs with a header carrying a table-name column; returns
    [] otherwise (headerless files cannot be diffed reliably).
    """
    rows = list(csv.reader(io.StringIO(csv_text)))
    if len(rows) < 2:
        return []
    first_row_lower = [cell.lower() for cell in rows[0]]
    if any("create table" in cell.replace("  ", " ") for cell in first_row_lower):
        return []  # headerless
    fieldnames = [name.strip().lower() for name in rows[0]]
    for key in ("table_name", "table", "table_fullname"):
        if key in fieldnames:
            idx = fieldnames.index(key)
            parsed = {t.table_name for t in tables}
            candidates = {
                row[idx].strip() for row in rows[1:] if len(row) > idx and row[idx].strip()
            }
            return sorted(candidates - parsed)
    return []


class IngestRequest(BaseModel):
    parse_id: str = Field(description="parse_id returned by /ddl/parse")
    database_name: str = Field(default="default", description="Vector store namespace")
```

然后在 `register_ddl_import_routes` 内、页面路由之后追加：

```python
    @app.post("/api/vanna/v1/ddl/parse")
    async def ddl_parse(file: UploadFile = File(...)) -> Dict[str, Any]:
        """Parse the uploaded DDL.csv and stage the result for ingest."""
        contents = await file.read()
        text = contents.decode("utf-8")
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(text)
                tmp_path = tmp.name
            tables, relations = DdlParser().parse_csv(tmp_path)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

        if not tables:
            raise HTTPException(status_code=400, detail="No tables could be parsed from the CSV")

        preview = _preview(tables, relations)
        parse_id = uuid.uuid4().hex
        _PENDING_PARSES[parse_id] = (tables, relations)
        preview.update(
            {
                "parse_id": parse_id,
                "database_name": "default",
                "warnings": _diff_unparsed_tables(text, tables),
            }
        )
        return preview
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_ddl_import.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/vanna/servers/fastapi/ddl_import.py tests/test_ddl_import.py
git commit -m "feat: add DDL parse API with preview and in-memory staging"
```

---

## Task 3: ingest API（确认写入向量库）

**Files:**
- Modify: `src/vanna/servers/fastapi/ddl_import.py`
- Test: `tests/test_ddl_import.py`（追加）

- [ ] **Step 1: 写失败测试（成功 / 未知 parse_id / 无 store / 一次性消费）**

追加：

```python
def _parse_then(client, csv_text=GOOD_CSV):
    """Parse and return (client, parse_id, preview)."""
    response = client.post(
        "/api/vanna/v1/ddl/parse",
        files={"file": ("DDL.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
    )
    data = response.json()
    return data["parse_id"], data


def test_ingest_success_writes_to_store():
    store = FakeStore()
    client = make_client(FakeAgent(schema_vector_store=store))
    parse_id, _ = _parse_then(client)
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "database_name": "chinook"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["database_name"] == "chinook"
    assert data["tables_count"] == 2
    assert data["relations_count"] == 1
    assert len(store.ingested) == 1
    ingested = store.ingested[0]
    assert ingested["database_name"] == "chinook"
    assert {t.table_name for t in ingested["tables"]} == {"orders", "customers"}


def test_ingest_unknown_parse_id_returns_400():
    client = make_client()
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": "nope", "database_name": "default"},
    )
    assert response.status_code == 400


def test_ingest_without_store_returns_503():
    client = make_client(FakeAgent(schema_vector_store=None))
    parse_id, _ = _parse_then(client)
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "database_name": "default"},
    )
    assert response.status_code == 503
    assert "vector" in response.json()["detail"].lower()


def test_ingest_consumes_parse_id():
    store = FakeStore()
    client = make_client(FakeAgent(schema_vector_store=store))
    parse_id, _ = _parse_then(client)
    assert client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "database_name": "default"},
    ).status_code == 200
    second = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "database_name": "default"},
    )
    assert second.status_code == 400  # already consumed
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_ddl_import.py -v`
Expected: 前 5 个 PASS；ingest 4 个 FAIL（404）

- [ ] **Step 3: 实现 ingest 路由**

在 `register_ddl_import_routes` 内继续追加：

```python
    @app.post("/api/vanna/v1/ddl/ingest")
    async def ddl_ingest(request_body: IngestRequest) -> Dict[str, Any]:
        """Ingest a previously parsed DDL preview into the vector store."""
        store = getattr(agent, "schema_vector_store", None)
        if store is None:
            raise HTTPException(
                status_code=503,
                detail="Current service has no schema vector store configured; "
                "start with VECTOR_BACKEND=faiss (or inject schema_vector_store) to ingest",
            )
        staged = _PENDING_PARSES.pop(request_body.parse_id, None)
        if staged is None:
            raise HTTPException(
                status_code=400,
                detail="Unknown or already-consumed parse_id; parse the CSV again",
            )
        tables, relations = staged
        try:
            await store.ingest_schema(tables, relations, request_body.database_name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ingest failed: {e}") from e
        return {
            "database_name": request_body.database_name,
            "tables_count": len(tables),
            "columns_count": sum(len(t.columns) for t in tables),
            "relations_count": len(relations),
            "message": "Ingested successfully; AutoLink can now search this namespace",
        }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_ddl_import.py -v`
Expected: 9 passed

- [ ] **Step 5: 提交**

```bash
git add src/vanna/servers/fastapi/ddl_import.py tests/test_ddl_import.py
git commit -m "feat: add DDL ingest API writing parsed schema into agent vector store"
```

---

## Task 4: 页面前端交互（预览渲染 + 确认入库）

**Files:**
- Modify: `src/vanna/servers/fastapi/ddl_import.py`（替换 `_INDEX_HTML`）
- Test: `tests/test_ddl_import.py`（追加 1 个页面静态检查）

- [ ] **Step 1: 写失败测试（页面包含交互所需元素）**

追加：

```python
def test_page_contains_interaction_elements():
    html = make_client().get("/ddl-import").text
    for marker in (
        "id=\"ddl-file\"",
        "id=\"database-name\"",
        "id=\"parse-btn\"",
        "id=\"ingest-btn\"",
        "id=\"preview\"",
        "id=\"result\"",
        "/api/vanna/v1/ddl/parse",
        "/api/vanna/v1/ddl/ingest",
        "fetch(",
        "parse_id",
    ):
        assert marker in html, f"missing {marker}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_ddl_import.py::test_page_contains_interaction_elements -v`
Expected: FAIL（当前 `_INDEX_HTML` 无这些元素）

- [ ] **Step 3: 实现完整页面**

用下面内容整体替换 `_INDEX_HTML`：

```python
_INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DDL Schema 导入</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
h1 { font-size: 1.4rem; }
.note { color: #666; font-size: .9rem; }
.row { display: flex; gap: .5rem; align-items: center; margin: 1rem 0; flex-wrap: wrap; }
input[type=text] { width: 220px; padding: .35rem; }
button { padding: .4rem 1rem; cursor: pointer; }
table { border-collapse: collapse; width: 100%; margin-top: .5rem; }
th, td { border: 1px solid #ddd; padding: .3rem .5rem; text-align: left; font-size: .85rem; }
.stats { display: flex; gap: 1rem; margin: 1rem 0; }
.stat { border: 1px solid #ddd; border-radius: 6px; padding: .5rem 1rem; }
.stat b { font-size: 1.2rem; }
.warn { background: #fff3cd; border: 1px solid #ffe08a; padding: .5rem; border-radius: 4px; margin: .5rem 0; }
.ok { background: #d1e7dd; border: 1px solid #a3cfbb; padding: .5rem; border-radius: 4px; margin: .5rem 0; }
.err { background: #f8d7da; border: 1px solid #f1aeb5; padding: .5rem; border-radius: 4px; margin: .5rem 0; }
details { margin: .25rem 0; }
</style>
</head>
<body>
<h1>DDL Schema 导入</h1>
<p class="note">上传 DDL.csv 解析预览，确认后写入当前服务的 schema 向量库。
写入的 database_name 需与 AutoLinkConfig.database_name 一致，入库存后 AutoLink 检索即刻生效。</p>

<div class="row">
  <input type="file" id="ddl-file" accept=".csv">
  <label>database_name <input type="text" id="database-name" value="default"></label>
  <button id="parse-btn">解析</button>
</div>

<div id="preview"></div>

<div class="row" id="ingest-row" style="display:none">
  <button id="ingest-btn">写入向量库</button>
</div>

<div id="result"></div>

<script>
let parseId = null;
const input = document.getElementById("ddl-file");
const dbName = document.getElementById("database-name");
const preview = document.getElementById("preview");
const result = document.getElementById("result");

function statsHtml(d) {
  return '<div class="stats">'
    + '<div class="stat">表 <b>' + d.tables_count + '</b></div>'
    + '<div class="stat">列 <b>' + d.columns_count + '</b></div>'
    + '<div class="stat">关系 <b>' + d.relations_count + '</b></div>'
    + '</div>';
}

function rowsHtml(rows) {
  if (!rows.length) return '';
  let html = '<table><tr><th>表</th><th>列/关系</th></tr>';
  rows.forEach(r => {
    html += '<tr><td>' + r.table_name + '</td><td><ul>'
      + r.columns.map(c => '<li>' + c.column_name + ' : ' + (c.data_type || '?') + '</li>').join('')
      + '</ul></td></tr>';
  });
  return html + '</table>';
}

function warningsHtml(warnings) {
  if (!warnings.length) return '';
  return '<div class="warn">解析失败的表（将不会被导入）：' + warnings.join(', ') + '</div>';
}

function showResult(cls, text) {
  result.innerHTML = '<div class="' + cls + '">' + text + '</div>';
}

document.getElementById("parse-btn").addEventListener("click", async () => {
  if (!input.files.length) { showResult("err", "请先选择 DDL.csv 文件"); return; }
  const form = new FormData();
  form.append("file", input.files[0]);
  showResult("ok", "解析中…");
  try {
    const resp = await fetch("/api/vanna/v1/ddl/parse", { method: "POST", body: form });
    const data = await resp.json();
    if (!resp.ok) { showResult("err", data.detail || ("parse failed: " + resp.status)); return; }
    parseId = data.parse_id;
    preview.innerHTML = statsHtml(data) + warningsHtml(data.warnings) + rowsHtml(data.tables);
    document.getElementById("ingest-row").style.display = "";
    showResult("ok", "解析成功，请确认后写入向量库（当前 namespace：" + dbName.value + "，重复导入同名 namespace 会覆盖旧索引）");
  } catch (e) {
    showResult("err", "解析请求失败：" + e);
  }
});

document.getElementById("ingest-btn").addEventListener("click", async () => {
  if (!parseId) { showResult("err", "请先解析 DDL.csv"); return; }
  showResult("ok", "写入中…");
  try {
    const resp = await fetch("/api/vanna/v1/ddl/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parse_id: parseId, database_name: dbName.value }),
    });
    const data = await resp.json();
    if (!resp.ok) { showResult("err", data.detail || ("ingest failed: " + resp.status)); return; }
    parseId = null;
    showResult("ok", "写入成功：" + data.tables_count + " 张表 / " + data.columns_count
      + " 列 / " + data.relations_count + " 关系 -> namespace [" + data.database_name + "]");
  } catch (e) {
    showResult("err", "写入请求失败：" + e);
  }
});
</script>
</body>
</html>
"""
```

注意：HTML 字符串内的 JS 使用了单引号；测试断言用的 `id="parse-btn"` 等 marker 用双引号括属性，与模板一致。替换时保持 `_INDEX_HTML = """..."""` 整段。

- [ ] **Step 4: 跑全部测试确认通过**

Run: `pytest tests/test_ddl_import.py -v`
Expected: 10 passed

- [ ] **Step 5: 提交**

```bash
git add src/vanna/servers/fastapi/ddl_import.py tests/test_ddl_import.py
git commit -m "feat: add DDL import page frontend with preview and ingest actions"
```

---

## Task 5: 注册进 FastAPI 服务 + 回归 + 手动 E2E

**Files:**
- Modify: `src/vanna/servers/fastapi/app.py`（`create_app()` 注册）
- Test: `tests/test_ddl_import.py`（追加 1 个服务级测试）

- [ ] **Step 1: 写失败测试（服务级：VannaFastAPIServer 挂载页面）**

在 `tests/test_ddl_import.py` 追加：

```python
def test_page_served_via_vanna_server():
    """The page must be reachable through VannaFastAPIServer.create_app()."""
    from vanna.servers.fastapi.app import VannaFastAPIServer

    agent = FakeAgent(schema_vector_store=FakeStore())
    server = VannaFastAPIServer(agent=agent)
    app = server.create_app()
    client = TestClient(app)
    response = client.get("/ddl-import")
    assert response.status_code == 200
    assert "DDL" in response.text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_ddl_import.py::test_page_served_via_vanna_server -v`
Expected: FAIL（404，`create_app` 未注册 ddl 路由）

- [ ] **Step 3: 注册路由**

修改 `src/vanna/servers/fastapi/app.py`：

```python
# 第 13 行之后追加 import
from .ddl_import import register_ddl_import_routes

# create_app() 中 register_chat_routes(...) 之后追加：
        register_ddl_import_routes(app, self.agent)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_ddl_import.py -v`
Expected: 11 passed

- [ ] **Step 5: 回归验证（受影响面，无回归要求）**

Run: `pytest tests/test_ddl_import.py tests/test_agent_auto_tools.py tests/test_schema_vector_store.py -q`
Expected: 全部 PASS（faiss 未装时 `test_vector_backend_derives_faiss_stores` skipped 属预期）

说明：仓库没有 server 层测试文件（`tests/` 下无 `test_chat_handler.py`/`test_server_base.py`，grep 确认为空），server 层回归由本计划 `test_page_served_via_vanna_server` 覆盖。本任务改动不影响 agent 装配与 schema store 内部逻辑，无需跑全量套件。

- [ ] **Step 6: 手动 E2E（本机验证）**

本机无 faiss（启动日志此前显示 "faiss unavailable"），因此 E2E 验证"无向量库"与"页面可用"路径：

1. 启动服务：
   Run: `python -m vanna.servers.cli.server_runner --host 127.0.0.1 --port 8080`（非阻塞，观察启动日志）
2. 打开 `http://127.0.0.1:8080/ddl-import`，确认页面渲染正常、有文件选择与 database_name 输入框。
3. 用 PowerShell 上传真实 CSV 验证 parse API：

```powershell
$csv = @"
table_name,ddl
artists,"CREATE TABLE artists (id INTEGER PRIMARY KEY, name NVARCHAR(120));"
albums,"CREATE TABLE albums (id INTEGER PRIMARY KEY, title NVARCHAR(160), artist_id INTEGER, FOREIGN KEY (artist_id) REFERENCES artists(id));"
"@
$tmp = "$env:TEMP\ddl_e2e.csv"; Set-Content -Path $tmp -Value $csv -Encoding UTF8
Invoke-RestMethod -Uri http://127.0.0.1:8080/api/vanna/v1/ddl/parse -Method Post -Form @{file = Get-Item $tmp}
```

Expected: JSON 含 `tables_count: 2`、`columns_count: 4`、`relations_count: 1`、`warnings: []`。

4. 验证 ingest 无 store 分支：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8080/api/vanna/v1/ddl/ingest -Method Post -ContentType "application/json" -Body '{"parse_id":"<上一步返回的 parse_id>","database_name":"chinook"}'
```

Expected: HTTP 503，detail 含 "no schema vector store configured"（本机未装 faiss 属预期）。

5. 停止服务进程。

（若本机已装 faiss + sentence-transformers：改用 `VECTOR_BACKEND=faiss` 启动，重复步骤 3-4，期望 ingest 返回 200 且后续 `explore_schema_links` 可搜到；该路径由 `test_schema_vector_store.py` 中的 store 集成测试兜底。）

- [ ] **Step 7: 提交**

```bash
git add src/vanna/servers/fastapi/app.py tests/test_ddl_import.py
git commit -m "feat: register DDL import page in VannaFastAPIServer"
```

---

## 收尾检查（全部任务完成后）

- [ ] `pytest tests/test_ddl_import.py -v`：11 passed
- [ ] `git status` 干净（无未提交变更）
- [ ] 向用户汇报：新增页面/路由清单、如何启用（`VECTOR_BACKEND=faiss` + `DATABASE_URL`）、docs 里 `.env` 说明是否需要补充