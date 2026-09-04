import { useState } from 'react';
import { useParams } from 'react-router';
import { Alert, Button, Card, Select, Space, Statistic, Table, Typography, Upload, message } from 'antd';
import { UploadOutlined } from '@ant-design/icons';
import { useAuth } from '../../lib/auth';
import type { UploadFile } from 'antd';

const { Title, Text } = Typography;

interface ParseResult {
  parse_id: string;
  tables_count: number;
  columns_count: number;
  relations_count: number;
  tables: Array<{ table_name: string; columns: Array<{ column_name: string; data_type: string }> }>;
  warnings: string[];
}

function DdlImport() {
  const { businessId } = useParams();
  const { user } = useAuth();
  const businesses = user?.businesses ?? [];
  const [selected, setSelected] = useState<string>(businessId || '');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ParseResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleParse() {
    if (!file) { message.error('Please select a DDL CSV file'); return; }
    if (!selected) { message.error('Please select a target business'); return; }
    setLoading(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch('/api/vanna/v1/ddl/parse', { method: 'POST', body: fd });
      if (!res.ok) { setError(await res.text()); return; }
      setPreview(await res.json());
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
      if (!res.ok) { setError(await res.text()); return; }
      const result = await res.json();
      message.success(`Ingested ${result.tables_count} tables into ${result.database_name}`);
      setPreview(null);
      setFile(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  const columns = [
    { title: 'Table', dataIndex: 'table_name', key: 'table_name' },
    {
      title: 'Columns',
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
      <Title level={4}>DDL Import</Title>
      <Text type="secondary">
        Upload DDL CSV, preview parsed schema, then ingest into the schema vector store.
        Business ID is required; namespace is resolved from business config (no fallback routing).
      </Text>

      <Card style={{ marginTop: 16 }}>
        <Space>
          <Select
            value={selected}
            onChange={setSelected}
            style={{ width: 240 }}
            placeholder="Select business"
            options={businesses.map(b => ({ label: b, value: b }))}
          />
          <Upload
            accept=".csv"
            beforeUpload={(f: UploadFile) => { setFile(f as any); return false; }}
            maxCount={1}
            fileList={file ? [{ uid: '-1', name: file.name, status: 'done' } as any] : []}
            onRemove={() => setFile(null)}
          >
            <Button icon={<UploadOutlined />}>Select CSV</Button>
          </Upload>
          <Button type="primary" onClick={handleParse} loading={loading} disabled={!file || !selected}>
            Parse
          </Button>
        </Space>
      </Card>

      {error && <Alert type="error" message={error} style={{ marginTop: 16 }} closable onClose={() => setError(null)} />}

      {preview && (
        <Card style={{ marginTop: 16 }}>
          <Space size="large">
            <Statistic title="Tables" value={preview.tables_count} />
            <Statistic title="Columns" value={preview.columns_count} />
            <Statistic title="Relations" value={preview.relations_count} />
          </Space>

          {preview.warnings.length > 0 && (
            <Alert
              type="warning"
              message="Parse failures (will not be imported)"
              description={preview.warnings.join(', ')}
              style={{ marginTop: 16 }}
            />
          )}

          <Table
            dataSource={preview.tables}
            columns={columns}
            rowKey="table_name"
            size="small"
            style={{ marginTop: 16 }}
            pagination={false}
          />

          <Button
            type="primary"
            onClick={handleIngest}
            loading={loading}
            style={{ marginTop: 16 }}
          >
            Ingest into Vector Store
          </Button>
        </Card>
      )}
    </div>
  );
}

export default DdlImport;
