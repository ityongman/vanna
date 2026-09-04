import { useState, useEffect } from 'react';
import { Alert, Button, Card, Descriptions, Form, Input, Modal, Select, Space, Statistic, Table, Tag, Typography, Upload, message } from 'antd';
import { UploadOutlined, ExclamationCircleOutlined, CheckCircleOutlined, WarningOutlined } from '@ant-design/icons';
import { useAuth } from '../../lib/auth';
import type { UploadFile } from 'antd';

const { Title, Text } = Typography;
const { confirm } = Modal;

interface ParseResult {
  parse_id: string;
  tables_count: number;
  columns_count: number;
  relations_count: number;
  tables: Array<{ table_name: string; columns: Array<{ column_name: string; data_type: string }> }>;
  warnings: string[];
  db_names: string[];
  has_db_name_column: boolean;
}

function DdlImport() {
  const { user, refresh } = useAuth();
  const businesses = user?.businesses ?? [];
  const [selected, setSelected] = useState<string>('');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ParseResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newBusinessNeeded, setNewBusinessNeeded] = useState<string | null>(null);
  const [newBusinessForm] = Form.useForm();

  // Check if new business is needed when preview changes
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
      } else {
        setNewBusinessNeeded(null);
      }
    } else {
      setNewBusinessNeeded(null);
    }
  }, [preview, businesses]);

  async function handleParse() {
    if (!file) { message.error('请先选择 DDL CSV 文件'); return; }
    if (!selected) { message.error('请先选择目标业务'); return; }
    setLoading(true);
    setError(null);
    setNewBusinessNeeded(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch('/api/vanna/v1/ddl/parse', { method: 'POST', body: fd });
      if (!res.ok) {
        let errorMsg = 'Parse failed';
        try {
          const errorData = await res.json();
          errorMsg = errorData.detail || errorMsg;
        } catch {
          errorMsg = await res.text();
        }
        setError(errorMsg);
        return;
      }
      const data = await res.json();
      setPreview(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleIngest() {
    if (!preview) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/vanna/v1/ddl/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parse_id: preview.parse_id, business_id: selected }),
      });
      if (!res.ok) {
        let errorMsg = 'Ingest failed';
        try {
          const errorData = await res.json();
          errorMsg = errorData.detail || errorMsg;
        } catch {
          errorMsg = await res.text();
        }
        setError(errorMsg);
        return;
      }
      const result = await res.json();
      message.success(`成功导入 ${result.tables_count} 张表到命名空间 "${result.database_name}"`);
      setPreview(null);
      setFile(null);
      setNewBusinessNeeded(null);
      // Refresh business list to reflect any changes
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function handleParseResult() {
    if (!preview) return;

    const { db_names, has_db_name_column } = preview;

    // Case 1: CSV doesn't have db_name column
    if (!has_db_name_column || db_names.length === 0) {
      confirm({
        title: '确认导入',
        icon: <ExclamationCircleOutlined />,
        content: (
          <div>
            <p>CSV 文件中未包含数据库名信息。</p>
            <p><strong>将导入到业务 "{selected}" 的命名空间中。</strong></p>
            <p>请确认这是您期望的导入目标。</p>
          </div>
        ),
        onOk: handleIngest
      });
      return;
    }

    const csvDbName = db_names[0];

    // Case 2: CSV db_name matches selected business
    if (csvDbName === selected) {
      confirm({
        title: '确认导入',
        icon: <CheckCircleOutlined />,
        content: (
          <div>
            <p>CSV 文件中的数据库名 "{csvDbName}" 与选择的业务一致。</p>
            <p><strong>将导入到业务 "{selected}" 的命名空间中。</strong></p>
          </div>
        ),
        onOk: handleIngest
      });
      return;
    }

    // Case 3: CSV db_name doesn't match, use CSV as source of truth
    confirm({
      title: '数据库名不一致',
      icon: <WarningOutlined />,
      content: (
        <div>
          <p>CSV 文件中的数据库名 "{csvDbName}" 与选择的业务 "{selected}" 不一致。</p>
          <p><strong>将以 CSV 文件中的数据库名为准</strong>进行导入。</p>
          <p>是否继续？</p>
        </div>
      ),
      onOk: () => {
        // Switch to CSV's business
        setSelected(csvDbName);
        // Continue with ingest (new business form will show if needed)
        handleIngest();
      }
    });
  }

  async function handleCreateAndIngest() {
    try {
      const values = await newBusinessForm.validateFields();
      setLoading(true);
      setError(null);

      // 1. Create business config
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
        const errorData = await createRes.json().catch(() => ({ detail: '创建业务配置失败' }));
        message.error(errorData.detail || '创建业务配置失败');
        return;
      }

      // 2. Refresh business list
      await refresh();
      setSelected(values.id);

      // 3. Execute ingest
      await handleIngest();

      // 4. Clear new business form
      setNewBusinessNeeded(null);
      message.success(`业务 "${values.id}" 创建成功，DDL 导入完成`);
    } catch (e: any) {
      if (e.errorFields) {
        message.error('请填写必填字段');
      } else {
        setError(e.message);
      }
    } finally {
      setLoading(false);
    }
  }

  // Get import target info
  function getImportTargetInfo() {
    if (!preview) return null;

    const { db_names, has_db_name_column } = preview;

    if (has_db_name_column && db_names.length > 0) {
      const csvDbName = db_names[0];
      const isMatch = csvDbName === selected;
      return {
        business: selected,
        csvDbName,
        isMatch,
        hasDbName: true
      };
    }

    return {
      business: selected,
      csvDbName: null,
      isMatch: null,
      hasDbName: false
    };
  }

  const importTarget = getImportTargetInfo();

  const columns = [
    { title: '表名', dataIndex: 'table_name', key: 'table_name' },
    {
      title: '列信息',
      key: 'columns',
      render: (_: any, record: any) => (
        <ul style={{ margin: 0, paddingLeft: 16 }}>
          {record.columns?.map((c: any) => (
            <li key={c.column_name}>{c.column_name} : {c.data_type || '?'}</li>
          ))}
        </ul>
      ),
    },
  ];

  return (
    <div>
      <Title level={4}>DDL 导入</Title>
      <Text type="secondary">
        上传 DDL CSV 文件，预览解析后的表结构，然后导入到 Schema 向量库。
        必须选择目标业务，命名空间由业务配置解析（无兜底路由）。
      </Text>

      <Card title="导入配置" style={{ marginTop: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <Text strong style={{ display: 'block', marginBottom: 8 }}>目标业务</Text>
            <Select
              value={selected}
              onChange={(val) => {
                setSelected(val);
                // Clear preview when business changes
                if (preview) {
                  setPreview(null);
                  setNewBusinessNeeded(null);
                }
              }}
              style={{ width: '100%' }}
              placeholder="请选择 DDL 要导入的目标业务"
              options={businesses.map(b => ({ label: b, value: b }))}
            />
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
              选择业务后，DDL 数据将导入到该业务对应的向量库命名空间中。
              如果 CSV 文件中包含数据库名，系统会自动检测并与您选择的业务进行比对。
            </Text>
          </div>
          
          <div>
            <Text strong style={{ display: 'block', marginBottom: 8 }}>DDL CSV 文件</Text>
            <Upload
              accept=".csv"
              beforeUpload={(f: UploadFile) => { setFile(f as any); return false; }}
              maxCount={1}
              fileList={file ? [{ uid: '-1', name: file.name, status: 'done' } as any] : []}
              onRemove={() => { setFile(null); setPreview(null); setNewBusinessNeeded(null); }}
            >
              <Button icon={<UploadOutlined />}>选择 CSV 文件</Button>
            </Upload>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
              支持两种格式：包含 db_name 列的 CSV（如 db_name,table_name,DDL）或不含 db_name 列的 CSV（如 table_name,DDL）
            </Text>
          </div>

          <Button type="primary" onClick={handleParse} loading={loading} disabled={!file || !selected}>
            解析预览
          </Button>
        </Space>
      </Card>

      {error && <Alert type="error" message={error} style={{ marginTop: 16 }} closable onClose={() => setError(null)} />}

      {preview && importTarget && (
        <Card title="解析结果" style={{ marginTop: 16 }}>
          {/* Import Target Info */}
          <Card 
            type="inner" 
            title="导入目标" 
            style={{ marginBottom: 16 }}
            extra={
              importTarget.hasDbName ? (
                importTarget.isMatch ? (
                  <Tag icon={<CheckCircleOutlined />} color="success">匹配</Tag>
                ) : (
                  <Tag icon={<WarningOutlined />} color="warning">不匹配</Tag>
                )
              ) : (
                <Tag>未指定</Tag>
              )
            }
          >
            <Descriptions column={1} size="small">
              <Descriptions.Item label="目标业务">
                <Text strong>{importTarget.business}</Text>
              </Descriptions.Item>
              {importTarget.hasDbName && (
                <Descriptions.Item label="CSV 中的数据库名">
                  <Text>{importTarget.csvDbName}</Text>
                </Descriptions.Item>
              )}
              {!importTarget.hasDbName && (
                <Descriptions.Item label="说明">
                  <Text type="secondary">CSV 文件中未包含数据库名信息，将使用目标业务的命名空间</Text>
                </Descriptions.Item>
              )}
            </Descriptions>
            
            {/* Allow changing business when CSV has no db_name */}
            {!importTarget.hasDbName && (
              <div style={{ marginTop: 16 }}>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                  如果这不是您期望的导入目标，请重新选择目标业务：
                </Text>
                <Select
                  value={selected}
                  onChange={setSelected}
                  style={{ width: '100%' }}
                  placeholder="重新选择目标业务"
                  options={businesses.map(b => ({ label: b, value: b }))}
                />
              </div>
            )}
          </Card>

          {/* Statistics */}
          <Space size="large">
            <Statistic title="表数量" value={preview.tables_count} />
            <Statistic title="列数量" value={preview.columns_count} />
            <Statistic title="关系数量" value={preview.relations_count} />
          </Space>

          {/* Warnings */}
          {preview.warnings.length > 0 && (
            <Alert
              type="warning"
              message="解析失败的表（将不会被导入）"
              description={preview.warnings.join(', ')}
              style={{ marginTop: 16 }}
            />
          )}

          {/* Table Preview */}
          <Table
            dataSource={preview.tables}
            columns={columns}
            rowKey="table_name"
            size="small"
            style={{ marginTop: 16 }}
            pagination={false}
          />

          {/* Import Button */}
          {!newBusinessNeeded && (
            <Button
              type="primary"
              onClick={handleParseResult}
              loading={loading}
              style={{ marginTop: 16 }}
            >
              确认导入到向量库
            </Button>
          )}
        </Card>
      )}

      {/* New business inline form */}
      {newBusinessNeeded && (
        <Card title="新建业务配置" style={{ marginTop: 16 }}>
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
              rules={[{ required: true, message: '请输入业务 ID' }]}
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
    </div>
  );
}

export default DdlImport;
