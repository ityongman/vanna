# DDL 导入功能增强计划

## 需求概述

1. **db_name 下拉选择框添加说明**
2. **二次确认弹窗**：
   - CSV 包含 db_name 时，比较与页面选择是否一致
   - 一致：提示可导入
   - 不一致：提示不一致，以 CSV 为准
3. **支持新数据库动态配置**：
   - 如果 db_name 在 app.json 中不存在，弹出配置表单
   - 新业务保存到 app.json，`enabled=false`
   - DDL 导入成功后设置 `enabled=true`

## 技术方案

### Phase 1：后端 API 增强

#### Task 1：DDL 解析 API 返回 db_name 信息

**修改文件**：`src/vanna/servers/fastapi/ddl_import.py`

修改 `/api/vanna/v1/ddl/parse` 响应，增加：
- `db_names`: 从 CSV 提取的唯一数据库名列表（可能为空）
- `has_db_name_column`: CSV 是否包含 db_name 列

```python
# parse 响应增加字段
{
    "parse_id": "...",
    "tables_count": 10,
    "columns_count": 50,
    "relations_count": 5,
    "tables": [...],
    "warnings": [...],
    "db_names": ["equipment_decay"],  # 新增
    "has_db_name_column": true  # 新增
}
```

#### Task 2：新增业务管理 API

**新增文件**：`src/vanna/servers/fastapi/business_routes.py`

```python
# API 列表
GET  /api/businesses          # 获取所有业务（包括 disabled）
POST /api/businesses          # 创建新业务
PUT  /api/businesses/{id}/enable  # 启用/禁用业务
```

**请求体**：
```json
// POST /api/businesses
{
    "id": "new_business",
    "database_url": "sqlite:///data/db/new_business.db",
    "namespace": "new_business"
}
```

**响应**：
```json
{
    "id": "new_business",
    "enabled": false,
    "database": {"url": "sqlite:///data/db/new_business.db"},
    "schema_vector": {"namespace": "new_business"}
}
```

#### Task 3：app.json 动态更新

**修改文件**：`src/vanna/servers/fastapi/business_routes.py`

实现 app.json 读写逻辑：
1. 读取现有配置
2. 添加新业务（`enabled=false`）
3. 写回文件
4. 热更新 agent.config.businesses（不重启服务）

#### Task 4：DDL 导入后自动启用业务

**修改文件**：`src/vanna/servers/fastapi/ddl_import.py`

在 `/api/vanna/v1/ddl/ingest` 成功后：
1. 如果 business_id 对应的业务 `enabled=false`
2. 自动设置 `enabled=true`
3. 创建 SqlRunner 并缓存

### Phase 2：前端 UI 增强

#### Task 5：DDL 导入页面 - db_name 说明

**修改文件**：`frontends/web/src/pages/DdlImport/index.tsx`

在业务选择框旁添加说明：
```tsx
<Select
  value={selected}
  onChange={setSelected}
  style={{ width: 240 }}
  placeholder="选择目标业务"
  options={businesses.map(b => ({ label: b, value: b }))}
/>
<Text type="secondary">
  目标业务决定 DDL 写入的向量库命名空间，由 app.json 业务配置解析
</Text>
```

#### Task 6：二次确认弹窗

**修改文件**：`frontends/web/src/pages/DdlImport/index.tsx`

解析完成后，点击"导入"前进行检查和确认：

```tsx
const handleParseResult = (parseResult: ParseResult) => {
    const { db_names, has_db_name_column } = parseResult;
    
    // 情况1：CSV 不包含 db_name 列，使用页面选择的业务
    if (!has_db_name_column || db_names.length === 0) {
        Modal.confirm({
            title: '确认导入',
            content: `CSV 文件中未包含数据库名信息，将使用您选择的业务 "${selected}" 进行导入。`,
            onOk: handleIngest
        });
        return;
    }
    
    const csvDbName = db_names[0]; // 假设单个数据库
    
    // 情况2：CSV 的 db_name 与页面选择一致
    if (csvDbName === selected) {
        Modal.confirm({
            title: '确认导入',
            content: `CSV 文件中的数据库名 "${csvDbName}" 与选择的业务一致，可以导入。`,
            onOk: handleIngest
        });
        return;
    }
    
    // 情况3：CSV 的 db_name 与页面选择不一致，以 CSV 为准
    Modal.confirm({
        title: '数据库名不一致',
        content: (
            <div>
                <p>CSV 文件中的数据库名 "{csvDbName}" 与选择的业务 "{selected}" 不一致。</p>
                <p><strong>将以 CSV 文件中的数据库名为准</strong>进行导入。</p>
                <p>是否继续？</p>
            </div>
        ),
        onOk: () => {
            // 切换到 CSV 中的业务
            setSelected(csvDbName);
            // 继续导入流程（Task 7 会处理业务不存在的情况）
            handleIngest();
        }
    });
};
```

#### Task 7：新业务内联提示与快速创建

**修改文件**：`frontends/web/src/pages/DdlImport/index.tsx`

当 db_name 在 businesses 中不存在时，在页面内显示提示和配置表单（非弹窗）：

```tsx
// 在页面中添加状态
const [newBusinessNeeded, setNewBusinessNeeded] = useState<string | null>(null);
const [newBusinessForm] = Form.useForm();

// 解析完成后检查
useEffect(() => {
    if (preview?.has_db_name_column && preview.db_names.length > 0) {
        const csvDbName = preview.db_names[0];
        if (!businesses.includes(csvDbName)) {
            setNewBusinessNeeded(csvDbName);
            newBusinessForm.setFieldsValue({
                id: csvDbName,
                dbPath: `data/db/${csvDbName}.db`,
                namespace: csvDbName
            });
        }
    }
}, [preview]);

// 内联提示和表单
{newBusinessNeeded && (
    <Card style={{ marginTop: 16 }}>
        <Alert
            type="info"
            showIcon
            message="检测到新业务"
            description={`CSV 文件中包含业务 "${newBusinessNeeded}"，但尚未在系统中配置。请填写以下信息创建业务配置。`}
        />
        <Form
            form={newBusinessForm}
            layout="vertical"
            style={{ marginTop: 16 }}
        >
            <Form.Item
                label="业务 ID"
                name="id"
                rules={[{ required: true }]}
            >
                <Input disabled />
            </Form.Item>
            <Form.Item
                label="数据库文件路径"
                name="dbPath"
                rules={[{ required: true, message: '请输入数据库文件路径' }]}
                extra="SQLite 数据库文件的相对路径，将自动添加 sqlite:/// 前缀"
            >
                <Input placeholder="data/db/xxx.db" />
            </Form.Item>
            <Form.Item
                label="命名空间"
                name="namespace"
                rules={[{ required: true, message: '请输入命名空间' }]}
                extra="用于向量库索引隔离，通常使用业务名称"
            >
                <Input />
            </Form.Item>
            <Form.Item>
                <Space>
                    <Button
                        type="primary"
                        onClick={handleCreateAndIngest}
                        loading={loading}
                    >
                        创建并导入
                    </Button>
                    <Button onClick={() => setNewBusinessNeeded(null)}>
                        取消
                    </Button>
                </Space>
            </Form.Item>
        </Form>
    </Card>
)}

// 创建并导入函数
const handleCreateAndIngest = async () => {
    try {
        const values = await newBusinessForm.validateFields();
        setLoading(true);
        
        // 1. 创建业务配置
        const createRes = await fetch('/api/businesses', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id: values.id,
                database_url: `sqlite:///${values.dbPath}`,
                namespace: values.namespace
            })
        });
        
        if (!createRes.ok) {
            message.error('创建业务配置失败');
            return;
        }
        
        // 2. 刷新业务列表
        await refresh();
        setSelected(values.id);
        
        // 3. 执行导入
        await handleIngest();
        
        // 4. 清除提示
        setNewBusinessNeeded(null);
        message.success(`业务 "${values.id}" 创建成功，DDL 导入完成`);
    } catch (e: any) {
        message.error(e.message);
    } finally {
        setLoading(false);
    }
};
```

#### Task 8：业务列表刷新

**修改文件**：`frontends/web/src/lib/auth.tsx`

添加 `refreshBusinesses` 方法，在创建新业务后刷新列表：

```tsx
const refreshBusinesses = async () => {
    const me = await api.me();
    setUser(me);
};
```

### Phase 3：测试

#### Task 9：后端测试

**新增文件**：`tests/test_business_routes.py`

- 测试 GET /api/businesses 返回所有业务
- 测试 POST /api/businesses 创建新业务
- 测试 PUT /api/businesses/{id}/enable 启用/禁用
- 测试 DDL 导入后自动启用

#### Task 10：前端测试

- 测试二次确认弹窗逻辑
- 测试新业务配置表单
- 测试业务列表刷新

## 实施顺序

1. Task 1：DDL 解析 API 返回 db_name
2. Task 2-4：业务管理 API + app.json 更新 + DDL 导入后启用
3. Task 5-8：前端 UI 增强
4. Task 9-10：测试

## 风险点

1. **app.json 并发写入**：多个管理员同时操作可能导致配置丢失
   - 缓解：使用文件锁或乐观锁
2. **SqlRunner 热更新**：动态创建 SqlRunner 可能影响现有请求
   - 缓解：使用线程安全的缓存，新 runner 创建不影响旧 runner
3. **CSV 格式多样性**：db_name 列名可能不统一
   - 缓解：支持多种列名（database_id, database, database_name, db, db_id）
