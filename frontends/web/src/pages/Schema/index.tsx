import { useEffect, useState } from 'react';
import { useParams } from 'react-router';
import { Button, Card, Popconfirm, Select, Space, Table, Tag, Typography, message } from 'antd';
import { DeleteOutlined, ReloadOutlined } from '@ant-design/icons';
import { api } from '../../lib/api';
import { useAuth } from '../../lib/auth';

const { Title, Text } = Typography;

interface SchemaTable {
  table_name: string;
  columns?: Array<{ column_name: string; data_type: string }>;
}

function SchemaPage() {
  const { businessId } = useParams();
  const { user } = useAuth();
  const businesses = user?.businesses ?? [];
  const [selected, setSelected] = useState<string>(businessId || '');
  const [tables, setTables] = useState<SchemaTable[]>([]);
  const [namespace, setNamespace] = useState<string>('');
  const [loading, setLoading] = useState(false);

  async function loadTables() {
    if (!selected) { setTables([]); setNamespace(''); return; }
    setLoading(true);
    try {
      const data = await api.schemaTables(selected);
      setNamespace(data.namespace);
      setTables(data.tables || []);
    } catch (e: any) {
      message.error(e.message || 'Failed to load tables');
      setTables([]);
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(tableName: string) {
    try {
      await api.deleteSchemaTable(tableName, selected);
      message.success(`Deleted table: ${tableName}`);
      loadTables();
    } catch (e: any) {
      message.error(e.message || 'Failed to delete table');
    }
  }

  useEffect(() => { loadTables(); }, [selected]);

  const columns = [
    {
      title: 'Table Name',
      dataIndex: 'table_name',
      key: 'table_name',
      render: (name: string) => <Tag>{name}</Tag>,
    },
    {
      title: 'Columns',
      key: 'columns',
      render: (_: any, record: SchemaTable) => (
        <span>{record.columns?.length || 0} columns</span>
      ),
    },
    {
      title: 'Action',
      key: 'action',
      render: (_: any, record: SchemaTable) => (
        <Popconfirm
          title={`Delete table "${record.table_name}"?`}
          description="This will remove the table and its columns from the vector store."
          onConfirm={() => handleDelete(record.table_name)}
          okText="Delete"
          cancelText="Cancel"
          okButtonProps={{ danger: true }}
        >
          <Button type="link" danger icon={<DeleteOutlined />} size="small">
            Delete
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <Title level={4}>Schema Management</Title>
      <Text type="secondary">
        View and manage tables in the schema vector store. Deletion removes columns and relations from the index.
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
          <Button icon={<ReloadOutlined />} onClick={loadTables} loading={loading}>
            Refresh
          </Button>
          {namespace && <Text type="secondary">Namespace: {namespace}</Text>}
        </Space>
      </Card>

      <Card style={{ marginTop: 16 }}>
        <Table
          dataSource={tables}
          columns={columns}
          rowKey="table_name"
          loading={loading}
          pagination={false}
          locale={{ emptyText: 'No tables found. Import DDL first.' }}
        />
      </Card>
    </div>
  );
}

export default SchemaPage;
