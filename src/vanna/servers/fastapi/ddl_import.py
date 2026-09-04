"""
DDL import page: upload DDL.csv, preview parsed schema, ingest into the
agent's schema vector store.
"""

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

from .config_sync import (
    resolve_business_namespace_from_config,
    set_business_enabled,
)

# parse_id -> (tables, relations)；确认入库后移除（一次性消费）
_PENDING_PARSES: Dict[str, Tuple[List[SchemaTable], List[SchemaRelation]]] = {}


_DB_NAME_KEYS = [
    "db_name", "database_id", "database", "database_name", "db", "db_id",
]
_TABLE_NAME_KEYS = ["table_name", "table", "table_fullname"]
_DDL_KEYS = ["ddl"]


def _validate_csv_text(text: str) -> str:
    """严格校验 CSV（db_name/table_name/ddl 三列 + 行级非空）。

    校验失败时抛 HTTPException(400)；成功时返回唯一的 db_name。
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
    return sorted(db_names)[0]


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
    business_id: str = Field(
        description=(
            "Business identifier; the namespace is resolved from the "
            "business configuration (no fallback routing)"
        ),
    )


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


def _resolve_business_namespace(agent, business_id: str) -> str:
    """Resolve the schema namespace for a business id.

    未知业务时回退到 app.json（含 disabled 配置）兜底读取；
    找不到时抛 HTTPException 400（路由无兜底：不允许写入其它业务的命名空间）。
    """
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
        detail=(
            f"business_id '{business_id}' not found or disabled; "
            f"available: {available}"
        ),
    )

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
必须选择目标业务，namespace 由业务配置解析（无兜底路由），写入后 AutoLink 检索即刻生效。</p>

<div class="row">
  <input type="file" id="ddl-file" accept=".csv">
  <label>业务 <select id="business-select">__BUSINESS_OPTIONS__</select></label>
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
const businessSelect = document.getElementById("business-select");
const preview = document.getElementById("preview");
const result = document.getElementById("result");

// 当前选中业务的 namespace（由业务配置解析，页面不可编辑）
function currentNamespace() {
  const opt = businessSelect.selectedOptions[0];
  return opt ? (opt.dataset.ns || opt.value) : "";
}

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
  if (!businessSelect.value) { showResult("err", "请先选择目标业务"); return; }
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
    showResult("ok", "解析成功，请确认后写入向量库（业务：" + businessSelect.value
      + "，namespace：" + currentNamespace() + "，重复导入同名 namespace 会覆盖旧索引）");
  } catch (e) {
    showResult("err", "解析请求失败：" + e);
  }
});

document.getElementById("ingest-btn").addEventListener("click", async () => {
  if (!parseId) { showResult("err", "请先解析 DDL.csv"); return; }
  if (!businessSelect.value) { showResult("err", "请先选择目标业务"); return; }
  showResult("ok", "写入中…");
  // namespace 由服务端按业务配置解析（无兜底路由）
  const payload = { parse_id: parseId, business_id: businessSelect.value };
  try {
    const resp = await fetch("/api/vanna/v1/ddl/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) { showResult("err", data.detail || ("ingest failed: " + resp.status)); return; }
    parseId = null;
    showResult("ok", "写入成功：" + data.tables_count + " 张表 / " + data.columns_count
      + " 列 / " + data.relations_count + " 关系 -> 业务 [" + businessSelect.value
      + "] namespace [" + data.database_name + "]");
  } catch (e) {
    showResult("err", "写入请求失败：" + e);
  }
});
</script>
</body>
</html>
"""


def _business_options_html(agent) -> str:
    """Build <option> entries for the business selector from agent config.

    Only loaded (enabled) businesses appear; there is no "no routing"
    option — every ingest must target exactly one business.
    """
    businesses = getattr(getattr(agent, "config", None), "businesses", None) or {}
    if not businesses:
        return '<option value="">（无可用业务）</option>'
    return "".join(
        (
            f'<option value="{business_id}" '
            f'data-ns="{business.effective_database_name()}">'
            f"{business_id} ({business.effective_database_name()})</option>"
        )
        for business_id, business in businesses.items()
    )


def register_ddl_import_routes(app: FastAPI, agent) -> None:
    """Register the DDL import page and API routes."""

    @app.get("/ddl-import", response_class=HTMLResponse)
    async def ddl_import_page() -> str:
        return _INDEX_HTML.replace("__BUSINESS_OPTIONS__", _business_options_html(agent))

    @app.post("/api/vanna/v1/ddl/parse")
    async def ddl_parse(file: UploadFile = File(...)) -> Dict[str, Any]:
        """Parse the uploaded DDL.csv and stage the result for ingest."""
        contents = await file.read()
        try:
            text = contents.decode("utf-8")
        except UnicodeDecodeError as e:
            raise HTTPException(
                status_code=415, detail="File must be UTF-8 encoded CSV"
            ) from e
        db_name = _validate_csv_text(text)
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

        result = {
            **preview,
            "parse_id": parse_id,
            "warnings": _diff_unparsed_tables(text, tables) or [],
            "db_name": db_name,
            **_business_state(agent, db_name),
        }
        return result

    @app.post("/api/vanna/v1/ddl/ingest")
    async def ddl_ingest(request_body: IngestRequest) -> Dict[str, Any]:
        """Ingest a previously parsed DDL preview into the vector store."""
        store = getattr(agent, "schema_vector_store", None)
        if store is None:
            raise HTTPException(
                status_code=503,
                detail="Current service has no schema vector store configured; "
                "configure storage.project.vector_db with backend 'faiss' "
                "(or inject schema_vector_store) to ingest",
            )
        staged = _PENDING_PARSES.pop(request_body.parse_id, None)
        if staged is None:
            raise HTTPException(
                status_code=400,
                detail="Unknown or already-consumed parse_id; parse the CSV again",
            )
        tables, relations = staged
        # Namespace comes from the business configuration (app.json fallback).
        database_name = _resolve_business_namespace(agent, request_body.business_id)

        merge_warning = None
        try:
            merged = await _merge_schema(store, tables, relations, database_name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ingest failed: {e}") from e
        if merged is None:
            # list_tables 不可用：回退为整库覆盖
            try:
                await store.ingest_schema(tables, relations, database_name)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Ingest failed: {e}") from e
            added = sorted(t.table_name for t in tables)
            updated = []
            kept = []
            merge_warning = "当前向量库后端不支持增量合并，已整库覆盖原有索引"
        else:
            merged_tables, merged_rels, added, updated, kept = merged
            try:
                await store.ingest_schema(merged_tables, merged_rels, database_name)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Ingest failed: {e}") from e

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