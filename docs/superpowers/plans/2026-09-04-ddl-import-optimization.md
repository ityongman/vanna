# DDL 导入页面优化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `.trae/requirements/require_desc.md` 优化 DDL 导入：强制三列 CSV 校验、业务配置自动创建/启用、向量库 insert_update 增量合并、Steps 向导式页面。

**Architecture:** 后端在 `ddl_import.py` 的 parse/ingest 两个端点完成严格校验与合并导入；app.json 读写逻辑提取到公共模块 `config_sync.py` 供 business_routes 与 ddl_import 共用；前端 DdlImport 页重写为 Steps 向导。

**Tech Stack:** Python/FastAPI/pytest；React 19 + TypeScript + antd v5（vite 构建）。

**设计文档:** `docs/superpowers/specs/2026-09-04-ddl-import-optimization-design.md`

---

### Task 1: 更新测试基线（三列 CSV + 新增失败测试）

**Files:**
- Modify: `tests/test_ddl_import.py`

- [ ] **Step 1: 更新基线 CSV 为三列格式**

将 `GOOD_CSV` 替换为（含 db_name 列）：

```python
GOOD_CSV = (
    "db_name,table_name,ddl\n"
    'mydb,orders,"CREATE TABLE orders (\n'
    "    id INTEGER PRIMARY KEY,\n"
    "    customer_id INTEGER\n"
    ')"\n'
    'mydb,customers,"CREATE TABLE customers (\n'
    "    id INTEGER PRIMARY KEY,\n"
    '    name VARCHAR(100)\n'
    ')"\n'
)
```

`test_parse_success_returns_preview` 增加断言 `assert data["db_name"] == "mydb"`。

`test_parse_unknown_encoding_or_path_never_crashes` 中的 `bad_csv` 替换为：

```python
bad_csv = (
    "db_name,table_name,ddl\n"
    'mydb,bad_table,"CREATE TABLE bad_table (id INTEGER"\n'
    'mydb,good_table,"CREATE TABLE good_table (id INTEGER, name TEXT);"\n'
)
```

- [ ] **Step 2: 移除 /ddl/check 相关测试与辅助函数**

删除：`_multi_business_client`、`test_check_reports_likely_business_when_selected_is_wrong`、`test_check_confirms_correct_business`、`test_check_unknown_parse_id_returns_400`、`test_check_unknown_business_returns_400`、`test_check_does_not_consume_parse_id`、`test_check_without_store_returns_503`。保留 `IndexedStore`（供合并测试使用）。

- [ ] **Step 3: 添加 import 与新增失败测试（先写测试，预期失败）**

文件头部 import 增加 `import json`、`import pytest`（如尚无）。

在文件末尾追加以下测试：

```python
MISSING_DB_NAME_CSV = 'table_name,ddl\norders,"CREATE TABLE orders (id INTEGER)"\n'
MISSING_TABLE_NAME_CSV = 'db_name,ddl\nmydb,"CREATE TABLE orders (id INTEGER)"\n'
MISSING_DDL_CSV = "db_name,table_name\nmydb,orders\n"
EMPTY_DDL_CSV = (
    'db_name,table_name,ddl\n'
    'mydb,orders,"CREATE TABLE orders (id INTEGER)"\n'
    "mydb,customers,\n"
)
MULTI_DB_CSV = (
    "db_name,table_name,ddl\n"
    'mydb,orders,"CREATE TABLE orders (id INTEGER)"\n'
    'otherdb,customers,"CREATE TABLE customers (id INTEGER)"\n'
)


def _post_parse(client, csv_text):
    return client.post(
        "/api/vanna/v1/ddl/parse",
        files={"file": ("DDL.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
    )


def _tmp_app_config(tmp_path, monkeypatch, config=None):
    """把 APP_CONFIG_PATH 指向临时 app.json，隔离对仓库真实配置文件的读写。"""
    cfg_path = tmp_path / "app.json"
    cfg_path.write_text(json.dumps(config or {}), encoding="utf-8")
    monkeypatch.setenv("APP_CONFIG_PATH", str(cfg_path))
    return cfg_path


@pytest.mark.parametrize(
    "csv_text,missing_col",
    [
        (MISSING_DB_NAME_CSV, "db_name"),
        (MISSING_TABLE_NAME_CSV, "table_name"),
        (MISSING_DDL_CSV, "ddl"),
    ],
)
def test_parse_missing_required_column_returns_400(csv_text, missing_col):
    client = make_client()
    response = _post_parse(client, csv_text)
    assert response.status_code == 400
    assert missing_col in response.json()["detail"]


def test_parse_empty_ddl_row_returns_400():
    client = make_client()
    response = _post_parse(client, EMPTY_DDL_CSV)
    assert response.status_code == 400
    assert "第 3 行 ddl 为空" in response.json()["detail"]


def test_parse_multiple_db_names_returns_400():
    client = make_client()
    response = _post_parse(client, MULTI_DB_CSV)
    assert response.status_code == 400
    assert "多个不同的 db_name" in response.json()["detail"]


def test_parse_reports_business_state_active(monkeypatch, tmp_path):
    store = FakeStore()
    agent = FakeAgent(
        schema_vector_store=store,
        businesses={"mydb": _business("mydb", "ns_mydb")},
    )
    client = make_client(agent)
    _tmp_app_config(tmp_path, monkeypatch)
    data = _post_parse(client, GOOD_CSV).json()
    assert data["db_name"] == "mydb"
    assert data["business_state"] == "active"
    assert data["business_id"] == "mydb"


def test_parse_reports_business_state_missing(monkeypatch, tmp_path):
    client = make_client()  # agent 只配置了 biz_a
    _tmp_app_config(tmp_path, monkeypatch)
    data = _post_parse(client, GOOD_CSV).json()
    assert data["business_state"] == "missing"


def test_parse_reports_business_state_disabled_from_app_json(monkeypatch, tmp_path):
    cfg = {
        "storage": {
            "businesses": [
                {
                    "id": "mydb",
                    "enabled": False,
                    "database": {"url": "sqlite:///data/db/mydb.db"},
                    "schema_vector": {"namespace": "ns_mydb", "backend": None},
                }
            ]
        }
    }
    client = make_client()  # mydb 未加载进 agent
    _tmp_app_config(tmp_path, monkeypatch, cfg)
    data = _post_parse(client, GOOD_CSV).json()
    assert data["business_state"] == "disabled"


def test_ingest_merges_into_existing_namespace():
    store = IndexedStore({"ns_a": ["legacy", "orders"]})
    client = make_client(
        FakeAgent(
            schema_vector_store=store,
            businesses={"biz_a": _business("biz_a", "ns_a")},
        )
    )
    parse_id, _ = _parse_then(client)
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "business_id": "biz_a"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["added_tables"] == ["customers"]
    assert data["updated_tables"] == ["orders"]
    assert data["kept_tables"] == ["legacy"]
    assert data["merge_warning"] is None
    ingested_names = {
        t.table_name for t in store.ingested[-1]["tables"]
    }
    assert ingested_names == {"orders", "customers", "legacy"}


def test_ingest_merge_fallback_when_list_tables_unsupported():
    store = FakeStore()  # 未实现 list_tables（基类抛 NotImplementedError）
    client = make_client(FakeAgent(schema_vector_store=store))
    parse_id, _ = _parse_then(client)
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "business_id": "biz_a"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["added_tables"] == ["customers", "orders"]
    assert data["updated_tables"] == []
    assert data["merge_warning"]


def test_enable_after_ingest(monkeypatch, tmp_path):
    cfg = {
        "storage": {
            "businesses": [
                {
                    "id": "biz_a",
                    "enabled": False,
                    "database": {"url": "sqlite:///data/db/a.db"},
                    "schema_vector": {"namespace": "ns_a", "backend": None},
                }
            ]
        }
    }
    cfg_path = _tmp_app_config(tmp_path, monkeypatch, cfg)
    store = FakeStore()
    client = make_client(
        FakeAgent(
            schema_vector_store=store,
            businesses={"biz_a": _business("biz_a", "ns_a")},
        )
    )
    parse_id, _ = _parse_then(client)
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "business_id": "biz_a"},
    )
    assert response.status_code == 200
    saved = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert saved["storage"]["businesses"][0]["enabled"] is True


def test_namespace_fallback_to_app_json_for_disabled_business(
    monkeypatch, tmp_path
):
    cfg = {
        "storage": {
            "businesses": [
                {
                    "id": "other_biz",
                    "enabled": False,
                    "database": {"url": "sqlite:///data/db/other.db"},
                    "schema_vector": {"namespace": "ns_other", "backend": None},
                }
            ]
        }
    }
    _tmp_app_config(tmp_path, monkeypatch, cfg)
    client = make_client(FakeAgent(schema_vector_store=FakeStore()))
    parse_id, _ = _parse_then(client)
    response = client.post(
        "/api/vanna/v1/ddl/ingest",
        json={"parse_id": parse_id, "business_id": "other_biz"},
    )
    assert response.status_code == 200
    assert response.json()["database_name"] == "ns_other"
```

- [ ] **Step 4: 运行测试验证失败**

Run: `python -m pytest tests/test_ddl_import.py -q`
Expected: 新增的校验/合并/business_state 测试 FAIL（`db_name` 不在响应、400 未触发、merge 字段缺失等）；旧的 check 测试已删除不再出现。

---

### Task 2: 提取 config_sync 模块并重构 business_routes

**Files:**
- Create: `src/vanna/servers/fastapi/config_sync.py`
- Modify: `src/vanna/servers/fastapi/business_routes.py`

- [ ] **Step 1: 创建 config_sync.py**

完整内容：

```python
"""Shared app.json (business configuration) read/write helpers.

``business_routes`` and the DDL import flow both mutate
``storage.businesses`` in app.json and hot-reload the running agent, so
the file I/O lives here to avoid duplicated config-handling logic.
"""

import json
import os
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

# Default config path (matches server_runner.py)
_DEFAULT_APP_CONFIG_PATH = "config/app.json"


def config_path() -> str:
    """Resolve the app.json path (overridable via APP_CONFIG_PATH)."""
    return os.getenv("APP_CONFIG_PATH") or _DEFAULT_APP_CONFIG_PATH


def load_app_config() -> Dict[str, Any]:
    """Load app.json; a missing file yields an empty config."""
    path = config_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to read app config: {e}"
        ) from e


def save_app_config(config: Dict[str, Any]) -> None:
    """Persist app.json (pretty-printed, UTF-8)."""
    path = config_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except OSError as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to save app config: {e}"
        ) from e


def get_businesses_from_config(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract the storage.businesses list from a config dict."""
    storage = config.get("storage") or {}
    return storage.get("businesses") or []


def sync_agent_businesses(agent, config: Dict[str, Any]) -> None:
    """Hot-reload businesses (enabled or not) into the running agent."""
    from vanna.core.agent.config import BusinessConfig

    new_businesses = {}
    for biz_data in get_businesses_from_config(config):
        biz_id = biz_data.get("id")
        if biz_id:
            try:
                new_businesses[biz_id] = BusinessConfig(**biz_data)
            except Exception:
                pass  # Skip invalid entries
    agent.config.businesses = new_businesses


def _find_business(config: Dict[str, Any], business_id: str):
    """First business entry whose id matches (case-insensitive)."""
    for biz in get_businesses_from_config(config):
        if str(biz.get("id", "")).lower() == business_id.lower():
            return biz
    return None


def set_business_enabled(agent, business_id: str, enabled: bool) -> bool:
    """Set ``enabled`` for one business in app.json and hot-reload.

    Returns True when the business exists in app.json.
    """
    config = load_app_config()
    biz = _find_business(config, business_id)
    if biz is None:
        return False
    biz["enabled"] = enabled
    save_app_config(config)
    sync_agent_businesses(agent, config)
    return True


def resolve_business_namespace_from_config(business_id: str) -> Optional[str]:
    """Namespace from app.json for a business (disabled entries included).

    Returns None when the file is unreadable or the business is unknown.
    """
    try:
        config = load_app_config()
    except HTTPException:
        return None
    biz = _find_business(config, business_id)
    if biz is None:
        return None
    schema_vector = biz.get("schema_vector") or {}
    return schema_vector.get("namespace") or None
```

- [ ] **Step 2: 重构 business_routes.py 复用 config_sync**

顶端 import 区增加：

```python
from .config_sync import (
    get_businesses_from_config,
    load_app_config,
    save_app_config,
    sync_agent_businesses,
)
```

删除本地定义：`_DEFAULT_APP_CONFIG_PATH`、`_load_app_config`、`_save_app_config`、`_get_businesses_from_config`、`_sync_agent_businesses`，并删除不再使用的 `import json` / `import os`（若文件其余处不再用到）。

函数体内调用同步改名：
- `_load_app_config()` → `load_app_config()`
- `_save_app_config(config)` → `save_app_config(config)`
- `_get_businesses_from_config(config)` → `get_businesses_from_config(config)`
- `_sync_agent_businesses(agent, config)` → `sync_agent_businesses(agent, config)`

（保留 `_update_business_in_config` 等仅本地使用的辅助。）

- [ ] **Step 3: 运行既有测试确认无回归**

Run: `python -m pytest tests/ -q -k "business"`（若存在 business 相关测试）；至少运行 `python -m pytest tests/test_ddl_import.py -q -k "page or ingest or parse"` 确认 business_routes 引入无误（business_routes 在 app 注册时被 import）。

Expected: 除 Task 1 中预期失败的新用例外，其余全 PASS。

---

### Task 3: ddl_parse 严格校验 + business_state + 移除旧逻辑

**Files:**
- Modify: `src/vanna/servers/fastapi/ddl_import.py`

- [ ] **Step 1: 更新 import**

```python
from .config_sync import (
    resolve_business_namespace_from_config,
    set_business_enabled,
)
```

删除不再使用的 `import json`（仅 `_auto_enable_business` 用到，本任务一并删除）。

- [ ] **Step 2: 添加校验与业务状态辅助函数**

在 `_preview` 之后、`ddl_parse` 之前添加：

```python
_DB_NAME_KEYS = [
    "db_name", "database_id", "database", "database_name", "db", "db_id",
]
_TABLE_NAME_KEYS = ["table_name", "table", "table_fullname"]
_DDL_KEYS = ["ddl"]


def _validate_csv_text(text: str):
    """严格校验 CSV（db_name/table_name/ddl 三列 + 行级非空）。

    返回 (db_name, None)。校验失败时抛 HTTPException(400)。
    """
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        raise HTTPException(
            status_code=400,
            detail=(
                "CSV 文件为空或缺少表头；请确保包含 db_name、table_name、ddl 三列"
            ),
        )
    header = [name.strip().lower() for name in rows[0]]

    def _find_col(keys):
        for key in keys:
            if key in header:
                return header.index(key)
        return None

    idx_cols = {}
    missing = []
    for label, keys in (
        ("db_name", _DB_NAME_KEYS),
        ("table_name", _TABLE_NAME_KEYS),
        ("ddl", _DDL_KEYS),
    ):
        idx = _find_col(keys)
        if idx is None:
            missing.append(label)
        else:
            idx_cols[label] = idx
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"缺少必需列：{', '.join(missing)}（识别到表头："
                f"{', '.join(header)}）。请确保 CSV 包含 db_name、table_name、ddl 三列"
            ),
        )

    errors = []
    db_names = set()
    for row_no, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue  # 跳过空行
        for label in ("db_name", "table_name", "ddl"):
            idx = idx_cols[label]
            if idx >= len(row) or not row[idx].strip():
                errors.append(f"第 {row_no} 行 {label} 为空")
        if idx_cols["db_name"] < len(row):
            db_name = row[idx_cols["db_name"]].strip()
            if db_name:
                db_names.add(db_name)

    if errors:
        shown = "; ".join(errors[:10])
        more = f"（共 {len(errors)} 处）" if len(errors) > 10 else ""
        raise HTTPException(
            status_code=400,
            detail=f"文件存在问题，请检查文件内容：{shown}{more}",
        )

    if len(db_names) > 1:
        raise HTTPException(
            status_code=400,
            detail=(
                f"CSV 包含多个不同的 db_name（{', '.join(sorted(db_names))}），"
                "一个文件只能对应一个数据库"
            ),
        )
    if not db_names:
        raise HTTPException(
            status_code=400,
            detail="CSV 没有有效的数据行",
        )
    return (sorted(db_names)[0])


def _business_state(agent, db_name: str) -> Dict[str, Any]:
    """判断 db_name 对应业务配置的状态：active/disabled/missing。"""
    businesses = getattr(getattr(agent, "config", None), "businesses", {}) or {}
    for biz_id, biz in businesses.items():
        if str(biz_id).lower() == db_name.lower():
            enabled = bool(getattr(biz, "enabled", True))
            return {
                "business_id": biz_id,
                "business_state": "active" if enabled else "disabled",
            }
    if resolve_business_namespace_from_config(db_name):
        return {"business_id": db_name, "business_state": "disabled"}
    return {"business_id": db_name, "business_state": "missing"}
```

- [ ] **Step 3: 改造 ddl_parse**

解码 UTF-8 后、写临时文件前插入校验：

```python
    db_name = _validate_csv_text(text)
```

响应字典增加：

```python
    result = {
        **preview,
        "parse_id": parse_id,
        "warnings": _diff_unparsed_tables(text, tables) or [],
        "db_name": db_name,
        **_business_state(agent, db_name),
    }
```

（原响应中的 `db_names` / `has_db_name_column` 字段删除。）

- [ ] **Step 4: 移除旧逻辑**

删除：`CheckRequest` 模型、`/api/vanna/v1/ddl/check` 端点、`_extract_db_names`、`_auto_enable_business`。

- [ ] **Step 5: 运行 Task 1 的校验类测试**

Run: `python -m pytest tests/test_ddl_import.py -q -k "required or empty_ddl or multiple_db or business_state"`
Expected: 全部 PASS。

---

### Task 4: ddl_ingest 增量合并 + enabled 流转 + namespace 兜底

**Files:**
- Modify: `src/vanna/servers/fastapi/ddl_import.py`

- [ ] **Step 1: 添加合并辅助函数**

在 `_resolve_business_namespace` 附近添加：

```python
async def _merge_schema(store, tables, relations, database_name):
    """把新解析的表合并进命名空间已有数据（insert_update 语义）。

    返回 (merged_tables, merged_relations, added, updated, kept)；
    store 不支持 list_tables 时返回 None（调用方整库覆盖）。
    """
    try:
        existing = await store.list_tables(database_name) or []
        old_rels = (
            await store.get_relations(
                [t.table_name for t in existing], database_name
            )
            or []
        )
    except Exception:
        return None
    old_names = {t.table_name.lower() for t in existing}
    new_names = {t.table_name.lower() for t in tables}
    merged = {t.table_name.lower(): t for t in existing}
    merged.update({t.table_name.lower(): t for t in tables})  # 同名覆盖
    kept_rels = [
        r
        for r in old_rels
        if r.from_table.lower() not in new_names
        and r.to_table.lower() not in new_names
    ]
    added = sorted(new_names - old_names)
    updated = sorted(new_names & old_names)
    kept = sorted(old_names - new_names)
    return list(merged.values()), kept_rels + list(relations), added, updated, kept
```

- [ ] **Step 2: 修改 _resolve_business_namespace（大小写不敏感 + app.json 兜底）**

替换现有函数为：

```python
def _resolve_business_namespace(agent, business_id: str) -> str:
    businesses = getattr(getattr(agent, "config", None), "businesses", {}) or {}
    for biz_id, business in businesses.items():
        if str(biz_id).lower() == business_id.lower():
            return business.effective_database_name()
    # 配置存在但未加载（如 enabled=false 的新业务）：从 app.json 兜底读取
    namespace = resolve_business_namespace_from_config(business_id)
    if namespace:
        return namespace
    available = ", ".join(sorted(businesses)) or "none"
    raise HTTPException(
        status_code=400,
        detail=f"Business `{business_id}` does not exist. Available: {available}",
    )
```

- [ ] **Step 3: 改造 ddl_ingest 主体**

将现有 `await store.ingest_schema(tables, relations, database_name)` 及后续响应替换为：

```python
    merge_warning = None
    merged = await _merge_schema(store, tables, relations, database_name)
    if merged is None:
        # list_tables 不可用：回退为整库覆盖
        await store.ingest_schema(tables, relations, database_name)
        added = sorted(t.table_name for t in tables)
        updated = []
        kept = []
        merge_warning = "当前向量库后端不支持增量合并，已整库覆盖原有索引"
    else:
        merged_tables, merged_rels, added, updated, kept = merged
        await store.ingest_schema(merged_tables, merged_rels, database_name)

    # 导入成功后启用业务（新业务以 enabled=false 创建，此处翻转）
    set_business_enabled(agent, request_body.business_id, True)

    return {
        "database_name": database_name,
        "tables_count": len(tables),
        "columns_count": sum(len(t.columns) for t in tables),
        "relations_count": len(relations),
        "added_tables": added,
        "updated_tables": updated,
        "kept_tables": kept,
        "merge_warning": merge_warning,
        "message": "Ingested successfully; AutoLink can now search this "
        "namespace",
    }
```

- [ ] **Step 4: 运行合并相关测试**

Run: `python -m pytest tests/test_ddl_import.py -q -k "merge or enable_after or fallback"`
Expected: 全部 PASS。

- [ ] **Step 5: 运行全量后端测试**

Run: `python -m pytest tests/test_ddl_import.py -q`
Expected: 全部 PASS。

---

### Task 5: 前端 DdlImport 页重写为 Steps 向导

**Files:**
- Modify: `frontends/web/src/pages/DdlImport/index.tsx`

- [ ] **Step 1: 整体重写文件**

用以下完整内容覆盖 `frontends/web/src/pages/DdlImport/index.tsx`：

```tsx
import { useEffect, useState } from 'react';
import {
  Alert, Button, Card, Col, Descriptions, Form, Input, Result, Row, Space,
  Steps, Table, Tag, Typography, Upload, message,
} from 'antd';
import {
  CheckCircleOutlined, DownloadOutlined, ReloadOutlined,
  UploadOutlined, WarningOutlined,
} from '@ant-design/icons';
import Modal from 'antd/es/modal';
import { useAuth } from '../../lib/auth';

const { Title, Text } = Typography;

interface ColumnInfo {
  column_name: string;
  data_type: string;
}

interface PreviewTable {
  table_name: string;
  columns: ColumnInfo[];
}

interface ParseResult {
  parse_id: string;
  db_name: string;
  business_id: string;
  business_state: 'active' | 'disabled' | 'missing';
  tables_count: number;
  columns_count: number;
  relations_count: number;
  tables: PreviewTable[];
  warnings: string[];
}

interface IngestResult {
  database_name: string;
  tables_count: number;
  columns_count: number;
  relations_count: number;
  added_tables: string[];
  updated_tables: string[];
  kept_tables: string[];
  merge_warning: string | null;
}

const SAMPLE_CSV = [
  'db_name,table_name,ddl',
  '"mydb","orders","CREATE TABLE orders (',
  '    id INTEGER PRIMARY KEY,',
  '    customer_id INTEGER',
  ')"',
  '',
].join('\n');

function downloadSample() {
  const blob = new Blob(['\ufeff' + SAMPLE_CSV], {
    type: 'text/csv;charset=utf-8',
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'ddl_sample.csv';
  a.click();
  URL.revokeObjectURL(url);
}

const BUSINESS_STATE_META: Record<
  ParseResult['business_state'],
  { color: string; text: string }
> = {
  active: { color: 'success', text: '已配置（启用中）' },
  disabled: { color: 'warning', text: '已配置（未启用）' },
  missing: { color: 'default', text: '未配置（将新建）' },
};

export default function DdlImportPage() {
  const { user, refresh } = useAuth();
  const [current, setCurrent] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [parseLoading, setParseLoading] = useState(false);
  const [ingestLoading, setIngestLoading] = useState(false);
  const [preview, setPreview] = useState<ParseResult | null>(null);
  const [ingestResult, setIngestResult] = useState<IngestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newBusinessForm] = Form.useForm();

  const resetToUpload = () => {
    setFile(null);
    setPreview(null);
    setIngestResult(null);
    setError(null);
    setCurrent(0);
    newBusinessForm.resetFields();
  };

  // 解析结果变化时，预填新业务表单默认值
  useEffect(() => {
    if (preview?.business_state === 'missing') {
      newBusinessForm.setFieldsValue({
        id: preview.db_name,
        dbPath: `data/db/${preview.db_name}.db`,
        namespace: preview.db_name,
      });
    }
  }, [preview, newBusinessForm]);

  async function handleParse() {
    if (!file) {
      message.warning('请先选择 CSV 文件');
      return;
    }
    const formData = new FormData();
    formData.append('file', file);
    setParseLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/vanna/v1/ddl/parse', {
        method: 'POST',
        body: formData,
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        setError(data?.detail || `解析失败（HTTP ${response.status}）`);
        return;
      }
      setPreview(data);
      setCurrent(1);
    } catch (e) {
      setError('网络异常，请重试');
    } finally {
      setParseLoading(false);
    }
  }

  async function doIngest(businessId: string) {
    if (!preview) return;
    setIngestLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/vanna/v1/ddl/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parse_id: preview.parse_id,
          business_id: businessId,
        }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        setError(data?.detail || `导入失败（HTTP ${response.status}）`);
        return;
      }
      setIngestResult(data);
      setCurrent(2);
      await refresh();
    } catch (e) {
      setError('网络异常，导入失败');
    } finally {
      setIngestLoading(false);
    }
  }

  async function handleCreateAndIngest() {
    try {
      const values = await newBusinessForm.validateFields();
      setIngestLoading(true);
      setError(null);
      const createResponse = await fetch('/api/businesses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: values.id,
          database_url: `sqlite:///${values.dbPath}`,
          namespace: values.namespace,
        }),
      });
      const createData = await createResponse.json().catch(() => null);
      if (!createResponse.ok) {
        setError(createData?.detail || '创建业务配置失败');
        return;
      }
      await refresh();
      await doIngest(values.id);
    } catch (e) {
      setError('请填写完整的新业务配置');
    } finally {
      setIngestLoading(false);
    }
  }

  function handleConfirmImport() {
    if (!preview) return;
    if (preview.business_state === 'missing') {
      handleCreateAndIngest();
      return;
    }
    const hint =
      preview.business_state === 'disabled'
        ? '该业务配置已存在但未启用，导入成功后会自动启用。'
        : '已存在同名业务，本次导入将增量合并：新增表追加、同名表覆盖、其余表保留。';
    Modal.confirm({
      title: '确认导入到向量库',
      icon: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
      content: (
        <div>
          <p>
            数据库名 <Text strong>{preview.db_name}</Text> 对应业务{' '}
            <Text strong>{preview.business_id}</Text>。
          </p>
          <p>{hint}</p>
        </div>
      ),
      okText: '确认导入',
      cancelText: '取消',
      onOk: () => doIngest(preview.business_id),
    });
  }

  const isAdmin = Boolean(user?.is_admin);

  const stepsItems = [
    { title: '上传 CSV' },
    { title: '解析预览' },
    { title: '导入结果' },
  ];

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: '24px 16px' }}>
      <Title level={3}>DDL 导入</Title>
      <Text type="secondary">
        上传数据库 DDL 语句 CSV，一键将表结构导入到向量库，供 Text-to-SQL 检索使用。
      </Text>
      <Steps
        style={{ margin: '24px 0' }}
        current={current}
        items={stepsItems}
      />
      {error && (
        <Alert
          style={{ marginBottom: 16 }}
          type="error"
          showIcon
          message="操作失败"
          description={error}
          closable
          onClose={() => setError(null)}
        />
      )}

      {current === 0 && (
        <Card title="上传 DDL CSV 文件">
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="CSV 格式要求"
            description={
              <div>
                <p>文件必须包含 <Text code>db_name</Text>、<Text code>table_name</Text>、<Text code>ddl</Text> 三列，缺任一列或 ddl 为空将被拒绝。</p>
                <p>含逗号、换行的 DDL 请用双引号包裹；一个文件只能包含一个 db_name。</p>
                <Button
                  type="link"
                  size="small"
                  icon={<DownloadOutlined />}
                  onClick={downloadSample}
                  style={{ padding: 0 }}
                >
                  下载示例 CSV
                </Button>
              </div>
            }
          />
          <Upload.Dragger
            accept=".csv"
            maxCount={1}
            fileList={file ? [{ uid: '-1', name: file.name }] : []}
            beforeUpload={(f) => {
              setFile(f);
              setPreview(null);
              setIngestResult(null);
              setError(null);
              return false; // 手动控制上传时机
            }}
            onRemove={() => {
              setFile(null);
              setPreview(null);
              setIngestResult(null);
            }}
          >
            <p className="ant-upload-drag-icon">
              <UploadOutlined />
            </p>
            <p className="ant-upload-text">点击或拖拽 CSV 文件到此处</p>
          </Upload.Dragger>
          <div style={{ marginTop: 16, textAlign: 'right' }}>
            <Button
              type="primary"
              loading={parseLoading}
              disabled={!file}
              onClick={handleParse}
            >
              解析并预览
            </Button>
          </div>
        </Card>
      )}

      {current === 1 && preview && (
        <Row gutter={16}>
          <Col xs={24} lg={15}>
            <Card
              title="解析结果"
              extra={
                <Button size="small" onClick={resetToUpload}>
                  <ReloadOutlined /> 重新上传
                </Button>
              }
            >
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={8}><b>表数量：</b>{preview.tables_count}</Col>
                <Col span={8}><b>列数量：</b>{preview.columns_count}</Col>
                <Col span={8}><b>关系数量：</b>{preview.relations_count}</Col>
              </Row>
              {preview.warnings.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 16 }}
                  message={`${preview.warnings.length} 行 DDL 未能解析，已跳过：${preview.warnings.slice(0, 3).join('; ')}${preview.warnings.length > 3 ? '...' : ''}`}
                />
              )}
              {preview.tables.map((t) => (
                <div key={t.table_name} style={{ marginBottom: 12 }}>
                  <Text strong>{t.table_name}</Text>
                  <Table
                    size="small"
                    pagination={false}
                    rowKey="column_name"
                    dataSource={t.columns}
                    columns={[
                      { title: '列名', dataIndex: 'column_name' },
                      { title: '类型', dataIndex: 'data_type' },
                    ]}
                  />
                </div>
              ))}
            </Card>
          </Col>
          <Col xs={24} lg={9}>
            <Card
              title="导入目标"
              extra={
                <Tag color={BUSINESS_STATE_META[preview.business_state].color}>
                  {BUSINESS_STATE_META[preview.business_state].text}
                </Tag>
              }
            >
              <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
                <Descriptions.Item label="db_name">{preview.db_name}</Descriptions.Item>
                <Descriptions.Item label="业务 ID">{preview.business_id}</Descriptions.Item>
              </Descriptions>
              {preview.business_state === 'missing' ? (
                <>
                  {!isAdmin && (
                    <Alert
                      type="error"
                      showIcon
                      style={{ marginBottom: 16 }}
                      message="当前账号无创建业务的权限，请联系管理员先配置该业务"
                    />
                  )}
                  <Form
                    form={newBusinessForm}
                    layout="vertical"
                    requiredMark="optional"
                  >
                    <Form.Item label="业务 ID" name="id">
                      <Input disabled />
                    </Form.Item>
                    <Form.Item
                      label="数据库路径（相对项目根目录）"
                      name="dbPath"
                      rules={[{ required: true, message: '请填写数据库路径' }]}
                    >
                      <Input disabled={!isAdmin} />
                    </Form.Item>
                    <Form.Item
                      label="向量库 namespace"
                      name="namespace"
                      rules={[{ required: true, message: '请填写 namespace' }]}
                    >
                      <Input disabled={!isAdmin} />
                    </Form.Item>
                  </Form>
                  <Button
                    type="primary"
                    block
                    loading={ingestLoading}
                    disabled={!isAdmin}
                    onClick={handleCreateAndIngest}
                  >
                    创建业务并导入向量库
                  </Button>
                </>
              ) : (
                <>
                  {preview.business_state === 'disabled' && (
                    <Alert
                      type="warning"
                      showIcon
                      icon={<WarningOutlined />}
                      style={{ marginBottom: 16 }}
                      message="该业务已配置但未启用，导入成功后会自动启用"
                    />
                  )}
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginBottom: 16 }}
                    message="增量合并（insert_update）"
                    description="新增表会追加、同名表会覆盖、其余已索引表保留。"
                  />
                  <Button
                    type="primary"
                    block
                    loading={ingestLoading}
                    onClick={handleConfirmImport}
                  >
                    确认导入到向量库
                  </Button>
                </>
              )}
            </Card>
          </Col>
        </Row>
      )}

      {current === 2 && ingestResult && (
        <Card>
          <Result
            status="success"
            title="导入成功"
            subTitle={
              <Space direction="vertical" size={4}>
                <span>
                  已写入业务命名空间 <Text strong>{ingestResult.database_name}</Text>
                  ，共 {ingestResult.tables_count} 张表。
                </span>
                <span>
                  新增 <Text strong>{ingestResult.added_tables.length}</Text> 张、更新{' '}
                  <Text strong>{ingestResult.updated_tables.length}</Text> 张、保留{' '}
                  <Text strong>{ingestResult.kept_tables.length}</Text> 张。
                </span>
              </Space>
            }
            extra={[
              <Button type="primary" key="again" onClick={resetToUpload}>
                <ReloadOutlined /> 继续导入
              </Button>,
            ]}
          >
            {ingestResult.merge_warning && (
              <Alert
                style={{ maxWidth: 640, margin: '16px auto' }}
                type="warning"
                showIcon
                message={ingestResult.merge_warning}
              />
            )}
            <Descriptions
              column={3}
              size="small"
              style={{ maxWidth: 640, margin: '16px auto' }}
              labelStyle={{ fontWeight: 600 }}
            >
              <Descriptions.Item label="新增表">
                {ingestResult.added_tables.length ? ingestResult.added_tables.join('、') : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="更新表">
                {ingestResult.updated_tables.length ? ingestResult.updated_tables.join('、') : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="保留表">
                {ingestResult.kept_tables.length ? ingestResult.kept_tables.join('、') : '—'}
              </Descriptions.Item>
            </Descriptions>
          </Result>
        </Card>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 前端类型检查/构建**

Run: `npm.cmd run build`（在 `frontends/web` 目录）
Expected: tsc + vite 构建通过，无 TS 报错。

---

### Task 6: 全量验证

**Files:**
- 无新增

- [ ] **Step 1: 后端全量测试**

Run: `python -m pytest tests/test_ddl_import.py -q`
Expected: 全部 PASS（含 Task 1 新增用例）。

- [ ] **Step 2: 前端构建**

Run: `npm.cmd run build`（在 `frontends/web` 目录）
Expected: 构建成功。

- [ ] **Step 3: 人工冒烟清单（供用户自测）**

1. 上传缺 db_name 列的 CSV → 报错「缺少必需列：db_name」
2. 上传含空 ddl 行的 CSV → 报错并指出行号
3. 上传含两个 db_name 的 CSV → 报错「一个文件只能对应一个数据库」
4. 以已配置业务（AdventureWorks/equipment_decay）的 db_name 上传 → 标签「已配置」，确认弹窗提示增量合并
5. 以新 db_name 上传 → 标签「未配置」，表单自动预填 dbPath/namespace → 创建并导入 → 结果页显示新增统计 → app.json 中 enabled=true
6. 对同业务再次导入（含 1 张已导入表 + 1 张新表）→ 结果页「更新 1、新增 1、保留 N」

---

## Self-Review 记录

- **Spec 覆盖：** 需求 1（Task 3 + Task 5 错误展示）、需求 1.2（Task 1 空 ddl 测试 + Task 3 行级校验）、需求 2.1（Task 2/4 enabled 流转 + Task 5 创建表单）、需求 2.2（Task 4 合并 + Task 1 合并测试）、需求 3（Task 5 Steps 重写）均有对应任务。
- **占位符扫描：** 无 TBD/TODO。
- **类型一致性：** `ParseResult.business_state`（active/disabled/missing）、`IngestResult`（added_tables/updated_tables/kept_tables/merge_warning）、`config_sync.*` 函数名前后一致。