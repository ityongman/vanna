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