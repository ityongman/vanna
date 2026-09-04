# DDL 导入页面优化设计与实现方案

> 日期：2026-09-04
> 需求来源：`.trae/requirements/require_desc.md`

## 1. 背景与目标

优化 DDL 导入功能（React 页面 `frontends/web/src/pages/DdlImport/index.tsx` + FastAPI 路由 `src/vanna/servers/fastapi/ddl_import.py`）：

1. CSV 必须包含 `db_name`、`table_name`、`ddl` 三列，缺列或 ddl 空值视为文件问题并提示
2. 解析预览时根据 db_name 判断业务配置：无配置 → 在 app.json 新建（enabled=false），导入成功后置 enabled=true；有配置 → 以 insert_update（增量合并）语义写入向量库
3. 页面美观性与易用性优化

## 2. 关键决策与假设

| 事项 | 决策 | 理由 |
|---|---|---|
| 三列校验 | 缺任一列 → 400；`ddl` 空值 → 400（含行号）；`db_name`/`table_name` 空值 → 400 | 需求字面要求 |
| 无 db_name 的旧流程 | 移除前端「无 db_name → 选业务」路径、选错检测 UI、后端 `/ddl/check` 路由及其测试 | 三列强制后该场景不可达 |
| 一个 CSV 多个 db_name | 判为文件错误（400） | 需求描述单一 db_name → 单一业务映射 |
| db_name 与业务匹配 | 与业务 `id` 匹配，大小写不敏感 | 与现有实现一致 |
| 新业务字段 | 按 db_name 预填默认值（database url=`sqlite:///data/db/{db_name}.db`、namespace=db_name），可编辑 | database.url 无合理默认来源，预填+可改最稳妥 |
| 新业务创建入口 | 复用 `POST /api/businesses`（enabled=false 落 app.json）；导入成功后置 enabled=true | 已存在该能力 |
| insert_update | ingest 时合并：同名表覆盖、新表追加、其余保留；关系同理；返回 added/updated/kept 统计；后端不支持 `list_tables` 时回退整库覆盖并附 `merge_warning` | FAISS 已实现 `list_tables`；通用方案 |
| 配置存在但 enabled=false | 解析 namespace 时，`agent.config.businesses` 未命中的业务回退从 app.json 读取（含 disabled），保证可导入并启用 | 覆盖「上次创建未导入即离开」场景 |
| 非管理员 + 无配置 | 提示「该业务未配置，请联系管理员」，禁用导入按钮 | `POST /api/businesses` 有 admin 守卫 |
| 页面优化 | Steps 向导式流程（上传校验 → 解析预览 → 导入结果） | 更符合操作心智模型 |

## 3. 后端改动

### 3.1 新模块 `src/vanna/servers/fastapi/config_sync.py`

从 `business_routes.py` 提取 app.json 读写/业务同步：

- `load_app_config() -> dict`
- `save_app_config(config) -> None`
- `get_businesses(config) -> list`
- `sync_agent_businesses(agent, config) -> None`（现有 `_sync_agent_businesses` 逻辑）
- `set_business_enabled(agent, business_id, enabled) -> bool`（写入 app.json + 同步 agent，替代 ddl_import 中的 `_auto_enable_business`）
- `resolve_business_namespace_from_config(business_id) -> str | None`（供 fallback：从 app.json 读取 namespace，含 disabled 业务）

`business_routes.py` 改为引用该模块（行为不变）；`ddl_import.py` 的 `_auto_enable_business` 删除并复用。

### 3.2 `ddl_parse` 严格校验（在现有解析之前）

```
_STRICT_COLUMNS 映射（大小写不敏感、去首尾空格）:
  db_name    <- [db_name, database_id, database, database_name, db, db_id]
  table_name <- [table_name, table, table_fullname]
  ddl        <- [ddl]
```

校验顺序与错误信息（全部 400）：

1. 文件为空/无表头 → "CSV 文件为空或缺少表头"
2. 缺列 → `缺少必需列: xxx（仅识别到: ...）。请确保 CSV 包含 db_name、table_name、ddl 三列`
3. 行级校验（从第 2 行起）：
   - `db_name` 空 → `第 N 行 db_name 为空，请检查文件内容`
   - `table_name` 空 → `第 N 行 table_name 为空，请检查文件内容`
   - `ddl` 空 → `第 N 行 ddl 为空，请检查文件内容`（需求 1.2）
   - 收集所有问题行后一次性报错（最多列出前 10 行）
4. 多个不同 db_name → `CSV 包含多个不同的 db_name（{...}），一个文件只能对应一个数据库`
5. 校验通过后走现有 `DdlParser().parse_csv`；解析结果为空 → 现有 400 逻辑保留

解析响应不再包含 `db_names`/`has_db_name_column`，改为 `db_name: str`（单一值）。

### 3.3 `ddl_ingest` 增量合并（insert_update）

```
async def _merge_schema(store, tables, relations, namespace):
    try:
        existing = await store.list_tables(namespace) or []
    except (NotImplementedError, Exception):
        return None  # 不支持 → 整库覆盖
    old_rels = await store.get_relations([t.table_name for t in existing], namespace)  # 异常时视为 []
    old_names = {t.table_name.lower() for t in existing}
    new_names = {t.table_name.lower() for t in tables}
    merged = {t.table_name.lower(): t for t in existing}
    merged.update({t.table_name.lower(): t for t in tables})   # 同名覆盖
    kept_rels = [r for r in old_rels
                 if r.from_table.lower() not in new_names and r.to_table.lower() not in new_names]
    merged_rels = kept_rels + relations                        # 涉及新表的旧关系被替换
    added = sorted(new_names - old_names)
    updated = sorted(new_names & old_names)
    kept = sorted(old_names - new_names)
    return list(merged.values()), merged_rels, added, updated, kept
```

- 命中合并 → `store.ingest_schema(merged_tables, merged_rels, namespace)`，响应含 `added_tables/updated_tables/kept_tables`
- 不支持合并 → 现有整库覆盖行为，响应附 `merge_warning: "当前后端不支持增量合并，已整库覆盖"`
- 保持 parse_id 一次性消费；`db_name` 由业务配置解析（含 app.json fallback）
- 导入成功后 `config_sync.set_business_enabled(agent, business_id, True)`

### 3.4 移除内容

- `/ddl/check` 路由及 `CheckRequest`
- `_extract_db_names`（被严格校验取代）
- `_auto_enable_business`（被 config_sync 取代）

## 4. 前端改动（Steps 向导）

```
Step1 上传 CSV
  - Upload(drag)、accept=.csv
  - 模板说明：三列格式 db_name,table_name,ddl；ddl 用双引号包裹含逗号/换行的 DDL
  - 「下载示例 CSV」链接（前端生成 blob）
Step2 解析预览
  - 统计（表/列/关系）+ 表结构预览表格 + 解析警告
  - 目标业务状态标签：
      · 已配置（id 匹配，含 enabled=false 时提示「已配置但未启用，导入后将启用」）→ 可直接导入
      · 未配置 → 新业务表单（db_name 作为 id 自动填充并只读；dbPath/namespace 预填可改）
        - 非管理员：显示提示并禁用「创建并导入」
  - 确认弹窗（Modal.confirm）：展示目标业务/namespace 与「增量合并（新增/更新/保留）」说明
Step3 导入结果
  - Result/success 展示 added_tables/updated_tables/kept_tables（或 merge_warning）
  - 「再导一次」按钮返回 Step1
```

移除：`BusinessMatch/CheckResult` 类型、`checkTargetBusiness/getMismatchHint/handleSelectChange` 检测逻辑、无 db_name 的 Radio 分支、`matchCheck` state。

## 5. 测试计划（`tests/test_ddl_import.py`）

更新基线 CSV 为三列（`db_name,table_name,ddl`）：

- 保留并通过：页面可达、三列解析预览、ingest 写库、parse_id 一次性消费、未知业务 400、无 store 503
- 新增：
  - `test_parse_missing_required_column_returns_400`（缺 db_name / 缺 table_name / 缺 ddl）
  - `test_parse_empty_ddl_row_returns_400`（含行号）
  - `test_parse_multiple_db_names_returns_400`
  - `test_ingest_merges_into_existing_namespace`（IndexedStore：先索引 a、b，再导入含 b、c 的 CSV → 断言 added=[c]、updated=[b]、kept=[a] 且 store 最终含 a、b、c）
  - `test_ingest_merge_fallback_when_list_tables_unsupported`（FakeStore → 响应带 merge_warning）
  - `test_enable_after_ingest`（app.json 幂等写 enabled=true —— 用 monkeypatch 临时配置路径）
  - `test_namespace_fallback_to_app_json_for_disabled_business`
- 移除：6 个 `/ddl/check` 相关测试
- 同步修复 FakeAgent 缺 `conversation_store`（已完成）

## 6. 验证方式

- 后端：`python -m pytest tests/test_ddl_import.py -q`
- 前端：`npm.cmd run build`（tsc + vite）