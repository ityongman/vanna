"""
DDL import page: upload DDL.csv, preview parsed schema, ingest into the
agent's schema vector store.
"""

import csv
import io
import os
import tempfile
import uuid
from typing import Any, Dict, List, Optional, Tuple

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
    database_name: Optional[str] = Field(
        default=None,
        description=(
            "Vector store namespace; defaults to the agent's "
            "autoLinkConfig.database_name when omitted"
        ),
    )


def _agent_database_name(agent) -> str:
    """Namespace used by the agent's AutoLink configuration.

    Falls back to "default" for agents without that configuration (e.g. the
    FakeAgent used in tests).
    """
    try:
        return agent.config.autolink_config.database_name
    except Exception:
        return "default"

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
  <label>database_name <input type="text" id="database-name" value="__AGENT_DATABASE_NAME__"></label>
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
    dbName.value = data.database_name;  // 服务端 AutoLink namespace 为准
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


def register_ddl_import_routes(app: FastAPI, agent) -> None:
    """Register the DDL import page and API routes."""

    @app.get("/ddl-import", response_class=HTMLResponse)
    async def ddl_import_page() -> str:
        return _INDEX_HTML.replace(
            "__AGENT_DATABASE_NAME__", _agent_database_name(agent)
        )

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
                "database_name": _agent_database_name(agent),
                "warnings": _diff_unparsed_tables(text, tables),
            }
        )
        return preview

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
        database_name = request_body.database_name or _agent_database_name(agent)
        try:
            await store.ingest_schema(tables, relations, database_name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ingest failed: {e}") from e
        return {
            "database_name": database_name,
            "tables_count": len(tables),
            "columns_count": sum(len(t.columns) for t in tables),
            "relations_count": len(relations),
            "message": "Ingested successfully; AutoLink can now search this namespace",
        }