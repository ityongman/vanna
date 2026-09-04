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