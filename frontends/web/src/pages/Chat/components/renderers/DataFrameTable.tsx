import { Table } from 'antd';
import type { RichComponent } from '../../types';

/** DataFrameComponent renderer: rows live under `data.data` after serialization. */
export default function DataFrameTable({ component }: { component: RichComponent }) {
  const data = component.data ?? {};
  const rows: Record<string, unknown>[] = data.data ?? [];
  const columns: string[] = data.columns ?? Object.keys(rows[0] ?? {});

  return (
    <Table
      size="small"
      bordered={data.bordered !== false}
      pagination={
        data.paginated === false
          ? false
          : { pageSize: data.page_size ?? 25, showSizeChanger: false }
      }
      rowKey={(_record, index) => String(index ?? 0)}
      dataSource={rows}
      columns={columns.map((col) => ({
        title: col,
        dataIndex: col,
        key: col,
        ellipsis: true,
      }))}
      style={{ marginTop: 8 }}
    />
  );
}