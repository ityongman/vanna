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